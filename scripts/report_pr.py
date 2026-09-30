"""Stage 3 - report findings on the pull request.

Produces three outputs:
  * inline annotations on the diff (GitHub workflow commands, `::error file=...`)
  * the job summary page ($GITHUB_STEP_SUMMARY)
  * a single PR comment that is updated in place on every re-scan

Posting the comment needs GITHUB_TOKEN with `pull-requests: write`. On fork PRs the
token is read-only, so posting is skipped with a warning instead of failing the job.

Usage:
    python scripts/report_pr.py --input enriched-findings.json
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

MARKER = "<!-- pr-security-gate -->"
SEVERITY_ORDER = ["critical", "high", "medium", "low"]
ICONS = {"critical": "🟥", "high": "🟧", "medium": "🟨", "low": "⬜"}
ANNOTATION_LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "notice"}
MAX_ANNOTATIONS = 50  # GitHub shows at most 50 annotations per step


def counts(findings):
    return {sev: sum(1 for f in findings if f["severity"] == sev) for sev in SEVERITY_ORDER}


def build_comment(findings, fail_on="high", run_url=""):
    tally = counts(findings)
    limit = SEVERITY_ORDER.index(fail_on)
    blockers = sum(tally[s] for s in SEVERITY_ORDER[:limit + 1])
    status = "❌ **Gate failed**" if blockers else "✅ **Gate passed**"

    lines = [MARKER, "## 🔒 PR Security Gate", ""]
    lines.append(f"{status} — {len(findings)} finding(s), {blockers} blocking (`{fail_on}` or worse)")
    lines.append("")
    lines.append("| Critical | High | Medium | Low |")
    lines.append("|---|---|---|---|")
    lines.append("| " + " | ".join(str(tally[s]) for s in SEVERITY_ORDER) + " |")
    lines.append("")

    if not findings:
        lines.append("No findings. Nice work.")
    for sev in SEVERITY_ORDER:
        group = [f for f in findings if f["severity"] == sev]
        if not group:
            continue
        lines.append(f"### {ICONS[sev]} {sev.capitalize()} ({len(group)})")
        for f in group:
            lines.append(f"- **`{f['file']}:{f['line']}`** `{f['rule']}` ({f['tool']}) — {f['message']}")
            s = f.get("suggestion")
            if s:
                fix = s["fix"].replace("\n", "\n    ")
                lines.append(f"  - 💡 **Suggested fix:** {fix}")
                lines.append(f"  - _Why:_ {s['rationale']}")
        lines.append("")
    lines.append("---")
    footer = "A human reviewer must approve before merge; pushing a new commit triggers an automatic re-scan."
    if run_url:
        footer += f" [Workflow run]({run_url})"
    lines.append(f"_{footer}_")
    return "\n".join(lines)


def print_annotations(findings):
    for f in findings[:MAX_ANNOTATIONS]:
        level = ANNOTATION_LEVEL[f["severity"]]
        text = f"[{f['severity']}] {f['message']}"
        s = f.get("suggestion")
        if s:
            text += f" | Suggested fix: {s['fix']}"
        text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::{level} file={f['file']},line={f['line']},title={f['rule']}::{text}")


def api(method, url, token, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def post_comment(body, repo, pr_number, token, api_url="https://api.github.com"):
    """Create the PR comment, or update the existing one that carries MARKER."""
    base = f"{api_url}/repos/{repo}/issues"
    comments = api("GET", f"{base}/{pr_number}/comments?per_page=100", token)
    existing = next((c for c in comments if MARKER in c.get("body", "")), None)
    if existing:
        api("PATCH", f"{base}/comments/{existing['id']}", token, {"body": body})
    else:
        api("POST", f"{base}/{pr_number}/comments", token, {"body": body})


def pr_number_from_event():
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        event = json.load(handle)
    return (event.get("pull_request") or {}).get("number")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="enriched-findings.json")
    parser.add_argument("--fail-on", default="high", choices=SEVERITY_ORDER)
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # emoji in the report crash cp1252 consoles

    with open(args.input, encoding="utf-8") as handle:
        findings = json.load(handle)

    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else ""
    body = build_comment(findings, args.fail_on, run_url)

    print_annotations(findings)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(body + "\n")

    token = os.environ.get("GITHUB_TOKEN")
    pr_number = pr_number_from_event()
    if token and repo and pr_number:
        try:
            post_comment(body, repo, pr_number, token,
                         os.environ.get("GITHUB_API_URL", "https://api.github.com"))
            print(f"Posted PR comment on #{pr_number}")
        except (urllib.error.URLError, OSError) as exc:
            print(f"::warning::Could not post PR comment ({exc}). Findings are in the job summary.")
    else:
        print("Skipping PR comment (no token / PR context); printing to stdout instead.\n")
        print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
