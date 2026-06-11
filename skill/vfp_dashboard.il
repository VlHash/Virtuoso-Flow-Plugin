;; =====================================================================
;; vfp_dashboard.il — Virtuoso Flow Plugin: dashboard form
;; ---------------------------------------------------------------------
;; A simple embedded panel showing connection status, current
;; lib/cell/view, ADE test, and the latest result/constraint summary,
;; plus a few action buttons. Functionality first; layout is minimal.
;; =====================================================================

;; ---- Field layout ---------------------------------------------------
;; Each entry is `list(field x:y width:height)` (2D form attributes).
defun( vfpDashboardFields ()
  list(
    list( hiCreateLabel(?name 'vfpConnLbl ?labelText "VFP Tunnel:")                       10:12  120:18 )
    list( hiCreateStringField(?name 'vfpConnVal ?defValue "Disconnected" ?editable nil)   140:10 320:24 )

    list( hiCreateLabel(?name 'vfpLibLbl ?labelText "Library:")                            10:42  120:18 )
    list( hiCreateStringField(?name 'vfpLibVal ?defValue "(none)" ?editable nil)           140:40 320:24 )

    list( hiCreateLabel(?name 'vfpCellLbl ?labelText "Cell:")                              10:72  120:18 )
    list( hiCreateStringField(?name 'vfpCellVal ?defValue "" ?editable nil)                140:70 320:24 )

    list( hiCreateLabel(?name 'vfpViewLbl ?labelText "View:")                              10:102 120:18 )
    list( hiCreateStringField(?name 'vfpViewVal ?defValue "" ?editable nil)                140:100 320:24 )

    list( hiCreateLabel(?name 'vfpAdeLbl ?labelText "ADE Test:")                           10:132 120:18 )
    list( hiCreateStringField(?name 'vfpAdeVal ?defValue "(n/a)" ?editable nil)            140:130 320:24 )

    list( hiCreateLabel(?name 'vfpResLbl ?labelText "Latest Result / Constraints:")        10:165 320:18 )
    list( hiCreateMLTextField(?name 'vfpResVal ?value "No results yet." ?editable nil
                              ?hasVerticalScrollbar t)                                      10:188 450:120 )

    list( hiCreateButton(?name 'vfpBtnConnect   ?buttonText "Connect"   ?callback "vfpMenuConnectCB()")         10:320  96:26 )
    list( hiCreateButton(?name 'vfpBtnExport    ?buttonText "Export"    ?callback "vfpMenuExportCB()")          114:320  96:26 )
    list( hiCreateButton(?name 'vfpBtnRefresh   ?buttonText "Refresh"   ?callback "vfpUpdateDashboard()")       218:320  96:26 )
    list( hiCreateButton(?name 'vfpBtnRollback  ?buttonText "Rollback"  ?callback "vfpMenuRollbackCB()")        322:320  96:26 )
    list( hiCreateButton(?name 'vfpBtnProposals ?buttonText "Proposals" ?callback "vfpFetchPendingProposals()") 426:320 100:26 )

    list( hiCreateButton(?name 'vfpBtnReview    ?buttonText "Review"    ?callback "vfpMenuReviewCB()")          10:352  96:26 )
    list( hiCreateButton(?name 'vfpBtnApply     ?buttonText "Apply"     ?callback "vfpMenuApplyCB()")           114:352  96:26 )
  )
)

;; ---- Open / update / close -----------------------------------------
defun( vfpOpenDashboard ()
  let( (form)
    form = vfpStateGet('dashForm)
    unless( form
      form = hiCreateAppForm(
        ?name        'vfpDashForm
        ?formTitle   "Virtuoso Flow - Dashboard"
        ?fields      vfpDashboardFields()
        ?buttonLayout 'Close
      )
      vfpStateSet('dashForm form)
    )
    hiDisplayForm(form)
    vfpUpdateDashboard()
    form
  )
)

defun( vfpUpdateDashboard ()
  let( (form cv)
    form = vfpStateGet('dashForm)
    if( null(form)
      then
        vfpLog("dashboard not open; nothing to refresh") nil
      else
        cv = vfpGetCurrentCellView()
        form->vfpConnVal->value =
          if( vfpStateGet('connected)
            sprintf(nil "Connected (%s)" or(vfpStateGet('sessionId) "?"))
            "Disconnected" )
        form->vfpLibVal->value  = if( cv cv~>libName "(none)" )
        form->vfpCellVal->value = if( cv cv~>cellName "" )
        form->vfpViewVal->value = if( cv cv~>viewName "" )
        when( vfpStateGet('connected) vfpRefreshResults() )
        t
    )
  )
)

;; Pull the latest result from the tunnel and render metrics + pass/fail
;; into the ADE field and the result text area.
defun( vfpRefreshResults ()
  let( (form res ok payload result metrics cons overall txt)
    form = vfpStateGet('dashForm)
    when( form
      res = vfpRpcExec("result.latest" nil)
      ok = car(res)
      payload = cadr(res)
      result = and(ok vfpAlistGet(payload "result"))
      if( null(result)
        then
          form->vfpAdeVal->value = "(no result)"
          vfpDashboardSetResult("No results yet.")
        else
          metrics = vfpAlistGet(result "metrics")
          cons    = vfpAlistGet(result "constraints")
          overall = and(cons vfpAlistGet(cons "overall"))
          form->vfpAdeVal->value =
            sprintf(nil "%s%s"
              vfpToStr(or(vfpAlistGet(result "test") vfpAlistGet(result "source") "result"))
              if(overall sprintf(nil " - %s" upperCase(overall)) ""))
          txt = ""
          foreach( pair metrics
            txt = strcat(txt sprintf(nil "%s = %s\n" car(pair) vfpToStr(cadr(pair)))) )
          when( cons
            txt = strcat(txt sprintf(nil "\nConstraints: %s\n" upperCase(overall)))
            foreach( item vfpAlistGet(cons "items")
              when( equal(vfpAlistGet(item "status") "fail")
                txt = strcat(txt sprintf(nil "  FAIL %s: %s\n"
                  vfpAlistGet(item "metric") vfpToStr(vfpAlistGet(item "reason")))) )
            )
          )
          vfpDashboardSetResult(txt)
      )
    )
    t
  )
)

defun( vfpCloseDashboard ()
  let( (form)
    form = vfpStateGet('dashForm)
    when( form errset( hiFormCancel(form) ) )
    t
  )
)

;; Set the multi-line result/status area (used by the RPC client to show
;; the tunnel summary or an error). Safe to call when the form is closed.
defun( vfpDashboardSetResult (text)
  let( (form)
    form = vfpStateGet('dashForm)
    when( form form->vfpResVal->value = text )
    t
  )
)
