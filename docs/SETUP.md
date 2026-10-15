# Setup, human approval gate and demo script

## 1. Make the scan a required check (Stage 0/5)

The workflow job is named **Security Scan**. Run the workflow once on a PR so
GitHub knows the check exists, then protect `main` (and `development`):

**UI:** Settings → Branches → Add branch protection rule → branch `main`
- Require a pull request before merging
- Require approvals: 1 (this is the human approval step)
- Dismiss stale approvals when new commits are pushed
- Require status checks to pass → add **Security Scan**
- Require branches to be up to date before merging

**CLI** (needs admin rights on the repo):

```
gh api -X PUT repos/OWNER/REPO/branches/main/protection --input - <<'EOF'
{
  "required_status_checks": { "strict": true, "contexts": ["Security Scan"] },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true
  },
  "restrictions": null
}
EOF
```

## 2. AI provider (Stage 4)

`scripts/suggest_fixes.py` calls the GitHub Models API using the workflow's
`GITHUB_TOKEN` (the workflow grants `models: read`). Change the model with the
`AI_MODEL` env var. If the API is unavailable the script falls back to built-in
rule-based hints, so the gate never breaks because of the AI.

## 3. Tuning the gate

`FAIL_ON` in `.github/workflows/scan.yml` (`critical | high | medium | low`)
sets which severity blocks a merge. Default: `high`.

Severity scale:

| Common | Pylint | ESLint |
|---|---|---|
| critical | fatal | parse error |
| high | error, or a security rule (bare-except) | error (severity 2), or a security rule (no-eval) |
| medium | warning | warn (severity 1) |
| low | refactor, convention, info | – |

## 4. Local run (no CI needed)

```
pip install pylint
npm install --save-dev eslint
pylint --recursive=y --output-format=json demo-app > pylint-report.json
npx eslint demo-app -f json > eslint-report.json
python scripts/parse_findings.py --pylint pylint-report.json --eslint eslint-report.json
python scripts/suggest_fixes.py
python scripts/report_pr.py
python scripts/gate.py
python -m unittest discover -s tests
```

## 5. Dashboard (Stage 7)

```
python -m http.server 8000
# open http://localhost:8000/dashboard/
```

It shows sample data by default. Download the `gate-results` artifact from a
workflow run and load its `metrics/metrics.json` with the file picker.
Metrics history persists between runs through the GitHub Actions cache.

## 6. Demo script

1. `git checkout -b demo` and open a PR to `development` with the buggy demo app.
2. Watch **Security Scan** run. It fails, a comment appears with ranked findings
   and AI fixes, and inline annotations show on the Files tab.
3. A reviewer requests changes. Fix the issues and push a new commit.
4. The scan re-runs automatically and the check turns green.
5. The reviewer approves and merges. Open the dashboard to show issues found,
   severity mix, time-to-fix and pass rate.
