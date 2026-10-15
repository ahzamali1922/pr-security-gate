# PR Security Gate

A CI gate that catches bugs and security problems **in the pull request, not in production**,
suggests fixes with an AI assistant, and **measures how trustworthy its own AI is**.

## The problem

Bugs and vulnerabilities keep slipping into production, where they cost far more to fix.
This project moves the check to the pull request: a free linter finds the issues, an AI
assistant suggests fixes with reasons ranked by severity, and a human decides what is merged.

## How it works

```
Developer opens or updates a PR
        |
        v
GitHub Actions  ->  Pylint + ESLint scan every file under demo-app/
        |
        v
Parse and rank by severity (critical / high / medium / low)
        |
        v
GitHub Copilot CLI suggests a fix and a reason for each finding
        |
        v
Verify: re-run the linter on the fixed file, keep only fixes that clear the finding
        |
        v
PR comment + one-click "Apply suggestion" buttons
        |
        v
A human reads the diff and applies the fix  ->  automatic re-scan
        |
        v
Gate: fails on any high or critical finding  ->  one human approval  ->  merge
```

The AI never edits or commits code by itself. Every change starts with a person clicking Apply.

## Features

- **Required CI gate** on every pull request. It fails on findings at `high` or worse
  (`FAIL_ON` in `.github/workflows/scan.yml`); medium and low are reported but do not block.
- **AI fixes with reasons, ranked by severity.** GitHub Copilot CLI is the first provider;
  Gemini, Groq, Grok, Anthropic and GitHub Models are fallbacks, then short rule-based hints.
- **One-click Apply buttons** (GitHub suggestion blocks) for fixes that pass the safety filters.
- **Lint-verified fixes.** Each fix is applied in memory and the linter is re-run. A fix that
  does not clear the finding, or breaks the file, gets no button and a "Not verified" note.
- **Safety filters** against bad suggestions: comment-only fixes, docstring inserts,
  statements joined with `;`, fixes that change the kind of statement, lines outside the diff.
- **Syntax errors are fixed one at a time**, since a syntax error hides every other finding
  in that file.
- **Honesty metrics.** Fix-acceptance rate (suggestions that were applied) and false-positive
  rate (suggestions a reviewer marked wrong with a thumbs-down or `/false-positive`).
- **Dashboard** with scans, severity mix, time-to-fix, both rates and the number of bad AI
  fixes blocked.

## Mapping to the problem statement

| Requirement | Where |
|---|---|
| A free linter or analyzer finds issues | Pylint and ESLint, `scan.yml` |
| AI suggests fixes with reasons, ranked by severity | `scripts/suggest_fixes.py`, `scripts/report_pr.py` |
| Scan runs as a required CI gate on every PR | `scan.yml` plus branch protection (see Setup) |
| Human approval before any AI fix is merged | Apply is a manual click; branch protection requires 1 approval |
| Track false-positive and fix-acceptance rates | `scripts/feedback.py`, `scripts/metrics.py`, dashboard |

## Tech stack

GitHub Actions, Pylint, ESLint, GitHub Copilot CLI, Python and Node.js, the GitHub REST API,
JSON files for metrics, Chart.js for the dashboard.

## Setup

1. **Copilot token.** Create a fine-grained personal access token with the account permission
   *Copilot Requests* and save it as the repository secret `COPILOT_GITHUB_TOKEN`.
   Without it, the other providers or the rule-based hints are used.
2. **Branch protection** on `main` and `development`: require a pull request, 1 approval,
   dismiss stale approvals, and require the status check **Security Scan**.
3. Open a pull request. The scan runs on every push to it.

Details and the local run commands are in [docs/SETUP.md](docs/SETUP.md); a step-by-step
check list is in [docs/VERIFY.md](docs/VERIFY.md).

## Demo walkthrough

1. Open a PR with one deliberate bug (a bare `except:`, an undefined name, an unused import).
2. The **Security Scan** check fails and a comment lists the findings, worst first.
3. Each fixable finding has an inline suggestion marked "Lint-verified". Read the diff, then
   click **Apply suggestion**.
4. The new commit re-runs the scan and the check turns green.
5. A reviewer approves and merges. Mark one suggestion with a thumbs-down to see the
   false-positive rate move.
6. View the numbers: run `python -m http.server 8000`, open `http://localhost:8000/dashboard/`
   and load `metrics.json` from the `gate-results` artifact of a workflow run.

## Project layout

```
.github/workflows/scan.yml    the pipeline
scripts/parse_findings.py     merge Pylint and ESLint output, one severity scale
scripts/suggest_fixes.py      ask the AI for a fix and a reason for each finding
scripts/verify_fixes.py       re-run the linter on each fixed file
scripts/report_pr.py          PR comment, annotations, Apply suggestions
scripts/feedback.py           count accepted and false-positive suggestions
scripts/metrics.py            one record per scan for the dashboard
scripts/gate.py               fail the check on high or critical findings
tests/                        unit tests (python -m unittest discover -s tests)
demo-app/                     small buggy programs used as scan targets
dashboard/                    local Chart.js dashboard
docs/                         setup and verification guides
```

## Limitations

- AI suggestions can be wrong. A person must read every diff before applying.
- Verification checks that the linter is satisfied, not that the program behaves the same.
- A suggestion replaces one line (or a few adjacent ones). Fixes that need edits in several
  places are shown as advice, without a button.
- A syntax error hides the other findings in that file until it is fixed.
- Only the first 15 findings per run get an AI suggestion.
- The dashboard is a local page, not a hosted live view.
- Rates are measured only for findings that received an inline suggestion.
