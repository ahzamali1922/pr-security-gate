# Verify the whole project, step by step

Branches used: `ahzam` (work) and `development` (integration). PR #1 is ahzam -> development.

## Part A. Local checks (about 2 minutes)

Run from the repo root.

| # | Command | Expected |
|---|---|---|
| A1 | `python -m unittest discover -s tests` | `Ran 17 tests ... OK` |
| A2 | `python scripts/parse_findings.py --pylint tests/fixtures/pylint-report.json --eslint tests/fixtures/eslint-report.json --output findings.json` | `Wrote 8 findings` |
| A3 | `python scripts/gate.py --input findings.json` | `GATE FAILED` and exit code 1 (fixtures contain high findings) |
| A4 | `python scripts/suggest_fixes.py --input findings.json --output enriched.json` | `AI provider: ...` and a count of AI vs rule-based suggestions (needs a key in `.env`) |
| A5 | `python scripts/report_pr.py --input enriched.json` | Markdown report with a severity table and a Suggested fix per finding |
| A6 | `python scripts/metrics.py --input findings.json --history metrics/metrics.json --pr 1` | `Recorded run: ...` and a `metrics/metrics.json` file |

Delete `findings.json`, `enriched.json` and `metrics/` afterwards (they are generated files).

## Part B. CI run on the PR

1. Push a commit to `ahzam`. The push triggers the **Security Scan** workflow on PR #1.
2. Open the PR -> **Checks** tab -> **Security Scan**. Confirm each step:

| Step | Pass looks like |
|---|---|
| Run Pylint / Run ESLint | green |
| Validate reports | prints `pylint-report.json: valid JSON, N entries` and the same for ESLint |
| Run parser unit tests | `OK` |
| Normalize findings | `Wrote N findings` |
| AI fix suggestions | `AI provider: Groq`, a `Groq model: ...` line, and `(N AI, 0 rule-based)` |
| Report to PR | green, a bot comment appears on the PR |
| Record metrics | `Recorded run: ...` |
| Enforce gate | `GATE PASSED` (no high or critical findings) or `GATE FAILED` (there are some) |

3. On the PR **Conversation** tab, find the **github-actions** comment "PR Security Gate":
   severity table, findings grouped by severity, a Suggested fix and Why under each.
4. On the run's Summary page, open **Annotations** and **Artifacts**
   (`sast-reports`, `gate-results`).

## Part C. Red to green (the re-scan loop)

1. A run with a `high` finding fails the check (red X).
2. Fix the code, commit, and push to `ahzam`.
3. The scan re-runs on its own and the bot comment updates in place.
4. The check turns green once no `high` or `critical` findings remain.
   Medium and low findings are still listed but do not block.

## Part D. Human approval and merge rules

1. Repo **Settings -> Branches -> Add branch protection rule**, branch name `development`:
   - Require a pull request before merging, 1 approval
   - Require status checks to pass, add **Security Scan**
2. On PR #1, with a red check: the **Merge** button must be blocked.
3. With a green check but no approval: the button must still be blocked.
4. A teammate (not the author) opens **Files changed -> Review changes -> Approve**.
5. Merge becomes available. Merge ahzam -> development.

## Part E. Dashboard

1. Download the `gate-results` artifact from a run and unzip it.
2. Run `python -m http.server 8000` in the repo root.
3. Open http://localhost:8000/dashboard/ . It shows sample data first.
4. Use **Load real data** and pick `metrics/metrics.json` from the artifact.
5. Confirm the tiles (scans run, issues, pass rate, time-to-fix) and four charts update.

Time-to-fix only appears after a failing run is followed by a passing run on the same PR.

## Done checklist

- [ ] A1-A6 pass locally
- [ ] CI shows real findings from both Pylint and ESLint
- [ ] AI suggestions are specific to the code (not generic one-liners)
- [ ] Bot comment appears and updates on a new commit
- [ ] Failing run turns green after a fix commit
- [ ] Merge is blocked until the check is green and a reviewer approves
- [ ] Dashboard loads real metrics
