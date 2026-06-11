;; =====================================================================
;; vfp_init.il — Virtuoso Flow Plugin: loader & lifecycle
;; ---------------------------------------------------------------------
;; Entry point. The user loads this single file and calls vfpInit():
;;
;;     load("<repo>/skill/vfp_init.il")
;;     vfpInit()
;;
;; It loads all VFP SKILL modules, initializes runtime state, and
;; registers the "Virtuoso Flow" menu.
;; =====================================================================

VFP_VERSION = "0.1.0"

;; ---- Locate the skill/ directory at load time -----------------------
;; `piport` is the input port of the file currently being loaded;
;; get_filename(piport) yields this file's absolute path. Its parent
;; directory ("<file>/..") simplifies to the skill/ directory, so module
;; loading works regardless of Virtuoso's current working directory.
unless( boundp('VFP_SKILL_DIR) VFP_SKILL_DIR = nil )
let( (here)
  here = car(errset( get_filename(piport) ))
  when( and(here stringp(here) nequal(here ""))
    VFP_SKILL_DIR = simplifyFilename( strcat(here "/..") )
  )
)

;; ---- Modules loaded by vfpLoad (vfp_utils first) --------------------
VFP_MODULES = '(
  "vfp_utils.il"
  "vfp_rpc_client.il"
  "vfp_context.il"
  "vfp_schematic.il"
  "vfp_ade.il"
  "vfp_proposal.il"
  "vfp_transaction.il"
  "vfp_menu.il"
  "vfp_dashboard.il"
  "vfp_rpc_server.il"
)

defun( vfpLoad (@optional (dir VFP_SKILL_DIR))
  unless( dir
    error("[VFP] cannot determine skill directory; set VFP_SKILL_DIR before calling vfpLoad()")
  )
  foreach( m VFP_MODULES
    let( (path)
      path = strcat(dir "/" m)
      if( isFile(path)
        then load(path)
        else printf("[VFP] WARNING: module not found: %s\n" path)
      )
    )
  )
  t
)

defun( vfpInit (@optional (dir VFP_SKILL_DIR))
  vfpLoad(dir)
  vfpStateSet('version VFP_VERSION)
  vfpStateSet('connected nil)
  vfpRegisterMenu()
  printf("[VFP] Virtuoso Flow Plugin %s initialized. Menu: \"Virtuoso Flow\".\n" VFP_VERSION)
  t
)

defun( vfpUnload ()
  when( isCallable('vfpEventBridgeStop) errset(vfpEventBridgeStop()) )
  when( isCallable('vfpCloseDashboard) vfpCloseDashboard() )
  when( isCallable('vfpUnregisterMenu) vfpUnregisterMenu() )
  printf("[VFP] Virtuoso Flow Plugin unloaded.\n")
  t
)

defun( vfpGetVersion () VFP_VERSION )
