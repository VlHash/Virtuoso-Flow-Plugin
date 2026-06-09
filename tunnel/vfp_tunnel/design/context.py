"""Design-context storage under ``.vfp/contexts/``.

Keeps the latest exported context plus a timestamped history.
"""

import json
import time
from pathlib import Path

from ..config import ensure_dirs, vfp_home


def contexts_dir():
    return vfp_home() / "contexts"


def _stamp():
    return time.strftime("%Y%m%d_%H%M%S")


class ContextStore:
    def __init__(self):
        self._latest = None
        self._load_latest()

    def _latest_path(self):
        return contexts_dir() / "latest_context.json"

    def _load_latest(self):
        p = self._latest_path()
        if p.exists():
            try:
                self._latest = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._latest = None

    def update(self, context):
        ensure_dirs()
        d = contexts_dir()
        d.mkdir(parents=True, exist_ok=True)
        self._latest = context
        blob = json.dumps(context, indent=2)
        self._latest_path().write_text(blob, encoding="utf-8")
        (d / ("context_%s.json" % _stamp())).write_text(blob, encoding="utf-8")
        return {"stored": True, "path": str(self._latest_path())}

    def latest(self):
        return self._latest
