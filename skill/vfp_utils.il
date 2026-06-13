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

;; ---- Minimal JSON encoder ------------------------------------------
;; SKILL has no JSON; we only need to *encode* (the helper decodes).
;; Represent JSON objects/arrays with the tagged constructors below so
;; object-vs-array-vs-null is unambiguous. Scalars map directly:
;;   string -> "..."   integer/float -> number   t/'true -> true
;;   'false -> false   nil -> null
;; Booleans must use 'true / 'false (nil always means JSON null).

defun( vfpJObj (@rest kv) cons('jobj kv) )    ; vfpJObj("k" v "k" v ...)
defun( vfpJArr (@rest elems) cons('jarr elems) )

defun( vfpJsonEsc (s)
  let( (out i n ch)
    out = ""
    n = strlen(s)
    for( i 1 n
      ch = substring(s i 1)
      out = strcat( out
        cond(
          ( equal(ch "\\") "\\\\" )
          ( equal(ch "\"") "\\\"" )
          ( equal(ch "\n") "\\n" )
          ( equal(ch "\t") "\\t" )
          ( t ch )
        ))
    )
    out
  )
)

defun( vfpToJson (x)
  cond(
    ( stringp(x)  strcat("\"" vfpJsonEsc(x) "\"") )
    ( eq(x 'true) "true" )
    ( eq(x 'false) "false" )
    ( eq(x t)     "true" )
    ( null(x)     "null" )
    ( fixp(x)     sprintf(nil "%d" x) )
    ( floatp(x)   sprintf(nil "%g" x) )
    ( numberp(x)  sprintf(nil "%L" x) )
    ( and(listp(x) eq(car(x) 'jobj))  vfpJObjToJson(cdr(x)) )
    ( and(listp(x) eq(car(x) 'jarr))  vfpJArrToJson(cdr(x)) )
    ( t  strcat("\"" vfpJsonEsc(sprintf(nil "%L" x)) "\"") )
  )
)

defun( vfpJObjToJson (kv)
  let( (parts rest)
    parts = nil
    rest = kv
    while( rest
      parts = cons( strcat(vfpToJson(car(rest)) ":" vfpToJson(cadr(rest))) parts )
      rest = cddr(rest)
    )
    strcat("{" buildString(reverse(parts) ",") "}")
  )
)

defun( vfpJArrToJson (elems)
  strcat("[" buildString( foreach(mapcar e elems vfpToJson(e)) "," ) "]")
)

;; Write a string to a file (truncating). Returns t on success.
defun( vfpWriteFile (path content)
  let( (port)
    port = outfile(path)
    if( port
      then fprintf(port "%s" content) close(port) t
      else nil
    )
  )
)

;; Timestamp string for context payloads (any string is schema-valid).
defun( vfpIsoTime () getCurrentTime() )

;; getCurrentTime() -> "Jun 13 14:30:05 2026"; collapse to a cellview-name-
;; safe token ("Jun_13_14_30_05_2026") for timestamped checkpoint views.
defun( vfpCompactTime ()
  buildString( parseString( getCurrentTime() " :" ) "_" )
)
