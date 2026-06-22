;; =====================================================================
;; vfp_layout_txn.il — layout-edit transactions (L4)
;; ---------------------------------------------------------------------
;; The read-WRITE half of the layout phase: apply a layout geometry edit as
;; a reversible, audited transaction. Unlike the schematic transaction engine
;; (which records before/after PARAMETER values and rolls back field-by-field),
;; a geometry edit is not field-invertible, so:
;;   - rollback restores the cellview from a CHECKPOINT view (a sibling copy
;;     taken before the edit), and
;;   - the transaction stores only a compact geometry DIFF (added/removed/
;;     moved shapes, instance moves) + before/after counts for audit, not the
;;     whole layout (the checkpoint view is the full pre-edit backup).
;;
;; The tunnel needs no change: transaction.create's before/after are optional,
;; the root schema allows the extra `kind`/`geometry`/`connectivity` blocks,
;; and transaction.rollback is only a state preflight (the restore is here).
;;
;; Shapes carry no persistent id across a serialized snapshot, but the SAME
;; dbObject is `eq` across two reads in ONE session — so the diff keys shapes
;; by dbId (memq) within the apply flow, where before/after are read from the
;; same open cellview.
;;
;; Loaded after vfp_utils.il, vfp_rpc_client.il, vfp_connectivity.il, and
;; vfp_layout.il (vfpLayoutSnapshotConnectivity). Connectivity-driven layouts
;; only; this is the transaction framework (L4a). Generic primitive mechanics
;; (widen_net, add_via_array, …) build on it as L5.
;; =====================================================================

;; ---- geometry snapshot ---------------------------------------------
;; A diff-able snapshot of a layout cellview, read from the live cv. Shapes
;; keep their dbId (eq-stable within the session) so the diff can match them.
;;   ("shapes"    ((sh layer purpose objType bbox netName) ...))
;;   ("instances" ((name origin orient) ...))
;;   ("counts"    (nShapes nVias nInstances))
defun( vfpLayoutGeomSnapshot (cv)
  let( (shapes insts nv)
    shapes = foreach( mapcar sh cv~>shapes
               list( sh sh~>layerName or(sh~>purpose "drawing")
                     sh~>objType sh~>bBox and(sh~>net sh~>net~>name) ) )
    insts = foreach( mapcar i cv~>instances
              list( i~>name i~>xy vfpToStr(i~>orient) ) )
    nv = or( car(errset(length(cv~>vias))) 0 )
    list(
      list("shapes"    shapes)
      list("instances" insts)
      list("counts"    list( length(cv~>shapes) nv length(cv~>instances) ))
    )
  )
)

;; ---- geometry diff -------------------------------------------------
;; Diff two snapshots taken from the SAME open cv (before/after an edit).
;; Shapes matched by dbId: gone -> shapeRemoved, new -> shapeAdded, same id
;; with a changed bBox -> shapeModified (moved/resized). Instances matched by
;; name: changed origin -> instMoved, changed orient -> instReoriented.
;; Returns a list of (kind subject detail); nil when nothing changed.
defun( vfpLayoutGeomDiff (snapA snapB)
  let( (shA shB iA iB aIds bIds diffs sb rb)
    shA = vfpAlistGet(snapA "shapes")
    shB = vfpAlistGet(snapB "shapes")
    iA  = vfpAlistGet(snapA "instances")
    iB  = vfpAlistGet(snapB "instances")
    aIds = foreach( mapcar s shA car(s) )
    bIds = foreach( mapcar s shB car(s) )
    diffs = nil
    ;; shapes removed or modified
    foreach( s shA
      if( memq(car(s) bIds)
        then
          sb = car(setof(x shB eq(car(x) car(s))))
          unless( equal(nth(3 s) nth(3 sb))
            diffs = cons(list('shapeModified nth(1 s)
                          sprintf(nil "%s on %s moved/resized" nth(2 s) nth(1 s))) diffs) )
        else
          diffs = cons(list('shapeRemoved nth(1 s)
                        sprintf(nil "removed %s on %s" nth(2 s) nth(1 s))) diffs)
      )
    )
    ;; shapes added
    foreach( s shB
      unless( memq(car(s) aIds)
        diffs = cons(list('shapeAdded nth(1 s)
                      sprintf(nil "added %s on %s" nth(2 s) nth(1 s))) diffs) )
    )
    ;; instances moved / reoriented (matched by name)
    foreach( ra iA
      progn(
        rb = car(setof(x iB equal(car(x) car(ra))))
        when( rb
          unless( equal(cadr(ra) cadr(rb))
            diffs = cons(list('instMoved car(ra)
                          sprintf(nil "%s moved" car(ra))) diffs) )
          unless( equal(caddr(ra) caddr(rb))
            diffs = cons(list('instReoriented car(ra)
                          sprintf(nil "%s orient %s -> %s" car(ra) caddr(ra) caddr(rb))) diffs) )
        )
      )
    )
    reverse(diffs)
  )
)

