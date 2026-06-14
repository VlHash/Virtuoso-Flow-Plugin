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
                             @optional (connJ nil) (ckptView nil))
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
    when( ckptView txn = append(txn list("checkpoint"
            vfpJObj("view" ckptView "created_at" vfpIsoTime()))) )
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
;; quiet (M11 P5b): suppress the per-proposal modal dialogs so a batch
;; apply (vfpApplyAllApproved) can run N proposals and summarise once.
;; Default nil keeps the single-apply path (VNC-verified) unchanged.
defun( vfpApplyTransaction (proposal @optional quiet)
  prog( (pid cvAlist lib cell changes cv beforeArr afterArr okAll res ok payload txnId
         connBefore connDiff connJ ckptView)
    pid     = vfpAlistGet(proposal "proposal_id")
    cvAlist = vfpAlistGet(proposal "cellview")
    lib     = vfpAlistGet(cvAlist "lib")
    cell    = vfpAlistGet(cvAlist "cell")
    changes = vfpAlistGet(proposal "changes")

    cv = vfpOpenSchematicForEdit(lib cell)
    unless( cv
      unless( quiet
        hiDisplayAppDBox(?name 'vfpErrDBox ?dboxBanner "Virtuoso Flow - Error"
          ?dboxText sprintf(nil "Cannot open schematic %s/%s for edit." lib cell)
          ?buttonLayout 'Close) )
      vfpRpcExec("proposal.mark_failed"
        list("--param" sprintf(nil "proposal_id=%s" pid)))
      return(nil)
    )

    ;; M11 P4: checkpoint the whole cellview before any edit, so the
    ;; pre-apply state (incl. unsaved manual edits the apply dbSave would
    ;; co-save) is recoverable wholesale. Best-effort: a failed checkpoint
    ;; does not block the apply.
    ckptView = and( isCallable('vfpCheckpointCellView)
                    vfpCheckpointCellView(cv "preapply") )

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
      unless( quiet
        hiDisplayAppDBox(?name 'vfpErrDBox ?dboxBanner "Virtuoso Flow - Error"
          ?dboxText sprintf(nil
            "Apply failed: not every parameter could be set.\nChange reverted; proposal %s marked failed." pid)
          ?buttonLayout 'Close) )
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

    res = vfpCreateTransaction(pid lib cell beforeArr afterArr connJ ckptView)
    ok = car(res)
    payload = cadr(res)
    return(
      if( ok
        then
          txnId = vfpAlistGet(vfpAlistGet(payload "transaction") "transaction_id")
          vfpLog(sprintf(nil "applied proposal %s as transaction %s" pid txnId))
          unless( quiet
            hiDisplayAppDBox(?name 'vfpInfoDBox ?dboxBanner "Virtuoso Flow"
              ?dboxText sprintf(nil "Applied proposal %s.\nTransaction: %s%s" pid txnId
                if( connDiff
                    sprintf(nil "\nWARNING - unexpected connectivity change:\n%s"
                            vfpConnDiffText(connDiff))
                    if( connBefore "\nConnectivity: clean" "" ) ))
              ?buttonLayout 'Close) )
          when( isCallable('vfpFetchPendingProposals) vfpFetchPendingProposals() )
          txnId
        else
          ;; Tunnel rejected (e.g. permission denied): undo and mark failed.
          vfpError(sprintf(nil "transaction.create rejected: %s" vfpFmtError(payload)))
          vfpRestoreFromChanges(cv changes)
          vfpRpcExec("proposal.mark_failed"
            list("--param" sprintf(nil "proposal_id=%s" pid)))
          unless( quiet
            hiDisplayAppDBox(?name 'vfpErrDBox ?dboxBanner "Virtuoso Flow - Error"
              ?dboxText sprintf(nil "Apply rejected: %s\nChange reverted." vfpFmtError(payload))
              ?buttonLayout 'Close) )
          nil
      )
    )
  )
)

;; ---- batch apply (M11 part 5b) --------------------------------------
;; Apply every approved proposal in one pass, quietly, then summarise once
;; — high-frequency loops should not click N modal dialogs. Each proposal
;; still becomes its own transaction (auditable + individually reversible);
;; the heavy "auto-approve within an envelope" policy is M12 (collab).
defun( vfpApplyAllApproved ()
  let( (res ok payload proposals applied failed pid txnId)
    res = vfpRpcExec("proposal.list" list("--param-json" "status=\"approved\""))
    ok = car(res)
    payload = cadr(res)
    if( null(ok)
      then
        hiDisplayAppDBox(?name 'vfpErrDBox ?dboxBanner "Virtuoso Flow - Error"
          ?dboxText sprintf(nil "Apply all failed (list):\n%s" vfpFmtError(payload))
          ?buttonLayout 'Close)
        nil
      else
        proposals = vfpAlistGet(payload "proposals")
        if( null(proposals)
          then
            hiDisplayAppDBox(?name 'vfpInfoDBox ?dboxBanner "Virtuoso Flow"
              ?dboxText "No approved proposals to apply."
              ?buttonLayout 'Close)
            nil
          else
            applied = nil
            failed  = nil
            foreach( p proposals
              pid = vfpAlistGet(p "proposal_id")
              ;; reuse vfpApplyProposal's get + approval gate, quietly
              txnId = and( isCallable('vfpApplyProposal)
                           vfpApplyProposal(pid t) )
              if( txnId
                then applied = cons(list(pid txnId) applied)
                else failed  = cons(pid failed)
              )
            )
            when( isCallable('vfpFetchPendingProposals) vfpFetchPendingProposals() )
            when( isCallable('vfpUpdateDashboard) vfpUpdateDashboard() )
            hiDisplayAppDBox(?name 'vfpInfoDBox ?dboxBanner "Virtuoso Flow"
              ?dboxText sprintf(nil "Applied %d of %d approved proposal(s).%s"
                length(applied) length(proposals)
                if( failed
                    sprintf(nil "\nFailed: %s" buildString(reverse(failed) ", "))
                    "" ))
              ?buttonLayout 'Close)
            reverse(applied)
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

;; ---- parameter history / blame chain (M11 part 5) -------------------
;; "When did R1.r change, and to what?" — the archaeology that cost a day
;; on the 996µA ghost regression. Aggregates every transaction that set a
;; given (instance, param) into a time-ordered chain. Pure read over the
;; existing transaction.list (no new RPC). Sort oldest-first by the ISO
;; timestamp (lexical order = chronological); do NOT just reverse the list,
;; because same-second timestamps make transaction.list fall back to insert
;; order, which reversing would flip. Each record:
;;   (transaction_id status timestamp proposal_id beforeVal afterVal)
;; NOTE: timestamps are second-granular — sub-second bursts of edits to the
;; same param order by insertion (stable sort) but cannot be distinguished
;; precisely; a created_ts epoch on the txn (tunnel) would tighten this.
defun( vfpAlistMatch (pv instName paramName)
  and( equal(vfpAlistGet(pv "instance") instName)
       equal(vfpAlistGet(pv "param") paramName) )
)

defun( vfpTxnTimeLess (a b)
  alphalessp( vfpToStr(vfpAlistGet(a "timestamp"))
              vfpToStr(vfpAlistGet(b "timestamp")) )
)

defun( vfpParamHistory (instName paramName)
  let( (res ok payload txns hits)
    res = vfpRpcExec("transaction.list" nil)
    ok = car(res)
    payload = cadr(res)
    if( null(ok)
      then nil
      else
        txns = vfpAlistGet(payload "transactions")
        ;; keep only transactions whose after[] sets this inst.param,
        ;; oldest-first by timestamp
        hits = sort( setof( tx txns
                 exists( pv vfpAlistGet(tx "after")
                         vfpAlistMatch(pv instName paramName) ) )
                 'vfpTxnTimeLess )
        foreach( mapcar tx hits
          let( (pvA pvB)
            pvA = car(setof(pv vfpAlistGet(tx "before")
                            vfpAlistMatch(pv instName paramName)))
            pvB = car(setof(pv vfpAlistGet(tx "after")
                            vfpAlistMatch(pv instName paramName)))
            list( vfpAlistGet(tx "transaction_id")
                  vfpAlistGet(tx "status")
                  vfpAlistGet(tx "timestamp")
                  vfpAlistGet(tx "proposal_id")
                  and(pvA vfpAlistGet(pvA "value"))
                  and(pvB vfpAlistGet(pvB "value")) ) ) )
    )
  )
)

;; "R1.r: 1K -> 2K -> 2.5K" — the before of the first change, then each
;; after in order. nil history => a clear "no recorded changes".
defun( vfpParamHistoryText (instName paramName)
  let( (hist parts)
    hist = vfpParamHistory(instName paramName)
    if( null(hist)
      then sprintf(nil "%s.%s: no recorded changes" instName paramName)
      else
        parts = cons( vfpToStr(nth(4 car(hist)))
                      foreach(mapcar h hist vfpToStr(nth(5 h))) )
        sprintf(nil "%s.%s: %s" instName paramName buildString(parts " -> "))
    )
  )
)

;; JSON-array form (one object per change) for a history RPC / dashboard.
defun( vfpParamHistoryJson (instName paramName)
  apply('vfpJArr
    foreach( mapcar h vfpParamHistory(instName paramName)
      vfpJObj( "transaction_id" nth(0 h) "status"      nth(1 h)
               "timestamp"      nth(2 h) "proposal_id" nth(3 h)
               "before"         nth(4 h) "after"       nth(5 h) ) ))
)

;; ---- transaction listing (M11 P5b — rollback picker) ----------------
;; One-line summary of a transaction's parameter changes, e.g.
;; "R0.r: 1K->2K, R1.r: 5K->6K", built from after[] paired with before[].
defun( vfpTxnSummary (tx)
  buildString(
    foreach( mapcar pa vfpAlistGet(tx "after")
      let( (inst param bef)
        inst  = vfpAlistGet(pa "instance")
        param = vfpAlistGet(pa "param")
        bef   = car(setof(pb vfpAlistGet(tx "before")
                          vfpAlistMatch(pb inst param)))
        sprintf(nil "%s.%s: %s->%s" inst param
          vfpToStr(and(bef vfpAlistGet(bef "value")))
          vfpToStr(vfpAlistGet(pa "value"))) ) )
    ", ")
)

;; Transactions for a rollback picker / dashboard: newest-first records
;; (tid status timestamp summary). Optional status filter (e.g. "applied").
defun( vfpListTransactions (@optional status)
  let( (res ok payload txns)
    res = vfpRpcExec("transaction.list"
            if(status list("--param-json"
                  sprintf(nil "status=\"%s\"" status)) nil))
    ok = car(res)
    payload = cadr(res)
    if( null(ok)
      then nil
      else
        txns = vfpAlistGet(payload "transactions")
        foreach( mapcar tx txns
          list( vfpAlistGet(tx "transaction_id")
                vfpAlistGet(tx "status")
                vfpAlistGet(tx "timestamp")
                vfpTxnSummary(tx) ) )
    )
  )
)

;; One line per transaction, for a log / picker label.
defun( vfpListTransactionsText (@optional status)
  buildString(
    foreach( mapcar r vfpListTransactions(status)
      sprintf(nil "%s [%s] %s  %s"
        nth(0 r) vfpToStr(nth(1 r)) nth(2 r) nth(3 r)) )
    "\n")
)

;; ---- rollback picker (M11 P5b) --------------------------------------
;; Roll back ANY applied transaction, not just the last. The core
;; vfpRollbackTransaction already takes any tid; this is the UI. The cyclic
;; field choices are "tid  summary"; vfpRollbackSelected parses the tid
;; back out of the chosen label.
defun( vfpShowRollbackPicker ()
  let( (txns labels form)
    txns = vfpListTransactions("applied")
    if( null(txns)
      then
        hiDisplayAppDBox(?name 'vfpInfoDBox ?dboxBanner "Virtuoso Flow"
          ?dboxText "No applied transactions to roll back."
          ?buttonLayout 'Close)
        nil
      else
        labels = foreach( mapcar r txns
                   sprintf(nil "%s  %s" nth(0 r) nth(3 r)) )
        form = hiCreateAppForm(
          ?name      'vfpRollbackForm
          ?formTitle "Rollback Transaction"
          ?fields list(
            list( hiCreateMLTextField(?name 'vfpRbList
                    ?value vfpListTransactionsText("applied")
                    ?editable nil ?hasVerticalScrollbar t) 10:10 540:160 )
            list( hiCreateCyclicField(?name 'vfpRbPick ?choices labels) 10:180 420:24 )
            list( hiCreateButton(?name 'vfpRbDo ?buttonText "Rollback"
                    ?callback "vfpRollbackSelected()") 10:212 100:28 )
          )
          ?buttonLayout 'Close
        )
        hiDisplayForm(form)
        form
    )
  )
)

;; Read the picked tid out of the form's cyclic field and roll it back.
defun( vfpRollbackSelected ()
  let( (form sel tid)
    form = hiGetCurrentForm()
    sel  = and(form form->vfpRbPick->value)
    tid  = and(sel stringp(sel) car(parseString(sel " ")))
    when( tid
      errset(hiFormCancel(form))
      vfpRollbackTransaction(tid) )
  )
)
