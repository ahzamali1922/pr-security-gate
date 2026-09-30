# TrustGate

TrustGate is a PR security gate for detecting code-quality and security issues before code reaches production.

The system analyzes pull requests, normalizes findings, provides AI-assisted remediation suggestions, verifies fixes through re-scanning, and controls merge readiness through CI.

## Demo Application

The `demo-app` directory contains intentionally flawed Python and JavaScript code used to demonstrate the TrustGate workflow.

## Planned Workflow

Pull Request
→ Static Analysis
→ Finding Normalization
→ Evidence / Trust Analysis
→ AI Suggestions
→ Human Review
→ Re-scan
→ CI Gate
→ Merge