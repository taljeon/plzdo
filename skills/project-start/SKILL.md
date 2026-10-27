---
name: project-start
description: >-
  Standard project inception, specification, harness, and multi-agent verification workflow. Use when the user says `/작업개시`, `작업개시`, `*/작업개시*`, `Target project: ...`, asks to start a new project from specifications, create 仕様書/要件定義書/技術設計書, generate AGENTS.md/CHECKS.md/TASKS/current.md, create a fixed harness, prevent implementation drift from docs, or run explorer/worker/reviewer/tester subagent-style validation.
---

# Project Start

Use this skill to start or repair a project from a stable operating frame: specs first, harness second, implementation third, review and test last.

## Command Contract

Treat these as triggers:
- `/작업개시`
- `작업개시`
- `*/작업개시*`
- `Target project: <name>` with inception, harness, specs, or subagent review language

Parse these optional fields when present:
- `Target project:` repository or folder name.
- `Goal:` desired outcome.
- `Mode:` `inception`, `implementation`, `review`, or `repair`.
- `Subagents:` `auto`, `yes`, or a role list.

If target root is ambiguous and cannot be inferred from cwd, ask one short question before editing.

## Source Of Truth

Create or maintain this project frame:
- `docs/inception.md`: product intent, user, non-goals, operating assumptions.
- `docs/requirements.md`: user-facing requirements and acceptance criteria.
- `docs/technical-design.md`: architecture, data flow, integrations, risks.
- `AGENTS.md`: project-wide main prompt with source-of-truth order, full Karpathy-style always-on engineering discipline, protected data, routing, and workflow.
- `CHECKS.md`: deterministic validation commands and what they cover.
- `TASKS/current.md`: current task frame and done criteria.
- `.gitignore`: public-safety ignore rules for secrets, auth state, local data, and build artifacts.
- `scripts/harness-env.sh`: isolated temp env for checks.
- `scripts/validate-local.sh`: local smoke checks.
- `scripts/verify-harness.sh`: one entrypoint that runs all required checks.

Use this source-of-truth order in generated projects:
1. Latest user request.
2. `TASKS/current.md` for current focus and done criteria.
3. `docs/requirements.md` for user-visible behavior and acceptance criteria.
4. `docs/technical-design.md` for ownership boundaries and validation design.
5. `AGENTS.md` for project-wide operating rules.
6. `CHECKS.md` for deterministic verification commands.

When these files already exist, read them first and update only what the current goal changes.
Do not overwrite existing operator rules, protected-data rules, or checks without explicit reason.

## Bootstrap

For a new or mostly empty project, use `scripts/bootstrap_project_start.py` from this skill if it fits. It creates the standard frame without overwriting existing files unless `--force` is passed.
When `--force` is used, the bootstrap script must back up existing managed files under `.project-start-backup/` before overwriting them.

Example:

```bash
python /path/to/project-start/scripts/bootstrap_project_start.py --root /path/to/project --project-name starlink --goal "..."
```

After bootstrapping, inspect generated files and adapt them to the project. Treat generated content as a starting point, not final truth.

The bootstrap output is the common base. Add a project-specific quality profile before implementation whenever the project has concrete code, UI, data, automation, deployment, mail, auth, payment, migration, deletion, or integration behavior.

## Workflow

1. Read local project rules first: `AGENTS.md`, `CHECKS.md`, `TASKS/current.md`, and existing specs if present.
2. Write or update specs before implementing behavior.
3. Define harness checks that can run without secrets, live production data, or external destructive writes.
4. Add fixture/smoke coverage before or with risky behavior changes.
5. Implement in the smallest owned file scope.
6. Run the relevant commands from `CHECKS.md`.
7. Report changed files, checks, skipped checks, operator impact, and residual risk.

## Subagents

`작업개시`, `/작업개시`, and `*/작업개시*` include permission for automatic subagent use unless the user says not to. `Subagents: auto` is the explicit long-form equivalent.

