;; =====================================================================
;; vfp_proposal.il — receive, display, and handle proposals
;; ---------------------------------------------------------------------
;; Proposal states:
;;   pending -> approved -> applied
;;           -> rejected
;;           -> failed -> rolled_back
;; All tunnel calls go through vfpRpcExec(method args).
;; Return value is list(ok payload); ok is t on success, nil on error.
;; =====================================================================


;; ---- vfpFetchPendingProposals ---------------------------------------
;; Returns a list of alist proposals with status "pending".
;; Populates the dashboard result area with a summary.
defun( vfpFetchPendingProposals ()
  let( (ret ok payload proposals summary line cv changes)
    ret = vfpRpcExec("proposal.list" list("--param-json" "status=\"pending\""))
    ok      = car(ret)
    payload = cadr(ret)
    if( null(ok)
      then
        vfpDashboardSetResult(vfpFmtError(payload))
        nil
      else
        proposals = vfpAlistGet(payload "proposals")
        if( null(proposals)
          then
            vfpDashboardSetResult("No pending proposals.")
            list()
          else
            summary = ""
            foreach( p proposals
              cv      = vfpAlistGet(p "cellview")
              changes = vfpAlistGet(p "changes")
              line    = sprintf(nil "[%s]  %s/%s/%s  %d change(s)  %s\n"
                          vfpAlistGet(p "proposal_id")
                          vfpAlistGet(cv "lib")
                          vfpAlistGet(cv "cell")
                          vfpAlistGet(cv "view")
                          length(changes)
                          vfpAlistGet(p "reason"))
              summary = strcat(summary line)
            )
            vfpDashboardSetResult(summary)
            proposals
        )
    )
  )
)


