"""Security gate: exit 1 if any finding is at or above the blocking severity.

Usage:
    python scripts/gate.py --input findings.json --fail-on high
"""
import argparse
import json
import sys

SEVERITY_ORDER = ["critical", "high", "medium", "low"]


def blocking(findings, fail_on):
    """Findings whose severity is `fail_on` or worse."""
    limit = SEVERITY_ORDER.index(fail_on)
    return [f for f in findings if SEVERITY_ORDER.index(f["severity"]) <= limit]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="findings.json")
    parser.add_argument("--fail-on", default="high", choices=SEVERITY_ORDER)
    args = parser.parse_args(argv)

    with open(args.input, encoding="utf-8") as handle:
        findings = json.load(handle)

    blockers = blocking(findings, args.fail_on)
    if blockers:
        print(f"GATE FAILED: {len(blockers)} finding(s) at '{args.fail_on}' or worse.")
        return 1
    print(f"GATE PASSED: no findings at '{args.fail_on}' or worse.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
