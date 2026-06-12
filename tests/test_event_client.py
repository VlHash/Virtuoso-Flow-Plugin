"""Tests for scripts/vfp_event_client.py (the SKILL ipc bridge feed)."""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "vfp_event_client.py")


def _run(*argv):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (os.path.join(ROOT, "tunnel"), env.get("PYTHONPATH")) if p)
    return subprocess.run(
        [sys.executable, SCRIPT] + list(argv),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, env=env, timeout=30)


def test_mock_emits_well_formed_lines():
    proc = _run("--mock", "--mock-count", "4", "--mock-interval", "0.01")
    assert proc.returncode == 0
    lines = proc.stdout.strip().splitlines()
    assert len(lines) == 4
    seqs = []
    for line in lines:
        tag, seq, etype = line.split(" ")
        assert tag == "VFP-EVT"
        seqs.append(int(seq))
        assert "." in etype
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_mock_resumes_after_since():
    proc = _run("--mock", "--mock-count", "2", "--mock-interval", "0.01",
                "--since", "41")
    seqs = [int(line.split()[1]) for line in proc.stdout.strip().splitlines()]
    assert seqs == [42, 43]


def test_real_mode_gives_up_when_tunnel_unreachable():
    proc = _run("--host", "127.0.0.1", "--port", "1",
                "--max-failures", "0", "--retry-interval", "0")
    assert proc.returncode == 1
    assert "giving up" in proc.stderr
    assert proc.stdout == ""


def test_session_id_flag_is_accepted():
    proc = _run("--mock", "--mock-count", "1", "--mock-interval", "0.01",
                "--session-id", "s_test123456")
    assert proc.returncode == 0
    assert proc.stdout.startswith("VFP-EVT ")
