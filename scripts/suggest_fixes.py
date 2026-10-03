"""Stage 4 - add an AI-suggested fix and rationale to each finding.

Uses the GitHub Models API (OpenAI-compatible, authenticated with GITHUB_TOKEN).
If no token is set, or the call fails, a built-in rule-based hint is used so the
pipeline never breaks because the AI provider is unavailable.

Environment:
    GEMINI_API_KEY     if set, use Google Gemini (highest priority)
    GROQ_API_KEY       if set (and no Gemini key), use Groq
    XAI_API_KEY        if set (and no Gemini key), use Grok (xAI)
    ANTHROPIC_API_KEY  if set (and none of the above), use the Anthropic API
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
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = "gemini-2.5-flash"
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
GROK_ENDPOINT = "https://api.x.ai/v1/chat/completions"
GROK_MODEL = "grok-3-mini"
CONTEXT_LINES = 8

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


def load_dotenv(path=".env"):
    """Load KEY=VALUE lines from a local .env into os.environ (never overrides real env vars)."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip("\"'")
        if value:
            os.environ.setdefault(key, value)


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
        f"File: {finding['file']}\nFlagged line: {finding['line']}\n\n"
        f"Code (each line prefixed with its line number):\n{snippet}\n\n"
        "Fix ONLY the problem reported at the flagged line. Do not rewrite unrelated code.\n"
        'Reply with ONLY a JSON object: {"fix": "<the corrected line(s) of code only, without '
        'line numbers or markdown, or one short instruction if code is not appropriate>", '
        '"rationale": "<one sentence explaining why>"}.'
    )


def post_json(endpoint, headers, body):
    """POST a JSON body and return the parsed JSON response, with readable errors."""
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "pr-security-gate/1.0", **headers},
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


def call_gemini(prompt, token, model, endpoint):
    """Google Gemini generateContent API. `endpoint` is the base URL up to /models."""
    payload = post_json(
        f"{endpoint}/{model}:generateContent",
        {"x-goog-api-key": token},
        {
            "systemInstruction": {"parts": [{"text": "You answer only with a single JSON object."}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        },
    )
    parts = payload["candidates"][0]["content"]["parts"]
    return "".join(part.get("text", "") for part in parts)


GROQ_PREFERRED = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
]
NON_CHAT_HINTS = ("whisper", "guard", "tts", "playai", "embed", "orpheus", "distil-whisper")


def pick_groq_model(token, endpoint=GROQ_ENDPOINT, default=GROQ_MODEL):
    """Ask Groq which models this key can use and choose the best chat model."""
    request = urllib.request.Request(
        endpoint.replace("/chat/completions", "/models"),
        headers={"Authorization": f"Bearer {token}", "User-Agent": "pr-security-gate/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            available = [m["id"] for m in json.load(response)["data"]]
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        print(f"Could not list Groq models ({exc}); using {default}", file=sys.stderr)
        return default
    for model in GROQ_PREFERRED:
        if model in available:
            return model
    chat = [m for m in available if not any(h in m.lower() for h in NON_CHAT_HINTS)]
    print(f"Groq models available: {', '.join(sorted(available))}")
    return chat[0] if chat else default


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
    load_dotenv()

    with open(args.input, encoding="utf-8") as handle:
        findings = json.load(handle)

    # Provider priority: Gemini, Groq, Grok (xAI), Anthropic, then GitHub Models.
    gemini_key = os.environ.get("GEMINI_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")
    grok_key = os.environ.get("XAI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if gemini_key:
        print("AI provider: Gemini")
        provider = dict(token=gemini_key, model=GEMINI_MODEL, endpoint=GEMINI_ENDPOINT, llm=call_gemini)
    elif groq_key:
        print("AI provider: Groq")
        model = os.environ.get("AI_MODEL") or pick_groq_model(groq_key)
        print(f"Groq model: {model}")
        provider = dict(token=groq_key, model=model, endpoint=GROQ_ENDPOINT, llm=call_llm)
    elif grok_key:
        print("AI provider: Grok (xAI)")
        provider = dict(token=grok_key, model=GROK_MODEL, endpoint=GROK_ENDPOINT, llm=call_llm)
    elif anthropic_key:
        print("AI provider: Anthropic")
        provider = dict(token=anthropic_key, model=ANTHROPIC_MODEL, endpoint=ANTHROPIC_ENDPOINT,
                        llm=call_anthropic)
    else:
        print("AI provider: GitHub Models (set GEMINI_API_KEY or ANTHROPIC_API_KEY to use another)")
        provider = dict(token=os.environ.get("MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN"),
                        model=DEFAULT_MODEL, endpoint=DEFAULT_ENDPOINT, llm=call_llm)
    provider["model"] = os.environ.get("AI_MODEL", provider["model"])
    provider["endpoint"] = os.environ.get("AI_ENDPOINT", provider["endpoint"])

    enriched = enrich(findings, max_ai=int(os.environ.get("AI_MAX_FINDINGS", "15")), **provider)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(enriched, handle, indent=2)
    ai_count = sum(1 for f in enriched if f["suggestion"]["source"] != "rule-based")
    print(f"Wrote {len(enriched)} findings ({ai_count} AI, {len(enriched) - ai_count} rule-based)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
