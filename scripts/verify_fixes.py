"""Stage 4b - verify AI fixes before they are offered as one-click suggestions.

For every suggestion that could become an "Apply suggestion" button, this script applies the
fix in memory, feeds the fixed file to the same linter on standard input (nothing is written
to disk), and compares the result with a baseline run on the original file:

  verified  the finding is gone and the fix introduced no new finding that would block the gate
  failed    the finding is still reported, or the fix introduced a new blocking finding
            (for example a syntax error)
  skipped   the linter could not run, or the finding could not be reproduced

The outcome is stored in suggestion["verification"]. report_pr.py hides the Apply button for
failed fixes and marks verified ones. This checks that the LINTER is satisfied, not that the
program behaves the same, so the badge says "lint-verified".

Usage:
    python scripts/verify_fixes.py --input enriched-findings.json --summary verification.json
"""
import argparse
import collections
import json
import os
import shutil
import subprocess
import sys

import parse_findings
import report_pr

SEVERITY_ORDER = parse_findings.SEVERITY_ORDER


class LintError(RuntimeError):
    """The linter could not be run or its output could not be read."""


def run_linter(command, content):
    try:
        done = subprocess.run(
            command, input=content, capture_output=True, text=True, encoding="utf-8",
            timeout=int(os.environ.get("VERIFY_TIMEOUT", "90")), check=False)
    except subprocess.SubprocessError as exc:
        raise LintError(f"linter failed to run: {exc}") from exc
    try:
        return json.loads(done.stdout or "[]")
    except ValueError as exc:
        raise LintError(f"linter output is not JSON: {(done.stderr or done.stdout)[:200]!r}") from exc


def lint_python(path, content):
    """Normalized Pylint findings for `content`, as if it were the file at `path`."""
    command = [sys.executable, "-m", "pylint", "--output-format=json", "--from-stdin", path]
    return parse_findings.parse_pylint(run_linter(command, content))


def lint_javascript(path, content):
    """Normalized ESLint findings for `content`, as if it were the file at `path`."""
    npx = shutil.which("npx")
    if not npx:
        raise LintError("npx is not available")
    command = [npx, "--no-install", "eslint", "--stdin", "--stdin-filename", path, "-f", "json"]
    return parse_findings.parse_eslint(run_linter(command, content))


LINTERS = {".py": lint_python, ".js": lint_javascript}


def lint_file(path, content):
    linter = LINTERS.get(os.path.splitext(path)[1])
    if linter is None:
        raise LintError(f"no linter configured for {path}")
    return linter(path, content)


def apply_fix(content, line, text):
    """`content` with line number `line` replaced by `text` (an empty text deletes the line)."""
    lines = content.split("\n")
    if not 1 <= line <= len(lines):
        raise LintError(f"line {line} is outside the file")
    lines[line - 1:line] = text.split("\n") if text else []
    return "\n".join(lines)


def count(findings):
    return collections.Counter((f["rule"], f["message"]) for f in findings)


def verify(finding, line, text, content, lint=lint_file, fail_on="high", baselines=None):
    """Verification result for one suggestion. `lint` and `baselines` are injectable."""
    path = finding["file"]
    baselines = {} if baselines is None else baselines
    if path not in baselines:
        baselines[path] = lint(path, content)
    before = count(baselines[path])
    key = (finding["rule"], finding["message"])
    is_syntax_error = finding["rule"] == "syntax-error"
    reproduced = (any(f["rule"] == "syntax-error" for f in baselines[path])
                  if is_syntax_error else before[key] > 0)
    if not reproduced:
        return {"status": "skipped", "reason": "this finding could not be reproduced in a re-scan"}

    after_findings = lint(path, apply_fix(content, line, text))
    if is_syntax_error:
        # A syntax error hides every other finding in the file, so whatever shows up once the
        # file parses again was already there. The only question is whether it parses now.
        if any(f["rule"] == "syntax-error" for f in after_findings):
            return {"status": "failed", "reason": "the file still does not parse with this fix"}
        return {"status": "verified", "reason": "the file parses again with this fix",
                "new_findings": len(after_findings)}
    after = count(after_findings)
    if after[key] >= before[key]:
        return {"status": "failed", "reason": "the finding is still reported with this fix"}

    limit = SEVERITY_ORDER.index(fail_on)
    severity = {(f["rule"], f["message"]): f["severity"] for f in after_findings}
    new_findings = 0
    for item, number in after.items():
        added = number - before[item]
        if added > 0:
            if SEVERITY_ORDER.index(severity[item]) <= limit:
                return {"status": "failed",
                        "reason": f"the fix introduces a new blocking finding ({item[0]})"}
            new_findings += added
    return {"status": "verified", "reason": "a re-scan no longer reports this finding",
            "new_findings": new_findings}


def verify_all(findings, lint=lint_file, fail_on="high", max_checks=15):
    """Add suggestion["verification"] to every one-click candidate; return the tallies."""
    tally = {"checked": 0, "verified": 0, "failed": 0, "skipped": 0}
    baselines = {}
    for finding in findings:
        suggestion = finding.get("suggestion")
        if not suggestion:
            continue
        line = suggestion.get("line") or finding["line"]
        original = report_pr.read_line(finding["file"], line)
        if original is None:
            continue
        text = report_pr.suggestion_text(finding, original)
        if text is None:
            continue  # not a one-click candidate, nothing to verify
        if tally["checked"] >= max_checks:
            break
        try:
            with open(finding["file"], encoding="utf-8") as handle:
                content = handle.read()
            result = verify(finding, line, text, content, lint, fail_on, baselines)
        except (LintError, OSError, ValueError, KeyError) as exc:
            result = {"status": "skipped", "reason": str(exc)[:200]}
        suggestion["verification"] = result
        tally["checked"] += 1
        tally[result["status"]] += 1
    return tally


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="enriched-findings.json")
    parser.add_argument("--output", help="defaults to --input (updated in place)")
    parser.add_argument("--summary", default="verification.json")
    parser.add_argument("--fail-on", default="high", choices=SEVERITY_ORDER)
    parser.add_argument("--max", type=int, default=15, help="max suggestions to verify")
    args = parser.parse_args(argv)

    with open(args.input, encoding="utf-8") as handle:
        findings = json.load(handle)

    tally = verify_all(findings, fail_on=args.fail_on, max_checks=args.max)

    with open(args.output or args.input, "w", encoding="utf-8") as handle:
        json.dump(findings, handle, indent=2)
    with open(args.summary, "w", encoding="utf-8") as handle:
        json.dump(tally, handle, indent=2)
    print(f"Verified {tally['checked']} fix(es): {tally['verified']} verified, "
          f"{tally['failed']} failed, {tally['skipped']} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
