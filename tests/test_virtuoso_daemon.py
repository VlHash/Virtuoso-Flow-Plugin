"""VFP Daemon (Phase 2) lifecycle manager -- tunnel/vfp_tunnel/sim/virtuoso_daemon.py.

Exercised against a FAKE headless Virtuoso (a tiny python that prints the ready
marker when it receives the boot load() line and exits on exit()), so start /
ready / status / stop / restart / serve are all covered without a real Cadence
install."""
import sys

import pytest

from vfp_tunnel import config
from vfp_tunnel.sim.virtuoso_daemon import (
    DEFAULT_VIRTUOSO_CMD, READY_MARKER, VirtuosoDaemon, resolve_command)

# A fake `virtuoso -nograph`: read the CIW stdin line by line (readline, not
# iteration, to avoid pipe read-ahead), print the ready marker once the boot
# load() arrives, exit cleanly on exit() (or when stdin closes).
FAKE_READY = (
    "import sys\n"
    "while True:\n"
    "    line = sys.stdin.readline()\n"
    "    if not line:\n"
    "        break\n"
    "    if 'load(' in line:\n"
    "        sys.stdout.write('boot...\\nVFP-DAEMON-READY\\n'); sys.stdout.flush()\n"
    "    if 'exit(' in line:\n"
    "        break\n"
)

# A fake that never reaches readiness -- it exits immediately.
FAKE_DIES = "import sys\nsys.exit(0)\n"


def _ready_daemon(**kw):
    return VirtuosoDaemon(command=[sys.executable, "-c", FAKE_READY],
                          boot="/x/boot.il", ready_timeout_s=5, **kw)


def _dying_daemon(**kw):
    return VirtuosoDaemon(command=[sys.executable, "-c", FAKE_DIES],
                          boot="/x/boot.il", ready_timeout_s=1, **kw)


def test_resolve_command_default(monkeypatch):
    monkeypatch.delenv("VFP_VIRTUOSO_CMD", raising=False)
    assert resolve_command() == DEFAULT_VIRTUOSO_CMD
    assert config.virtuoso_cmd() is None


def test_resolve_command_from_env_json(monkeypatch):
    monkeypatch.setenv("VFP_VIRTUOSO_CMD", '["virtuoso", "-nograph", "-restore"]')
    assert config.virtuoso_cmd() == ["virtuoso", "-nograph", "-restore"]
    assert resolve_command() == ["virtuoso", "-nograph", "-restore"]


def test_start_reaches_ready_then_stop():
    d = _ready_daemon()
    try:
        d.start()
        assert d.wait_ready() is True
        st = d.status()
        assert st["alive"] is True and st["ready"] is True
        assert st["pid"] and st["uptime_s"] is not None
        assert READY_MARKER in "\n".join(d.tail())
    finally:
        d.stop()
    assert d.is_alive() is False
    assert d.status()["alive"] is False


def test_start_is_idempotent_while_alive():
    d = _ready_daemon()
    try:
        d.start()
        assert d.wait_ready()
        pid1 = d.status()["pid"]
        d.start()                       # no-op while alive -- same process
        assert d.status()["pid"] == pid1
    finally:
        d.stop()


def test_ensure_up_starts_and_waits():
    d = _ready_daemon()
    try:
        assert d.ensure_up(wait=True) is True
        assert d.is_alive() is True
    finally:
        d.stop()


def test_restart_replaces_process():
    d = _ready_daemon()
    try:
        d.start()
        assert d.wait_ready()
        pid1 = d.status()["pid"]
        d.restart()
        assert d.wait_ready()
        pid2 = d.status()["pid"]
        assert pid1 and pid2 and pid1 != pid2
    finally:
        d.stop()


def test_wait_ready_false_when_process_dies():
    d = _dying_daemon()
    try:
        d.start()
        assert d.wait_ready(timeout=2) is False
        assert d.is_alive() is False
        assert d.status()["ready"] is False
    finally:
        d.stop()


def test_start_raises_on_bad_command():
    d = VirtuosoDaemon(command=["vfp-no-such-binary-xyz"], boot="/x/b.il")
    with pytest.raises(RuntimeError):
        d.start()


def test_serve_restarts_on_death():
    d = _dying_daemon()
    n = d.serve(restart=True, poll_s=0.02, _max_restarts=2)
    assert n == 2
    assert d.is_alive() is False
