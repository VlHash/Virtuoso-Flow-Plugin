;; =====================================================================
;; vfp_sim.il — simulation pre-flight: dirty-check + inputs fingerprint
;; ---------------------------------------------------------------------
;; The single most expensive sim failure is running on a STALE netlist:
;; the schematic was edited but not saved, so createNetlist either fails
;; or silently reuses yesterday's deck (the 996µA ghost-regression chain).
;; Only the in-Virtuoso plugin can see a cellview's unsaved state, so the
;; dirty-check lives here and gates every netlist/job.
;;
;;   vfpCellViewDirty(cv)        unsaved changes on this cellview?
;;   vfpCellViewDirtyHier(cv)    ...or on any open sub-master
;;   vfpInputsFingerprint(cv t)  content digest (params+conn+test) — the
;;                               authoritative fingerprint the tunnel's
;;                               freshness guard reuses (its own fallback
;;                               keys on lib/cell/view+test only, so an
;;                               edited param would wrongly reuse a result)
;;   vfpSimPreflight(cv t)       {ready, dirty, cellview, fingerprint, reason}
;;
;; Loaded after vfp_connectivity.il (uses vfpCvId / vfpJObj / vfpToStr).
;; =====================================================================

;; Unsaved changes on this cellview? dbIsCellViewModified is true from the
;; first edit until save (and flips back to nil when every change is undone).
defun( vfpCellViewDirty (cv)
  and( cv car(errset( dbIsCellViewModified(cv) )) t )
)

;; Dirty including the hierarchy: the target cellview, or any of its
;; instance masters that are open and modified (a sub-circuit edited but
;; not saved would netlist stale just the same). PDK device masters are
;; read-only and never report dirty, so they cost nothing here.
defun( vfpCellViewDirtyHier (cv)
  or( vfpCellViewDirty(cv)
      and( cv
           exists( inst cv~>instances
                   vfpCellViewDirty(inst~>master) ) ) )
)

