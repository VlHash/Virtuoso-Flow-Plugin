#!/usr/bin/env python3
"""Fake Spectre for the M10b cellview-wrapper tests: pretends to simulate a
deck and writes a PSF-ASCII dcOp file the wrapper can parse, then exits 0.

Honors the wrapper's CLI (deck positional, ``-raw <psfdir>``). VFP_FAKE_VMID
overrides the 'mid' node value; set it to ``nan`` to exercise the
metric_quality path. VFP_FAKE_FAIL=1 forces a nonzero exit.
"""
import os
import sys


def main():
    if os.environ.get("VFP_FAKE_FAIL"):
        sys.stderr.write("fake spectre psf: forced failure\n")
        return 1
    argv = sys.argv[1:]
    psfdir = None
    for i, a in enumerate(argv):
        if a == "-raw" and i + 1 < len(argv):
            psfdir = argv[i + 1]
    if not psfdir:
        psfdir = os.path.join(os.getcwd(), "psf")
    os.makedirs(psfdir, exist_ok=True)
    vmid = os.environ.get("VFP_FAKE_VMID", "5.0e-01")
    with open(os.path.join(psfdir, "dcOp.dc"), "w", encoding="utf-8") as f:
        f.write('"mid" "V" %s\n' % vmid)
        f.write('"out" "V" 9.0e-01\n')
    print("fake spectre psf: wrote dcOp.dc")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
