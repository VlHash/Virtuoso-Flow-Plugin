;; =====================================================================
;; vfp_layout_prim.il — generic layout primitive mechanics (L5)
;; ---------------------------------------------------------------------
;; The parameter-driven *actuators* of the layout phase: small, generic,
;; PDK-agnostic geometry operations exposed through a uniform contract and a
;; registry, built on the L4a transaction engine. A primitive does NOT decide
;; WHAT to do or WHY — it takes explicit geometric parameters and performs the
;; edit. The intelligence that chooses a primitive and its parameters (RF/EMC/
;; matching recipes) is a separate, consuming layer — it is not in this repo.
;;
;; Uniform contract per primitive (the plan's input/dry-run/apply/diff/rollback):
;;   describeFn(cv params) -> list of (type subject oldVal newVal)   [no mutation]
;;   editFn(cv params)     -> t on success, nil otherwise            [mutates cv]
;; The runner adds: pre-check, dry-run (describe only, returns a proposal),
;; apply (wrap editFn in vfpLayoutTxnApply -> a reversible transaction), and a
;; structured result (schemas/layout_primitive.schema.json).
;;
;; Registry is open so a consuming extension can add primitives without editing
;; this file (vfpLayoutRegisterPrimitive). Loaded after vfp_layout_txn.il.
;; =====================================================================

;; ---- registry -------------------------------------------------------
;; name -> (describeFn editFn riskLevel (requiredCheck ...))
VFP_LAYOUT_PRIMS = makeTable('vfpLayoutPrims nil)

defun( vfpLayoutRegisterPrimitive (name describeFn editFn @optional (risk "medium")
                                   (checks '("drc")))
  VFP_LAYOUT_PRIMS[name] = list(describeFn editFn risk checks)
  name
)

defun( vfpLayoutPrimitiveP (name) and( VFP_LAYOUT_PRIMS[name] t ) )

defun( vfpLayoutPrimitiveNames ()
  let( (out) out = nil
    foreach( k VFP_LAYOUT_PRIMS out = cons(k out) ) reverse(out) )
)

;; ---- result JSON ----------------------------------------------------
;; A change value is a number/string (e.g. a width) or a point list (e.g. an
;; xy) -> a JSON number/string or [x,y].
defun( vfpLayoutPrimVal (v)
  if( listp(v) apply('vfpJArr v) v )
)

;; Structured primitive result (matches layout_primitive.schema.json).
defun( vfpLayoutPrimResultJ (name params status changes risk checks txnId)
  vfpJObj(
    "schema_version" "0.1"
    "primitive" name
    "target"    or( vfpAlistGet(params "net") vfpAlistGet(params "instance") "" )
    "status"    status
    "risk_level" risk
    "changes" apply('vfpJArr
      foreach( mapcar ch changes
        vfpJObj( "type"    vfpToStr(car(ch))
                 "subject" vfpToStr(cadr(ch))
                 "old"     vfpLayoutPrimVal(caddr(ch))
                 "new"     vfpLayoutPrimVal(nth(3 ch)) ) ))
    "required_checks"    apply('vfpJArr checks)
    "rollback_available" if( member(status '("proposal" "applied")) 'true 'false )
    "transaction_id"     or(txnId "") )
)

;; ---- runner ---------------------------------------------------------
;; Run a registered primitive. dryRun -> a proposal (describe only, no edit);
;; otherwise apply the edit as a reversible transaction (vfpLayoutTxnApply) and
;; report the transaction_id. Returns the result JSON object (vfpJObj tree; pass
;; to vfpToJson for the wire), or nil after logging a pre-check failure.
;; params is an alist: lib, cell, [view="layout"], + the primitive's own keys.
;; NOTE: the locals here must NOT shadow vfpLayoutTxnApply's `editFn` parameter
;; (SKILL is dynamically scoped) — the apply lambda references primEdit/params,
;; which resolve to THIS frame while vfpLayoutTxnApply runs synchronously. A
;; local named `editFn` would make the lambda call itself. Hence primDesc/primEdit.
defun( vfpLayoutRunPrimitive (name params @optional dryRun)
  prog( (entry primDesc primEdit risk checks lib cell view cv changes txnId)
    entry = VFP_LAYOUT_PRIMS[name]
    unless( entry
      vfpError(sprintf(nil "vfpLayoutRunPrimitive: unknown primitive %s" name))
      return(nil) )
    lib  = vfpAlistGet(params "lib")
    cell = vfpAlistGet(params "cell")
    view = or( vfpAlistGet(params "view") "layout" )
    unless( and(lib cell)
      vfpError("vfpLayoutRunPrimitive: params need lib + cell")
      return(nil) )
    primDesc = nth(0 entry)  primEdit = nth(1 entry)
    risk     = nth(2 entry)  checks   = nth(3 entry)
    if( dryRun
      then
        cv = car(errset( dbOpenCellViewByType(lib cell view "" "r") ))
        unless( cv
          vfpError(sprintf(nil "vfpLayoutRunPrimitive: cannot open %s/%s/%s" lib cell view))
          return(nil) )
        changes = car(errset( apply(primDesc list(cv params)) ))
        errset( dbClose(cv) )
        return( vfpLayoutPrimResultJ(name params "proposal" changes risk checks nil) )
      else
        cv = car(errset( dbOpenCellViewByType(lib cell view "maskLayout" "a") ))
        unless( cv
          vfpError(sprintf(nil "vfpLayoutRunPrimitive: cannot open %s/%s/%s for edit" lib cell view))
          return(nil) )
        ;; describe BEFORE the edit (old/new values are read from current state)
        changes = car(errset( apply(primDesc list(cv params)) ))
        txnId = vfpLayoutTxnApply(cv
                  lambda( (c) apply(primEdit list(c params)) )
                  name)
        errset( dbClose(cv) )
        return( vfpLayoutPrimResultJ(name params if(txnId "applied" "failed")
                                     changes risk checks txnId) )
    )
  )
)

;; ---- primitive: widen_net ------------------------------------------
;; Widen every path on a net to `width` (user units). The canonical RF/EMC
;; actuator — generic geometry, no process judgment (the caller picks width).
;; params: net (string), width (number), [view].
defun( vfpPrimWidenNetPaths (cv net)
  setof( sh cv~>shapes
    and( sh~>objType == "path" sh~>net sh~>net~>name == net ) )
)

defun( vfpPrimWidenNetDescribe (cv params)
  let( (net width)
    net   = vfpAlistGet(params "net")
    width = vfpAlistGet(params "width")
    foreach( mapcar p vfpPrimWidenNetPaths(cv net)
      list( "path_width" p~>layerName p~>width width ) )
  )
)

defun( vfpPrimWidenNetEdit (cv params)
  let( (net width n)
    net   = vfpAlistGet(params "net")
    width = vfpAlistGet(params "width")
    n = 0
    foreach( p vfpPrimWidenNetPaths(cv net)
      p~>width = width
      n = n + 1 )
    greaterp(n 0)
  )
)

;; ---- primitive: move_instance --------------------------------------
;; Move an instance by (dx, dy) user units. Pure placement; reversible.
;; params: instance (string), dx (number), dy (number), [view].
defun( vfpPrimMoveInst (cv nm)
  car( setof( i cv~>instances i~>name == nm ) )
)

defun( vfpPrimMoveInstDescribe (cv params)
  let( (nm dx dy inst)
    nm = vfpAlistGet(params "instance")
    dx = vfpAlistGet(params "dx")  dy = vfpAlistGet(params "dy")
    inst = vfpPrimMoveInst(cv nm)
    if( inst
      list( list( "inst_move" nm inst~>xy
                  list( xCoord(inst~>xy) + dx  yCoord(inst~>xy) + dy ) ) )
      nil )
  )
)

defun( vfpPrimMoveInstEdit (cv params)
  let( (nm dx dy inst)
    nm = vfpAlistGet(params "instance")
    dx = vfpAlistGet(params "dx")  dy = vfpAlistGet(params "dy")
    inst = vfpPrimMoveInst(cv nm)
    and( inst dbMoveFig(inst cv list(list(dx dy) "R0" 1.0)) t )
  )
)

;; ---- register the built-in primitives ------------------------------
vfpLayoutRegisterPrimitive("widen_net"     'vfpPrimWidenNetDescribe 'vfpPrimWidenNetEdit
                           "medium" '("drc"))
vfpLayoutRegisterPrimitive("move_instance" 'vfpPrimMoveInstDescribe 'vfpPrimMoveInstEdit
                           "medium" '("drc" "lvs"))
