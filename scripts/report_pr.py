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
import base64
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

MARKER = "<!-- pr-security-gate -->"
SEVERITY_ORDER = ["critical", "high", "medium", "low"]
ICONS = {"critical": "🟥", "high": "🟧", "medium": "🟨", "low": "⬜"}
ANNOTATION_LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "notice"}
MAX_ANNOTATIONS = 50  # GitHub shows at most 50 annotations per step


CODE_HINT = re.compile(r"[=(){};]|^\s*(import|from|except|with|const|let|var|def|return|try|if|for)\b")
LANGS = {".py": "python", ".js": "javascript", ".ts": "typescript"}


def clean_fix(fix):
    """Strip any markdown fences the model added."""
    fix = fix.strip()
    fix = re.sub(r"^```[a-zA-Z]*\n?", "", fix)
    return re.sub(r"\n?```$", "", fix).strip()


def format_fix(fix, file):
    """Render a suggested fix as an indented code block when it looks like code."""
    fix = clean_fix(fix)
    is_sentence = "\n" not in fix and re.match(r"^[A-Z][a-z]+ ", fix)
    if not is_sentence and ("\n" in fix or CODE_HINT.search(fix)):
        lang = LANGS.get(os.path.splitext(file)[1], "")
        body = "\n".join("    " + line for line in fix.splitlines())
        return f"\n    ```{lang}\n{body}\n    ```"
    return " " + fix


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
                lines.append(f"  - 💡 **Suggested fix:**{format_fix(s['fix'], f['file'])}")
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
            text += f" | Suggested fix: {clean_fix(s['fix'])}"
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


# ---- inline "Commit suggestion" comments (human applies each fix) ----

DELETE_OK = {"unused-import", "unused-variable", "no-unused-vars", "pointless-statement"}
COMMENT_PREFIXES = ("#", "//", "/*", "*")
# These need a new line inserted, which a one-line replacement cannot express.
NEEDS_INSERT = {"missing-function-docstring", "missing-module-docstring", "missing-class-docstring"}
MAX_SUGGESTIONS = 20


def parse_patch_lines(patch):
    """Map new-file line number -> text for the lines of a PR diff that GitHub lets us comment on."""
    lines, new, in_hunk = {}, 0, False
    for raw in (patch or "").splitlines():
        hunk = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if hunk:
            new, in_hunk = int(hunk.group(1)), True
        elif in_hunk and not raw.startswith(("-", "\\")):
            lines[new] = raw[1:]
            new += 1
    return lines


STATEMENT_WORDS = {"return", "def", "class", "if", "elif", "else", "for", "while", "try", "except",
                   "finally", "with", "import", "from", "raise", "assert", "yield"}


def statement_kind(line):
    word = re.match(r"\s*(\w+)", line)
    return word.group(1) if word and word.group(1) in STATEMENT_WORDS else "other"


def suggestion_text(finding, original_line):
    """Replacement text for an inline suggestion, or None if the fix is not safe to offer."""
    s = finding.get("suggestion") or {}
    if s.get("source") == "rule-based" or finding["rule"] in NEEDS_INSERT:
        return None
    fix = clean_fix(s.get("fix", ""))
    if not fix:
        return "" if finding["rule"] in DELETE_OK else None
    if "```" in fix:
        return None
    if finding["file"].endswith(".py") and re.search(r";\s*\S", fix):
        return None  # statements joined with ";" are not a real fix in Python
    lines = fix.splitlines()
    if all(l.strip().startswith(COMMENT_PREFIXES) for l in lines if l.strip()):
        return None  # a comment-only "fix" just hides the problem
    is_sentence = "\n" not in fix and re.match(r"^[A-Z][a-z]+ ", fix)
    if is_sentence or not CODE_HINT.search(fix):
        return None
    if statement_kind(original_line) not in {statement_kind(l) for l in lines}:
        return None  # e.g. an assignment replaced by a return: the fix belongs to another line
    indent = original_line[:len(original_line) - len(original_line.lstrip())]
    if not lines[0].startswith((" ", "\t")):
        # the first line lost its indent when the reply was trimmed; later lines either already
        # carry the absolute indent of the file or are written flush-left
        rest = [l for l in lines[1:] if l.strip()]
        absolute = bool(rest) and all(len(l) - len(l.lstrip()) >= len(indent) for l in rest)
        tail = lines[1:] if absolute else [indent + l if l.strip() else l for l in lines[1:]]
        lines = [indent + lines[0]] + tail
    text = "\n".join(lines)
    return None if text.rstrip() == original_line.rstrip() else text


