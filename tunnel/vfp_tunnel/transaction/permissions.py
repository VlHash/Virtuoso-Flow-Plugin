"""Modify-permission matching over '<instance>.<param>' targets.

Patterns are glob-like (shell wildcards via ``fnmatch``), e.g. ``M*.w``,
``C*.c``, ``VDD.*``. Semantics:

  * a target matching any ``deny_modify`` pattern is always blocked;
  * if ``allow_modify`` is non-empty, a target must match at least one
    allow pattern (otherwise it is blocked);
  * if ``allow_modify`` is empty/None, anything not denied is allowed.

Pure stdlib, Python 3.6+. These are the primitives the constraint engine
(Milestone 6) will feed with patterns parsed from the constraint file.
"""

import fnmatch


def target_of(change):
    """Return the '<instance>.<param>' target string for a change/param-value."""
    return "%s.%s" % (change.get("instance", ""), change.get("param", ""))


def is_allowed(target, allow=None, deny=None):
    """Return (allowed: bool, reason: str) for a single target string."""
    for pat in (deny or []):
        if fnmatch.fnmatchcase(target, pat):
            return False, "denied by deny_modify pattern %r" % pat
    allow = allow or []
    if allow and not any(fnmatch.fnmatchcase(target, pat) for pat in allow):
        return False, "not matched by any allow_modify pattern"
    return True, "ok"


def violations(changes, allow=None, deny=None):
    """Return a list of {target, reason} for every blocked change.

    *changes* is an iterable of dicts each carrying ``instance`` and ``param``
    (proposal ``set_instance_param`` items or transaction ``param_value``
    items both qualify). An empty result means every change is permitted.
    """
    out = []
    for ch in changes or []:
        target = target_of(ch)
        ok, reason = is_allowed(target, allow, deny)
        if not ok:
            out.append({"target": target, "reason": reason})
    return out
