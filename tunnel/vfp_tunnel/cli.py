"""VFP Tunnel CLI entry point (skeleton).

The full command set (``vfp tunnel start|stop|status``, ``vfp session ...``,
``vfp proposal ...``, etc.) is implemented from Milestone 2 onward; see
``project.md`` §9.1. For now this only proves the ``vfp`` console script is
wired up.
"""

from __future__ import annotations

import sys

from . import __version__


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-v", "--version"):
        print(f"vfp {__version__}")
        return 0
    print(f"vfp {__version__} - VFP Tunnel CLI (skeleton; not implemented yet).")
    print("Planned commands: tunnel, session, context, proposal, transaction, "
          "result, constraint. See project.md section 9.1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