def encode_meta(finding, text):
    """Hidden, comment-safe metadata describing one posted suggestion (read by feedback.py)."""
    meta = {"file": finding["file"], "rule": finding["rule"],
            "message": finding["message"], "text": text}
    raw = json.dumps(meta, separators=(",", ":")).encode("utf-8")
    return "<!-- pr-gate-meta: " + base64.urlsafe_b64encode(raw).decode("ascii") + " -->"


def suggestion_body(finding, text, line=None):
    line = line or finding["line"]
    marker = "<!-- pr-security-gate:{}:{}:{}:{} -->".format(
        finding["file"], line, finding["rule"],
        hashlib.sha1(text.encode("utf-8")).hexdigest()[:8])
    block = "```suggestion\n" + (text + "\n" if text else "") + "```"
    s = finding["suggestion"]
    where = "" if line == finding["line"] else f" (flagged at line {finding['line']}, the cause is here)"
    return "\n".join([
        marker,
        f"🤖 **{finding['rule']}** ({finding['severity']}) — {finding['message']}{where}",
        "",
        f"_Why:_ {s['rationale']}",
        "",
        block,
        "",
        "_Review the change, then click **Apply suggestion**. The scan re-runs on the new "
        "commit; a human approval is still required to merge._",
        "",
        "_Wrong finding? React 👎 or reply `/false-positive` so the tool's honesty is measured._",
        encode_meta(finding, text),
    ])


def read_line(path, line):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().splitlines()[line - 1]
    except (OSError, IndexError):
        return None


def build_suggestion_comments(findings, diff_lines, existing_text="", read=read_line):
    """Review comments for findings whose fix can be applied with one click.

    Only lines that are inside the PR diff, still match the scanned file, and were not
    already suggested on an earlier run are included.
    """
    comments, used = [], set()
    for f in findings:
        # the model may point at a different line than the flagged one (e.g. a misspelled def)
        line = (f.get("suggestion") or {}).get("line") or f["line"]
        original = diff_lines.get(f["file"], {}).get(line)
        current = read(f["file"], line)
        if original is None or current is None or original.rstrip() != current.rstrip():
            continue
        text = suggestion_text(f, original)
        if text is None or (f["file"], line) in used:
            continue
        body = suggestion_body(f, text, line)
        if body.splitlines()[0] in existing_text:
            continue
        used.add((f["file"], line))
        comments.append({"path": f["file"], "line": line, "side": "RIGHT", "body": body})
        if len(comments) >= MAX_SUGGESTIONS:
            break
    return comments


def pr_diff_lines(repo, pr_number, token, api_url):
    """{path: {new_line: text}} for every file in the PR diff."""
    result = {}
    for page in range(1, 11):
        files = api("GET", f"{api_url}/repos/{repo}/pulls/{pr_number}/files?per_page=100&page={page}", token)
        for item in files:
            result[item["filename"]] = parse_patch_lines(item.get("patch"))
        if len(files) < 100:
            break
    return result


def post_suggestions(findings, repo, pr_number, sha, token, api_url="https://api.github.com"):
    """Post one review whose inline comments carry GitHub suggestion blocks. Returns the count."""
    diff_lines = pr_diff_lines(repo, pr_number, token, api_url)
    existing = api("GET", f"{api_url}/repos/{repo}/pulls/{pr_number}/comments?per_page=100", token)
    existing_text = "\n".join(c.get("body", "") for c in existing)
    comments = build_suggestion_comments(findings, diff_lines, existing_text)
    if not comments:
        return 0
    api("POST", f"{api_url}/repos/{repo}/pulls/{pr_number}/reviews", token, {
        "commit_id": sha,
        "event": "COMMENT",
        "body": f"🔒 PR Security Gate: {len(comments)} fix(es) can be applied. Open **Files changed** "
                "and click **Apply suggestion** on the ones you accept.",
        "comments": comments,
    })
    return len(comments)


def pr_head_sha_from_event():
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        event = json.load(handle)
    return ((event.get("pull_request") or {}).get("head") or {}).get("sha")


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
        sha = pr_head_sha_from_event()
        if sha:
            try:
                count = post_suggestions(findings, repo, pr_number, sha, token,
                                         os.environ.get("GITHUB_API_URL", "https://api.github.com"))
                print(f"Posted {count} inline suggestion(s)")
            except (OSError, KeyError, ValueError) as exc:
                print(f"::warning::Could not post inline suggestions ({exc}).")
    else:
        print("Skipping PR comment (no token / PR context); printing to stdout instead.\n")
        print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
