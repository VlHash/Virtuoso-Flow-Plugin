;; =====================================================================
;; vfp_transaction.il — before/after snapshots and rollback
;; ---------------------------------------------------------------------
;; STUB (Milestone 5). Every applied proposal is linked to a transaction
;; id; every parameter change must be reversible.
;; =====================================================================

defun( vfpCreateTransaction (proposalId changes) vfpNotImplemented("vfpCreateTransaction") )
defun( vfpRecordBeforeState (changes)            vfpNotImplemented("vfpRecordBeforeState") )
defun( vfpRecordAfterState (changes)             vfpNotImplemented("vfpRecordAfterState") )
defun( vfpApplyTransaction (transactionId)       vfpNotImplemented("vfpApplyTransaction") )
defun( vfpRollbackTransaction (transactionId)    vfpNotImplemented("vfpRollbackTransaction") )
defun( vfpGetLastTransaction ()                  vfpNotImplemented("vfpGetLastTransaction") )
