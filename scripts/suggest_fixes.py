"""Stage 4 - add an AI-suggested fix and rationale to each finding.

Uses the GitHub Models API (OpenAI-compatible, authenticated with GITHUB_TOKEN).
If no token is set, or the call fails, a built-in rule-based hint is used so the
pipeline never breaks because the AI provider is unavailable.

Environment:
    ANTHROPIC_API_KEY  if set, use the Anthropic API (recommended)
    MODELS_TOKEN   personal access token with the Models permission (preferred for GitHub Models)
    GITHUB_TOKEN   token with `models: read` permission (GitHub Models fallback)
    AI_MODEL       model id, default "openai/gpt-4o-mini"
    AI_ENDPOINT    chat completions URL, default GitHub Models
    AI_MAX_FINDINGS  max findings sent to the model per run, default 15

Usage:
    python scripts/suggest_fixes.py --input findings.json --output enriched.json
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"
ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
CONTEXT_LINES = 3

FALLBACK_HINTS = {
    "unused-import": ("Remove the unused import.", "Unused imports add clutter and can hide real dependencies."),
    "no-unused-vars": ("Remove the unused variable or use it.", "Unused variables usually indicate dead code or a logic slip."),
    "unused-variable": ("Remove the unused variable or use it.", "Unused variables usually indicate dead code or a logic slip."),
    "bare-except": (
        "Catch a specific exception, e.g. `except OSError:`, and log or re-raise it.",
        "A bare except swallows every error, including KeyboardInterrupt, and hides failures.",
    ),
    "consider-using-with": (
        "Open the file with `with open(...) as handle:`.",
        "A context manager guarantees the file is closed even if an error occurs.",
    ),
    "no-console": ("Replace console.log with a proper logger.", "Console output can leak data and is noisy in production."),
    "no-eval": ("Avoid eval(); parse the input explicitly instead.", "eval executes arbitrary code and is a code-injection risk."),
    "missing-function-docstring": ("Add a short docstring describing the function.", "Docstrings make intent clear to reviewers."),
    "missing-module-docstring": ("Add a module docstring at the top of the file.", "Docstrings make intent clear to reviewers."),
}


def read_snippet(path, line, context=CONTEXT_LINES):
    """Return the lines around `line` in `path`, or '' if the file is unreadable."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return ""
    start = max(line - 1 - context, 0)
    end = min(line + context, len(lines))
    return "\n".join(f"{n + 1}: {lines[n]}" for n in range(start, end))


def build_prompt(finding, snippet):
    return (
        "You are a code-review assistant in a CI security gate.\n"
        f"Tool: {finding['tool']}\nRule: {finding['rule']}\n"
        f"Severity: {finding['severity']}\nMessage: {finding['message']}\n"
        f"File: {finding['file']} (line {finding['line']})\n\n"
        f"Code:\n{snippet}\n\n"
        'Reply with ONLY a JSON object: {"fix": "<the corrected code or a one-sentence '
        'instruction>", "rationale": "<one sentence>"}.'
    )


def post_json(endpoint, headers, body):
    """POST a JSON body and return the parsed JSON response, with readable errors."""
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise OSError(f"HTTP {exc.code} from {endpoint}: {detail}") from exc
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"HTTP {status} but body is not JSON: {raw[:300]!r}") from exc


def call_llm(prompt, token, model, endpoint):
    """OpenAI-compatible chat completions (GitHub Models)."""
    payload = post_json(
        endpoint,
        {"Authorization": f"Bearer {token}", "Accept": "application/json"},
        {
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You answer only with a single JSON object."},
                {"role": "user", "content": prompt},
            ],
        },
    )
    return payload["choices"][0]["message"].get("content") or ""


def call_anthropic(prompt, token, model, endpoint):
    """Anthropic Messages API."""
    payload = post_json(
        endpoint,
        {"x-api-key": token, "anthropic-version": "2023-06-01"},
        {
            "model": model,
            "max_tokens": 400,
            "system": "You answer only with a single JSON object.",
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    return "".join(b.get("text", "") for b in payload["content"] if b.get("type") == "text")


def parse_reply(text):
    """Extract {"fix", "rationale"} from a model reply, tolerating code fences."""
    raw = text
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in model reply: {raw!r:.200}")
    try:
        data = json.loads(text[start:end + 1])
        return str(data["fix"]).strip(), str(data["rationale"]).strip()
    except (KeyError, TypeError) as exc:
        raise ValueError(f"model reply missing fix/rationale: {raw!r:.200}") from exc


def fallback(finding):
    fix, why = FALLBACK_HINTS.get(
        finding["rule"],
        (f"Review the code and address rule `{finding['rule']}`.", finding["message"]),
    )
    return {"fix": fix, "rationale": why, "source": "rule-based"}


def enrich(findings, token=None, model=DEFAULT_MODEL, endpoint=DEFAULT_ENDPOINT,
           max_ai=15, llm=call_llm):
    """Return findings with a `suggestion` dict added. `llm` is injectable for tests."""
    result = []
    for index, finding in enumerate(findings):
        item = dict(finding)
        suggestion = None
        if token and index < max_ai:
            try:
                snippet = read_snippet(finding["file"], finding["line"])
                fix, why = parse_reply(llm(build_prompt(finding, snippet), token, model, endpoint))
                suggestion = {"fix": fix, "rationale": why, "source": model}
            except (urllib.error.URLError, OSError, KeyError, ValueError, IndexError) as exc:
                print(f"AI suggestion failed for {finding['file']}:{finding['line']}: {exc}",
                      file=sys.stderr)
        item["suggestion"] = suggestion or fallback(finding)
        result.append(item)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="findings.json")
    parser.add_argument("--output", default="enriched-findings.json")
    args = parser.parse_args(argv)

    with open(args.input, encoding="utf-8") as handle:
        findings = json.load(handle)

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        print("AI provider: Anthropic")
        enriched = enrich(
            findings,
            token=anthropic_key,
            model=os.environ.get("AI_MODEL", ANTHROPIC_MODEL),
            endpoint=os.environ.get("AI_ENDPOINT", ANTHROPIC_ENDPOINT),
            max_ai=int(os.environ.get("AI_MAX_FINDINGS", "15")),
            llm=call_anthropic,
        )
    else:
        print("AI provider: GitHub Models (set ANTHROPIC_API_KEY to use Anthropic)")
        enriched = enrich(
            findings,
            token=os.environ.get("MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN"),
            model=os.environ.get("AI_MODEL", DEFAULT_MODEL),
            endpoint=os.environ.get("AI_ENDPOINT", DEFAULT_ENDPOINT),
            max_ai=int(os.environ.get("AI_MAX_FINDINGS", "15")),
        )
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(enriched, handle, indent=2)
    ai_count = sum(1 for f in enriched if f["suggestion"]["source"] != "rule-based")
    print(f"Wrote {len(enriched)} findings ({ai_count} AI, {len(enriched) - ai_count} rule-based)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
