"""JSON-RPC error taxonomy for the VFP Tunnel.

Single source of truth for error codes. Standard JSON-RPC 2.0 codes are
re-exported from ``jsonrpc``; application codes live in the server-reserved
range (-32000..-32099). Clients branch on these, so the values are stable.
"""

from .jsonrpc import (INTERNAL_ERROR, INVALID_PARAMS, INVALID_REQUEST,
                      METHOD_NOT_FOUND, PARSE_ERROR, SERVER_ERROR)

# ---- application errors (server-reserved -32000..-32099) ------------
# Assigned:
NOT_FOUND = -32001          # unknown id (proposal/transaction/run/session)
PERMISSION_DENIED = -32002  # modify blocked by allow_modify/deny_modify
INVALID_STATE = -32003      # illegal state transition / precondition not met
CONFLICT = -32004           # duplicate id / already exists
STALE = -32005              # data is out of date (freshness guard)

# Reserved ranges for forthcoming subsystems (do not collide with the above):
#   -32010 .. -32019   session / connectivity
#   -32020 .. -32029   sim / job            (M9)
#   -32030 .. -32039   constraints / results
SESSION_BASE = -32010
JOB_BASE = -32020
RESULT_BASE = -32030


def message_for(code):
    """Short human label for a code (best-effort; for logs/diagnostics)."""
    return {
        PARSE_ERROR: "parse error",
        INVALID_REQUEST: "invalid request",
        METHOD_NOT_FOUND: "method not found",
        INVALID_PARAMS: "invalid params",
        INTERNAL_ERROR: "internal error",
        SERVER_ERROR: "server error",
        NOT_FOUND: "not found",
        PERMISSION_DENIED: "permission denied",
        INVALID_STATE: "invalid state",
        CONFLICT: "conflict",
        STALE: "stale",
    }.get(code, "error")


__all__ = [
    "PARSE_ERROR", "INVALID_REQUEST", "METHOD_NOT_FOUND", "INVALID_PARAMS",
    "INTERNAL_ERROR", "SERVER_ERROR",
    "NOT_FOUND", "PERMISSION_DENIED", "INVALID_STATE", "CONFLICT", "STALE",
    "SESSION_BASE", "JOB_BASE", "RESULT_BASE", "message_for",
]
