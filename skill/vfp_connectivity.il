;; =====================================================================
;; vfp_connectivity.il — connectivity snapshot & diff (M11 / roadmap P4)
;; ---------------------------------------------------------------------
;; The most expensive silent failures in practice are connectivity
;; changes nobody audited: a reshaped symbol detaching a testbench wire,
;; or manual rewiring renaming the auto nets that automation depends on.
;; This module gives VFP eyes on both:
;;
;;   vfpSnapshotConnectivity(cv)  instance-terminal -> net mapping plus
;;                                explicit/auto net classification
;;   vfpConnectivityDiff(a b)     structural diff of two snapshots
;;   vfpConnectivityJson(cv)      JSON form (context export / txn audit)
;;   vfpInstTermPoint(inst term)  sheet coordinates of a terminal's pin
;;
;; Auto-named nets (net<N>) are second-class: their names are not stable
;; under manual rewiring, so anything referencing them is flagged.
;; Uses vfpAlistGet (vfp_rpc_client.il) and the JSON helpers
;; (vfp_utils.il); loaded after both by vfp_init.il.
;; =====================================================================

;; Auto-generated net name? ("net12" -> t, "vout" -> nil)
defun( vfpAutoNetP (name)
  and( stringp(name) rexMatchp("^net[0-9]+$" name) t )
)

