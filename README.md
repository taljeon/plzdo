# PlzDo

Tell your AI coding agent: plz do it, then prove it.

PlzDo is a local-first control-plane template for developers who already use AI coding agents and want safer, more repeatable work. It is not an agent runtime, cloud service, browser extension, or autonomous framework. It is a small set of rules, checks, examples, and optional Codex-compatible skills that make agent work easier to review.

Copy `AGENTS.md`, `CHECKS.md`, and `TASKS/current.md` into a project to give your coding agent source-of-truth rules, stop conditions, and a local verification gate.

## What You Get

- A public `AGENTS.md` template with hard safety boundaries.
- A source-of-truth order for requests, task files, docs, checks, code, and tests.
- A bounded-work model so long tasks have stop conditions and evidence.
- A local verify gate that does not call providers or mutate targets.
- A public release leak check for obvious private paths, keys, and local artifacts.
- A small `scripts/plzdo` helper to initialize and check target projects.
- Two optional Codex-compatible skills:
  - `adaptive-project-harness`
  - `external-review-router`

## Five-Minute Quickstart

Requirements:

- Bash
- Git
- Python 3

```bash
git clone https://github.com/taljeon/plzdo
cd plzdo
./scripts/verify
./scripts/plzdo init /tmp/plzdo-demo
./scripts/plzdo check /tmp/plzdo-demo
CODEX_HOME="$HOME/.codex" ./scripts/install-codex-skills --dry-run adaptive-project-harness external-review-router
```

`scripts/plzdo init` copies the public template into the target directory. It refuses to overwrite existing files unless `--force` is passed. The skill installer dry run prints what would be copied. Neither command installs hooks, daemons, MCP servers, browser extensions, provider tools, or background automation.

## Core Model

```text
Input -> Brain -> Tool -> Evidence -> State
```

- **Input** is the accepted task frame: user request, local docs, constraints, and relevant prior context.
- **Brain** is the policy and routing layer: safety checks, source-of-truth comparison, task sizing, and verification planning.
- **Tool** is the bounded action layer: edits, tests, scripts, reports, and explicit apply steps.
- **Evidence** decides whether work is done: command output, checks, generated reports, diffs, and stated residual risk.
- **State** is recovery context only. It helps resume work; it is not source of truth.

## What This Is Not

- Not a hosted service.
- Not a package manager.
- Not a replacement for your coding agent.
- Not an autonomous production deployer.
- Not a default external-provider gate.
- Not a memory system that overrides your docs or code.

## Repository Layout

```text
AGENTS.md                                Public agent operating guide
CHECKS.md                                Verification and release checklist
TASKS/current.md                         Current task template
docs/architecture.md                     Control-plane architecture
docs/case-study.md                       Anonymized extraction notes
docs/what-not-to-automate.md             Automation boundaries
docs/external-review-policy.md           Advisory external review policy
examples/basic-project/                  Minimal toy project
scripts/plzdo                            Minimal init/check helper
scripts/verify                           Default local gate
scripts/check-release-leaks              Public release leak preflight
scripts/install-codex-skills             Optional local skill copy helper
resources/codex-skills/                  Public-safe Codex skill pack
review/REVIEW-PROMPT.md                  Optional external review prompt template
```

## Minimal Project Gate

```bash
./scripts/plzdo init ./my-agent-harness
./scripts/plzdo check ./my-agent-harness
```

The check verifies that the target has the minimal control files and the core non-authority boundaries. It does not run external providers or mutate the target's code.

## Evidence

PlzDo is extracted from a private predecessor, but the public repository includes only reusable rules, checks, and templates. See `docs/case-study.md` for the sanitized design lessons.

## Demo Checks

Clean repo:

```bash
./scripts/verify
```

Leak scanner self-test:

```bash
./scripts/check-release-leaks --self-test
```

The self-test creates a temporary fake secret outside tracked release contents, proves the scanner rejects it, deletes it, and exits successfully because the rejection was expected.

Expected self-test output:

```text
leak scanner self-test passed
```

If a real release file contains a hard-fail marker, `scripts/check-release-leaks` prints a `FAIL <file>:<line>: <reason>` line and exits nonzero.

Example failure shape:

```text
FAIL path/to/file:12: reason-name
```

## Safety Boundaries

- No default network calls.
- No default provider calls.
- No hooks, daemons, launch agents, MCP servers, browser extensions, or background watchers.
- No target repository mutation outside an explicit operator-reviewed apply path.
- No secrets, auth stores, cookies, private keys, raw logs, live databases, or full private documents.
- External AI reviewers are advisory evidence only.
- Memory and summaries are recovery aids, not source of truth.

## Optional Skill Install

Read each `SKILL.md` before installing. Skills are instruction files and should be treated as supply-chain content.

```bash
CODEX_HOME="$HOME/.codex" ./scripts/install-codex-skills --list
CODEX_HOME="$HOME/.codex" ./scripts/install-codex-skills --dry-run adaptive-project-harness external-review-router
CODEX_HOME="$HOME/.codex" ./scripts/install-codex-skills adaptive-project-harness external-review-router
```

The installer copies files only from `resources/codex-skills/<skill>/` into `$CODEX_HOME/skills/<skill>/`. It refuses overwrite unless `--force` is passed.

## License

MIT. See `LICENSE`.
