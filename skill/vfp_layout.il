;; =====================================================================
;; vfp_layout.il — layout context export (L1) + geometry lint (L2)
;; ---------------------------------------------------------------------
;; The SKILL half of the layout phase (the L1 tunnel/schema half landed in #63).
;; Read-only. L1: cell bbox, instance placement, per-layer shape counts, via
;; count. L2: a cheap geometry lint (unconnected device pins, net-less metal,
;; off-grid shapes) riding the layout block as `lint`. The block rides
;; design.context.update like the schematic context; the tunnel stores and
;; validates it (schemas/context.schema.json `layout`, loose) and the agent
;; reads it (`vfp context show` / the MCP context_get tool).
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

;; ---- L2: layout geometry lint --------------------------------------
;; Cheap, read-only geometry checks (NOT a DRC sign-off): device pins on no
;; net, net-less metal (floating), and off-grid shapes. The layout analogue of
;; the testbench lint (vfpLintTestbench). Each issue is (kind subject detail).

defun( vfpLayoutMetalP (layer)
  and( layer stringp(layer) rexMatchp("^M[0-9]" layer) )   ;; M1, M2, ...
)

defun( vfpLayoutOnGridP (coord grid)
  let( (q)
    q = quotient(coord grid)
    lessp( abs(difference(q round(q))) 0.001 ) )
)

;; Any corner of a shape's bBox off the manufacturing grid?
defun( vfpLayoutOffGridP (bb grid)
  and( bb grid greaterp(grid 0.0)
    let( (ll ur)
      ll = lowerLeft(bb)  ur = upperRight(bb)
      not( and( vfpLayoutOnGridP(xCoord(ll) grid) vfpLayoutOnGridP(yCoord(ll) grid)
                vfpLayoutOnGridP(xCoord(ur) grid) vfpLayoutOnGridP(yCoord(ur) grid) ) ) ) )
)

;; Lint a layout cv -> list of (kind subject detail).
defun( vfpLayoutLint (cv)
  let( (issues grid)
    issues = nil
    grid = or( car(errset(techGetMfgGridResolution(techGetTechFile(cv)))) 0.001 )
    foreach( inst cv~>instances
      foreach( it inst~>instTerms
        unless( it~>net
          issues = cons( list('unconnectedPin
                              sprintf(nil "%s.%s" inst~>name and(it~>term it~>term~>name))
                              "device terminal on no net") issues ) ) ) )
    foreach( sh cv~>shapes
      ;; geometry only -- skip labels/text (net/pin annotations legitimately
      ;; carry no net and aren't "floating metal").
      when( not( or(equal(sh~>objType "label") equal(sh~>objType "text")) )
        when( and( null(sh~>net) vfpLayoutMetalP(sh~>layerName) )
          issues = cons( list('floatingMetal sh~>layerName
                              sprintf(nil "net-less %s on metal %s" sh~>objType sh~>layerName))
                         issues ) )
        when( vfpLayoutOffGridP(sh~>bBox grid)
          issues = cons( list('offGrid sh~>layerName
                              sprintf(nil "off-grid %s on %s" sh~>objType sh~>layerName))
                         issues ) ) ) )
    reverse(issues)
  )
)

;; Lint as JSON [{kind, subject, detail}] for the context layout block.
defun( vfpLayoutLintJ (cv)
  apply('vfpJArr
    foreach( mapcar iss vfpLayoutLint(cv)
      vfpJObj( "kind"    vfpToStr(car(iss))
               "subject" cadr(iss)
               "detail"  caddr(iss) ) ) )
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
                         list("instances" vfpLayoutInstancesJ(cv)
                              "lint"      vfpLayoutLintJ(cv)) )) )
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
