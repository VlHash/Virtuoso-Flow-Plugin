"""Configuration and on-disk layout for VFP Tunnel.

Pure stdlib, Python 3.6+. The artifact root defaults to ``./.vfp`` and can
be overridden with the ``VFP_HOME`` environment variable; host/port can be
overridden with ``VFP_HOST`` / ``VFP_PORT``.
"""

import os
import shlex
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 47891
DEFAULT_SIM_TIMEOUT_S = 600
DEFAULT_SIM_METRICS_FILE = "metrics.json"

# Pending proposals older than this many seconds are aged out to "expired"
# (lazily, on the next list/get). Override with VFP_PROPOSAL_TTL_S; set to
# 0 (or negative) to disable expiry entirely.
DEFAULT_PROPOSAL_TTL_S = 300

# Sessions idle longer than this (no heartbeat) may be reaped. Heartbeat is
# the event-bridge long-poll, so a dead Virtuoso stops touching within one
# poll interval. Override with VFP_SESSION_TTL_S; 0 (default) = no auto-reap.
DEFAULT_SESSION_TTL_S = 0


def vfp_home():
    env = os.environ.get("VFP_HOME")
    return Path(env) if env else (Path.cwd() / ".vfp")


def state_file():
    return vfp_home() / "tunnel.json"


def log_dir():
    return vfp_home() / "logs"


def sessions_dir():
    return vfp_home() / "sessions"


def proposals_dir():
    return vfp_home() / "proposals"


def transactions_dir():
    return vfp_home() / "transactions"


def results_dir():
    return vfp_home() / "results"


def runs_dir():
    return vfp_home() / "runs"


def events_dir():
    return vfp_home() / "events"


def jobs_dir():
    return vfp_home() / "jobs"


def ensure_dirs():
    for d in (vfp_home(), log_dir(), sessions_dir(), proposals_dir(),
              transactions_dir(), results_dir(), runs_dir(), events_dir(),
              jobs_dir()):
        d.mkdir(parents=True, exist_ok=True)


def proposal_ttl_s():
    """Seconds a pending proposal lives before being auto-expired (0 = off)."""
    raw = os.environ.get("VFP_PROPOSAL_TTL_S")
    if raw in (None, ""):
        return DEFAULT_PROPOSAL_TTL_S
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PROPOSAL_TTL_S


def session_ttl_s():
    """Seconds a session may be idle before it can be reaped (0 = off)."""
    raw = os.environ.get("VFP_SESSION_TTL_S")
    if raw in (None, ""):
        return DEFAULT_SESSION_TTL_S
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_SESSION_TTL_S


def sim_cmd():
    """Argv for the simulator the job runner executes, from VFP_SIM_CMD.

    Server-configured ONLY (never taken from an RPC client), so an agent
    cannot inject an arbitrary command. Returns a list (shlex-split) or None
    if unset. The command runs in the job's run dir and must write the metrics
    file (see sim_metrics_file()).
    """
    raw = os.environ.get("VFP_SIM_CMD")
    if not raw:
        return None
    try:
        argv = shlex.split(raw)
    except ValueError:
        return None
    return argv or None


def sim_metrics_file():
    return os.environ.get("VFP_SIM_METRICS_FILE") or DEFAULT_SIM_METRICS_FILE


def sim_timeout_s():
    raw = os.environ.get("VFP_SIM_TIMEOUT_S")
    if raw in (None, ""):
        return DEFAULT_SIM_TIMEOUT_S
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_SIM_TIMEOUT_S


def resolve_host(host=None):
    return host or os.environ.get("VFP_HOST") or DEFAULT_HOST


def resolve_port(port=None):
    if port not in (None, ""):
        return int(port)
    return int(os.environ.get("VFP_PORT", DEFAULT_PORT))
