;; =====================================================================
;; vfp_netlist.il — assemble a complete spectre deck for a cellview
;; ---------------------------------------------------------------------
;; The VFP loop must sim the CURRENT design, never a stale netlist. A
;; complete spectre deck (design + PDK models + analyses + options) only
;; comes from the ADE/maestro netlister, so we trigger
;; maeCreateNetlistForCorner INSIDE a running Virtuoso session — reusing
;; that session's framework license (no separate `si`/Virtuoso checkout).
;; The headless wrapper then sims the deck.
;;
;; This module is loaded by the plugin (attended / 值守: the user's live
;; session) AND by the delegated worker (代管: a persistent headless
;; Virtuoso driven over vcli) — both call vfpNetlistCellView. It is kept
;; free of tunnel-RPC dependencies so it loads cleanly on its own.
;;
;;   vfpNetlistDir()        base dir for decks (VFP_NETLIST_DIR env)
;;   vfpNetlistCvDir(cv)    per-cellview deck dir (wrapper convention)
;;   vfpNetlistCellView(cv) assemble the deck; return its path or nil
;;   vfpCvSavedAt(cv)       cellview last-saved time (-> provenance.saved_at)
;;
;; Loaded after vfp_utils.il (uses vfpError / vfpLog).
;; =====================================================================

;; Base dir for netlist decks; the headless wrapper derives the same
;; per-cellview path, so override BOTH with the shared VFP_NETLIST_DIR env.
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
      vfpLog(sprintf(nil "netlisted %s/%s -> %s (corner %s)" lib cell deck corner))
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
