#!/usr/bin/env python3
"""Stand-in for a real simulator: writes metrics.json into the cwd and exits 0.

Used by the job-runner tests (and as a template for what a real VFP_SIM_CMD
wrapper should produce). Set VFP_FAKE_FAIL=1 to simulate a sim failure.
"""
import json
import os
import sys


def main():
    if os.environ.get("VFP_FAKE_FAIL"):
        sys.stderr.write("fake spectre: forced failure\n")
        return 1
    metrics = {"A0_dB": 101.2, "PM_deg": 72.0, "UGB_MHz": 58.0, "Itotal_uA": 540.0}
    with open(os.path.join(os.getcwd(), "metrics.json"), "w", encoding="utf-8") as f:
        json.dump({"metrics": metrics}, f)
    print("fake spectre: completed, wrote metrics.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
