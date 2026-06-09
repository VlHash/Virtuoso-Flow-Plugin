;; =====================================================================
;; vfp_schematic.il — controlled schematic access
;; ---------------------------------------------------------------------
;; STUB (Milestone 5). All parameter changes MUST go through the
;; transaction-aware wrappers in vfp_transaction.il. No unrestricted
;; SKILL evaluation is ever exposed to the agent-facing API.
;; =====================================================================

defun( vfpListInstances (cv)                          vfpNotImplemented("vfpListInstances") )
defun( vfpGetInstanceParams (cv instName)             vfpNotImplemented("vfpGetInstanceParams") )
defun( vfpSetInstanceParam (cv instName paramName value) vfpNotImplemented("vfpSetInstanceParam") )
defun( vfpBatchSetInstanceParams (cv changes)         vfpNotImplemented("vfpBatchSetInstanceParams") )
defun( vfpSaveCellView (cv)                           vfpNotImplemented("vfpSaveCellView") )
