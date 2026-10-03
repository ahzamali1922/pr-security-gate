"""Stage 2 - normalize Pylint and ESLint JSON reports into one schema.

Output: a JSON list of {file, line, rule, severity, message, tool}, sorted with
the most severe findings first.

Usage:
    python scripts/parse_findings.py --pylint pylint-report.json \
        --eslint eslint-report.json --output findings.json
"""
import argparse
import json
import os
import sys

SEVERITY_ORDER = ["critical", "high", "medium", "low"]

# Pylint message types -> common severity scale.
PYLINT_SEVERITY = {
    "fatal": "critical",
    "error": "high",
    "warning": "medium",
    "refactor": "low",
    "convention": "low",
    "info": "low",
}

# ESLint severities: 2 = error, 1 = warn. Parse errors (fatal) are critical.
ESLINT_SEVERITY = {2: "high", 1: "medium"}

# Rules that indicate a real security risk are bumped up one level.
SECURITY_RULES = {
    "bare-except",
    "eval-used",
    "exec-used",
    "subprocess-run-check",
    "no-eval",
    "no-implied-eval",
    "no-new-func",
}


def bump(severity):
    """Raise a severity by one level (low -> medium -> high -> critical)."""
    index = SEVERITY_ORDER.index(severity)
    return SEVERITY_ORDER[max(index - 1, 0)]


def relpath(path):
    """Return path relative to the working directory, with forward slashes."""
    try:
        path = os.path.relpath(path)
    except ValueError:  # different drive on Windows
        pass
    return path.replace("\\", "/")


def parse_pylint(data):
    findings = []
    for item in data:
        rule = item.get("symbol") or item.get("message-id", "unknown")
        severity = PYLINT_SEVERITY.get(item.get("type"), "low")
        if rule in SECURITY_RULES:
            severity = bump(severity)
        findings.append({
            "file": relpath(item.get("path", "")),
            "line": item.get("line") or 1,
            "rule": rule,
            "severity": severity,
            "message": item.get("message", ""),
            "tool": "pylint",
        })
    return findings


def parse_eslint(data):
    findings = []
    for entry in data:
        path = relpath(entry.get("filePath", ""))
        for msg in entry.get("messages", []):
            rule = msg.get("ruleId") or "parse-error"
            if msg.get("fatal"):
                severity = "critical"
            else:
                severity = ESLINT_SEVERITY.get(msg.get("severity"), "low")
                if rule in SECURITY_RULES:
                    severity = bump(severity)
            findings.append({
                "file": path,
                "line": msg.get("line") or 1,
                "rule": rule,
                "severity": severity,
                "message": msg.get("message", ""),
                "tool": "eslint",
            })
    return findings


def sort_findings(findings):
    return sorted(
        findings,
        key=lambda f: (SEVERITY_ORDER.index(f["severity"]), f["file"], f["line"]),
    )


def load_json(path):
    if not path:
        return []
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def normalize(pylint_data=None, eslint_data=None):
    findings = parse_pylint(pylint_data or []) + parse_eslint(eslint_data or [])
    return sort_findings(findings)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pylint", help="path to pylint JSON report")
    parser.add_argument("--eslint", help="path to eslint JSON report")
    parser.add_argument("--output", default="findings.json")
    args = parser.parse_args(argv)

    findings = normalize(load_json(args.pylint), load_json(args.eslint))
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(findings, handle, indent=2)
    print(f"Wrote {len(findings)} findings to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
