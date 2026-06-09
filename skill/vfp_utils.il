;; =====================================================================
;; vfp_utils.il — Virtuoso Flow Plugin: shared utilities
;; ---------------------------------------------------------------------
;; Logging, global runtime state, and small helpers shared by all VFP
;; SKILL modules. This file is loaded first by vfp_init.il.
;; =====================================================================

;; ---- Global runtime state (disembodied property list) ---------------
;; Holds plugin state at runtime, e.g. 'connected, 'menu, 'dashForm.
unless( boundp('VFP_STATE) VFP_STATE = list(nil) )

defun( vfpStateGet (key)
  get(VFP_STATE key)
)

defun( vfpStateSet (key value)
  putprop(VFP_STATE value key)
  value
)

;; ---- Logging --------------------------------------------------------
defun( vfpLog (msg)
  printf("[VFP %s] %s\n" getCurrentTime() msg)
  msg
)

defun( vfpError (msg)
  warn("[VFP] %s\n" msg)
  nil
)

defun( vfpNotImplemented (what)
  vfpLog( sprintf(nil "'%s' is not implemented yet (planned for a later milestone)." what) )
  nil
)

;; ---- Cellview helpers ----------------------------------------------
;; Returns the edit cellview of the current window, falling back to any
;; open window that has one. Returns nil if none is found.
;;
;; Uses the `win->editCellView` property (the documented shorthand for
;; geGetEditCellView) rather than the function: the property is a quiet
;; slot read that yields nil for non-graphic windows (e.g. the CIW),
;; whereas the function emits a GE-2067 warning for them.
defun( vfpGetCurrentCellView ()
  let( (cv win)
    win = hiGetCurrentWindow()
    cv = and(win win->editCellView)
    unless( cv
      foreach( w hiGetWindowList()
        unless( cv cv = w->editCellView )
      )
    )
    cv
  )
)

;; Pretty "lib/cell/view" string for a cellview (or "(none)").
defun( vfpCvId (cv)
  if( cv
    then sprintf(nil "%s/%s/%s" cv~>libName cv~>cellName cv~>viewName)
    else "(none)"
  )
)

;; Coerce any value to a plain string for "%s" formatting (numbers print
;; bare, strings pass through, nil -> "").
defun( vfpToStr (x)
  cond(
    ( stringp(x) x )
    ( null(x) "" )
    ( t sprintf(nil "%L" x) )
  )
)
