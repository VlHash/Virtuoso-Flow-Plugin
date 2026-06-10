import json
import os
import shutil
import threading
import time
import uuid

from ..config import ensure_dirs, runs_dir

VALID_STATUSES = ("created", "running", "done", "failed")


def _iso(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts or time.time()))


class RunStore:
    """Tracks simulation runs and their artifacts under .vfp/runs/<run_id>/."""

    def __init__(self):
        self._runs = {}
        self._lock = threading.Lock()
        self._load()

    # ---- persistence ------------------------------------------------
    def _run_dir(self, run_id):
        return runs_dir() / run_id

    def _meta_path(self, run_id):
        return self._run_dir(run_id) / "run.json"

    def _load(self):
        d = runs_dir()
        if not d.exists():
            return
        for sub in d.glob("*/run.json"):
            try:
                r = json.loads(sub.read_text(encoding="utf-8"))
                rid = r.get("run_id")
                if rid:
                    self._runs[rid] = r
            except (OSError, ValueError):
                continue

    def _persist(self, r):
        try:
            ensure_dirs()
            self._run_dir(r["run_id"]).mkdir(parents=True, exist_ok=True)
            self._meta_path(r["run_id"]).write_text(
                json.dumps(r, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ---- operations -------------------------------------------------
    def create(self, meta=None):
        rid = "run_" + uuid.uuid4().hex[:12]
        r = dict(meta or {})
        r["run_id"] = rid
        r.setdefault("status", "created")
        r["created_at"] = _iso()
        r.setdefault("artifacts", {})
        r.setdefault("result_id", None)
        with self._lock:
            self._runs[rid] = r
        self._persist(r)
        return r

    def get(self, run_id):
        return self._runs.get(run_id)

    def list(self, status=None):
        with self._lock:
            items = list(self._runs.values())
        if status:
            items = [r for r in items if r.get("status") == status]
        return sorted(items, key=lambda r: r.get("created_at", ""), reverse=True)

    def latest(self):
        items = self.list()
        return items[0] if items else None

    def set_status(self, run_id, status):
        if status not in VALID_STATUSES:
            raise ValueError("invalid run status: %s" % status)
        return self._update(run_id, lambda r: r.update({"status": status}))

    def link_result(self, run_id, result_id):
        return self._update(run_id, lambda r: r.update({"result_id": result_id}))

    def attach_text(self, run_id, label, filename, text):
        r = self.get(run_id)
        if r is None:
            raise KeyError("unknown run_id: %s" % run_id)
        self._run_dir(run_id).mkdir(parents=True, exist_ok=True)
        path = self._run_dir(run_id) / filename
        path.write_text(text, encoding="utf-8")
        return self._update(run_id,
                            lambda rr: rr["artifacts"].__setitem__(label, str(path)))

    def attach_file(self, run_id, label, src_path):
        r = self.get(run_id)
        if r is None:
            raise KeyError("unknown run_id: %s" % run_id)
        self._run_dir(run_id).mkdir(parents=True, exist_ok=True)
        dst = self._run_dir(run_id) / os.path.basename(src_path)
        shutil.copyfile(src_path, str(dst))
        return self._update(run_id,
                            lambda rr: rr["artifacts"].__setitem__(label, str(dst)))

    # ---- helpers ----------------------------------------------------
    def _update(self, run_id, mutate):
        with self._lock:
            r = self._runs.get(run_id)
            if r is None:
                raise KeyError("unknown run_id: %s" % run_id)
            mutate(r)
            r["updated_at"] = _iso()
        self._persist(r)
        return r
