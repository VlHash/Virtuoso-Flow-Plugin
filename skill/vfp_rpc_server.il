;; =====================================================================
;; vfp_rpc_server.il — optional in-Virtuoso JSON-RPC listener
;; ---------------------------------------------------------------------
;; STUB (deferred). Optional small listener so VFP Tunnel can push
;; events (e.g. "new proposal available") to the plugin instead of the
;; plugin polling. Not loaded by vfp_init.il in the MVP; the plugin acts
;; as a client (see vfp_rpc_client.il).
;; =====================================================================

defun( vfpServerStart ()  vfpNotImplemented("vfpServerStart") )
defun( vfpServerStop ()   vfpNotImplemented("vfpServerStop") )
