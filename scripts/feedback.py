"""Stage 8 - measure how trustworthy the AI suggestions are.

Every inline suggestion the gate posts carries a hidden metadata line. This script reads
those comments back from the pull request and counts, per PR:

  * posted          suggestions the bot offered
  * accepted        the finding is gone AND the suggested code is now in the file
                    (for a delete suggestion: the finding is gone)
  * false_positive  a reviewer reacted with a thumbs-down, or replied `/false-positive`
                    (or `/fp`), on the suggestion

  acceptance_rate = accepted / posted        false_positive_rate = false_positive / posted

A finding that a developer fixed by hand in a different way is NOT counted as accepted.
Only findings that received an inline suggestion can be rated.

Usage:
    python scripts/feedback.py --findings findings.json --output feedback.json
"""
import argparse
import base64
import json
import os
import re
import sys

import report_pr

META_RE = re.compile(r"<!-- pr-gate-meta: (\S+) -->")
FP_COMMANDS = ("/false-positive", "/fp")
MAX_PAGES = 5


encode_meta = report_pr.encode_meta  # the bot writes it, this script reads it back


def parse_meta(body):
    """Metadata dict from a comment body, or None if it is not one of our suggestions."""
    found = META_RE.search(body or "")
    if not found:
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(found.group(1).encode("ascii")).decode("utf-8"))
    except ValueError:  # includes bad base64, bad UTF-8 and bad JSON
        return None


def file_lines(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return {line.strip() for line in handle.read().splitlines()}
    except OSError:
        return None


def is_accepted(meta, current_keys, read=file_lines):
    """True if the finding is gone and the suggested code is in the file."""
    if (meta["file"], meta["rule"], meta["message"]) in current_keys:
        return False
    text = (meta.get("text") or "").strip()
    if not text:
        return True  # delete suggestion: the finding disappearing is the evidence
    lines = read(meta["file"])
    return lines is not None and text.splitlines()[0].strip() in lines


def is_false_positive(comment, replies):
    """Thumbs-down reaction, or a reply containing /false-positive or /fp."""
    if (comment.get("reactions") or {}).get("-1", 0) > 0:
        return True
    return any(cmd in (r.get("body") or "").lower() for r in replies for cmd in FP_COMMANDS)


def rate(part, whole):
    return round(part / whole, 3) if whole else None


def compute(comments, findings, read=file_lines):
    """Posted / accepted / false-positive counts from the PR's review comments."""
    current = {(f["file"], f["rule"], f["message"]) for f in findings}
    replies = {}
    for c in comments:
        if c.get("in_reply_to_id"):
            replies.setdefault(c["in_reply_to_id"], []).append(c)

    posted = accepted = false_positive = 0
    for c in comments:
        meta = parse_meta(c.get("body"))
        if not meta:
            continue
        posted += 1
        if is_false_positive(c, replies.get(c.get("id"), [])):
            false_positive += 1
        elif is_accepted(meta, current, read):
            accepted += 1
    return {
        "posted": posted,
        "accepted": accepted,
        "false_positive": false_positive,
        "acceptance_rate": rate(accepted, posted),
        "false_positive_rate": rate(false_positive, posted),
    }


def fetch_comments(repo, pr_number, token, api_url):
    comments = []
    for page in range(1, MAX_PAGES + 1):
        batch = report_pr.api(
            "GET", f"{api_url}/repos/{repo}/pulls/{pr_number}/comments?per_page=100&page={page}", token)
        comments.extend(batch)
        if len(batch) < 100:
            break
    return comments


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--findings", default="findings.json")
    parser.add_argument("--output", default="feedback.json")
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    pr_number = report_pr.pr_number_from_event()
    if not (token and repo and pr_number):
        print("No PR context; skipping feedback measurement.")
        return 0

    with open(args.findings, encoding="utf-8") as handle:
        findings = json.load(handle)
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    try:
        result = compute(fetch_comments(repo, pr_number, token, api_url), findings)
    except (OSError, ValueError) as exc:  # OSError covers URLError / HTTPError
        print(f"::warning::Could not measure suggestion feedback ({exc}).")
        return 0  # never fail the pipeline because of metrics

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print(f"Suggestions: {result['posted']} posted, {result['accepted']} accepted, "
          f"{result['false_positive']} marked false positive")
    return 0


if __name__ == "__main__":
    sys.exit(main())