;; Diff as JSON [{kind, subject, detail}] for the transaction geometry block.
defun( vfpLayoutGeomDiffJ (diffs)
  apply('vfpJArr
    foreach( mapcar d diffs
      vfpJObj( "kind"    vfpToStr(car(d))
               "subject" cadr(d)
               "detail"  caddr(d) ) ))
)

;; Human-readable one-line-per-change rendering.
defun( vfpLayoutGeomDiffText (diffs)
  buildString(
    foreach( mapcar d diffs
      sprintf(nil "%s %s: %s" vfpToStr(car(d)) cadr(d) caddr(d)) )
    "\n")
)

;; counts (nShapes nVias nInsts) -> JSON {shapes, vias, instances}.
defun( vfpLayoutGeomCountsJ (snap)
  let( (c)
    c = vfpAlistGet(snap "counts")
    vfpJObj( "shapes" nth(0 c) "vias" nth(1 c) "instances" nth(2 c) )
  )
)

;; ---- checkpoint + restore ------------------------------------------
;; A whole-cellview backup before the edit — the rollback source for a
;; geometry transaction. Layout-prefixed view name (the schematic checkpoint
;; uses a "schematic_vfpckpt_" prefix; keep them distinct).
defun( vfpLayoutCheckpoint (cv @optional (tag "preedit"))
  let( (vn dst)
    when( cv
      vn  = sprintf(nil "layout_vfpckpt_%s_%s" tag vfpCompactTime())
      dst = car(errset( dbCopyCellView(cv cv~>libName cv~>cellName vn nil nil t) ))
      if( dst
        then vfpLog(sprintf(nil "checkpointed %s/%s to view %s"
                            cv~>libName cv~>cellName vn)) vn
        else vfpError(sprintf(nil "layout checkpoint of %s/%s failed"
                              cv~>libName cv~>cellName)) nil
      )
    )
  )
)

;; Open editor windows showing lib/cell/view (CIW and other windows have no
;; cellView and drop out of the filter).
defun( vfpLayoutWindowsFor (lib cell view)
  setof( w hiGetWindowList()
    and( windowp(w) w~>cellView
         w~>cellView~>libName  == lib
         w~>cellView~>cellName == cell
         w~>cellView~>viewName == view ) )
)

;; Restore lib/cell/view from a checkpoint sibling view. dbCopyCellView will
;; NOT overwrite an existing view (returns nil — verified live), and an OPEN
;; view cannot be deleted, so: close any editor windows on the view, delete it,
;; copy the checkpoint into its place, then reopen a window if one was open (so
;; the editor shows the rolled-back layout). Used by rollback and by the apply
;; path when recording fails.
defun( vfpLayoutRestoreFromView (lib cell view ckptView)
  let( (src tgt ok wins reopen)
    src = car(errset( dbOpenCellViewByType(lib cell ckptView "" "r") ))
    if( null(src)
      then
        vfpError(sprintf(nil "vfpLayoutRestoreFromView: cannot open checkpoint %s/%s/%s"
                         lib cell ckptView))
        nil
      else
        wins   = vfpLayoutWindowsFor(lib cell view)
        reopen = and(wins t)
        foreach( w wins errset( hiCloseWindow(w) ) )
        tgt = ddGetObj(lib cell view)
        when( tgt errset( ddDeleteObj(tgt) ) )
        ok = car(errset( dbCopyCellView(src lib cell view nil nil nil) ))
        errset( dbClose(src) )
        when( reopen
          errset( geOpen(?lib lib ?cell cell ?view view ?viewType "maskLayout" ?mode "a") ) )
        if( ok
          then vfpLog(sprintf(nil "restored %s/%s/%s from checkpoint %s"
                              lib cell view ckptView)) t
          else vfpError("vfpLayoutRestoreFromView: dbCopyCellView failed") nil )
    )
  )
)

