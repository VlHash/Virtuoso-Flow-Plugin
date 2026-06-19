;; =====================================================================
;; vfp_layout.il — L1: read a layout cellview into a context "layout" block
;; ---------------------------------------------------------------------
;; The SKILL half of L1 (the tunnel/schema half landed in #63). Read-only:
;; cell bbox, instance placement, per-layer shape counts, via count. The block
;; rides design.context.update like the schematic context; the tunnel stores
;; and validates it (schemas/context.schema.json `layout`) and the agent reads
;; it (`vfp context show` / the MCP context_get tool).
;;
;; Field conventions per docs/layout_l1_plan.md + #63's schema:
;;   bbox   nested [[x0,y0],[x1,y1]] (lower-left, upper-right)
;;   origin [x,y] point ; orient string ; master "lib/cell/view" string
;;   layers [{layer, purpose, shapes:<int>}] ; vias <int> count ; units "um"
;; Routed nets are deferred to L3 (this stays a clean read).
;;
;; Loaded after vfp_utils.il (vfpJObj / vfpJArr / vfpToStr / vfpToJson /
;; vfpError) and vfp_rpc_client.il (vfpRpcExec, for the export path).
;; =====================================================================

;; ---- low-level JSON builders ----------------------------------------

;; A point -> JSON [x, y] (numbers, user units).
defun( vfpLayoutPointJ (pt)
  and( pt vfpJArr( xCoord(pt) yCoord(pt) ) )
)

;; A bBox (ll ur) -> JSON [[x0,y0],[x1,y1]].
defun( vfpLayoutBBoxJ (bb)
  and( bb vfpJArr( vfpLayoutPointJ(lowerLeft(bb))
                   vfpLayoutPointJ(upperRight(bb)) ) )
)

;; instances -> [{name, master, origin, orient, bbox}]
defun( vfpLayoutInstancesJ (cv)
  apply('vfpJArr
    foreach( mapcar inst cv~>instances
      vfpJObj(
        "name"   inst~>name
        "master" sprintf(nil "%s/%s/%s"
                   inst~>libName inst~>cellName inst~>viewName)
        "origin" vfpLayoutPointJ(inst~>xy)
        "orient" vfpToStr(inst~>orient)
        "bbox"   vfpLayoutBBoxJ(inst~>bBox) ) ) )
)

;; shapes -> [{layer, purpose, shapes:<count>}] bucketed by (layer, purpose).
;; A string-keyed count table (reliable) plus a separate key list for the
;; unique pairs, so we never depend on iterating the table's keys.
defun( vfpLayoutLayersJ (cv)
  let( (counts keys k)
    counts = makeTable('vfpLyr 0)
    keys = nil
    foreach( sh cv~>shapes
      k = sprintf(nil "%s|%s" sh~>layerName or(sh~>purpose "drawing"))
      when( zerop(counts[k]) keys = cons(k keys) )
      counts[k] = counts[k] + 1 )
    apply('vfpJArr
      foreach( mapcar key reverse(keys)
        let( (parts)
          parts = parseString(key "|")
          vfpJObj( "layer"   car(parts)
                   "purpose" cadr(parts)
                   "shapes"  counts[key] ) ) ) )
  )
)

;; ---- readers (names match #63's schema descriptions) ----------------

;; Common (summary-level) fields, as a flat k/v list for `apply('vfpJObj ...)`.
defun( vfpLayoutCommonKV (cv)
  list(
    "cellview" vfpJObj("lib" cv~>libName "cell" cv~>cellName "view" cv~>viewName)
    "bbox"     vfpLayoutBBoxJ(cv~>bBox)
    "units"    "um"
    "layers"   vfpLayoutLayersJ(cv)
    "vias"     or(car(errset(length(cv~>vias))) 0) )
)

;; Lightweight summary: cell bbox + layer/shape counts + via count (no
;; per-instance placement).
defun( vfpLayoutReadSummary (cv)
  and( cv apply('vfpJObj vfpLayoutCommonKV(cv)) )
)

;; Full L1 read: the summary plus per-instance placement (origin/orient/bbox).
;; This is the block exported as context.layout.
defun( vfpLayoutReadGeometry (cv)
  and( cv apply('vfpJObj
                 append( vfpLayoutCommonKV(cv)
                         list("instances" vfpLayoutInstancesJ(cv)) )) )
)

;; ---- open + export --------------------------------------------------

;; Open <lib>/<cell>/<view> (default layout) read-only -> its full layout
;; block, or nil. Always closes the read handle (no lock).
defun( vfpExtractLayoutContext (lib cell @key (view "layout"))
  let( (cv res)
    cv = car(errset( dbOpenCellViewByType(lib cell view "" "r") ))
    unless( cv
      vfpError(sprintf(nil "vfpExtractLayoutContext: cannot open %s/%s/%s"
                       lib cell view))
      return(nil) )
    res = car(errset( vfpLayoutReadGeometry(cv) ))
    errset( dbClose(cv) )
    unless( res
      vfpError(sprintf(nil "vfpExtractLayoutContext: no layout block for %s/%s/%s"
                       lib cell view)) )
    res
  )
)

;; Build a context { cellview, layout } and send it to the tunnel
;; (design.context.update), reusing the schematic-context send path.
defun( vfpExportLayoutContext (lib cell @key (view "layout"))
  let( (block json pf res)
    block = vfpExtractLayoutContext(lib cell ?view view)
    unless( block return(nil) )
    json = vfpToJson( vfpJObj("context"
             vfpJObj( "cellview" vfpJObj("lib" lib "cell" cell "view" view)
                      "layout"   block )) )
    pf = sprintf(nil "%s/layoutctx_%d.json" vfpHelperOutDir() vfpRpcSeq())
    unless( vfpWriteFile(pf json)
      vfpError("vfpExportLayoutContext: could not write context file")
      return(nil) )
    res = vfpRpcExec("design.context.update" list("--params-file" pf))
    errset( deleteFile(pf) )
    res
  )
)
