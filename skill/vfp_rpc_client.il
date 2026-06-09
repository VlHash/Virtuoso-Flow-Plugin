;; =====================================================================
;; vfp_rpc_client.il — JSON-RPC client to VFP Tunnel
;; ---------------------------------------------------------------------
;; STUB (Milestone 2). Talks to VFP Tunnel over localhost JSON-RPC
;; (default 127.0.0.1:47891). RPC methods:
;;   session.register     proposal.list       transaction.record
;;   session.ping         proposal.approve    transaction.rollback
;;   design.context.update proposal.reject    result.latest
;;                                            task.status
;; =====================================================================

VFP_TUNNEL_HOST = "127.0.0.1"
VFP_TUNNEL_PORT = 47891

defun( vfpConnect ()        vfpNotImplemented("vfpConnect") )
defun( vfpDisconnect ()     vfpNotImplemented("vfpDisconnect") )
defun( vfpRpcCall (method params) vfpNotImplemented("vfpRpcCall") )
defun( vfpPing ()           vfpNotImplemented("vfpPing") )