;; Does the net carry an explicit wire label? That is what pins its name
;; against schCheck renumbering. The label fig may be the figure itself or
;; a child glued to a wire (schCreateWireLabel glues to the wire, so the
;; label shows up under the wire's children). A net with an auto-style name
;; but a real label IS pinned — name pattern alone does not decide it.
defun( vfpNetLabeledP (net)
  and( net
       exists( f net~>figs
               or( schIsWireLabel(f)
                   exists(c f~>children schIsWireLabel(c)) ) )
       t )
)

;; Sheet coordinates of an instance terminal's pin: the master pin's
;; bBox center pushed through the instance transform. Works for wired
;; and floating terminals alike (master geometry, not instTerms).
defun( vfpInstTermPoint (inst termName)
  let( (term pin fig bb)
    term = car(setof(tm inst~>master~>terminals tm~>name == termName))
    pin  = and(term car(term~>pins))
    fig  = and(pin pin~>fig)
    bb   = and(fig fig~>bBox)
    when( bb
      dbTransformPoint(
        list( (xCoord(lowerLeft(bb)) + xCoord(upperRight(bb))) / 2.0
              (yCoord(lowerLeft(bb)) + yCoord(upperRight(bb))) / 2.0 )
        inst~>transform)
    )
  )
)

;; ---- snapshot --------------------------------------------------------
;; Returns an alist:
;;   ("cellview"   "lib/cell/view")
;;   ("instances"  list of (name master ((term netName|nil) ...)))
;;   ("named_nets" (...))   ("auto_nets" (...))
;; netName is nil for a terminal with no net (floating, pre-schCheck).
defun( vfpSnapshotConnectivity (cv)
  let( (insts named auto)
    insts = foreach( mapcar i cv~>instances
      list( i~>name
            vfpCvId(i~>master)
            foreach( mapcar it i~>instTerms
              list( it~>term~>name it~>net~>name ) )
      )
    )
    foreach( n cv~>nets
      if( vfpAutoNetP(n~>name)
        then auto  = cons(n~>name auto)
        else named = cons(n~>name named)
      )
    )
    list(
      list("cellview"   vfpCvId(cv))
      list("instances"  insts)
      list("named_nets" reverse(named))
      list("auto_nets"  reverse(auto))
    )
  )
)

;; ---- diff ------------------------------------------------------------
;; Auto-net names are NOT stable: deleting and redrawing a wire makes
;; schCheck renumber (net4 -> net1) even though the topology is back to
;; identical. So the diff compares named nets by name but auto nets by
;; their member set (canonical form); pure renames are surfaced
;; separately by vfpConnAutoRenames as the fragility signal.

;; Flat list of ("inst.term" rawNetName|nil) pairs from a snapshot.
defun( vfpConnTermMap (snap)
  let( (out)
    foreach( r vfpAlistGet(snap "instances")
      foreach( tn caddr(r)
        out = cons( list( sprintf(nil "%s.%s" car(r) car(tn)) cadr(tn) )
                    out )
      )
    )
    reverse(out)
  )
)

;; ((rawNetName . (member "inst.term" ...)) ...) for a snapshot.
defun( vfpConnNetMembers (snap)
  let( (acc entry)
    acc = nil
    foreach( pr vfpConnTermMap(snap)
      when( cadr(pr)
        entry = assoc(cadr(pr) acc)
        if( entry
          then rplacd(entry cons(car(pr) cdr(entry)))
          else acc = cons( cons(cadr(pr) list(car(pr))) acc )
        )
      )
    )
    acc
  )
)

;; ((rawNetName canonicalName) ...): named nets keep their name; auto
;; nets canonicalize to their sorted member set. Two-element lists, not
;; dotted pairs — dotted pairs do not survive the bridge eval channel.
;; (Also: 3-arg `if` — the then/else keyword form does not parse in
;; argument position.)
defun( vfpConnCanonMap (snap)
  foreach( mapcar e vfpConnNetMembers(snap)
    list( car(e)
          if( vfpAutoNetP(car(e))
              strcat("~" buildString(sort(copy(cdr(e)) 'alphalessp) "|"))
              car(e) ) )
  )
)

;; Structural diff of two snapshots (A = before, B = after). Returns a
;; list of records, nil when the connectivity TOPOLOGY is identical
;; (auto-net renames alone do not count; see vfpConnAutoRenames):
;;   ('instRemoved name)            ('instAdded name)
;;   ('masterChanged name a b)      ('netChanged "inst.term" rawA rawB)
;; A param-only edit must produce nil; a detached or rerouted terminal
;; shows up as netChanged with its exact inst.term and raw net names.
defun( vfpConnectivityDiff (snapA snapB)
  let( (instsA instsB canonA canonB termsB diffs rb pb ca cb)
    instsA = vfpAlistGet(snapA "instances")
    instsB = vfpAlistGet(snapB "instances")
    canonA = vfpConnCanonMap(snapA)
    canonB = vfpConnCanonMap(snapB)
    termsB = vfpConnTermMap(snapB)
    diffs = nil
    ;; instance-level changes
    foreach( ra instsA
      rb = car(setof(r instsB equal(car(r) car(ra))))
      if( null(rb)
        then diffs = cons(list('instRemoved car(ra)) diffs)
        else
          unless( equal(cadr(ra) cadr(rb))
            diffs = cons(list('masterChanged car(ra) cadr(ra) cadr(rb)) diffs)
          )
      )
    )
    foreach( rb2 instsB
      unless( car(setof(r instsA equal(car(r) car(rb2))))
        diffs = cons(list('instAdded car(rb2)) diffs)
      )
    )
    ;; terminal-level: compare canonical nets
    foreach( pa vfpConnTermMap(snapA)
      pb = car(setof(x termsB equal(car(x) car(pa))))
      when( pb    ;; instance add/remove already reported above
        ca = and(cadr(pa) cadr(assoc(cadr(pa) canonA)))
        cb = and(cadr(pb) cadr(assoc(cadr(pb) canonB)))
        unless( equal(ca cb)
          diffs = cons(list('netChanged car(pa) cadr(pa) cadr(pb)) diffs)
        )
      )
    )
    reverse(diffs)
  )
)

;; Pure auto-net renames between two snapshots: same member set, both
;; auto-named, different name. The "auto-net fragility" signal — any
;; profile/proposal referencing the old name is now stale even though
;; the circuit is untouched. Returns list of ('autoNetRenamed a b).
defun( vfpConnAutoRenames (snapA snapB)
  let( (canonB out eb)
    canonB = vfpConnCanonMap(snapB)
    out = nil
    foreach( ea vfpConnCanonMap(snapA)
      eb = car(setof(e canonB equal(cadr(e) cadr(ea))))
      when( and( eb
                 !equal(car(ea) car(eb))
                 vfpAutoNetP(car(ea))
                 vfpAutoNetP(car(eb)) )
        out = cons(list('autoNetRenamed car(ea) car(eb)) out)
      )
    )
    reverse(out)
  )
)

;; ---- JSON ------------------------------------------------------------
;; vfpJObj form of a snapshot — embeddable in larger JSON trees (the
;; transaction record stores the pre-apply snapshot this way).
defun( vfpConnSnapJ (snap)
  vfpJObj(
    "schema_version" "0.1"
    "cellview" vfpAlistGet(snap "cellview")
    "instances" apply('vfpJArr
      foreach( mapcar r vfpAlistGet(snap "instances")
        vfpJObj( "name" car(r) "master" cadr(r)
                 "terms" apply('vfpJArr
                   foreach( mapcar tn caddr(r)
                     vfpJObj("term" car(tn) "net" cadr(tn)) )) )
      ))
    "named_nets" apply('vfpJArr vfpAlistGet(snap "named_nets"))
    "auto_nets"  apply('vfpJArr vfpAlistGet(snap "auto_nets"))
  )
)

defun( vfpConnectivityJson (cv)
  vfpToJson( vfpConnSnapJ( vfpSnapshotConnectivity(cv) ) )
)

;; Diff records as a JSON array form (kind/subject/before/after).
defun( vfpConnDiffJ (diffs)
  apply('vfpJArr
    foreach( mapcar d diffs
      vfpJObj( "kind"    vfpToStr(car(d))
               "subject" vfpToStr(cadr(d))
               "before"  caddr(d)
               "after"   cadr(cddr(d)) ) ))
)

;; Human-readable one-line-per-record rendering for logs and dialogs.
;; A terminal can change nets while the raw NAME stays the same (the
;; net kept its name but lost/gained members) — say so rather than
;; printing a confusing "net3 -> net3".
defun( vfpConnDiffText (diffs)
  buildString(
    foreach( mapcar d diffs
      if( and(caddr(d) equal(caddr(d) cadr(cddr(d))))
          sprintf(nil "%s %s: %s membership changed"
            vfpToStr(car(d)) vfpToStr(cadr(d)) vfpToStr(caddr(d)))
          sprintf(nil "%s %s: %s -> %s"
            vfpToStr(car(d)) vfpToStr(cadr(d))
            vfpToStr(caddr(d)) vfpToStr(cadr(cddr(d)))) ) )
    "\n")
)

;; ---- auto-net risk flags (context export) ----------------------------
;; The fragility (memory rfctsopa_autonet_label_fragility): a net Cadence
;; auto-names "net8" is renumbered to "net32" the moment a wire is added or
;; redrawn, so any proposal/profile keyed on "net8" silently misses. A net
;; is at risk when its name is auto-style AND it carries no explicit wire
;; label AND it actually bears instance terminals (load-bearing — an
;; unconnected stub is not worth flagging). vfpPinNetLabel clears the flag.
;;
;; Returns a list of (netName (inst.term ...)) records, ordered by first
;; appearance. Built off the snapshot's instance-terminal map, then the net
;; object is consulted for the label check (the snapshot does not carry it).
defun( vfpConnectivityRisks (cv)
  let( (members risks net)
    members = vfpConnNetMembers(vfpSnapshotConnectivity(cv))   ;; ((raw . (terms..)) ..)
    risks = nil
    foreach( e members
      when( vfpAutoNetP(car(e))
        net = car(setof(n cv~>nets n~>name == car(e)))
        unless( vfpNetLabeledP(net)
          risks = cons(list(car(e) reverse(cdr(e))) risks)
        )
      )
    )
    reverse(risks)
  )
)

;; JSON-array form for the context export (vfpJArr of risk objects).
defun( vfpConnRisksJ (cv)
  apply('vfpJArr
    foreach( mapcar r vfpConnectivityRisks(cv)
      vfpJObj( "net"       car(r)
               "kind"      "auto_net"
               "terminals" apply('vfpJArr cadr(r)) ) ))
)

;; ---- pin an auto net to an explicit label ----------------------------
;; "One-click" fix for the fragility above: glue a wire label so the name
;; survives schCheck. Glues to one of the net's wire figs at the midpoint
;; of its first segment. With newName the net is renamed to that label;
;; without it the current (auto) name is pinned in place. Pass cv to act on
;; a specific cellview (tests); defaults to the current edit cellview.
;; Returns the label id, or nil after logging why (no cellview / net not
;; found / no wire to glue to — a terminal-abutment net has no wire fig).
defun( vfpPinNetLabel (netName @optional newName cv)
  let( (net wire pts p0 p1 mid txt lbl)
    cv   = or(cv vfpGetCurrentCellView())
    net  = and(cv car(setof(n cv~>nets n~>name == netName)))
    wire = and(net car(setof(f net~>figs f~>objType == "line")))
    cond(
      ( null(cv)
        vfpError("vfpPinNetLabel: no editable cellview") )
      ( null(net)
        vfpError(sprintf(nil "vfpPinNetLabel: net %s not found" netName)) )
      ( null(wire)
        vfpError(sprintf(nil "vfpPinNetLabel: net %s has no wire to label" netName)) )
      ( t
        pts = wire~>points
        p0  = car(pts)
        p1  = cadr(pts)
        mid = list( (xCoord(p0) + xCoord(p1)) / 2.0
                    (yCoord(p0) + yCoord(p1)) / 2.0 )
        txt = or(newName netName)
        lbl = car(errset(
                schCreateWireLabel(cv wire mid txt
                  "lowerCenter" "R0" "stick" 0.0625 nil)))
        if( lbl
          then
            errset(schCheck(cv))
            dbSave(cv)
            vfpLog(sprintf(nil "pinned net %s as label %s" netName txt))
            lbl
          else
            vfpError(sprintf(nil "vfpPinNetLabel: could not label net %s" netName))
        )
      )
    )
  )
)

;; Rebuild snapshot form from an RPC payload (the JSON object comes back
;; from the tunnel as an alist of string keys). Inverse of vfpConnSnapJ;
;; used by rollback verification against the stored pre-apply snapshot.
defun( vfpConnSnapFromJson (j)
  when( j
    list(
      list("cellview" vfpAlistGet(j "cellview"))
      list("instances"
        foreach( mapcar r vfpAlistGet(j "instances")
          list( vfpAlistGet(r "name") vfpAlistGet(r "master")
                foreach( mapcar tn vfpAlistGet(r "terms")
                  list( vfpAlistGet(tn "term") vfpAlistGet(tn "net") ) ) )
        ))
      list("named_nets" vfpAlistGet(j "named_nets"))
      list("auto_nets"  vfpAlistGet(j "auto_nets"))
    )
  )
)
