import json
import time

from ..config import ensure_dirs, results_dir


def _stamp():
    return time.strftime("%Y%m%d_%H%M%S")


class ResultStore:
    def __init__(self):
        self._latest = None
        self._load_latest()

    def _latest_path(self):
        return results_dir() / "latest_result.json"

    def _load_latest(self):
        p = self._latest_path()
        if p.exists():
            try:
                self._latest = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._latest = None

    def update(self, result):
        ensure_dirs()
        d = results_dir()
        d.mkdir(parents=True, exist_ok=True)
        self._latest = result
        blob = json.dumps(result, indent=2)
        self._latest_path().write_text(blob, encoding="utf-8")
        (d / ("result_%s.json" % _stamp())).write_text(blob, encoding="utf-8")
        return {"stored": True, "path": str(self._latest_path())}

    def latest(self):
        return self._latest
