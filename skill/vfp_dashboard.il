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
        ;; ADE test and result summary are populated in later milestones.
        t
    )
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
