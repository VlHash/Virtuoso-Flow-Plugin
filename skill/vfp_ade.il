;; ADE interaction is best-effort: the asi* calls below target ADE-L and MUST
;; be confirmed in a live Virtuoso/ADE session. Every asi* call is wrapped in
;; errset so a missing/renamed API degrades to the tunnel run flow instead of
;; erroring. Result harvesting from raw sim output is simulator-specific, so
;; metrics are imported via `vfp run import-result` rather than parsed here.

defun( vfpAdeSession ()
  let( (win)
    win = hiGetCurrentWindow()
    and( win car(errset( asiGetCurrentSession(win) )) )
  )
)

defun( vfpGetAdeContext ()
  let( (s cv)
    s = vfpAdeSession()
    cv = vfpGetCurrentCellView()
    if( s
      then list( list("session" t) list("cellview" vfpCvId(cv)) )
      else nil
    )
  )
)

defun( vfpListAdeTests ()
  ;; ADE-L is single-test (the open ADE cellview). ADE-XL multi-test
  ;; enumeration needs the axl* API and is left for live verification.
  let( (s cv)
    s = vfpAdeSession()
    cv = vfpGetCurrentCellView()
    if( and(s cv) list(vfpCvId(cv)) nil )
  )
)

defun( vfpGetActiveAdeTest ()
  let( (cv)
    cv = vfpGetCurrentCellView()
    and( cv vfpCvId(cv) )
  )
)

;; Open a run record on the tunnel; returns (ok payload).
defun( vfpCreateRun (test lib cell)
  let( (json pf res)
    json = vfpToJson( vfpJObj(
      "run" vfpJObj(
        "test"     test
        "cellview" vfpJObj("lib" lib "cell" cell "view" "schematic")
      )))
    pf = sprintf(nil "%s/run_%d.json" vfpHelperOutDir() vfpRpcSeq())
    if( null(vfpWriteFile(pf json))
      then list(nil list(list("message" "could not write run file")))
      else
        res = vfpRpcExec("run.create" list("--params-file" pf))
        errset(deleteFile(pf))
        res
    )
  )
)

defun( vfpRunAdeTest (testName)
  prog( (cv test lib cell res ok payload run runId s)
    cv   = vfpGetCurrentCellView()
    test = or( testName and(cv vfpCvId(cv)) "ade_test" )
    lib  = if( cv vfpToStr(cv~>libName) "" )
    cell = if( cv vfpToStr(cv~>cellName) "" )

    ;; 1. Create a run record (gives an id to attach results to).
    res = vfpCreateRun(test lib cell)
    ok = car(res)
    payload = cadr(res)
    unless( ok
      hiDisplayAppDBox(?name 'vfpErrDBox
        ?dboxText sprintf(nil "Could not create run:\n%s" vfpFmtError(payload))
        ?buttonLayout 'Close)
      return(nil)
    )
    run   = vfpAlistGet(payload "run")
    runId = vfpAlistGet(run "run_id")

    ;; 2. Best-effort: trigger the ADE simulation if a session exists.
    s = vfpAdeSession()
    if( s
      then
        errset( asiRunSimulation(s) )
        vfpRpcExec("run.set_status"
          list("--param" sprintf(nil "run_id=%s" runId) "--param" "status=running"))
        hiDisplayAppDBox(?name 'vfpInfoDBox
          ?dboxText sprintf(nil "Run %s started (ADE session).\nWhen the sim finishes, import metrics:\n  vfp run import-result --run %s --file <metrics>"
            runId runId)
          ?buttonLayout 'Close)
      else
        hiDisplayAppDBox(?name 'vfpInfoDBox
          ?dboxText sprintf(nil "Run %s created (no ADE session detected).\nImport metrics when ready:\n  vfp run import-result --run %s --file <metrics>"
            runId runId)
          ?buttonLayout 'Close)
    )
    return(runId)
  )
)
