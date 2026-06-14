import subprocess

from ..config import runs_dir
from .metrics import make_result
from .parser import parse_metrics_file


class JobRunner:
    """Drives a queued job to done/failed by executing a (server-configured)
    command in a fresh run dir, parsing the metrics file it writes, and storing
    a result. The command is never supplied by an RPC client.
    """

    def __init__(self, jobs, results, runs, events=None):
        self.jobs = jobs
        self.results = results
        self.runs = runs
        self.events = events

    def _emit(self, etype, payload):
        if self.events is not None:
            self.events.emit(etype, payload)

    def _fail(self, job_id, run_id, error):
        if run_id:
            try:
                self.runs.set_status(run_id, "failed")
            except (KeyError, ValueError):
                pass
        job = self.jobs.mark_failed(job_id, error=error)
        self._emit("job.failed", {"job_id": job_id, "error": error})
        return job

    def run(self, job_id, command, metrics_file="metrics.json", timeout_s=600):
        """Synchronous; returns the final job record (done or failed)."""
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError("unknown job_id: %s" % job_id)

        run = self.runs.create({"test": job.get("test"),
                                "cellview": job.get("cellview"),
                                "job_id": job_id})
        rid = run["run_id"]
        run_dir = runs_dir() / rid
        self.jobs.mark_running(job_id)
        self.runs.set_status(rid, "running")

        try:
            proc = subprocess.run(
                command, cwd=str(run_dir),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return self._fail(job_id, rid, "simulator timed out after %ss" % timeout_s)
        except OSError as e:
            return self._fail(job_id, rid, "could not launch simulator: %s" % e)

        log = (proc.stdout or b"").decode("utf-8", "replace")
        try:
            self.runs.attach_text(rid, "log", "sim.log", log)
        except (KeyError, OSError):
            pass

        if proc.returncode != 0:
            return self._fail(job_id, rid, "simulator exited %d" % proc.returncode)

        mpath = run_dir / metrics_file
        if not mpath.exists():
            return self._fail(job_id, rid,
                              "simulator produced no metrics file (%s)" % metrics_file)
        try:
            metrics = parse_metrics_file(str(mpath))
        except (OSError, ValueError) as e:
            return self._fail(job_id, rid, "could not parse metrics: %s" % e)
        if not metrics:
            return self._fail(job_id, rid, "no metrics parsed from %s" % metrics_file)

        result = make_result({"metrics": metrics, "source": "spectre",
                              "test": job.get("test"),
                              "cellview": job.get("cellview")})
        self.results.update(result)
        self.runs.link_result(rid, result["result_id"])
        self.runs.set_status(rid, "done")
        done = self.jobs.mark_done(job_id, result_id=result["result_id"], run_id=rid)
        self._emit("result.updated", {"result_id": result["result_id"]})
        self._emit("job.done", {"job_id": job_id,
                                "result_id": result["result_id"], "run_id": rid})
        return done
