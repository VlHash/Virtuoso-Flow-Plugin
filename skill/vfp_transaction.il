;; =====================================================================
;; vfp_transaction.il — before/after snapshots and rollback
;; ---------------------------------------------------------------------
;; Every applied proposal is recorded as a transaction (before/after
;; parameter values) so every change is reversible. The schematic edits
;; happen here in SKILL; the tunnel stores the transaction and links it to
;; the proposal. Rollback restores the captured "before" values.
;;
;; Tunnel methods used: transaction.create / .rollback / .mark_rolled_back
;; / .mark_failed / .list, and proposal.mark_failed.
;; =====================================================================

;; ---- snapshots ------------------------------------------------------
;; Read the *current* value of every (instance, param) in `changes` (a
;; proposal change list of alists) and return a JSON array constructor
;; (vfpJArr of vfpJObj) of {instance, param, value} for transaction.create.
defun( vfpSnapshotJson (cv changes)
  let( (objs)
    objs = foreach( mapcar ch changes
      let( (instName param val)
        instName = vfpAlistGet(ch "instance")
        param    = vfpAlistGet(ch "param")
        val      = vfpGetInstanceParamValue(cv instName param)
        vfpJObj("instance" instName "param" param "value" vfpToStr(val))
      )
    )
    apply('vfpJArr objs)
  )
)

defun( vfpRecordBeforeState (cv changes) vfpSnapshotJson(cv changes) )
defun( vfpRecordAfterState  (cv changes) vfpSnapshotJson(cv changes) )

;; ---- low-level create ----------------------------------------------
;; Send a transaction.create with before/after JSON arrays. Returns the
;; (ok payload) pair from vfpRpcExec. connJ, when given, is a vfpJObj
;; connectivity block (M11 audit: status/diff/pre-apply snapshot); the
;; transaction schema leaves top-level additionalProperties open.
defun( vfpCreateTransaction (proposalId lib cell beforeArr afterArr
                             @optional (connJ nil))
  let( (json pf res txn)
    txn = vfpJObj(
      "schema_version" "0.1"
      "proposal_id"    proposalId
      "status"         "applied"
      "cellview"       vfpJObj("lib" lib "cell" cell "view" "schematic")
      "before"         beforeArr
      "after"          afterArr
    )
    when( connJ txn = append(txn list("connectivity" connJ)) )
    json = vfpToJson( vfpJObj("transaction" txn) )
    pf = sprintf(nil "%s/txn_%d.json" vfpHelperOutDir() vfpRpcSeq())
    if( null(vfpWriteFile(pf json))
      then
        vfpError(sprintf(nil "could not write transaction file %s" pf))
        list(nil list(list("message" "could not write transaction file")))
      else
        res = vfpRpcExec("transaction.create" list("--params-file" pf))
        errset(deleteFile(pf))
        res
    )
  )
)

;; ---- restore helper (undo) -----------------------------------------
;; Set each change back to its proposal "before" value. Used to undo a
;; just-applied change when transaction.create is rejected.
defun( vfpRestoreFromChanges (cv changes)
  foreach( ch changes
    vfpSetInstanceParam(cv vfpAlistGet(ch "instance")
                           vfpAlistGet(ch "param")
                           vfpAlistGet(ch "before"))
  )
  vfpSaveCellView(cv)
)

;; ---- apply a proposal as a transaction ------------------------------
;; proposal: an alist (from proposal.get). Opens the schematic for edit,
;; captures before, applies each change, captures after, saves, and records
;; the transaction. On a tunnel rejection the change is undone and the
;; proposal marked failed. Returns the transaction_id on success, else nil.
defun( vfpApplyTransaction (proposal)
  prog( (pid cvAlist lib cell changes cv beforeArr afterArr okAll res ok payload txnId
         connBefore connDiff connJ)
    pid     = vfpAlistGet(proposal "proposal_id")
    cvAlist = vfpAlistGet(proposal "cellview")
    lib     = vfpAlistGet(cvAlist "lib")
    cell    = vfpAlistGet(cvAlist "cell")
    changes = vfpAlistGet(proposal "changes")

    cv = vfpOpenSchematicForEdit(lib cell)
    unless( cv
      hiDisplayAppDBox(?name 'vfpErrDBox ?dboxBanner "Virtuoso Flow - Error"
        ?dboxText sprintf(nil "Cannot open schematic %s/%s for edit." lib cell)
        ?buttonLayout 'Close)
      vfpRpcExec("proposal.mark_failed"
        list("--param" sprintf(nil "proposal_id=%s" pid)))
      return(nil)
    )

    ;; M11 connectivity audit: snapshot before touching anything.
    connBefore = and( isCallable('vfpSnapshotConnectivity)
                      vfpSnapshotConnectivity(cv) )
    beforeArr = vfpRecordBeforeState(cv changes)

    okAll = t
    foreach( ch changes
      unless( vfpSetInstanceParam(cv vfpAlistGet(ch "instance")
                                     vfpAlistGet(ch "param")
                                     vfpAlistGet(ch "after"))
        okAll = nil )
    )
    ;; A partial write must never be recorded as an applied transaction:
    ;; undo, mark the proposal failed, and stop.
    unless( okAll
      vfpError(sprintf(nil "could not set every parameter for proposal %s" pid))
      vfpRestoreFromChanges(cv changes)
      vfpRpcExec("proposal.mark_failed"
        list("--param" sprintf(nil "proposal_id=%s" pid)))
      hiDisplayAppDBox(?name 'vfpErrDBox ?dboxBanner "Virtuoso Flow - Error"
        ?dboxText sprintf(nil
          "Apply failed: not every parameter could be set.\nChange reverted; proposal %s marked failed." pid)
        ?buttonLayout 'Close)
      return(nil)
    )
    afterArr = vfpRecordAfterState(cv changes)
    vfpSaveCellView(cv)

    ;; M11: a parameter apply must not move any terminal between nets.
    ;; Record the verdict (and the pre-apply snapshot, for rollback
    ;; verification) in the transaction; an unexpected topology change
    ;; is surfaced in the log and the success dialog.
    when( connBefore
      connDiff = vfpConnectivityDiff(connBefore vfpSnapshotConnectivity(cv))
      connJ = vfpJObj(
        "status" if(connDiff "changed" "clean")
        "diff"   vfpConnDiffJ(connDiff)
        "before" vfpConnSnapJ(connBefore) )
      when( connDiff
        vfpError(sprintf(nil "unexpected connectivity change applying %s:\n%s"
                  pid vfpConnDiffText(connDiff))) )
    )

    res = vfpCreateTransaction(pid lib cell beforeArr afterArr connJ)
    ok = car(res)
    payload = cadr(res)
    return(
      if( ok
        then
          txnId = vfpAlistGet(vfpAlistGet(payload "transaction") "transaction_id")
          vfpLog(sprintf(nil "applied proposal %s as transaction %s" pid txnId))
          hiDisplayAppDBox(?name 'vfpInfoDBox ?dboxBanner "Virtuoso Flow"
            ?dboxText sprintf(nil "Applied proposal %s.\nTransaction: %s%s" pid txnId
              if( connDiff
                  sprintf(nil "\nWARNING - unexpected connectivity change:\n%s"
                          vfpConnDiffText(connDiff))
                  if( connBefore "\nConnectivity: clean" "" ) ))
            ?buttonLayout 'Close)
          when( isCallable('vfpFetchPendingProposals) vfpFetchPendingProposals() )
          txnId
        else
          ;; Tunnel rejected (e.g. permission denied): undo and mark failed.
          vfpError(sprintf(nil "transaction.create rejected: %s" vfpFmtError(payload)))
          vfpRestoreFromChanges(cv changes)
          vfpRpcExec("proposal.mark_failed"
            list("--param" sprintf(nil "proposal_id=%s" pid)))
          hiDisplayAppDBox(?name 'vfpErrDBox ?dboxBanner "Virtuoso Flow - Error"
            ?dboxText sprintf(nil "Apply rejected: %s\nChange reverted." vfpFmtError(payload))
            ?buttonLayout 'Close)
          nil
      )
    )
  )
)

;; Compat alias for the original stub name.
defun( vfpApplyTransactionFor (transactionId) vfpNotImplemented("vfpApplyTransactionFor") )

;; ---- rollback -------------------------------------------------------
;; Restore the "before" values recorded in a transaction, then confirm.
defun( vfpRollbackTransaction (transactionId)
  prog( (res ok payload txn restore cvAlist lib cell cv okAll
         connStored connDiff connNote)
    res = vfpRpcExec("transaction.rollback"
            list("--param" sprintf(nil "transaction_id=%s" transactionId)))
    ok = car(res)
    payload = cadr(res)
    unless( ok
      hiDisplayAppDBox(?name 'vfpErrDBox ?dboxBanner "Virtuoso Flow - Error"
        ?dboxText sprintf(nil "Rollback failed:\n%s" vfpFmtError(payload))
        ?buttonLayout 'Close)
      return(nil)
    )

    txn     = vfpAlistGet(payload "transaction")
    restore = vfpAlistGet(payload "restore")
    cvAlist = vfpAlistGet(txn "cellview")
    lib     = vfpAlistGet(cvAlist "lib")
    cell    = vfpAlistGet(cvAlist "cell")

    cv = vfpOpenSchematicForEdit(lib cell)
    unless( cv
      hiDisplayAppDBox(?name 'vfpErrDBox ?dboxBanner "Virtuoso Flow - Error"
        ?dboxText sprintf(nil "Cannot open schematic %s/%s for rollback." lib cell)
        ?buttonLayout 'Close)
      return(nil)
    )

    okAll = t
    foreach( pv restore
      unless( vfpSetInstanceParam(cv vfpAlistGet(pv "instance")
                                     vfpAlistGet(pv "param")
                                     vfpAlistGet(pv "value"))
        okAll = nil )
    )
    vfpSaveCellView(cv)

    ;; M11: verify connectivity is back at the recorded pre-apply state
    ;; (only for transactions that carry the snapshot; older ones skip).
    connNote = ""
    connStored = and( isCallable('vfpConnSnapFromJson)
                      vfpConnSnapFromJson(
                        vfpAlistGet(vfpAlistGet(txn "connectivity") "before")) )
    when( connStored
      connDiff = vfpConnectivityDiff(connStored vfpSnapshotConnectivity(cv))
      if( connDiff
        then
          vfpError(sprintf(nil "rollback of %s: connectivity NOT restored:\n%s"
                    transactionId vfpConnDiffText(connDiff)))
          connNote = sprintf(nil "\nWARNING - connectivity NOT restored:\n%s"
                       vfpConnDiffText(connDiff))
        else
          connNote = "\nConnectivity restored: verified."
      )
    )

    return(
      if( okAll
        then
          vfpRpcExec("transaction.mark_rolled_back"
            list("--param" sprintf(nil "transaction_id=%s" transactionId)))
          vfpLog(sprintf(nil "rolled back transaction %s" transactionId))
          hiDisplayAppDBox(?name 'vfpInfoDBox ?dboxBanner "Virtuoso Flow"
            ?dboxText sprintf(nil "Transaction %s rolled back.%s"
                        transactionId connNote)
            ?buttonLayout 'Close)
          when( isCallable('vfpUpdateDashboard) vfpUpdateDashboard() )
          t
        else
          vfpRpcExec("transaction.mark_failed"
            list("--param" sprintf(nil "transaction_id=%s" transactionId)))
          hiDisplayAppDBox(?name 'vfpErrDBox ?dboxBanner "Virtuoso Flow - Error"
            ?dboxText sprintf(nil "Rollback of %s incomplete; marked failed." transactionId)
            ?buttonLayout 'Close)
          nil
      )
    )
  )
)

;; ---- last transaction ----------------------------------------------
;; Return the id of the most recent *applied* transaction (or nil).
defun( vfpGetLastTransaction ()
  let( (res ok payload txns)
    res = vfpRpcExec("transaction.list" list("--param-json" "status=\"applied\""))
    ok = car(res)
    payload = cadr(res)
    if( null(ok)
      then nil
      else
        txns = vfpAlistGet(payload "transactions")
        and( txns vfpAlistGet(car(txns) "transaction_id") )
    )
  )
)
