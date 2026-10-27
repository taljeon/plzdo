---
name: leak-check
description: Public-release leak and security preflight workflow. Use when the user says `/유출검수`, `유출검수`, `*/유출검수*`, asks to prepare a project for GitHub/public/portfolio release, or wants to scan for .env/auth/data/token/secret/real email/local path/screenshot leaks before publishing, pushing, committing, or opening a PR.
---

# Leak Check

Use this skill as a public-release gate. The goal is to prevent accidental exposure of secrets, personal data, operational mail/calendar data, local paths, screenshots, and unsafe repo state before a project is shown on GitHub or in a portfolio.

## Operating Rules

- Do not read or print `.env`, auth stores, browser auth state, cookies, token files, private keys, raw mail, or production database contents unless the user explicitly asks.
- Treat GitHub/public release as stricter than normal code review: real names, personal email addresses, meeting links, local absolute paths, screenshots of live tools, and sample data can be blockers even when tests pass.
- Prefer path, metadata, redacted scanners, and tracked-file inventory over opening sensitive files.
- Do not delete files or rewrite git history automatically. Report what must change; ask or use the repo's normal cleanup path for destructive remediation.
- If the user asks to publish, push, create a PR, or make a portfolio release, run this preflight before staging/pushing unless they explicitly waive it.

## Subagents

`유출검수`, `/유출검수`, and `*/유출검수*` include permission for automatic subagent use unless the user says not to. Keep small repos local; use subagents when the repo is non-trivial, the release target is public, history scanning is needed, or remediation spans several files.

Use a supervisor pattern:
- Main agent: orchestrates the release gate, runs or chooses scanners, decides blockers, and owns the final publish/no-publish recommendation.
- `inventory` as explorer: read-only repo structure, tracked/untracked sensitive paths, `.gitignore`, release docs, and screenshot/media inventory. No secret contents.
- `security-reviewer` as reviewer-style worker: classify findings by public-release risk, false-positive likelihood, credential rotation need, and whether history cleanup is required.
- `tester` as tester-style worker: run `CHECKS.md`, bundled scanner, and installed redacted tools only. Report skipped tools and reasons.
- `remediation-worker` as worker: only after the main agent assigns exact files. Do not delete data, rewrite history, or alter credentials without explicit user approval.

Delegation constraints:
- Never pass raw `.env`, token values, cookies, auth state, raw mail, live DB rows, or production screenshots to subagents.
- Prefer path names, finding IDs, redacted scanner output, and file ownership boundaries.
- If a finding implies a leaked real credential, recommend rotation even after code cleanup.
- The main agent must re-run the bundled scanner after remediation.

## Quick Start

From the target repository:

```bash
python3 ~/.claude/skills/leak-check/scripts/check_release_leaks.py --root .
```

If the installed path differs, resolve this skill directory and run `scripts/check_release_leaks.py`.

The bundled scanner is intentionally conservative and dependency-free. It reports paths, line numbers, and finding types without printing matched secret values.

## Hooks

The optional PlzDo `release-gate` hook only allows publishing commands in the canonical forms it can check. It does not scan content and does not replace this preflight. Before the first public push of an existing history, or before making a repository public, run this skill on the full history: the scanner checks the working tree, not earlier commits, commit messages or author emails.

## Workflow

1. Identify the release target and exposure level: private PR, public GitHub repo, portfolio screenshot/demo, package publish, or handoff archive.
2. Read repo guidance first: `AGENTS.md`, `CHECKS.md`, current task docs, release checklists, and any existing `.gitignore` or security policy.
3. Run the bundled leak scanner and any repo-provided preflight scripts. Keep output redacted in summaries.
4. Inspect git state with safe metadata: tracked files, untracked sensitive paths, ignored files, large files, and recent changes. Avoid printing sensitive file contents.
5. If available, run relevant optional scanners:
   - Gitleaks for git history and working tree secret detection.
   - TruffleHog for verified leaked credentials when history depth matters.
   - detect-secrets for baseline-oriented team workflows.
   - git-secrets for commit-hook style AWS/custom prohibited patterns.
   - Semgrep or Secretlint for broader SAST/credential linting when the project stack supports it.
6. Check release-specific leaks that generic scanners miss: real emails, calendar/meeting URLs, local absolute paths, raw mail fragments, production screenshots, database files, OAuth state, generated reports, and app logs.
7. Remediate with the smallest safe change: ignore files, replace fixtures with synthetic samples, add templates, redact docs, remove tracked artifacts, rotate exposed credentials, or document required manual cleanup.
8. Re-run the scanner and relevant checks from `CHECKS.md`. Final output should list blockers, changed files, skipped checks, and residual risks.

## Blocker Categories

Treat these as high severity for public release:

- `.env`, `.env.*`, `auth/`, `playwright/.auth/`, browser profiles, OAuth tokens, cookies, session state.
- `data/`, `.db`, `.sqlite`, production exports, local app caches, raw logs, raw mail/calendar/task dumps.
- API keys, GitHub tokens, OpenAI keys, AWS keys, Slack/Stripe tokens, private keys, service account JSON, client secrets.
- Personal email addresses, real candidate/company mail bodies, calendar invite links, Google Meet/Zoom/Teams URLs, phone numbers when not intentionally public.
- Absolute paths into a user's home folder (macOS, Linux or Windows), machine-specific paths, local-only absolute paths embedded in docs or configs.
- Screenshots/videos that show real inboxes, calendars, issue trackers, credentials, internal dashboards, customer data, or non-public company names.

## Optional References

Read `references/security-tools.md` when choosing external scanner commands, comparing tool coverage, or explaining why several scanners may be combined.
