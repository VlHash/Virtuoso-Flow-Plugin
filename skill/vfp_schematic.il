;; =====================================================================
;; vfp_schematic.il — controlled schematic access
;; ---------------------------------------------------------------------
;; All parameter changes MUST go through the transaction-aware wrappers in
;; vfp_transaction.il. No unrestricted SKILL evaluation is ever exposed to
;; the agent-facing API. These helpers read/write CDF instance parameters
;; on an open cellview; the caller is responsible for opening the cellview
;; for edit ("a") and saving it (vfpSaveCellView) once.
;;
;; NOTE: the exact CDF calls below are best-effort against IC23.1 and must
;; be confirmed in a live Virtuoso session (an agent cannot drive the GUI).
;; They are centralized here so a single edit fixes every call site.
;; =====================================================================

;; Find an instance object on cellview `cv` by its name (or nil).
defun( vfpFindInstance (cv instName)
  and( cv car(setof(i cv~>instances i~>name == instName)) )
)

;; Read a single CDF parameter value off an instance object (or nil).
defun( vfpInstParamGet (inst paramName)
  let( (cdf pv)
    cdf = and(inst cdfGetInstCDF(inst))
    pv  = and(cdf car(setof(p cdf~>parameters p~>name == paramName)))
    and(pv pv~>value)
  )
)

;; Set a single CDF parameter value on an instance object.
;; Returns t on success, nil if the param could not be located.
defun( vfpInstParamSet (inst paramName value)
  let( (cdf pv)
    cdf = and(inst cdfGetInstCDF(inst))
    pv  = and(cdf car(setof(p cdf~>parameters p~>name == paramName)))
    if( pv
      then pv~>value = value t
      else vfpError(sprintf(nil "param %s not found on instance" paramName)) nil
    )
  )
)

;; ---- name-based wrappers (the stubbed public API) -------------------
defun( vfpListInstances (cv)
  if( cv foreach( mapcar i cv~>instances i~>name ) nil )
)

;; Return an alist of ("param" value) for the named instance (or nil).
defun( vfpGetInstanceParams (cv instName)
  let( (inst cdf)
    inst = vfpFindInstance(cv instName)
    cdf  = and(inst cdfGetInstCDF(inst))
    if( cdf
      foreach( mapcar p cdf~>parameters list(p~>name p~>value) )
      nil
    )
  )
)

defun( vfpGetInstanceParamValue (cv instName paramName)
  vfpInstParamGet( vfpFindInstance(cv instName) paramName )
)

defun( vfpSetInstanceParam (cv instName paramName value)
  let( (inst)
    inst = vfpFindInstance(cv instName)
    if( inst
      then vfpInstParamSet(inst paramName value)
      else vfpError(sprintf(nil "instance %s not found" instName)) nil
    )
  )
)

;; changes: list of ("instance" "param" value) triples. Returns t if every
;; change was applied, nil if any failed (best-effort, continues on error).
defun( vfpBatchSetInstanceParams (cv changes)
  let( (okAll)
    okAll = t
    foreach( ch changes
      unless( vfpSetInstanceParam(cv nth(0 ch) nth(1 ch) nth(2 ch))
        okAll = nil )
    )
    okAll
  )
)

defun( vfpSaveCellView (cv)
  and( cv car(errset( dbSave(cv) )) t )
)

;; Open a schematic cellview for edit (append). Returns the cv or nil.
defun( vfpOpenSchematicForEdit (lib cell)
  car(errset( dbOpenCellViewByType(lib cell "schematic" "schematic" "a") ))
)

;; ---- pre-apply checkpoint (M11 part 4) ------------------------------
;; Snapshot the whole cellview to a timestamped sibling view BEFORE an apply
;; edits it. The apply's dbSave co-saves any unsaved manual edits the user
;; had open (the M11 motivation), so the param-level rollback alone cannot
;; always get the user back; this checkpoint can. Copies the in-memory cv
;; (current state, including unsaved edits), so call it before touching
;; anything. Returns the checkpoint view name, or nil on failure.
defun( vfpCheckpointCellView (cv @optional (tag "preapply"))
  let( (vn dst)
    when( cv
      vn  = sprintf(nil "schematic_vfpckpt_%s_%s" tag vfpCompactTime())
      dst = car(errset( dbCopyCellView(cv cv~>libName cv~>cellName vn nil nil t) ))
      if( dst
        then vfpLog(sprintf(nil "checkpointed %s/%s to view %s"
                             cv~>libName cv~>cellName vn)) vn
        else vfpError(sprintf(nil "checkpoint of %s/%s failed"
                               cv~>libName cv~>cellName)) nil
      )
    )
  )
)
