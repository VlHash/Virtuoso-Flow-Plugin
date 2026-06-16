;; =====================================================================
;; vfp_daemon_boot.il — boot the plugin in a headless (-nograph) Virtuoso
;; ---------------------------------------------------------------------
;; The VFP Daemon (Phase 2; tunnel/vfp_tunnel/sim/virtuoso_daemon.py) feeds
;; this to the CIW stdin of a managed `virtuoso -nograph`. It loads the
;; plugin modules, registers a session, and starts the event bridge so the
;; plugin services netlist.request events headless (vfpServiceNetlistRequests)
;; -- delegated netlisting over VFP's OWN channel, with no GUI and no vcli.
;;
;; HEADLESS, so it does NOT call vfpInit (which installs the "Virtuoso Flow"
;; GUI menu): it does the minimal init -- vfpLoad modules, then connect +
;; event bridge. The bridge's long-poll doubles as the M8 session heartbeat.
;;
;; It prints a single readiness marker line once connected + servicing, which
;; the manager scans stdout for:
;;
;;     VFP-DAEMON-READY
;;
;; On failure it prints a one-line reason instead (manager surfaces tail()):
;;
;;     VFP-DAEMON-ERROR connect=<t/nil> bridge=<t/nil>
;;
;; The daemon loads it explicitly:  load("<repo>/skill/vfp_daemon_boot.il")
;; =====================================================================

let( (here skillDir ok)
  ;; Resolve skill/ from this file's path, like vfp_init.il does, so the boot
  ;; works regardless of Virtuoso's working directory.
  here = car(errset( get_filename(piport) ))
  skillDir = if( and(here stringp(here) nequal(here ""))
                 simplifyFilename( strcat(here "/..") )
                 "." )
  ;; vfp_init.il defines vfpLoad/vfpInit + VFP_VERSION and resolves VFP_SKILL_DIR.
  load( strcat(skillDir "/vfp_init.il") )
  vfpLoad()                              ;; load modules; NO menu (headless)
  when( isCallable('vfpStateSet) vfpStateSet('version VFP_VERSION) )

  ;; Register the session, then start the long-poll bridge that auto-services
  ;; netlist.request (and heartbeats the session).
  ok = car(errset( vfpConnect() ))
  when( ok errset( vfpEventBridgeStart() ) )

  if( and(ok vfpEventBridgeRunning())
      printf("VFP-DAEMON-READY\n")
      printf("VFP-DAEMON-ERROR connect=%L bridge=%L\n"
             ok and(boundp('vfpEventBridgeRunning) vfpEventBridgeRunning())) )
  ok
)
