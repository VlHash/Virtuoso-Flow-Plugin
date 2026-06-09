"""Tests for the SKILL s-expression encoder used by the bridge helper."""

from vfp_tunnel.skillrpc import to_sexpr


def test_scalars():
    assert to_sexpr(True) == "t"
    assert to_sexpr(False) == "nil"
    assert to_sexpr(None) == "nil"
    assert to_sexpr(42) == "42"
    assert to_sexpr(-32601) == "-32601"
    assert to_sexpr("abc") == '"abc"'


def test_string_escaping():
    # backslash and double-quote are escaped for the SKILL reader
    assert to_sexpr('a"b\\c') == '"a\\"b\\\\c"'


def test_dict_becomes_alist():
    assert to_sexpr({"session_id": "s_1"}) == '(("session_id" "s_1"))'


def test_list_becomes_plain_list():
    assert to_sexpr(["a", "b"]) == '("a" "b")'


def test_nested_preserves_order():
    s = to_sexpr({"ok": True, "n": 2, "items": ["a", "b"]})
    assert s == '(("ok" t) ("n" 2) ("items" ("a" "b")))'
