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


;; ---- vfpShowProposal ------------------------------------------------
;; proposal: an alist (as returned by vfpFetchPendingProposals).
;; Opens a read-only dialog with the proposal details and
;; Approve / Reject buttons.
defun( vfpShowProposal (proposal)
  let( (pid reason cv changes txt form)
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
    form
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
          ?dboxText sprintf(nil "Approve failed:\n%s" vfpFmtError(payload))
          ?buttonLayout 'Close
        )
        nil
      else
        p = vfpAlistGet(payload "proposal")
        vfpLog(sprintf(nil "approved proposal %s" proposalId))
        hiDisplayAppDBox(
          ?name    'vfpInfoDBox
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
          ?dboxText sprintf(nil "Reject failed:\n%s" vfpFmtError(payload))
          ?buttonLayout 'Close
        )
        nil
      else
        p = vfpAlistGet(payload "proposal")
        vfpLog(sprintf(nil "rejected proposal %s" proposalId))
        hiDisplayAppDBox(
          ?name    'vfpInfoDBox
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
defun( vfpApplyProposal (proposalId)
  prog( (ret ok payload proposal status)
    ;; 1. Fetch the full proposal record.
    ret     = vfpRpcExec("proposal.get"
                list("--param" sprintf(nil "proposal_id=%s" proposalId)))
    ok      = car(ret)
    payload = cadr(ret)
    unless( ok
      hiDisplayAppDBox(
        ?name    'vfpErrDBox
        ?dboxText sprintf(nil "Apply failed (get):\n%s" vfpFmtError(payload))
        ?buttonLayout 'Close)
      return(nil)
    )

    proposal = vfpAlistGet(payload "proposal")
    status   = vfpAlistGet(proposal "status")

    ;; 2. Enforce the approval gate: only approved proposals may be applied.
    unless( equal(status "approved")
      hiDisplayAppDBox(
        ?name    'vfpInfoDBox
        ?dboxText sprintf(nil "Proposal %s is '%s'.\nApprove it before applying."
                    proposalId status)
        ?buttonLayout 'Close)
      return(nil)
    )

    ;; 3. Apply as a reversible transaction.
    return(
      if( isCallable('vfpApplyTransaction)
        then vfpApplyTransaction(proposal)
        else vfpNotImplemented("vfpApplyTransaction")
      )
    )
  )
)