;; Close the proposal review form if it is open. Called after Approve /
;; Reject / Apply so the review window does not linger once acted upon.
;; (Stale pending proposals are aged out tunnel-side via a TTL; see the
;; tunnel's proposal store -- GUI timers are unavailable in this build.)
defun( vfpCloseProposalForm ()
  when( and(boundp('vfpProposalForm) vfpProposalForm)
    errset( hiFormCancel(vfpProposalForm) ) )
  t
)


;; ---- vfpShowProposal ------------------------------------------------
;; proposal: an alist (as returned by vfpFetchPendingProposals).
;; Opens a modeless review dialog with the proposal details and
;; Approve / Reject / Apply buttons, each of which closes the form on
;; success. The form is modeless, so it never blocks; stale pending
;; proposals are aged out tunnel-side via a TTL.
defun( vfpShowProposal (proposal)
  prog( (pid reason cv changes txt form)
    ;; Guard against an empty pending list (car of nil) or a bad caller.
    unless( proposal
      vfpError("vfpShowProposal: called with no proposal")
      return(nil) )
    pid     = vfpAlistGet(proposal "proposal_id")
    reason  = vfpAlistGet(proposal "reason")
    cv      = vfpAlistGet(proposal "cellview")
    changes = vfpAlistGet(proposal "changes")

    ;; Build a human-readable summary string.
    txt = sprintf(nil
      "Proposal: %s\nCellview: %s/%s/%s\nReason:   %s\n\nChanges (%d):\n"
      pid
      vfpAlistGet(cv "lib")
      vfpAlistGet(cv "cell")
      vfpAlistGet(cv "view")
      reason
      length(changes)
    )
    foreach( ch changes
      txt = strcat(txt
        sprintf(nil "  %s.%s: %s -> %s\n"
          vfpAlistGet(ch "instance")
          vfpAlistGet(ch "param")
          vfpAlistGet(ch "before")
          vfpAlistGet(ch "after")
        )
      )
    )

    form = hiCreateAppForm(
      ?name        'vfpProposalForm
      ?formTitle   sprintf(nil "Proposal: %s" pid)
      ?fields      list(
        list( hiCreateMLTextField(?name 'vfpPropDetail ?value txt ?editable nil
                                  ?hasVerticalScrollbar t)
              10:10 460:200 )
        list( hiCreateButton(?name 'vfpPropApprove ?buttonText "Approve"
                ?callback sprintf(nil "vfpApproveProposal(\"%s\")" pid))
              10:220 100:28 )
        list( hiCreateButton(?name 'vfpPropReject  ?buttonText "Reject"
                ?callback sprintf(nil "vfpRejectProposal(\"%s\")" pid))
              120:220 100:28 )
        list( hiCreateButton(?name 'vfpPropApply   ?buttonText "Apply"
                ?callback sprintf(nil "vfpApplyProposal(\"%s\")" pid))
              230:220 100:28 )
      )
      ?buttonLayout 'Close
    )
    hiDisplayForm(form)
    return(form)
  )
)


;; ---- vfpReviewPendingProposal ---------------------------------------
;; Menu/button entry point for vfpShowProposal: fetch the pending
;; proposals and open the review form (Approve / Reject / Apply) on the
;; first one. Each action refreshes the pending list, so repeating this
;; walks the queue.
defun( vfpReviewPendingProposal ()
  let( (proposals)
    proposals = vfpFetchPendingProposals()
    if( proposals
      then vfpShowProposal(car(proposals))
      else
        hiDisplayAppDBox(
          ?name    'vfpInfoDBox
          ?dboxBanner "Virtuoso Flow"
          ?dboxText "No pending proposal to review."
          ?buttonLayout 'Close
        )
        nil
    )
  )
)


;; ---- vfpApproveProposal --------------------------------------------
defun( vfpApproveProposal (proposalId)
  let( (ret ok payload p)
    ret     = vfpRpcExec("proposal.approve"
                list("--param" sprintf(nil "proposal_id=%s" proposalId)))
    ok      = car(ret)
    payload = cadr(ret)
    if( null(ok)
      then
        hiDisplayAppDBox(
          ?name    'vfpErrDBox
          ?dboxBanner "Virtuoso Flow - Error"
          ?dboxText sprintf(nil "Approve failed:\n%s" vfpFmtError(payload))
          ?buttonLayout 'Close
        )
        nil
      else
        p = vfpAlistGet(payload "proposal")
        vfpLog(sprintf(nil "approved proposal %s" proposalId))
        vfpCloseProposalForm()       ;; auto-close the review form
        hiDisplayAppDBox(
          ?name    'vfpInfoDBox
          ?dboxBanner "Virtuoso Flow"
          ?dboxText sprintf(nil "Proposal %s approved.\nStatus: %s"
                      proposalId vfpAlistGet(p "status"))
          ?buttonLayout 'Close
        )
        vfpFetchPendingProposals()   ;; refresh list
        t
    )
  )
)


;; ---- vfpRejectProposal ---------------------------------------------
defun( vfpRejectProposal (proposalId)
  let( (ret ok payload p)
    ret     = vfpRpcExec("proposal.reject"
                list("--param" sprintf(nil "proposal_id=%s" proposalId)))
    ok      = car(ret)
    payload = cadr(ret)
    if( null(ok)
      then
        hiDisplayAppDBox(
          ?name    'vfpErrDBox
          ?dboxBanner "Virtuoso Flow - Error"
          ?dboxText sprintf(nil "Reject failed:\n%s" vfpFmtError(payload))
          ?buttonLayout 'Close
        )
        nil
      else
        p = vfpAlistGet(payload "proposal")
        vfpLog(sprintf(nil "rejected proposal %s" proposalId))
        vfpCloseProposalForm()       ;; auto-close the review form
        hiDisplayAppDBox(
          ?name    'vfpInfoDBox
          ?dboxBanner "Virtuoso Flow"
          ?dboxText sprintf(nil "Proposal %s rejected.\nStatus: %s"
                      proposalId vfpAlistGet(p "status"))
          ?buttonLayout 'Close
        )
        vfpFetchPendingProposals()   ;; refresh list
        t
    )
  )
)


;; ---- vfpApplyProposal -----------------------------------------------
;; Actually sets the instance parameters in the open schematic, then
;; calls proposal.mark_applied (or proposal.mark_failed on error).
;; Apply an *approved* proposal. The actual schematic edit + reversible
;; transaction recording live in vfp_transaction.il (vfpApplyTransaction);
;; this function fetches the proposal and enforces the approval gate.
;; quiet (M11 P5b): suppress modal dialogs + form-close so a batch caller
;; (vfpApplyAllApproved) can drive many proposals and summarise once.
defun( vfpApplyProposal (proposalId @optional quiet)
  prog( (ret ok payload proposal status)
    ;; 1. Fetch the full proposal record.
    ret     = vfpRpcExec("proposal.get"
                list("--param" sprintf(nil "proposal_id=%s" proposalId)))
    ok      = car(ret)
    payload = cadr(ret)
    unless( ok
      unless( quiet
        hiDisplayAppDBox(
          ?name    'vfpErrDBox
          ?dboxBanner "Virtuoso Flow - Error"
          ?dboxText sprintf(nil "Apply failed (get):\n%s" vfpFmtError(payload))
          ?buttonLayout 'Close) )
      return(nil)
    )

    proposal = vfpAlistGet(payload "proposal")
    status   = vfpAlistGet(proposal "status")

    ;; 2. Enforce the approval gate: only approved proposals may be applied.
    unless( equal(status "approved")
      unless( quiet
        hiDisplayAppDBox(
          ?name    'vfpInfoDBox
          ?dboxBanner "Virtuoso Flow"
          ?dboxText sprintf(nil "Proposal %s is '%s'.\nApprove it before applying."
                      proposalId status)
          ?buttonLayout 'Close) )
      return(nil)
    )

    ;; 3. Apply as a reversible transaction; close the review form on success.
    return(
      let( (res)
        res = if( isCallable('vfpApplyTransaction)
                then vfpApplyTransaction(proposal quiet)
                else vfpNotImplemented("vfpApplyTransaction") )
        when( and(res null(quiet)) vfpCloseProposalForm() )
        res
      )
    )
  )
)


;; ---- vfpApplyApprovedProposal ---------------------------------------
;; Menu/button entry point for vfpApplyProposal: fetch the approved
;; proposals and apply the first one. vfpApplyProposal re-checks the
;; approval gate itself.
defun( vfpApplyApprovedProposal ()
  let( (ret ok payload proposals)
    ret     = vfpRpcExec("proposal.list" list("--param-json" "status=\"approved\""))
    ok      = car(ret)
    payload = cadr(ret)
    if( null(ok)
      then
        hiDisplayAppDBox(
          ?name    'vfpErrDBox
          ?dboxBanner "Virtuoso Flow - Error"
          ?dboxText sprintf(nil "Apply failed (list):\n%s" vfpFmtError(payload))
          ?buttonLayout 'Close
        )
        nil
      else
        proposals = vfpAlistGet(payload "proposals")
        if( null(proposals)
          then
            hiDisplayAppDBox(
              ?name    'vfpInfoDBox
              ?dboxBanner "Virtuoso Flow"
              ?dboxText "No approved proposal to apply.\nReview and approve a pending proposal first."
              ?buttonLayout 'Close
            )
            nil
          else
            vfpApplyProposal(vfpAlistGet(car(proposals) "proposal_id"))
        )
    )
  )
)
