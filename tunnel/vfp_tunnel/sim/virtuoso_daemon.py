"""VFP Daemon (Phase 2): manage a persistent headless Virtuoso with the plugin
loaded and connected, so delegated netlisting runs FULLY UNATTENDED over VFP's
own plugin<->tunnel channel -- no user GUI, and no third-party vcli.

It is the standalone counterpart of the attended (值守) path. Where attended
reuses the *user's* live session and delegated-over-vcli reuses a *vcli-managed*
session, the VFP Daemon owns its own session:

    VirtuosoDaemon.start()
      -> launch `virtuoso -nograph`            (VFP_VIRTUOSO_CMD, else default)
      -> feed `load("<skill/vfp_daemon_boot.il>")` on the CIW stdin
           boot: vfpLoad -> vfpConnect -> vfpEventBridgeStart
                 -> prints READY_MARKER once connected + servicing
      -> the connected plugin services `netlist.request` events headless
         (vfpServiceNetlistRequests, #51) -> deck at the convention path.

The `plugin` delegated backend (scripts/delegated_netlist.py) then drives this
managed session exactly as it would a GUI one: a `netlist.request` RPC, polled to
the deck. The daemon's job is only lifecycle -- launch, readiness, health,
restart, stop.

Pure stdlib, Python 3.6+. The launch command is server-configured only (like
VFP_SIM_CMD / VFP_NETLIST_CMD), never taken from an RPC client.
"""
import subprocess
import threading
import time
from pathlib import Path

from ..config import virtuoso_cmd as _cfg_virtuoso_cmd

# Headless Virtuoso evaluates SKILL from the CIW stdin; the default is the
# standard no-graphics invocation. Override with VFP_VIRTUOSO_CMD.
DEFAULT_VIRTUOSO_CMD = ["virtuoso", "-nograph"]

# The boot script prints this single line once the plugin is connected and the
# event bridge (netlist servicing) is running. The manager scans stdout for it.
READY_MARKER = "VFP-DAEMON-READY"

_TAIL_MAX = 200


def _repo_root():
    # tunnel/vfp_tunnel/sim/virtuoso_daemon.py -> repo root is parents[3].
    return Path(__file__).resolve().parents[3]


def default_boot_il():
    """Path to the SKILL boot script fed to Virtuoso (the in-repo
    skill/vfp_daemon_boot.il). Overridable per-instance via the constructor."""
    return str(_repo_root() / "skill" / "vfp_daemon_boot.il")


def resolve_command():
    """The launch argv: VFP_VIRTUOSO_CMD if set, else `virtuoso -nograph`."""
    return _cfg_virtuoso_cmd() or list(DEFAULT_VIRTUOSO_CMD)


class VirtuosoDaemon:
    """Lifecycle for one VFP-managed headless Virtuoso + plugin.

    start()       launch + feed the boot script; idempotent while alive.
    wait_ready()  block until the plugin reports connected + servicing.
    ensure_up()   start if not alive (the entry point a supervisor/backend uses).
    status()      a small dict for `vfp` / health checks.
    stop()        graceful exit() then terminate/kill.
    restart()     stop + start.
    serve()       foreground supervisor loop; restarts on unexpected exit.
    """

    def __init__(self, command=None, boot=None, ready_marker=READY_MARKER,
                 ready_timeout_s=120):
        self.command = list(command) if command else resolve_command()
        self.boot = boot or default_boot_il()
        self.ready_marker = ready_marker
        self.ready_timeout_s = ready_timeout_s
        self._proc = None
        self._started_at = None
        self._ready = threading.Event()
        self._log_lock = threading.Lock()
        self._tail = []          # bounded recent stdout lines, for status/debug
        self._drain = None

    # ---- process control -------------------------------------------------
    def start(self):
        """Launch Virtuoso and feed the boot script on stdin. No-op if alive."""
        if self.is_alive():
            return self.status()
        self._ready.clear()
        with self._log_lock:
            self._tail = []
        try:
            self._proc = subprocess.Popen(
                self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)
        except OSError as e:
            self._proc = None
            raise RuntimeError(
                "could not launch Virtuoso %r: %s" % (self.command, e))
        self._started_at = time.time()
        self._drain = threading.Thread(target=self._drain_stdout, daemon=True)
        self._drain.start()
        # -nograph evaluates the CIW stdin, so a single load() boots the plugin;
        # stdin stays open afterwards to keep the CIW alive (closed in stop()).
        try:
            self._proc.stdin.write('load("%s")\n' % self.boot)
            self._proc.stdin.flush()
        except (OSError, ValueError):
            pass
        return self.status()

    def _drain_stdout(self):
        """Drain the child's stdout so the pipe never blocks Virtuoso, keep a
        bounded tail for status, and flip the ready flag on the marker."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.rstrip("\n")
            with self._log_lock:
                self._tail.append(line)
                if len(self._tail) > _TAIL_MAX:
                    self._tail = self._tail[-_TAIL_MAX:]
            if self.ready_marker and self.ready_marker in line:
                self._ready.set()

    def is_alive(self):
        return self._proc is not None and self._proc.poll() is None

    def wait_ready(self, timeout=None):
        """Block until the boot prints the ready marker. Returns True if ready,
        False on timeout or if the process died before signalling."""
        if timeout is None:
            timeout = self.ready_timeout_s
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._ready.is_set():
                return True
            if not self.is_alive():
                return self._ready.is_set()
            self._ready.wait(0.1)
        return self._ready.is_set()

    def ensure_up(self, wait=True):
        """Start the daemon if it is not already running. With wait=True, block
        until the plugin is connected + servicing (returns readiness); else
        return liveness. The supervisor / a future `vfp daemon` CLI calls this so
        an unattended job needs no pre-started Virtuoso."""
        if not self.is_alive():
            self.start()
        return self.wait_ready() if wait else self.is_alive()

    def stop(self, timeout=10):
        """Graceful shutdown: ask the CIW to exit(), then terminate/kill."""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write("exit()\n")
                    proc.stdin.flush()
                    proc.stdin.close()
            except (OSError, ValueError):
                pass
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self._proc = None
        self._started_at = None
        self._ready.clear()

    def restart(self, timeout=10):
        self.stop(timeout=timeout)
        return self.start()

    # ---- introspection ---------------------------------------------------
    def status(self):
        alive = self.is_alive()
        return {
            "alive": alive,
            "ready": self._ready.is_set(),
            "pid": self._proc.pid if self._proc else None,
            "started_at": self._started_at,
            "uptime_s": (time.time() - self._started_at)
                        if (alive and self._started_at) else None,
            "command": list(self.command),
            "boot": self.boot,
        }

    def tail(self, n=20):
        """The most recent stdout lines (boot log) -- for diagnosing a daemon
        that started but never reached readiness."""
        with self._log_lock:
            return list(self._tail[-n:])

    # ---- supervisor ------------------------------------------------------
    def serve(self, restart=True, poll_s=2.0, _max_restarts=None):
        """Foreground supervisor: keep Virtuoso up, restarting on unexpected
        exit. Blocks until interrupted (Ctrl-C). `_max_restarts` bounds the loop
        for tests. Returns the number of restarts performed."""
        restarts = 0
        self.ensure_up(wait=True)
        try:
            while True:
                if not self.is_alive():
                    if not restart:
                        break
                    if _max_restarts is not None and restarts >= _max_restarts:
                        break
                    restarts += 1
                    self.start()
                    self.wait_ready()
                time.sleep(poll_s)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
        return restarts
