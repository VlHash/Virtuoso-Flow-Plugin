"""Delegated netlist worker (scripts/delegated_netlist.py): the pluggable
backend interface — default vcli, a code-free `command` backend, and a
`module:callable` extension form. The vcli backend itself needs a live vcli
Virtuoso and is verified separately."""
import json
import pathlib
import sys

import pytest

_SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import delegated_netlist as dn  # noqa: E402


def test_resolve_backend_default_is_vcli(monkeypatch):
    monkeypatch.delenv("VFP_DELEGATED_BACKEND", raising=False)
    assert dn.resolve_backend() is dn.vcli_backend


def test_resolve_backend_named(monkeypatch):
    monkeypatch.setenv("VFP_DELEGATED_BACKEND", "command")
    assert dn.resolve_backend() is dn.command_backend


def test_resolve_backend_module_callable():
    fn = dn.resolve_backend("delegated_netlist:vcli_backend")
    assert fn is dn.vcli_backend


def test_resolve_backend_unknown():
    with pytest.raises(ValueError):
        dn.resolve_backend("nope")


def test_netlist_accepts_callable_backend():
    calls = []

    def fake(lib, cell, view, corner):
        calls.append((lib, cell, view, corner))
        return "/tmp/d.scs"

    assert dn.netlist("L", "C", "v", backend=fake) == "/tmp/d.scs"
    assert calls == [("L", "C", "v", "Nominal")]


def test_is_local_mode(monkeypatch):
    # empty / local / localhost -> run vcli directly (co-located); else ssh.
    for val, expected in [("", True), ("local", True), ("LOCALHOST", True),
                          ("  local  ", True), ("meow@host", False)]:
        monkeypatch.setattr(dn, "TARGET", val)
        assert dn._is_local() is expected


def test_command_backend_runs_and_returns_last_line(monkeypatch):
    # the command backend runs a server-configured command and returns its last
    # stdout line (the deck path); the cellview flows via VFP_JOB_* env.
    code = ("import os, sys;"
            "sys.stdout.write('noise\\n');"
            "sys.stdout.write('/decks/%s__%s__%s.scs' % ("
            "os.environ['VFP_JOB_LIB'], os.environ['VFP_JOB_CELL'],"
            " os.environ['VFP_JOB_VIEW']))")
    monkeypatch.setenv("VFP_DELEGATED_NETLIST_CMD",
                       json.dumps([sys.executable, "-c", code]))
    assert dn.command_backend("Project", "inv_tb", "schematic") == \
        "/decks/Project__inv_tb__schematic.scs"


def test_command_backend_without_cmd_returns_none(monkeypatch):
    monkeypatch.delenv("VFP_DELEGATED_NETLIST_CMD", raising=False)
    assert dn.command_backend("L", "C", "v") is None
