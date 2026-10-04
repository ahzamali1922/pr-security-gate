"""Stage 6 - record one metrics entry per scan run.

Each record: timestamp, pr, sha, run_id, total, severity mix, gate_passed, and
time_to_fix_minutes (set on the first passing run after one or more failing runs
of the same PR). History is a JSON list so the dashboard can read it directly.

Usage:
    python scripts/metrics.py --input findings.json --history metrics/metrics.json \
        --pr 12 --sha abc123 --run-id 999 --fail-on high
"""
import argparse
import datetime
import json
import os
import sys

SEVERITY_ORDER = ["critical", "high", "medium", "low"]


def load_history(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def make_record(findings, history, pr, sha, run_id, fail_on="high", now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    limit = SEVERITY_ORDER.index(fail_on)
    severity = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITY_ORDER}
    passed = sum(severity[s] for s in SEVERITY_ORDER[:limit + 1]) == 0

    record = {
        "timestamp": now.isoformat(timespec="seconds"),
        "pr": pr,
        "sha": sha,
        "run_id": run_id,
        "total": len(findings),
        "severity": severity,
        "gate_passed": passed,
        "time_to_fix_minutes": None,
    }
    if passed:
        # find the first failing run in the current streak of failures for this PR
        first_fail = None
        for previous in reversed([r for r in history if r.get("pr") == pr]):
            if previous["gate_passed"]:
                break
            first_fail = previous
        if first_fail:
            start = datetime.datetime.fromisoformat(first_fail["timestamp"])
            record["time_to_fix_minutes"] = round((now - start).total_seconds() / 60, 1)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="findings.json")
    parser.add_argument("--history", default="metrics/metrics.json")
    parser.add_argument("--pr", type=int, default=0)
    parser.add_argument("--sha", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--fail-on", default="high", choices=SEVERITY_ORDER)
    args = parser.parse_args(argv)

    with open(args.input, encoding="utf-8") as handle:
        findings = json.load(handle)

    history = load_history(args.history)
    record = make_record(findings, history, args.pr, args.sha, args.run_id, args.fail_on)
    history.append(record)

    os.makedirs(os.path.dirname(args.history) or ".", exist_ok=True)
    with open(args.history, "w", encoding="utf-8") as handle:
        json.dump(history, handle, indent=2)
    print(f"Recorded run: {record['total']} findings, gate_passed={record['gate_passed']}, "
          f"time_to_fix_minutes={record['time_to_fix_minutes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
