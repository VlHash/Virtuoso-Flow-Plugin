;; =====================================================================
;; vfp_layout.il — layout context export (L1) + geometry lint (L2) +
;;                 layout<->schematic LVS-lite (L3)
;; ---------------------------------------------------------------------
;; The SKILL half of the layout phase (the L1 tunnel/schema half landed in #63).
;; Read-only. L1: cell bbox, instance placement, per-layer shape counts, via
;; count. L2: a cheap geometry lint (unconnected device pins, net-less metal,
;; off-grid shapes) riding the layout block as `lint`. L3: an agent-readable
;; connectivity consistency check (LVS-lite) between a cell's layout and
;; schematic, riding the context as a top-level `lvs` block. The blocks ride
;; design.context.update like the schematic context; the tunnel stores and
;; validates it (schemas/context.schema.json `layout` / `lvs`, loose) and the
;; agent reads it (`vfp context show` / the MCP context_get tool).
;;
;; Field conventions per docs/layout_l1_plan.md + #63's schema:
;;   bbox   nested [[x0,y0],[x1,y1]] (lower-left, upper-right)
;;   origin [x,y] point ; orient string ; master "lib/cell/view" string
;;   layers [{layer, purpose, shapes:<int>}] ; vias <int> count ; units "um"
;; Routed nets are deferred to L3 (this stays a clean read).
;;
;; Loaded after vfp_utils.il (vfpJObj / vfpJArr / vfpToStr / vfpToJson /
;; vfpError) and vfp_rpc_client.il (vfpRpcExec, for the export path).
;; =====================================================================

;; ---- low-level JSON builders ----------------------------------------

;; A point -> JSON [x, y] (numbers, user units).
defun( vfpLayoutPointJ (pt)
  and( pt vfpJArr( xCoord(pt) yCoord(pt) ) )
)

;; A bBox (ll ur) -> JSON [[x0,y0],[x1,y1]].
defun( vfpLayoutBBoxJ (bb)
  and( bb vfpJArr( vfpLayoutPointJ(lowerLeft(bb))
                   vfpLayoutPointJ(upperRight(bb)) ) )
)

;; instances -> [{name, master, origin, orient, bbox}]
defun( vfpLayoutInstancesJ (cv)
  apply('vfpJArr
    foreach( mapcar inst cv~>instances
      vfpJObj(
        "name"   inst~>name
        "master" sprintf(nil "%s/%s/%s"
                   inst~>libName inst~>cellName inst~>viewName)
        "origin" vfpLayoutPointJ(inst~>xy)
        "orient" vfpToStr(inst~>orient)
        "bbox"   vfpLayoutBBoxJ(inst~>bBox) ) ) )
)

;; shapes -> [{layer, purpose, shapes:<count>}] bucketed by (layer, purpose).
;; A string-keyed count table (reliable) plus a separate key list for the
;; unique pairs, so we never depend on iterating the table's keys.
defun( vfpLayoutLayersJ (cv)
  let( (counts keys k)
    counts = makeTable('vfpLyr 0)
    keys = nil
    foreach( sh cv~>shapes
      k = sprintf(nil "%s|%s" sh~>layerName or(sh~>purpose "drawing"))
      when( zerop(counts[k]) keys = cons(k keys) )
      counts[k] = counts[k] + 1 )
    apply('vfpJArr
      foreach( mapcar key reverse(keys)
        let( (parts)
          parts = parseString(key "|")
          vfpJObj( "layer"   car(parts)
                   "purpose" cadr(parts)
                   "shapes"  counts[key] ) ) ) )
  )
)

;; ---- L2: layout geometry lint --------------------------------------
;; Cheap, read-only geometry checks (NOT a DRC sign-off): device pins on no
;; net, net-less metal (floating), and off-grid shapes. The layout analogue of
;; the testbench lint (vfpLintTestbench). Each issue is (kind subject detail).

defun( vfpLayoutMetalP (layer)
  and( layer stringp(layer) rexMatchp("^M[0-9]" layer) )   ;; M1, M2, ...
)

defun( vfpLayoutOnGridP (coord grid)
  let( (q)
    q = quotient(coord grid)
    lessp( abs(difference(q round(q))) 0.001 ) )
)

;; Any corner of a shape's bBox off the manufacturing grid?
defun( vfpLayoutOffGridP (bb grid)
  and( bb grid greaterp(grid 0.0)
    let( (ll ur)
      ll = lowerLeft(bb)  ur = upperRight(bb)
      not( and( vfpLayoutOnGridP(xCoord(ll) grid) vfpLayoutOnGridP(yCoord(ll) grid)
                vfpLayoutOnGridP(xCoord(ur) grid) vfpLayoutOnGridP(yCoord(ur) grid) ) ) ) )
)

;; Lint a layout cv -> list of (kind subject detail).
defun( vfpLayoutLint (cv)
  let( (issues grid)
    issues = nil
    grid = or( car(errset(techGetMfgGridResolution(techGetTechFile(cv)))) 0.001 )
    foreach( inst cv~>instances
      foreach( it inst~>instTerms
        unless( it~>net
          issues = cons( list('unconnectedPin
                              sprintf(nil "%s.%s" inst~>name and(it~>term it~>term~>name))
                              "device terminal on no net") issues ) ) ) )
    foreach( sh cv~>shapes
      ;; geometry only -- skip labels/text (net/pin annotations legitimately
      ;; carry no net and aren't "floating metal").
      when( not( or(equal(sh~>objType "label") equal(sh~>objType "text")) )
        when( and( null(sh~>net) vfpLayoutMetalP(sh~>layerName) )
          issues = cons( list('floatingMetal sh~>layerName
                              sprintf(nil "net-less %s on metal %s" sh~>objType sh~>layerName))
                         issues ) )
        when( vfpLayoutOffGridP(sh~>bBox grid)
          issues = cons( list('offGrid sh~>layerName
                              sprintf(nil "off-grid %s on %s" sh~>objType sh~>layerName))
                         issues ) ) ) )
    reverse(issues)
  )
)

;; Lint as JSON [{kind, subject, detail}] for the context layout block.
defun( vfpLayoutLintJ (cv)
  apply('vfpJArr
    foreach( mapcar iss vfpLayoutLint(cv)
      vfpJObj( "kind"    vfpToStr(car(iss))
               "subject" cadr(iss)
               "detail"  caddr(iss) ) ) )
)

;; ---- readers (names match #63's schema descriptions) ----------------

;; Common (summary-level) fields, as a flat k/v list for `apply('vfpJObj ...)`.
defun( vfpLayoutCommonKV (cv)
  list(
    "cellview" vfpJObj("lib" cv~>libName "cell" cv~>cellName "view" cv~>viewName)
    "bbox"     vfpLayoutBBoxJ(cv~>bBox)
    "units"    "um"
    "layers"   vfpLayoutLayersJ(cv)
    "vias"     or(car(errset(length(cv~>vias))) 0) )
)

;; Lightweight summary: cell bbox + layer/shape counts + via count (no
;; per-instance placement).
defun( vfpLayoutReadSummary (cv)
  and( cv apply('vfpJObj vfpLayoutCommonKV(cv)) )
)

;; Full L1 read: the summary plus per-instance placement (origin/orient/bbox).
;; This is the block exported as context.layout.
defun( vfpLayoutReadGeometry (cv)
  and( cv apply('vfpJObj
                 append( vfpLayoutCommonKV(cv)
                         list("instances" vfpLayoutInstancesJ(cv)
                              "lint"      vfpLayoutLintJ(cv)) )) )
)

;; ---- open + export --------------------------------------------------

;; Open <lib>/<cell>/<view> (default layout) read-only -> its full layout
;; block, or nil. Always closes the read handle (no lock).
defun( vfpExtractLayoutContext (lib cell @key (view "layout"))
  let( (cv res)
    cv = car(errset( dbOpenCellViewByType(lib cell view "" "r") ))
    unless( cv
      vfpError(sprintf(nil "vfpExtractLayoutContext: cannot open %s/%s/%s"
                       lib cell view))
      return(nil) )
    res = car(errset( vfpLayoutReadGeometry(cv) ))
    errset( dbClose(cv) )
    unless( res
      vfpError(sprintf(nil "vfpExtractLayoutContext: no layout block for %s/%s/%s"
                       lib cell view)) )
    res
  )
)

;; Build a context { cellview, layout } and send it to the tunnel
;; (design.context.update), reusing the schematic-context send path.
defun( vfpExportLayoutContext (lib cell @key (view "layout"))
  let( (block json pf res)
    block = vfpExtractLayoutContext(lib cell ?view view)
    unless( block return(nil) )
    json = vfpToJson( vfpJObj("context"
             vfpJObj( "cellview" vfpJObj("lib" lib "cell" cell "view" view)
                      "layout"   block )) )
    pf = sprintf(nil "%s/layoutctx_%d.json" vfpHelperOutDir() vfpRpcSeq())
    unless( vfpWriteFile(pf json)
      vfpError("vfpExportLayoutContext: could not write context file")
      return(nil) )
    res = vfpRpcExec("design.context.update" list("--params-file" pf))
    errset( deleteFile(pf) )
    res
  )
)

;; =====================================================================
;; L3 — layout <-> schematic consistency (LVS-lite)
;; ---------------------------------------------------------------------
;; The layout-phase differentiator: a cheap, agent-readable check that the
;; layout's connectivity matches the schematic's. NOT a sign-off LVS — a
;; *connectivity* consistency check. Reuses the schematic snapshot machinery
;; (vfpSnapshotConnectivity + vfpConnNetMembers/vfpConnTermMap, M11): the
;; layout dbObject exposes the same instTerm/net API, so the connectivity-
;; driven case (instTerms already carry nets) reads straight through.
;; Raw drawn layouts with no instTerm/shape nets need geometry net extraction
;; and are deferred (per docs/layout_l3_plan.md).
;; =====================================================================

;; The layout analogue of vfpSnapshotConnectivity. Layout instances expose the
;; same ~>instTerms / it~>net / it~>term API as schematic instances, so the
;; generic snapshot reads a connectivity-driven layout directly. Kept as a
;; named entry point so the L3 call sites read intent (and so a future
;; geometry-extraction path has one place to diverge).
defun( vfpLayoutSnapshotConnectivity (cv)
  vfpSnapshotConnectivity(cv)
)

;; Instance name of an "inst.term" string (substring before the first '.').
;; First increment is flat (top-level instTerms), so inst names carry no dots.
defun( vfpLvsInstOf (instTerm)
  car( parseString(instTerm ".") )
)

;; A schematic pin/port symbol? Pins are basic-lib ipin/opin/iopin instances
;; — they exist as schematic instances but NOT as layout device instances
;; (layout pins are shapes/labels). Excluding them keeps every schematic from
;; flagging its pins as "only in schematic". (Live finding on Project/inv.)
defun( vfpLvsPinCellP (cellName)
  and( stringp(cellName) member(cellName '("ipin" "opin" "iopin")) t )
)

;; Cell name out of a snapshot master id ("lib/cell/view" from vfpCvId).
defun( vfpLvsCellOfMaster (masterId)
  and( masterId cadr(parseString(masterId "/")) )
)

;; Device instance names in a snapshot, pins excluded.
defun( vfpLvsDeviceNames (snap)
  let( (out)
    foreach( r vfpAlistGet(snap "instances")        ;; (name masterId terms)
      unless( vfpLvsPinCellP(vfpLvsCellOfMaster(cadr(r)))
        out = cons(car(r) out) ) )
    reverse(out)
  )
)

;; For a snapshot, map each inst.term in keepTerms -> the sorted set of its
;; co-connected inst.terms, restricted to keepTerms. Net *names* differ
;; between layout and schematic, so consistency is judged by membership, not
;; name. keepTerms is the SHARED inst.term universe (terms present in both
;; views, devices only): so a terminal the layout master simply omits — most
;; commonly a MOS bulk, tied to substrate via a tap rather than a drawn net —
;; does not pollute the groups of terminals that do exist on both sides.
;; A nil-net (floating) term groups to itself. Returns ((inst.term (member ...)) ...).
defun( vfpLvsTermGroups (snap keepTerms)
  let( (members out grp)
    members = vfpConnNetMembers(snap)        ;; ((rawNet . (inst.term ...)) ...)
    foreach( pr vfpConnTermMap(snap)         ;; (inst.term rawNet|nil)
      when( member(car(pr) keepTerms)
        grp = if( cadr(pr)
                  cdr(assoc(cadr(pr) members))
                  list(car(pr)) )
        grp = setof( m grp member(m keepTerms) )
        out = cons( list(car(pr) sort(copy(grp) 'alphalessp)) out ) ) )
    reverse(out)
  )
)

;; Compare a cell's layout connectivity against its schematic. Returns an
;; alist (plain data; the JSON/text renderers consume it):
;;   ("schematic" (lib cell view)) ("layout" (lib cell view))
;;   ("status" "clean"|"issues")   ("matched" <int>)
;;   ("only_in_layout" (name ...)) ("only_in_schematic" (name ...))
;;   ("net_mismatches" ((inst.term (schGroup) (layGroup)) ...))
;; Devices match by instance name, pins excluded (first increment). For every
;; inst.term shared by both views, its net-group (membership over the shared
;; term universe) must agree.
defun( vfpLayoutVsSchematic (layoutCv schematicCv)
  let( (lsnap ssnap lDev sDev matched onlyL onlyS
        lTerms sTerms shared lGroups sGroups mism sg lg)
    lsnap = vfpLayoutSnapshotConnectivity(layoutCv)
    ssnap = vfpSnapshotConnectivity(schematicCv)
    lDev = vfpLvsDeviceNames(lsnap)
    sDev = vfpLvsDeviceNames(ssnap)
    matched = setof( n sDev member(n lDev) )
    onlyL   = setof( n lDev not(member(n sDev)) )
    onlyS   = setof( n sDev not(member(n lDev)) )
    ;; shared inst.term universe: a matched-device terminal present on both sides
    lTerms = foreach( mapcar p vfpConnTermMap(lsnap) car(p) )
    sTerms = foreach( mapcar p vfpConnTermMap(ssnap) car(p) )
    shared = setof( tnm sTerms
              and( member(vfpLvsInstOf(tnm) matched) member(tnm lTerms) ) )
    lGroups = vfpLvsTermGroups(lsnap shared)
    sGroups = vfpLvsTermGroups(ssnap shared)
    mism = nil
    foreach( tnm shared
      sg = car(setof(x sGroups equal(car(x) tnm)))
      lg = car(setof(x lGroups equal(car(x) tnm)))
      when( and(sg lg)
        unless( equal(cadr(sg) cadr(lg))
          mism = cons(list(tnm cadr(sg) cadr(lg)) mism) ) ) )
    mism = reverse(mism)
    list(
      list("schematic" list(schematicCv~>libName schematicCv~>cellName schematicCv~>viewName))
      list("layout"    list(layoutCv~>libName layoutCv~>cellName layoutCv~>viewName))
      list("status"    if(and(null(onlyL) null(onlyS) null(mism)) "clean" "issues"))
      list("matched"   length(matched))
      list("only_in_layout"    onlyL)
      list("only_in_schematic" onlyS)
      list("net_mismatches"    mism)
    )
  )
)

;; A (lib cell view) list -> JSON cellview object {lib, cell, view}.
defun( vfpLvsCvJ (lcv)
  vfpJObj( "lib" car(lcv) "cell" cadr(lcv) "view" caddr(lcv) )
)

;; The `lvs` JSON block for the context export (consumes vfpLayoutVsSchematic).
defun( vfpLayoutVsSchematicJ (res)
  and( res
    vfpJObj(
      "schema_version" "0.1"
      "schematic" vfpLvsCvJ(vfpAlistGet(res "schematic"))
      "layout"    vfpLvsCvJ(vfpAlistGet(res "layout"))
      "status"    vfpAlistGet(res "status")
      "devices"   vfpJObj(
        "matched"            vfpAlistGet(res "matched")
        "only_in_layout"     apply('vfpJArr vfpAlistGet(res "only_in_layout"))
        "only_in_schematic"  apply('vfpJArr vfpAlistGet(res "only_in_schematic")) )
      "net_mismatches" apply('vfpJArr
        foreach( mapcar m vfpAlistGet(res "net_mismatches")
          vfpJObj( "inst_term"       car(m)
                   "schematic_group" apply('vfpJArr cadr(m))
                   "layout_group"    apply('vfpJArr caddr(m)) ) )) )
  )
)

;; Human-readable one-line-per-issue rendering for logs and dialogs.
defun( vfpLayoutVsSchematicText (res)
  buildString(
    append(
      foreach( mapcar n vfpAlistGet(res "only_in_layout")
        sprintf(nil "only in layout: %s" n) )
      foreach( mapcar n vfpAlistGet(res "only_in_schematic")
        sprintf(nil "only in schematic: %s" n) )
      foreach( mapcar m vfpAlistGet(res "net_mismatches")
        sprintf(nil "net mismatch %s: sch %L vs lay %L"
          car(m) cadr(m) caddr(m)) ) )
    "\n")
)

;; ---- open + export --------------------------------------------------

;; Open <lib>/<cell> layout + schematic read-only, diff connectivity, close
;; both. Returns the `lvs` JSON block (string), or nil after logging why.
defun( vfpExtractLvs (lib cell @key (layoutView "layout") (schView "schematic"))
  let( (lcv scv res)
    lcv = car(errset( dbOpenCellViewByType(lib cell layoutView "" "r") ))
    scv = car(errset( dbOpenCellViewByType(lib cell schView "" "r") ))
    unless( and(lcv scv)
      errset( and(lcv dbClose(lcv)) )
      errset( and(scv dbClose(scv)) )
      vfpError(sprintf(nil "vfpExtractLvs: cannot open %s/%s (%s + %s)"
                       lib cell layoutView schView))
      return(nil) )
    res = car(errset( vfpLayoutVsSchematicJ(vfpLayoutVsSchematic(lcv scv)) ))
    errset( dbClose(lcv) )
    errset( dbClose(scv) )
    unless( res
      vfpError(sprintf(nil "vfpExtractLvs: no lvs block for %s/%s" lib cell)) )
    res
  )
)

;; Build a context { cellview (=layout), lvs } and send it to the tunnel
;; (design.context.update), reusing the schematic-context send path.
defun( vfpExportLvsContext (lib cell @key (layoutView "layout") (schView "schematic"))
  let( (block json pf res)
    block = vfpExtractLvs(lib cell ?layoutView layoutView ?schView schView)
    unless( block return(nil) )
    json = vfpToJson( vfpJObj("context"
             vfpJObj( "cellview" vfpJObj("lib" lib "cell" cell "view" layoutView)
                      "lvs"      block )) )
    pf = sprintf(nil "%s/lvsctx_%d.json" vfpHelperOutDir() vfpRpcSeq())
    unless( vfpWriteFile(pf json)
      vfpError("vfpExportLvsContext: could not write context file")
      return(nil) )
    res = vfpRpcExec("design.context.update" list("--params-file" pf))
    errset( deleteFile(pf) )
    res
  )
)