Use a supervisor pattern: the main agent is the orchestrator, owns scope and final integration, and delegates bounded work to specialized agents. Do not use subagents for tiny one-file edits, simple questions, or work where the immediate next step depends entirely on the delegated result.

Automatic routing:
- `explorer`: first pass for non-empty repos, unclear architecture, existing auth/data flows, or before touching unfamiliar code. Read-only; answer with paths and flow.
- `spec-writer`: prompted worker for large inception work when docs can be drafted in a disjoint scope such as `docs/**` and `TASKS/current.md`.
- `worker`: implementation only after the main agent gives exact file ownership and non-overlapping write scope.
- `reviewer`: prompted worker or reviewer-style pass focused on security, regression, data loss, duplicate writes, over-broad automation, and drift from specs.
- `tester`: prompted worker or tester-style pass that runs only `CHECKS.md` or declared harness commands and reports skipped checks.
- `release-preflight`: use the `leak-check` skill before public GitHub, portfolio, package, or external handoff.

Default split by task:
- New project or empty folder: main drafts the initial specs/harness, then reviewer/tester validate the frame when the scope is more than a minimal skeleton.
- Existing project with unclear structure: explorer first, then main decides whether worker/reviewer/tester are needed.
- Multi-file implementation: explorer if needed, worker for exact files, reviewer for risk, tester for checks.
- Security, auth, payments, mail/calendar sync, data migration, deletion, or duplicate-write logic: reviewer and tester are expected unless the change is trivial.
- Public release or GitHub push/PR: run `leak-check`; attach security/release-preflight review for non-trivial repos.

Delegation constraints:
- Each subagent gets a concrete output contract and file scope.
- Workers are told they are not alone in the codebase and must not revert unrelated edits.
- Reviewer and tester are read-only unless explicitly assigned a fix.
- No subagent should read or print secrets, raw personal data, live DB contents, auth stores, cookies, or token files unless the user explicitly asks.
- The main agent reconciles conflicts, applies final judgment, and reports what was delegated.

## Harness Rules

Harness must be deterministic and safe:
- Use temp DBs, temp blobs, and temp auth paths where possible.
- Do not read `.env`, `auth/`, `playwright/.auth/`, live DBs, or raw personal data unless the user explicitly asks.
- Keep live APIs out of default harness checks.
- Do not run arbitrary package scripts, deploy commands, mail sends, browser auth flows, or production mutations in the default generated harness.
- Use one command such as `./scripts/verify-harness.sh` as the final gate.
- If a behavior changes, add fixture coverage for the incident that motivated it.

Generate harnesses with this layered model:
1. Common base: `AGENTS.md`, source-of-truth order, data safety, subagent routing, and final gate.
2. Universal quality gates: deterministic local checks, secret isolation, no live APIs by default, no private logs, and no arbitrary package scripts.
3. Project-specific quality profile: language checks, fixture tests, integration mocks, UI checks, or deployment checks chosen from that project's specs.
4. Opt-in live checks: manual commands for real APIs, mail, deployments, or production data, never part of the default final gate.

Use AI Engineering Coach concepts as harness-quality criteria, not as a dashboard requirement:
- Prompt quality: specs, acceptance criteria, file references, and clear constraints exist.
- Session hygiene: `TASKS/current.md` is focused and the final response reports checks and skipped checks.
- Code review: reviewer checks security, regression, data loss, duplicate writes, and spec drift.
- Tool mastery: use relevant skills/subagents when they materially reduce risk.
- Context management: keep always-on prompt files useful; move project-specific detail into scoped docs.

## Drift Control

Prevent ずれ between specs and code:
- Requirements state behavior in user terms.
- Technical design states data flow and ownership.
- Harness fixtures lock high-risk behavior.
- Reviewer checks for security, regression, data loss, duplicate writes, and over-broad automation.
- Tester runs only declared checks and reports skipped checks.

If docs and code disagree, stop and reconcile them before claiming completion.

## Final Response

Keep the final response short:
- State what was created or changed.
- List key files.
- List validation commands and pass/fail.
- Call out skipped checks and remaining risks.
