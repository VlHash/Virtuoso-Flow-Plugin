;; =====================================================================
;; vfp_daemon_boot.il — boot the plugin in a headless (-nograph) Virtuoso
;; ---------------------------------------------------------------------
;; The VFP Daemon (Phase 2; tunnel/vfp_tunnel/sim/virtuoso_daemon.py) feeds
;; this to the CIW stdin of a managed `virtuoso -nograph`. It loads the
;; netlist-servicing modules, registers a session, and SERVICES netlist
;; requests headless -- delegated netlisting over VFP's OWN channel, no GUI
;; and no external netlister.
;;
;; MINIMAL, GUARDED LOAD (not vfpLoad / vfpInit):
;;   - It loads ONLY the modules a headless netlist daemon needs.
;;   - It does NOT load vfp_sim.il: vfpRunSimJob mixes @optional + @key, which
;;     does not parse under a vcli/RAMIC reader (some sites auto-load the vcli
;;     bridge from .cdsinit). The daemon never runs sim jobs -- it only assembles
;;     decks (vfpNetlistCellView, in vfp_netlist.il) -- so vfp_sim.il is omitted.
;;   - It does NOT install the GUI menu (headless): no vfp_menu / vfp_dashboard.
;;   - Each load is wrapped in errset so one bad module can't abort the boot.
;;
;; Servicing is a POLL LOOP (vfpServiceNetlistRequests every second), not the
;; GUI event bridge, because a -nograph CIW blocked on stdin does not reliably
;; pump ipc data handlers. The event bridge is still started for the M8 session
;; heartbeat (its long-poll child touches the session server-side).
;;
;; Prints a single readiness marker (drained to the pipe) once connected:
;;     VFP-DAEMON-READY            (or VFP-DAEMON-ERROR connect=nil)
;;
;; The daemon loads it explicitly:  load("<repo>/skill/vfp_daemon_boot.il")
;; =====================================================================

let( (here skillDir mods ok)
  here = car(errset( get_filename(piport) ))
  skillDir = if( and(here stringp(here) nequal(here ""))
                 simplifyFilename( strcat(here "/..") )
                 "." )
  ;; vfp_init.il: defuns + VFP_VERSION + VFP_SKILL_DIR (does not auto-run vfpLoad).
  errset( load( strcat(skillDir "/vfp_init.il") ) )

  mods = '("vfp_utils.il" "vfp_rpc_client.il" "vfp_context.il"
           "vfp_schematic.il" "vfp_connectivity.il" "vfp_netlist.il"
           "vfp_rpc_server.il")
  foreach( m mods errset( load( strcat(skillDir "/" m) ) ) )
  when( and(boundp('VFP_VERSION) isCallable('vfpStateSet))
        vfpStateSet('version VFP_VERSION) )

  ;; Register the session, then start the long-poll bridge (heartbeats the
  ;; session; servicing is the poll loop below). vfpConnect is wrapped so a
  ;; failure cannot abort the boot -- it reports via the marker instead.
  ok = car(errset( vfpConnect() ))
  when( ok errset( vfpEventBridgeStart() ) )

  if( ok
      printf("VFP-DAEMON-READY\n")
      printf("VFP-DAEMON-ERROR connect=%L\n" ok) )
  errset( drain(poport) )                ;; flush the marker to the daemon's pipe

  ;; Headless service loop: poll the tunnel for pending netlist requests and
  ;; service each (vfpServiceNetlistRequests -> vfpNetlistCellView ->
  ;; netlist.complete). Runs until the managing daemon terminates the process.
  when( ok
    while( t
      errset( vfpServiceNetlistRequests() )
      sleep(1)
    )
  )
  ok
)
