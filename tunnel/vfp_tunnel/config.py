"""Configuration and on-disk layout for VFP Tunnel.

Pure stdlib, Python 3.6+. The artifact root defaults to ``./.vfp`` and can
be overridden with the ``VFP_HOME`` environment variable; host/port can be
overridden with ``VFP_HOST`` / ``VFP_PORT``.
"""

import os
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 47891


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


def ensure_dirs():
    for d in (vfp_home(), log_dir(), sessions_dir(), proposals_dir()):
        d.mkdir(parents=True, exist_ok=True)


def resolve_host(host=None):
    return host or os.environ.get("VFP_HOST") or DEFAULT_HOST


def resolve_port(port=None):
    if port not in (None, ""):
        return int(port)
    return int(os.environ.get("VFP_PORT", DEFAULT_PORT))
