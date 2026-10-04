# PR Security Gate

A DevSecOps CI/CD security gate that detects bugs and security issues
during the Pull Request stage instead of after deployment.

## Core Workflow

Developer
    ↓
Pull Request
    ↓
GitHub Actions
    ↓
Pylint / ESLint
    ↓
Finding Parser
    ↓
AI Fix Suggestions
    ↓
PR Feedback
    ↓
Human Approval
    ↓
Re-scan
    ↓
Merge

## Tech Stack

- GitHub
- GitHub Actions
- Pylint
- ESLint
- Python / Node.js
- LLM API
- GitHub Checks API
- SQLite / JSON
- Chart.js

## Project Status

Stage 0 — Skeleton