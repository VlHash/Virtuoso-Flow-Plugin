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

defun( vfpEventBridgeDataH (cid data)
  let( (buf pos line sawEvent sawProposal sawNetlist)
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
