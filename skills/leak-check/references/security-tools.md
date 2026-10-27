# Security Scanner Notes

Use these as selection notes, not as mandatory dependencies. Install or run external tools only when already available or when the user approves dependency installation.

## Secret and Credential Scanners

- GitHub secret scanning: GitHub scans repositories and git history for known secret types, and public repositories receive secret scanning. Use as a platform-side safety net, not a replacement for local checks before push.
  Source: https://docs.github.com/en/code-security/concepts/secret-security/about-secret-scanning

- Gitleaks: scans git repositories, directories, files, and stdin for passwords, API keys, and tokens. Prefer `gitleaks git --redact` for history checks and `gitleaks dir --redact .` for working tree checks.
  Source: https://github.com/gitleaks/gitleaks

- TruffleHog: finds, verifies, and analyzes leaked credentials. Use when you need verified credential checks across git history or external sources.
  Source: https://github.com/trufflesecurity/trufflehog

- detect-secrets: baseline-oriented scanner for detecting and preventing secrets in code. Use when a repo wants auditable baselines and recurring pre-commit review.
  Source: https://github.com/Yelp/detect-secrets

- git-secrets: commit hook and scanner for prohibited secret patterns, especially useful for AWS credential patterns and custom deny rules.
  Source: https://github.com/awslabs/git-secrets

- Secretlint: pluggable credential linting tool for project files, CI, and pre-commit hooks.
  Source: https://github.com/secretlint/secretlint

## Broader Security Checks

- Semgrep: open-source static analysis for bugs, secure guardrails, and coding standards across many languages. Use after leak checks when the release also needs SAST coverage.
  Source: https://github.com/semgrep/semgrep

## Multi-Agent Review Pattern

- Use a supervisor pattern for release gates: one main agent owns the publish decision while inventory, security review, test execution, and remediation are separated.
- CrewAI's hierarchical process is the closest reference: a manager delegates work and validates outcomes.
  Source: https://docs.crewai.com/en/learn/hierarchical-process
- LangGraph's supervisor architecture is also relevant: individual agents are coordinated by one central supervisor that controls task delegation.
  Source: https://langchain-ai.lang.chat/langgraph/agents/multi-agent/

## Practical Combination

- Fast local gate: bundled `check_release_leaks.py` plus repo `CHECKS.md`.
- Public GitHub gate: bundled scanner, `gitleaks git --redact`, `.gitignore` review, tracked artifact inventory, and GitHub secret scanning enabled/available.
- High-risk history gate: add TruffleHog verified checks and rotate any previously exposed credential even if it is later removed from history.
- Team workflow: add detect-secrets or git-secrets as pre-commit/CI if repeated leaks are likely.
