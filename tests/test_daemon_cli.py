"""`vfp daemon` CLI + the supervisor entry (serve_main) in
tunnel/vfp_tunnel/sim/virtuoso_daemon.py. The detached-spawn + ready path is
live-tested; here we cover the state file, the failed-boot path, pid checks,
and the parser wiring."""
import types

from vfp_tunnel import cli
from vfp_tunnel.sim import virtuoso_daemon as vd


class _FakeNotReady:
    """A VirtuosoDaemon whose boot never reaches readiness."""

    def __init__(self, boot=None, cwd=None, ready_timeout_s=120):
        self.boot = boot or "/x/boot.il"
        self.cwd = cwd

    def status(self):
        return {"pid": None}

    def ensure_up(self, wait=True):
        return False

    def tail(self, n=20):
        return ["boot...", "VFP-DAEMON-ERROR connect=nil"]

    def stop(self, timeout=10):
        self.stopped = True


def test_serve_main_failed_writes_state_and_returns_3(monkeypatch, tmp_path):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    monkeypatch.setattr(vd, "VirtuosoDaemon", _FakeNotReady)
    captured = []
    monkeypatch.setattr(vd, "_write_state", lambda d: captured.append(d))
    rc = vd.serve_main(["--cwd", str(tmp_path)])
    assert rc == 3
    statuses = [c.get("status") for c in captured]
    assert "starting" in statuses and "failed" in statuses


def test_state_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    vd._write_state({"supervisor_pid": 123, "status": "ready"})
    st = vd.read_state()
    assert st["supervisor_pid"] == 123 and st["status"] == "ready"
    vd._unlink_state()
    assert vd.read_state() is None


def test_pid_alive_invalid():
    assert cli._pid_alive(None) is False
    assert cli._pid_alive("nope") is False
    assert cli._pid_alive(-1) is False


def test_daemon_status_not_running(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    rc = cli.cmd_daemon_status(types.SimpleNamespace())
    assert rc == 1
    assert "not running" in capsys.readouterr().out


def test_daemon_stop_when_not_running(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    rc = cli.cmd_daemon_stop(types.SimpleNamespace())
    assert rc == 0
    assert "not running" in capsys.readouterr().out


def test_parser_has_daemon_subcommands():
    p = cli.build_parser()
    ns = p.parse_args(["daemon", "start", "--cwd", "/tmp/x"])
    assert ns.func is cli.cmd_daemon_start and ns.cwd == "/tmp/x"
    assert p.parse_args(["daemon", "status"]).func is cli.cmd_daemon_status
    assert p.parse_args(["daemon", "stop"]).func is cli.cmd_daemon_stop