;; ---- transaction create (layout) -----------------------------------
;; Send a layout_geom transaction.create. geomJ is the vfpJObj geometry block,
;; connJ an optional connectivity block, ckptView the checkpoint view name.
;; Returns the (ok payload) pair from vfpRpcExec.
defun( vfpCreateLayoutTransaction (lib cell geomJ connJ ckptView)
  let( (txn json pf res)
    txn = vfpJObj(
      "schema_version" "0.1"
      "kind"     "layout_geom"
      "status"   "applied"
      "cellview" vfpJObj("lib" lib "cell" cell "view" "layout")
      "geometry" geomJ )
    when( connJ    txn = append(txn list("connectivity" connJ)) )
    when( ckptView txn = append(txn list("checkpoint"
            vfpJObj("view" ckptView "created_at" vfpIsoTime()))) )
    json = vfpToJson( vfpJObj(
      "session_id"  or(vfpStateGet('sessionId) "")
      "actor"       or(vfpStateGet('actor) "user")
      "transaction" txn) )
    pf = sprintf(nil "%s/ltxn_%d.json" vfpHelperOutDir() vfpRpcSeq())
    if( null(vfpWriteFile(pf json))
      then
        vfpError("vfpCreateLayoutTransaction: could not write transaction file")
        list(nil list(list("message" "could not write layout transaction file")))
      else
        res = vfpRpcExec("transaction.create" list("--params-file" pf))
        errset(deleteFile(pf))
        res
    )
  )
)

;; ---- apply an edit as a layout transaction -------------------------
;; editFn: a callable (symbol or lambda) of one arg (the open cv) that performs
;; the geometry edit and returns non-nil on success. The wrapper snapshots
;; geometry + connectivity, checkpoints, runs the edit, re-snapshots, diffs,
;; and records the transaction. On edit failure or a rejected create it
;; restores from the checkpoint so on-disk state stays truthful. Returns the
;; transaction_id on success, else nil.
defun( vfpLayoutTxnApply (cv editFn @optional (tag "edit"))
  let( (snapBefore connBefore ckpt editOk snapAfter connAfter geomDiff connDiff
        geomJ connJ res ok payload txnId)
    unless( cv
      vfpError("vfpLayoutTxnApply: no cellview")
      return(nil) )
    snapBefore = vfpLayoutGeomSnapshot(cv)
    connBefore = and( isCallable('vfpLayoutSnapshotConnectivity)
                      car(errset(vfpLayoutSnapshotConnectivity(cv))) )
    ckpt = vfpLayoutCheckpoint(cv tag)
    unless( ckpt
      vfpError("vfpLayoutTxnApply: checkpoint failed; refusing the edit")
      return(nil) )
    editOk = car(errset( apply(editFn list(cv)) ))
    unless( editOk
      vfpError("vfpLayoutTxnApply: edit function failed; restoring checkpoint")
      vfpLayoutRestoreFromView(cv~>libName cv~>cellName cv~>viewName ckpt)
      return(nil) )
    dbSave(cv)
    snapAfter = vfpLayoutGeomSnapshot(cv)
    geomDiff  = vfpLayoutGeomDiff(snapBefore snapAfter)
    connJ = nil
    when( connBefore
      connAfter = car(errset(vfpLayoutSnapshotConnectivity(cv)))
      connDiff  = and( connAfter vfpConnectivityDiff(connBefore connAfter) )
      connJ = vfpJObj(
        "status" if(connDiff "changed" "clean")
        "diff"   vfpConnDiffJ(connDiff)
        "before" vfpConnSnapJ(connBefore) )
      when( connDiff
        vfpError(sprintf(nil "vfpLayoutTxnApply: connectivity changed by the edit:\n%s"
          vfpConnDiffText(connDiff))) ) )
    geomJ = vfpJObj(
      "before_counts" vfpLayoutGeomCountsJ(snapBefore)
      "after_counts"  vfpLayoutGeomCountsJ(snapAfter)
      "changes"       vfpLayoutGeomDiffJ(geomDiff) )
    res = vfpCreateLayoutTransaction(cv~>libName cv~>cellName geomJ connJ ckpt)
    ok = car(res)
    payload = cadr(res)
    if( ok
      then
        txnId = vfpAlistGet(vfpAlistGet(payload "transaction") "transaction_id")
        vfpLog(sprintf(nil "layout edit on %s/%s -> transaction %s (%d geom change(s))"
          cv~>libName cv~>cellName txnId length(geomDiff)))
        txnId
      else
        vfpError(sprintf(nil "vfpLayoutTxnApply: transaction.create rejected: %s"
          vfpFmtError(payload)))
        vfpLayoutRestoreFromView(cv~>libName cv~>cellName cv~>viewName ckpt)
        nil
    )
  )
)

;; ---- rollback a layout transaction ---------------------------------
;; Restore the layout cellview from the transaction's checkpoint view, then
;; mark it rolled back. transaction.rollback is just a state preflight here
;; (its `restore` = before[] is empty for a layout txn — we ignore it).
defun( vfpLayoutTxnRollback (txnId)
  prog( (res ok payload txn cvAlist lib cell ckpt okRestore)
    res = vfpRpcExec("transaction.rollback"
            list("--param" sprintf(nil "transaction_id=%s" txnId)))
    ok = car(res)
    payload = cadr(res)
    unless( ok
      vfpError(sprintf(nil "vfpLayoutTxnRollback: %s" vfpFmtError(payload)))
      return(nil) )
    txn     = vfpAlistGet(payload "transaction")
    cvAlist = vfpAlistGet(txn "cellview")
    lib     = vfpAlistGet(cvAlist "lib")
    cell    = vfpAlistGet(cvAlist "cell")
    ckpt    = vfpAlistGet(vfpAlistGet(txn "checkpoint") "view")
    unless( ckpt
      vfpError("vfpLayoutTxnRollback: transaction has no checkpoint view")
      vfpRpcExec("transaction.mark_failed"
        list("--param" sprintf(nil "transaction_id=%s" txnId)))
      return(nil) )
    okRestore = vfpLayoutRestoreFromView(lib cell "layout" ckpt)
    return(
      if( okRestore
        then
          vfpRpcExec("transaction.mark_rolled_back"
            list("--param" sprintf(nil "transaction_id=%s" txnId)))
          vfpLog(sprintf(nil "rolled back layout transaction %s (restored from %s)"
            txnId ckpt))
          t
        else
          vfpRpcExec("transaction.mark_failed"
            list("--param" sprintf(nil "transaction_id=%s" txnId)))
          nil
      )
    )
  )
)
