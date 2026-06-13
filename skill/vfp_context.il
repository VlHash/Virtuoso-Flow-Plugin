;; =====================================================================
;; vfp_context.il — design context extraction (Milestone 3)
;; ---------------------------------------------------------------------
;; Walks the current schematic and builds the design-context payload
;; (schemas/context.schema.json), then exports it to VFP Tunnel via
;; design.context.update. vfpGetCurrentCellView lives in vfp_utils.il.
;; =====================================================================

;; Terminal -> net map for one instance, as a JSON object.
defun( vfpInstNets (inst)
  let( (kv)
    kv = nil
    foreach( it inst~>instTerms
      kv = append(kv list( it~>name if(it~>net it~>net~>name "") ))
    )
    cons('jobj kv)
  )
)

;; Device/instance parameters via CDF, as a JSON object of string values.
defun( vfpInstParams (inst)
  let( (cdfg kv)
    cdfg = car(errset( cdfGetInstCDF(inst) ))
    kv = nil
    when( cdfg
      foreach( p cdfg~>parameters
        kv = append(kv list( p~>name vfpToStr(p~>value) ))
      )
    )
    cons('jobj kv)
  )
)

defun( vfpExtractInstances (cv)
  cons('jarr
    foreach( mapcar inst cv~>instances
      vfpJObj(
        "name"   inst~>name
        "master" vfpJObj("lib" inst~>libName "cell" inst~>cellName "view" inst~>viewName)
        "params" vfpInstParams(inst)
        "nets"   vfpInstNets(inst)
      )
    )
  )
)

defun( vfpExtractNets (cv)
  cons('jarr
    foreach( mapcar net cv~>nets vfpJObj("name" net~>name) )
  )
)

defun( vfpExtractPorts (cv)
  cons('jarr
    foreach( mapcar term cv~>terminals
      vfpJObj("name" term~>name "direction" vfpToStr(term~>direction)) )
  )
)

;; Build the full design-context payload (tagged JSON structure) or nil.
defun( vfpExtractDesignContext ()
  let( (cv)
    cv = vfpGetCurrentCellView()
    if( null(cv)
      then vfpError("no current cellview to export") nil
      else
        vfpJObj(
          "schema_version" "0.1"
          "source"         "virtuoso-flow-plugin"
          "timestamp"      vfpIsoTime()
          "cellview"       vfpJObj("lib" cv~>libName "cell" cv~>cellName "view" cv~>viewName)
          "instances"      vfpExtractInstances(cv)
          "ports"          vfpExtractPorts(cv)
          "nets"           vfpExtractNets(cv)
          ;; M11 P4: auto-named nets with no explicit label are fragile —
          ;; flag the load-bearing ones so consumers do not key on their
          ;; names. Guarded: vfp_connectivity.il loads after this module.
          "connectivity_risks" if( isCallable('vfpConnRisksJ)
                                    vfpConnRisksJ(cv) vfpJArr() )
          ;; M11 P4: floating terminals / dead nets / dangling sources.
          "tb_lint"        if( isCallable('vfpLintJson)
                               vfpLintJson(cv) vfpJArr() )
          "ade"            vfpJObj("available" 'false)
          "last_result"    vfpJObj("available" 'false)
        )
    )
  )
)

;; Extract + send the current context to VFP Tunnel (design.context.update).
defun( vfpExportDesignContext ()
  let( (ctx json pf res ok payload)
    ctx = vfpExtractDesignContext()
    if( null(ctx)
      then nil
      else
        json = vfpToJson( vfpJObj("context" ctx) )
        pf = sprintf(nil "%s/ctx_%d.json" vfpHelperOutDir() vfpRpcSeq())
        if( null(vfpWriteFile(pf json))
          then
            vfpError(sprintf(nil "could not write context file %s" pf)) nil
          else
            res = vfpRpcExec("design.context.update" list("--params-file" pf))
            errset(deleteFile(pf))
            ok = car(res)
            payload = cadr(res)
            if( ok
              then
                vfpLog("design context exported to VFP Tunnel")
                when( isCallable('vfpDashboardSetResult)
                  vfpDashboardSetResult("Design context exported to VFP Tunnel.") )
                t
              else
                vfpError(sprintf(nil "context export failed: %s" vfpFmtError(payload)))
                when( isCallable('vfpDashboardSetResult)
                  vfpDashboardSetResult(sprintf(nil "Export failed: %s" vfpFmtError(payload))) )
                nil
            )
        )
    )
  )
)
