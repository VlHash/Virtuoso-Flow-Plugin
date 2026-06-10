;; =====================================================================
;; vfp_menu.il — Virtuoso Flow Plugin: menu integration
;; ---------------------------------------------------------------------
;; Builds the "Virtuoso Flow" pulldown menu and installs it into the CIW
;; banner and into schematic windows (via a post-install trigger).
;; =====================================================================

;; ---- Menu construction ---------------------------------------------
defun( vfpBuildMenu ()
  let( (items)
    items = list(
      hiCreateMenuItem(?name 'vfpMiConnect   ?itemText "Connect VFP Tunnel"        ?callback "vfpMenuConnectCB()")
      hiCreateMenuItem(?name 'vfpMiDashboard ?itemText "Open Dashboard"            ?callback "vfpOpenDashboard()")
      hiCreateSeparatorMenuItem(?name 'vfpMiSep1)
      hiCreateMenuItem(?name 'vfpMiExport    ?itemText "Export Current Context"    ?callback "vfpMenuExportCB()")
      hiCreateMenuItem(?name 'vfpMiProposals ?itemText "Show Pending Proposals"    ?callback "vfpMenuProposalsCB()")
      hiCreateMenuItem(?name 'vfpMiReview    ?itemText "Review Pending Proposal"   ?callback "vfpMenuReviewCB()")
      hiCreateMenuItem(?name 'vfpMiApply     ?itemText "Apply Approved Proposal"   ?callback "vfpMenuApplyCB()")
      hiCreateMenuItem(?name 'vfpMiRollback  ?itemText "Rollback Last Transaction" ?callback "vfpMenuRollbackCB()")
      hiCreateSeparatorMenuItem(?name 'vfpMiSep2)
      hiCreateMenuItem(?name 'vfpMiRunTest   ?itemText "Run Selected ADE Test"     ?callback "vfpMenuRunTestCB()")
      hiCreateMenuItem(?name 'vfpMiRefresh   ?itemText "Refresh Results"           ?callback "vfpMenuRefreshCB()")
      hiCreateSeparatorMenuItem(?name 'vfpMiSep3)
      hiCreateMenuItem(?name 'vfpMiSettings  ?itemText "Settings..."               ?callback "vfpMenuSettingsCB()")
    )
    hiCreatePulldownMenu('vfpMenu "Virtuoso &Flow" items)
  )
)

;; ---- Install / uninstall -------------------------------------------
defun( vfpRegisterMenu ()
  if( vfpStateGet('menuInstalled)
    then
      vfpLog("menu already installed") t
    else
      let( (menu ciw)
        menu = vfpBuildMenu()
        vfpStateSet('menu menu)
        ;; Always reachable from the CIW banner.
        ciw = hiGetCIWindow()
        when( ciw hiInsertBannerMenu(ciw menu 100) )   ;; large index => append right
        ;; Add to schematic windows as they are opened (post-install = 4th arg).
        deRegUserTriggers("schematic" nil nil 'vfpSchematicMenuTrigger)
        ;; Add to any schematic windows that are already open.
        foreach( win hiGetWindowList() vfpMaybeAddMenuToWindow(win) )
        vfpStateSet('menuInstalled t)
        vfpLog("menu installed")
        t
      )
  )
)

;; Post-install trigger: called with each newly opened schematic window.
defun( vfpSchematicMenuTrigger (win)
  vfpMaybeAddMenuToWindow(win)
)

;; Insert the menu into a window only if it is a graphic editor window
;; (has an edit cellview) and does not already carry the menu. The
;; `win->editCellView` property read is quiet for non-graphic windows
;; (CIW, forms), so no GE-2067 warning is emitted.
defun( vfpMaybeAddMenuToWindow (win)
  let( (menu)
    menu = vfpStateGet('menu)
    when( and( win menu win->editCellView
               !member('vfpMenu hiGetBannerMenus(win)) )
      hiInsertBannerMenu(win menu 100)
    )
  )
)

defun( vfpUnregisterMenu ()
  ;; deRegUserTriggers *registers*; removal is deUnRegUserTriggers.
  deUnRegUserTriggers("schematic")
  foreach( win hiGetWindowList()
    errset(
      let( (pos idx)
        pos = nil
        idx = 0
        foreach( sym hiGetBannerMenus(win)
          when( and(null(pos) sym == 'vfpMenu) pos = idx )
          idx = idx + 1
        )
        when( pos hiDeleteBannerMenu(win pos) )
      )
    )
  )
  vfpStateSet('menuInstalled nil)
  vfpLog("menu uninstalled")
  t
)

;; ---- Menu callbacks -------------------------------------------------
;; Thin wrappers. Items not yet implemented log a message until their
;; owning module lands in a later milestone.
defun( vfpMenuConnectCB ()
  if( isCallable('vfpConnect) vfpConnect()
      vfpNotImplemented("Connect VFP Tunnel") )
)
defun( vfpMenuExportCB ()
  if( isCallable('vfpExportDesignContext) vfpExportDesignContext()
      vfpNotImplemented("Export Current Context") )
)
defun( vfpMenuProposalsCB ()
  if( isCallable('vfpFetchPendingProposals) vfpFetchPendingProposals()
      vfpNotImplemented("Show Pending Proposals") )
)
defun( vfpMenuReviewCB ()
  if( isCallable('vfpReviewPendingProposal) vfpReviewPendingProposal()
      vfpNotImplemented("Review Pending Proposal") )
)
defun( vfpMenuApplyCB ()
  if( isCallable('vfpApplyApprovedProposal) vfpApplyApprovedProposal()
      vfpNotImplemented("Apply Approved Proposal") )
)
defun( vfpMenuRollbackCB ()
  let( (tid)
    if( and(isCallable('vfpGetLastTransaction) isCallable('vfpRollbackTransaction))
      then
        tid = vfpGetLastTransaction()
        if( tid
          then vfpRollbackTransaction(tid)
          else
            hiDisplayAppDBox(?name 'vfpInfoDBox ?dboxBanner "Virtuoso Flow"
              ?dboxText "No applied transaction to roll back."
              ?buttonLayout 'Close)
        )
      else vfpNotImplemented("Rollback Last Transaction")
    )
  )
)
defun( vfpMenuRunTestCB ()
  if( isCallable('vfpRunAdeTest)
      vfpRunAdeTest(nil)
      vfpNotImplemented("Run Selected ADE Test") )
)
defun( vfpMenuRefreshCB ()
  if( isCallable('vfpUpdateDashboard) vfpUpdateDashboard()
      vfpNotImplemented("Refresh Results") )
)
defun( vfpMenuSettingsCB ()
  vfpNotImplemented("Settings")
)