;; Canonical content string of the design inputs: the test name, every
;; instance terminal's net, and every instance's master + EXPLICIT params,
;; each list sorted so the string is order-independent.
;;
;; Explicit params = inst~>prop (the overrides that actually reach the
;; netlist), NOT the 200+ expanded CDF parameters — on a real 27-instance
;; bench the full CDF blob was 25 KB, almost all of it untouched PDK
;; defaults. Any edit lands in inst~>prop (verified: setting R0.r adds
;; ("r" "9K")), so every CHANGE still moves the fingerprint; identical
;; untouched defaults stay out, which is safe (same defaults => same sim).
;; Fed verbatim to job.create as inputs_fingerprint (freshness guard == ).
defun( vfpInputsFingerprint (cv @optional (test ""))
  let( (terms parts)
    terms = nil
    when( cv
      foreach( inst cv~>instances
        foreach( it inst~>instTerms
          terms = cons( sprintf(nil "%s.%s=%s" inst~>name it~>term~>name
                          if(it~>net it~>net~>name "")) terms ) ) ) )
    terms = sort(terms 'alphalessp)
    parts = nil
    when( cv
      foreach( inst cv~>instances
        let( (pp)
          pp = nil
          foreach( p inst~>prop
            pp = cons( sprintf(nil "%s=%s" p~>name vfpToStr(p~>value)) pp ) )
          parts = cons( sprintf(nil "%s:%s[%s]" inst~>name inst~>cellName
                          buildString(sort(pp 'alphalessp) ",")) parts ) ) ) )
    parts = sort(parts 'alphalessp)
    sprintf(nil "test=%s;conn=%s;params=%s"
      vfpToStr(test) buildString(terms "|") buildString(parts "|"))
  )
)

;; Pre-flight a netlist/sim of `cv`: bundle the dirty verdict, the inputs
;; fingerprint, and a ready flag. ready is nil when the cellview is dirty,
;; with a reason that names the cellview (so the caller can refuse the
;; netlist or save first — never silently netlist a stale schematic).
defun( vfpSimPreflight (cv @optional (test ""))
  let( (cvid dirty)
    cvid  = vfpCvId(cv)
    dirty = vfpCellViewDirtyHier(cv)
    list(
      list("ready"       if(dirty nil t))
      list("dirty"       if(dirty t nil))
      list("cellview"    cvid)
      list("fingerprint" vfpInputsFingerprint(cv test))
      list("reason"      if(dirty
                            sprintf(nil "%s has unsaved changes; save before netlisting" cvid)
                            ""))
    )
  )
)

;; JSON object form of the pre-flight (for context export / a sim RPC).
defun( vfpSimPreflightJson (cv @optional (test ""))
  let( (pf)
    pf = vfpSimPreflight(cv test)
    vfpJObj(
      "ready"       if(vfpAlistGet(pf "ready") 'true 'false)
      "dirty"       if(vfpAlistGet(pf "dirty") 'true 'false)
      "cellview"    vfpAlistGet(pf "cellview")
      "fingerprint" vfpAlistGet(pf "fingerprint")
      "reason"      vfpAlistGet(pf "reason")
    )
  )
)

;; ---- M10b attended netlist: assemble a complete deck in this session ----
;; The VFP loop must sim the CURRENT design, never a stale netlist. A complete
;; spectre deck (design + PDK models + analyses + options) only comes from the
;; ADE/maestro netlister, so we trigger maeCreateNetlistForCorner INSIDE this
;; live Virtuoso session — reusing the session's framework license (no separate
;; `si`/Virtuoso checkout). The headless wrapper then sims the deck.

;; Base dir for attended netlists; the wrapper derives the same per-cellview
;; path, so override BOTH with the shared VFP_NETLIST_DIR env.
defun( vfpNetlistDir ()
  or( getShellEnvVar("VFP_NETLIST_DIR") "/tmp/vfp_nl" )
)

;; Per-cellview deck dir, matching the wrapper convention
;; <base>/<lib>__<cell>__<view> (maeCreateNetlistForCorner writes
;; <dir>/netlist/input.scs under it).
defun( vfpNetlistCvDir (cv)
  sprintf(nil "%s/%s__%s__%s" vfpNetlistDir() cv~>libName cv~>cellName cv~>viewName)
)

;; Assemble a complete deck for cv via its maestro session; return the deck
;; path (<dir>/netlist/input.scs) or nil. Best-effort: needs the mae* API and a
;; maestro setup on cv's cell. Opens a background session and always closes it
;; (force) so no edit lock leaks.
defun( vfpNetlistCellView (cv @key (corner "Nominal"))
  prog( (lib cell od session test deck)
    unless( cv vfpError("vfpNetlistCellView: no cellview") return(nil) )
    unless( fboundp('maeCreateNetlistForCorner)
      vfpError("vfpNetlistCellView: mae* netlister unavailable")
      return(nil) )
    lib  = cv~>libName
    cell = cv~>cellName
    unless( and(lib cell cv~>viewName)
      vfpError("vfpNetlistCellView: incomplete cellview")
      return(nil) )
    od = vfpNetlistCvDir(cv)
    errset( system(sprintf(nil "rm -rf '%s'" od)) )
    session = car(errset( maeOpenSetup(lib cell "maestro") ))
    unless( and(session stringp(session))
      vfpError(sprintf(nil "vfpNetlistCellView: maeOpenSetup failed for %s/%s" lib cell))
      return(nil) )
    test = car(errset( car(maeGetSetup(?session session)) ))
    when( test
      errset( maeCreateNetlistForCorner(test corner od ?session session) ) )
    errset( maeCloseSession(?session session ?forceClose t) )
    unless( test
      vfpError("vfpNetlistCellView: no test in maestro setup")
      return(nil) )
    deck = sprintf(nil "%s/netlist/input.scs" od)
    when( isFile(deck)
      vfpLog(sprintf(nil "attended netlist %s/%s -> %s (corner %s)" lib cell deck corner))
      return(deck) )
    vfpError(sprintf(nil "vfpNetlistCellView: no deck produced at %s" deck))
    return(nil)
  )
)

;; M10c: the cellview's last-saved time -> provenance.saved_at. ddGetObjLastModify
;; on the view returns a human-readable string like "Oct 13 08:30:26 2025"; nil
;; if the view can't be resolved.
defun( vfpCvSavedAt (cv)
  and( cv
       car(errset(
         ddGetObjLastModify( ddGetObj(cv~>libName cv~>cellName cv~>viewName) ) )) )
)

;; ---- run a sim job (M9 closed loop) ---------------------------------
;; Pre-flight (dirty-check + content fingerprint), then create + run a sim
;; job on the tunnel. The fingerprint is ours (content-based), so the
;; tunnel's freshness guard reuses a prior *done* job for identical inputs
;; instead of re-running — we detect that by the returned job already being
;; "done" (a fresh create returns "queued", which we then job.run). Refuses
;; a dirty cellview so we never sim a stale netlist. Returns (job_id reused)
;; or nil.
defun( vfpRunSimJob (cv @optional (test "tran") @key (attended nil) (corner "Nominal"))
  prog( (pf sid jjson pfile res ok payload job jid jstatus rr)
    unless( cv
      vfpError("vfpRunSimJob: no cellview")
      return(nil) )
    pf = vfpSimPreflight(cv test)
    when( vfpAlistGet(pf "dirty")
      vfpError(vfpAlistGet(pf "reason"))
      return(nil) )
    ;; M10b attended: assemble a fresh complete deck in THIS live session
    ;; (license reused) so the headless wrapper sims the current design. The
    ;; deck lands at the convention path the wrapper derives from the cellview.
    when( attended
      unless( vfpNetlistCellView(cv ?corner corner)
        return(nil) ) )
    ;; M10a: carry the M8 session_id at the params level so the tunnel can
    ;; resolve provenance.session from its registry (harmless until read).
    sid = or(vfpStateGet('sessionId) "")
    jjson = vfpToJson( vfpJObj(
              "session_id" sid
              "job" vfpJObj(
                "cellview" vfpJObj("lib"  cv~>libName
                                   "cell" cv~>cellName
                                   "view" cv~>viewName)
                "test"               test
                "inputs_fingerprint" vfpAlistGet(pf "fingerprint")
                "saved_at"           or(vfpCvSavedAt(cv) ""))) )
    pfile = sprintf(nil "%s/job_%d.json" vfpHelperOutDir() vfpRpcSeq())
    unless( vfpWriteFile(pfile jjson)
      vfpError("vfpRunSimJob: could not write job file")
      return(nil) )
    res = vfpRpcExec("job.create" list("--params-file" pfile))
    errset(deleteFile(pfile))
    ok = car(res)
    payload = cadr(res)
    unless( ok
      vfpError(sprintf(nil "job.create failed: %s" vfpFmtError(payload)))
      return(nil) )
    job     = vfpAlistGet(payload "job")
    jid     = vfpAlistGet(job "job_id")
    jstatus = vfpAlistGet(job "status")
    ;; a reused done job needs no run
    when( equal(jstatus "done")
      vfpLog(sprintf(nil "reused fresh job %s (identical inputs)" jid))
      return(list(jid t)) )
    rr = vfpRpcExec("job.run" list("--param" sprintf(nil "job_id=%s" jid)
                                   "--param" sprintf(nil "session_id=%s" sid)))
    return(
      if( car(rr)
        then vfpLog(sprintf(nil "started sim job %s" jid)) list(jid nil)
        else vfpError(sprintf(nil "job.run failed: %s" vfpFmtError(cadr(rr)))) nil
      )
    )
  )
)

;; Current status of a job (queued/running/done/failed/cancelled) or nil.
defun( vfpJobStatus (jid)
  let( (res)
    res = vfpRpcExec("job.get" list("--param" sprintf(nil "job_id=%s" jid)))
    and( car(res) vfpAlistGet(vfpAlistGet(cadr(res) "job") "status") )
  )
)
