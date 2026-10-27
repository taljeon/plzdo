# Project Start Templates

Use these as compact starting points when creating a new project frame. Adapt names, domains, and checks to the repository.

The bootstrap script is the executable source for full templates. This reference summarizes the required shape and must stay aligned with `scripts/bootstrap_project_start.py`.

## AGENTS.md

```markdown
# <Project> Agent Guide

## Read First

- `CHECKS.md`
- `TASKS/current.md`
- `docs/inception.md`
- `docs/requirements.md`
- `docs/technical-design.md`
- `docs/harness-generation.md`

## Source Of Truth Order

1. Latest user request.
2. `TASKS/current.md` for current focus and done criteria.
3. `docs/requirements.md` for user-visible behavior and acceptance criteria.
4. `docs/technical-design.md` for ownership boundaries and validation design.
5. `AGENTS.md` for project-wide operating rules.
6. `CHECKS.md` for deterministic verification commands.

## Product Rules

- Specs are the source of truth.
- Harness checks must be safe and repeatable.
- Manual operations must not be blocked by automation failures.
- Use the common base plus project-specific quality profile in `docs/harness-generation.md`.

## Always-On Engineering Discipline

- Embed the complete Karpathy-style guideline set: Think Before Coding, Simplicity First, Surgical Changes, and Goal-Driven Execution.
- Every changed line should trace directly to the user's request.

## Coach-Inspired Harness Quality

- Prompt quality, session hygiene, code review, tool mastery, and context management guide harness quality.

## Architecture Rules

- Keep assembly, orchestration, storage, UI, and scripts in separate layers.
- Prefer existing repo patterns over new abstractions.

## Data Safety

- Do not read or print secrets, credentials, session state, or live personal data unless explicitly requested.
- Prefer fixtures and temp state for checks.

## Working Loop

1. Read the task frame and governing docs.
2. Inspect only needed files.
3. Use subagents automatically for large, risky, or multi-file work; keep small work local.
4. Make scoped edits.
5. Run `CHECKS.md`.
6. Report changed files, checks, skipped checks, and residual risk.

## Subagent Operating Model

- Main agent: orchestrator, final scope, final integration, final report.
- `explorer`: read-only structure, architecture, and data-flow analysis.
- `worker`: exact file ownership and non-overlapping implementation scope.
- `reviewer`: security, regression, data loss, duplicate writes, and spec drift.
- `tester`: `CHECKS.md` validation and skipped-check reporting.
- `release-preflight`: public-release leak/security review before GitHub, portfolio, package, or external handoff.

Use subagents by default when a task touches auth, payments, personal data, mail/calendar sync, data migration, deletion, duplicate writes, public release, or several modules. Do not pass secrets, raw personal data, live DB contents, auth stores, cookies, or token files to subagents unless explicitly requested.
```

## CHECKS.md

```markdown
# Checks

## Standard

- `./scripts/verify-harness.sh`

## Local

- `./scripts/validate-local.sh`

## Notes

- Checks must not require secrets or live production data by default.
- If a check is skipped, explain why in the final response.
```

## .gitignore

```gitignore
.env
.env.*
!.env.example
auth/
data/
logs/
playwright/.auth/
*.db
*.sqlite
*.sqlite3
*.zip
env.production*
*token*.json
*credentials*.json
.context_summary.md
.project-start-backup/
__pycache__/
.pytest_cache/
.venv/
node_modules/
dist/
build/
```

## TASKS/current.md

```markdown
# Current Task Frame

## Current Focus

- <current goal>

## Done When

- Specs reflect the intended behavior.
- Harness covers the risky behavior.
- Relevant checks pass.
- Remaining risk is called out.

## Recommended Agent Split

- `explorer`: structure and flow only.
- `worker`: scoped implementation.
- `reviewer`: security, regression, data loss.
- `tester`: `CHECKS.md` validation.
```

## docs/harness-generation.md

```markdown
# <Project> Harness Generation

## Generation Model

Project harnesses use a shared common base plus a project-specific quality profile.

## Default Safety Rules

- Use temp state from `HARNESS_DIR`.
- Do not read secrets, auth stores, private logs, live databases, cookies, tokens, or raw personal data.
- Do not call live APIs, send mail, deploy services, or mutate production systems by default.
- Do not run arbitrary package scripts in the generated default harness.
```
