# Architecture

PlzDo preserves the owner's lead-engineer workflow in a Claude-only kit. Claude owns requirements, design, specifications, and final acceptance. Skills select the procedure; agents do bounded delegated work. Optional hooks enforce checks at tool boundaries, and separately loaded mods add session behavior.

```text
Request
  -> Rules: harness/CLAUDE.md
  -> Skills: selection, workflow skills, task procedure
  -> Claude agents: implementer / reviewer / code-reviewer
  -> Optional hooks: checks before tool actions
  -> Mods: session behavior from a pinned separate repository
  -> Evidence and lead-engineer acceptance
```

Hooks intercept relevant events during work. Mods operate during the session rather than only after review; the diagram shows their place in the setup, not a strict execution order.

## Rules and authority

Copy or merge [harness/CLAUDE.md](../harness/CLAUDE.md) into the Claude configuration's `CLAUDE.md`. It folds shared rules into one file and replaces the owner's Codex routes with Claude skills and agents. The current request takes priority, and repository-specific rules take priority over these global rules.

The act-or-ask list permits investigation, tests, Markdown edits, and reversible in-project code edits directly. Multi-file features need a 3-5 line plan and approval before execution. Deletes, destructive Git operations, actions leaving the machine, installations, and global settings changes require asking first. A skill or an agent's output cannot grant those permissions.

The delegation table routes design to `design-spec`, unclear features to `requirements-clarification`, `hn` requests to `adaptive-project-harness`, approved core work to `implement-change`, and code review to `review-change`. It also names agents for coding practice, documentation, document artifacts, readiness checks, and bounded side tasks. Small single-file edits and short answers stay with Claude directly.

## Skills

The rules call for zero or the smallest useful set of complementary skills. Selection follows the task, project constraints, and available tools, rather than a keyword alone. Read the selected skill and only the references needed for the current phase.

For code tasks, load these three workflow skills once at the start:

- `ponytail` lite: before editing, choose the smallest change that meets the request.
- `anti-slop`: while editing, preserve behavior and use the project's checks.
- `verification-before-completion`: before claiming completion, run and read the relevant checks.

The rules also require `pr-oss` before PR titles or descriptions and `leak-check` before public pushes, PRs, or releases. Hooks do not replace that preflight.

## Claude delegation

[review-change](../skills/review-change/SKILL.md) starts `reviewer` and `code-reviewer` in parallel. The first checks specification conformance, including missing or unrequested behavior and weakened tests. The second checks security, performance, and bugs with file and line evidence. Give both the code and specification, plus the implementer's report when available, but not the lead's verdict. The lead verifies findings, fixes confirmed problems, and reports rejected findings and coverage gaps. The `reviewer` cannot run commands, so the lead runs any needed verification.

[implement-change](../skills/implement-change/SKILL.md) sends approved implementation work to an `implementer` in a Git worktree. Record the base commit and existing changes first: a worktree does not include uncommitted work. The packet names the objective, requirements, allowed paths, tests, and acceptance command. After implementation, run `review-change` against the recorded base. The lead reads the diff, reruns acceptance, and merges only with the user's approval for that merge.

The `explorer` agent handles read-only search across many files. The other agent definitions cover coding-test coaching, technical writing, document generation, readiness checks, and bounded side work. Their reports are evidence to examine, not final acceptance or permission to widen the task.

## hn routing

Start a request with `hn` or `HN`, or ask for the harness method, to select [adaptive-project-harness](../skills/adaptive-project-harness/SKILL.md). It uses `Input -> Brain -> Tool -> Evidence` and returns a task weight plus a separate unattended-work flag:

- One-shot: small, reversible work with a quick check.
- Plan: bounded work with multiple steps that fits one session.
- Goal: durable state, architecture, significant implementation risk, or costly uncertainty. Formalize the task and obtain approval first.
- UW: bounded repeated work. It requires approved loop limits, stopping rules, a timeout, checkpoints, and evidence for each iteration.

Goal and UW approval binds to the written formalization and its SHA-256. Changes to approved sections require renewed approval. The kit expresses this method in project documents and ordinary tools; it does not include the owner's harness CLI, registry, or memory runtime. The skill contains the routing precedence, recovery rules, and route-feedback format.

## Hooks and mods

The optional `workflow-skill-gate` checks that the three workflow skills are loaded before the first code edit. The optional `release-gate` checks publishing commands in supported canonical forms. See [Hooks](hooks.md) for events, failure behavior, and manual configuration.

Mods stay in [taljeon/plzdo-claude-mods](https://github.com/taljeon/plzdo-claude-mods); `mods.lock` pins the commit and `mods.sha256` supplies the integrity check. All 8 load by default. Read [Company set step 6](../INVENTORY.md#company-set) and the mods README before loading them: some transmit prompt and answer content, send prompts after idle time, or read local session files.

## Differences from the owner's live setup

Second-model review becomes same-model review. Separate Claude agents have separate assignments, but provide less model independence than the owner's Claude-to-Codex delegation. Supplying the specification without the lead's conclusion remains important.

Hook enforcement exists only when hooks are enabled and allowed to execute. Without them, the workflow instructions are text rules. Even when enabled, the workflow gate fails open on internal errors; the release gate fails closed. The public release gate is an adaptation, not the owner's larger gate bound to private configuration.

The owner's private memory runtime, private project data, and Codex delegation are omitted. Built-in Claude auto-memory is the rules file's suggested substitute, not a reproduction of that runtime.
