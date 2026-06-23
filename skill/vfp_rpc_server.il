;; =====================================================================
;; vfp_rpc_server.il — tunnel→Virtuoso event bridge
;; ---------------------------------------------------------------------
;; SKILL cannot listen on a socket, and hiRegTimer never fires in this
;; build, so neither a real push listener nor a timer poll is possible.
;; What does work (verified live; see AGENTS.md): ipcBeginProcess data
;; handlers fire asynchronously, per output line, while the child is
;; still alive. The bridge therefore spawns a persistent helper
;; (scripts/vfp_event_client.py) that long-polls the tunnel and prints
;; one line per event:
;;
;;     VFP-EVT <seq> <type>
;;
;; The data handler below parses those lines and refreshes the GUI.
;; The bridge is started after vfpConnect succeeds and stopped by
;; vfpDisconnect / vfpUnload. While the tunnel has no event RPCs
;; (event.list / event.wait), the helper exits 0 quietly and the rest
;; of the plugin is unaffected.
;; =====================================================================

;; The spawn command. Override with vfpStateSet('eventClientCmd "...")
;; — gui_test uses that to point at a mock. NOTE: ipc command strings
;; with nested quotes fail silently (AGENTS.md), so this is built
;; unquoted; the repo and python paths must not contain spaces.
defun( vfpEventClientCmd ()
  let( (sid)
    sid = vfpStateGet('sessionId)
    or( vfpStateGet('eventClientCmd)
        sprintf(nil
          "env -u PYTHONHOME LD_LIBRARY_PATH= PYTHONPATH=%s %s %s/scripts/vfp_event_client.py --since %d%s"
          vfpTunnelDir() vfpRpcPython() vfpRepoRoot()
          or(vfpStateGet('eventLastSeq) 0)
          ;; The long-poll doubles as the session heartbeat (M8).
          if( sid sprintf(nil " --session-id %s" sid) ""))
    )
  )
)

defun( vfpEventBridgeRunning () and(vfpStateGet('eventBridgePid) t) )

defun( vfpEventBridgeStart ()
  if( vfpEventBridgeRunning()
    then
      vfpLog("event bridge already running") t
    else
      let( (cmd pid)
        cmd = vfpEventClientCmd()
        vfpStateSet('eventBuf "")
        pid = car(errset( ipcBeginProcess(cmd "" 'vfpEventBridgeDataH
                            'vfpEventBridgeErrH 'vfpEventBridgeExitH) ))
        if( pid
          then
            vfpStateSet('eventBridgePid pid)
            ;; announce the layout namespace so clients can discover + drive it
            when( isCallable('vfpRegisterLayoutExtension)
              errset(vfpRegisterLayoutExtension()) )
            vfpLog("event bridge started")
            t
          else
            vfpError("event bridge failed to start")
            nil
        )
      )
  )
)

defun( vfpEventBridgeStop ()
  let( (pid)
    pid = vfpStateGet('eventBridgePid)
    when( pid errset(ipcKillProcess(pid)) )
    vfpStateSet('eventBridgePid nil)
    vfpStateSet('eventBuf "")
    when( pid vfpLog("event bridge stopped") )
    t
  )
)

;; ---- ipc handlers ----------------------------------------------------
;; Data arrives in arbitrary chunks: buffer, consume complete lines, keep
;; the trailing partial line. One GUI refresh per chunk, not per line.
;; Service pending netlist requests from the tunnel: for each, assemble the deck
;; (vfpNetlistCellView) and report it back via netlist.complete. Driven by the
;; netlist.request event -- delegated netlist over VFP's OWN channel (no vcli).
defun( vfpServiceNetlistRequests ()
  let( (res reqs)
    res = vfpRpcExec("netlist.pending" nil)
    when( car(res)
      reqs = vfpAlistGet(cadr(res) "requests")
      foreach( req reqs
        let( (rid cv lib cell view corner deck)
          rid    = vfpAlistGet(req "request_id")
          cv     = vfpAlistGet(req "cellview")
          lib    = vfpAlistGet(cv "lib")
          cell   = vfpAlistGet(cv "cell")
          view   = vfpAlistGet(cv "view")
          corner = or(vfpAlistGet(req "corner") "Nominal")
          deck   = and(lib cell view
                       vfpNetlistCellView(dbOpenCellViewByType(lib cell view "" "r")
                                          ?corner corner))
          when( rid
            if( deck
              vfpRpcExec("netlist.complete"
                list("--param" sprintf(nil "request_id=%s" rid)
                     "--param" sprintf(nil "deck=%s" deck)))
              vfpRpcExec("netlist.complete"
                list("--param" sprintf(nil "request_id=%s" rid)
                     "--param" "error=netlist failed")) ) )
        )
      )
    )
    t
  )
)

;; ---- generic extension API: the "layout" servicer --------------------
;; Expose the L1-L5 layout capabilities to ANY tunnel client (a CLI, an MCP/LLM
;; controller, another process) through the generic action channel. We announce
;; a "layout" namespace (extension.register) and service its action.request
;; events: each action's method is dispatched to a layout function and the
;; result posted with action.complete. The tunnel only routes -- a write action
;; runs through the L4 transaction engine (reversible), never blind. Mirrors
;; vfpServiceNetlistRequests.

;; Announce the layout namespace + its methods so clients can discover it.
defun( vfpRegisterLayoutExtension ()
  let( (json pf res)
    json = vfpToJson( vfpJObj(
      "namespace"   "layout"
      "methods"     vfpJArr("runPrimitive" "exportContext" "lvs" "rollback")
      "description" "layout read (context/lvs) + parameter-driven geometry primitives, applied as reversible transactions") )
    pf = sprintf(nil "%s/extreg_%d.json" vfpHelperOutDir() vfpRpcSeq())
    if( vfpWriteFile(pf json)
      then
        res = vfpRpcExec("extension.register" list("--params-file" pf))
        errset(deleteFile(pf))
        res
      else nil
    )
  )
)

;; Dispatch one layout action -> (resultObj errStr); exactly one is non-nil.
;; resultObj is a vfpJObj tree (serialized when posted back).
defun( vfpDispatchLayoutAction (method params)
  let( (lib cell view)
    lib  = vfpAlistGet(params "lib")
    cell = vfpAlistGet(params "cell")
    view = or( vfpAlistGet(params "view") "layout" )
    cond(
      ( equal(method "runPrimitive")
        list( vfpLayoutRunPrimitive(vfpAlistGet(params "name") params
                                    vfpAlistGet(params "dry_run"))
              nil ) )
      ( equal(method "exportContext")
        list( vfpExtractLayoutContext(lib cell ?view view) nil ) )
      ( equal(method "lvs")
        list( vfpExtractLvs(lib cell) nil ) )
      ( equal(method "rollback")
        let( (tid ok)
          tid = vfpAlistGet(params "transaction_id")
          ok  = and(tid vfpLayoutTxnRollback(tid))
          list( vfpJObj("rolled_back" if(ok 'true 'false) "transaction_id" or(tid ""))
                nil ) ) )
      ( t list( nil sprintf(nil "unknown layout method: %s" method) ) )
    )
  )
)

;; Post an action's outcome: a result object, or an error string.
defun( vfpActionComplete (aid resultObj @optional errStr)
  let( (params json pf res)
    params = if( errStr
                 vfpJObj("action_id" aid "error" errStr)
                 vfpJObj("action_id" aid "result" resultObj) )
    json = vfpToJson(params)
    pf = sprintf(nil "%s/actcplt_%d.json" vfpHelperOutDir() vfpRpcSeq())
    if( vfpWriteFile(pf json)
      then
        res = vfpRpcExec("action.complete" list("--params-file" pf))
        errset(deleteFile(pf))
        res
      else nil
    )
  )
)

;; Service pending "layout" actions: dispatch each, then action.complete.
;; Driven by the action.request event (vfpEventBridgeDataH).
defun( vfpServiceActionRequests ()
  let( (res acts)
    res = vfpRpcExec("action.pending" list("--param" "namespace=layout"))
    when( car(res)
      acts = vfpAlistGet(cadr(res) "actions")
      foreach( act acts
        let( (aid method params disp resultObj errStr)
          aid    = vfpAlistGet(act "action_id")
          method = vfpAlistGet(act "method")
          params = vfpAlistGet(act "params")
          disp = car(errset( vfpDispatchLayoutAction(method params) ))
          resultObj = and(disp car(disp))
          errStr    = if(disp cadr(disp) "layout action raised an error")
          when( aid
            if( or(resultObj errStr)
              then vfpActionComplete(aid resultObj errStr)
              else vfpActionComplete(aid nil "layout action produced no result") ) )
        )
      )
    )
    t
  )
)

defun( vfpEventBridgeDataH (cid data)
  let( (buf pos line sawEvent sawProposal sawNetlist sawAction)
    cid  ;; unused
    buf = strcat( or(vfpStateGet('eventBuf) "") data )
    pos = nindex(buf "\n")
    while( pos
      line = if( pos > 1 substring(buf 1 pos-1) "" )
      buf  = if( pos < strlen(buf) substring(buf pos+1) "" )
      let( (toks seq type)
        toks = parseString(line " ")
        when( equal(car(toks) "VFP-EVT")
          seq  = and(cadr(toks) atoi(cadr(toks)))
          type = caddr(toks)
          when( seq vfpStateSet('eventLastSeq seq) )
          vfpLog(sprintf(nil "event %L: %s" seq or(type "?")))
          sawEvent = t
          when( and(type nindex(type "proposal.") == 1) sawProposal = t )
          when( equal(type "netlist.request") sawNetlist = t )
          when( equal(type "action.request") sawAction = t )
        )
      )
      pos = nindex(buf "\n")
    )
    vfpStateSet('eventBuf buf)
    when( sawEvent
      when( and(sawProposal isCallable('vfpFetchPendingProposals))
        errset(vfpFetchPendingProposals()) )
      when( and(sawNetlist isCallable('vfpServiceNetlistRequests))
        errset(vfpServiceNetlistRequests()) )
      when( and(sawAction isCallable('vfpServiceActionRequests))
        errset(vfpServiceActionRequests()) )
      when( isCallable('vfpUpdateDashboard) errset(vfpUpdateDashboard()) )
    )
    t
  )
)

defun( vfpEventBridgeErrH (cid data)
  cid  ;; unused
  vfpLog(sprintf(nil "event client: %s" data))
  t
)

defun( vfpEventBridgeExitH (cid status)
  cid  ;; unused
  vfpStateSet('eventBridgePid nil)
  vfpLog(sprintf(nil "event client exited (status %L)" status))
  t
)
