;; =====================================================================
;; vfp_rpc_client.il — JSON-RPC client to VFP Tunnel (via Python helper)
;; ---------------------------------------------------------------------
;; Base SKILL has no raw TCP sockets, so each call shells out (synchronously
;; via system()) to `python -m vfp_tunnel.skillrpc`, which connects to the
;; tunnel and writes the response back as a SKILL s-expression that we parse
;; with `read`. The helper resolves the tunnel endpoint from the daemon's
;; state file (or the default 127.0.0.1:47891), so SKILL passes no host/port.
;; =====================================================================

VFP_TUNNEL_HOST = "127.0.0.1"
VFP_TUNNEL_PORT = 47891

;; ---- paths / environment -------------------------------------------
defun( vfpRepoRoot ()
  if( and(boundp('VFP_SKILL_DIR) VFP_SKILL_DIR)
    then simplifyFilename(strcat(VFP_SKILL_DIR "/.."))
    else "."
  )
)

defun( vfpTunnelDir () strcat(vfpRepoRoot() "/tunnel") )

;; Absolute system python. Inside Virtuoso, PATH points `python3` at
;; Cadence's bundled interpreter (e.g. .../tools.lnx86/python/64bit), whose
;; libpython mismatches and fails with "undefined symbol:
;; _Py_LegacyLocaleDetected". Use the system python explicitly; override
;; with VFP_PYTHON if it lives elsewhere.
defun( vfpRpcPython () or(getShellEnvVar("VFP_PYTHON") "/usr/bin/python3") )

defun( vfpHelperOutDir ()
  let( (d)
    d = strcat( or(getShellEnvVar("TMPDIR") "/tmp") "/vfp_skill" )
    unless( isDir(d) system(sprintf(nil "mkdir -p '%s'" d)) )
    d
  )
)

;; Minimal single-quote shell wrapping. NOTE: argument values must not
;; contain a single quote (true for lib/cell/view/host identifiers).
defun( vfpShQuote (s) strcat("'" s "'") )

VFP_RPC_SEQ = 0
defun( vfpRpcSeq () VFP_RPC_SEQ = VFP_RPC_SEQ + 1 )

;; ---- core call ------------------------------------------------------
;; Returns list(ok payload): ok is t/nil; payload is an alist of
;; ("key" value) pairs (or a scalar / list, per the method).
defun( vfpRpcExec (method @optional (args nil))
  let( (out errf qargs cmd rc port datum)
    out  = sprintf(nil "%s/resp_%d.sx" vfpHelperOutDir() vfpRpcSeq())
    errf = strcat(vfpHelperOutDir() "/skillrpc.err")
    qargs = foreach(mapcar a args vfpShQuote(a))
    ;; Sanitize the environment Cadence pollutes: drop PYTHONHOME and clear
    ;; LD_LIBRARY_PATH so the system python uses its own libs, and pin
    ;; PYTHONPATH to the tunnel package.
    cmd = sprintf(nil "env -u PYTHONHOME LD_LIBRARY_PATH= PYTHONPATH=%s %s -m vfp_tunnel.skillrpc %s %s > %s 2>> %s"
                  vfpShQuote(vfpTunnelDir())
                  vfpShQuote(vfpRpcPython())
                  method
                  buildString(qargs " ")
                  vfpShQuote(out)
                  vfpShQuote(errf))
    vfpLog(sprintf(nil "rpc -> %s" method))
    rc = system(cmd)
    if( nequal(rc 0)
      then
        vfpError(sprintf(nil "rpc helper exec failed (rc=%L) for %s; see %s" rc method errf))
        list(nil list(list("code" -32000) list("message" "helper exec failed")))
      else
        port = infile(out)
        if( null(port)
          then list(nil list(list("message" "no helper output")))
          else
            datum = errset(read(port))
            close(port)
            errset(deleteFile(out))
            if( datum
              then car(datum)          ;; parsed (ok payload)
              else list(nil list(list("message" "parse error")))
            )
        )
    )
  )
)

;; ---- helpers --------------------------------------------------------
defun( vfpAlistGet (alist key)
  let( (val)
    foreach( pair alist
      when( and(listp(pair) stringp(car(pair)) equal(car(pair) key))
        val = cadr(pair)
      )
    )
    val
  )
)

defun( vfpFmtError (payload)
  let( (msg code)
    msg  = vfpAlistGet(payload "message")
    code = vfpAlistGet(payload "code")
    sprintf(nil "%s%s"
            if(msg msg "unknown error")
            if(code sprintf(nil " (code %L)" code) ""))
  )
)

;; Generic call: params is a list of ("key" "value") string pairs.
defun( vfpRpcCall (method @optional (params nil))
  let( (args)
    args = nil
    foreach( pair params
      args = append(args list("--param" sprintf(nil "%s=%s" car(pair) cadr(pair))))
    )
    vfpRpcExec(method args)
  )
)

;; ---- high-level operations -----------------------------------------
defun( vfpConnect ()
  let( (cv host res ok payload sid st sok spay)
    cv = vfpGetCurrentCellView()
    host = or(getShellEnvVar("HOSTNAME") getShellEnvVar("HOST") "")
    res = vfpRpcExec("session.register"
            list("--param" "client=virtuoso-flow-plugin"
                 "--param" strcat("lib="  if(cv cv~>libName ""))
                 "--param" strcat("cell=" if(cv cv~>cellName ""))
                 "--param" strcat("view=" if(cv cv~>viewName ""))
                 "--param" strcat("host=" host)))
    ok = car(res)
    payload = cadr(res)
    if( ok
      then
        sid = vfpAlistGet(payload "session_id")
        vfpStateSet('connected t)
        vfpStateSet('sessionId sid)
        vfpLog(sprintf(nil "connected to VFP Tunnel; session %s" sid))
        ;; Pull a one-line tunnel summary into the dashboard result area.
        st = vfpRpcExec("tunnel.status" nil)
        sok = car(st)
        spay = cadr(st)
        when( and(sok isCallable('vfpDashboardSetResult))
          vfpDashboardSetResult(sprintf(nil "Tunnel %s, up %ss, %s session(s) @ %s:%s"
            vfpToStr(or(vfpAlistGet(spay "version") "?"))
            vfpToStr(or(vfpAlistGet(spay "uptime_s") "?"))
            vfpToStr(or(vfpAlistGet(spay "sessions") "?"))
            vfpToStr(or(vfpAlistGet(spay "host") "?"))
            vfpToStr(or(vfpAlistGet(spay "port") "?"))))
        )
        when( isCallable('vfpUpdateDashboard) vfpUpdateDashboard() )
        ;; Start the tunnel→GUI event bridge (no-op if already running;
        ;; the client exits quietly while the tunnel lacks event RPCs).
        when( isCallable('vfpEventBridgeStart) errset(vfpEventBridgeStart()) )
        sid
      else
        vfpStateSet('connected nil)
        vfpError(sprintf(nil "connect failed: %s" vfpFmtError(payload)))
        when( isCallable('vfpDashboardSetResult)
          vfpDashboardSetResult(sprintf(nil "Connect failed: %s" vfpFmtError(payload))) )
        when( isCallable('vfpUpdateDashboard) vfpUpdateDashboard() )
        nil
    )
  )
)

defun( vfpDisconnect ()
  when( isCallable('vfpEventBridgeStop) errset(vfpEventBridgeStop()) )
  vfpStateSet('connected nil)
  vfpStateSet('sessionId nil)
  when( isCallable('vfpUpdateDashboard) vfpUpdateDashboard() )
  vfpLog("disconnected (local state cleared)")
  t
)

;; Lightweight liveness check; returns t if the tunnel answers.
defun( vfpPing ()
  let( (sid res)
    sid = vfpStateGet('sessionId)
    res = if( sid
            vfpRpcExec("session.ping" list("--param" strcat("session_id=" sid)))
            vfpRpcExec("tunnel.status" nil) )
    and(car(res) t)
  )
)

defun( vfpTunnelStatus () vfpRpcExec("tunnel.status" nil) )
