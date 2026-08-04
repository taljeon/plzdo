---
name: plzdo-project-harness
description: Route local software work through bounded project context, explicit authority, and evidence-backed completion.
---

# PlzDo Project Harness

Use this skill when a repository follows the PlzDo Local control-plane method.

## Run Model

Treat meaningful work as `Input -> Judgment -> Tool -> Evidence`.

1. Read the latest request and repository-local control files in their declared order.
2. Classify the work as Quick, Plan, or Goal and decide whether repetition must be bounded.
3. Require an approved formalization before Goal work or a bounded loop begins.
4. Use the smallest local tool surface that can complete the work.
5. Verify each completion claim with the repository's declared checks.

## Boundaries

- Keep credentials, auth state, private logs, live databases, and full private documents out of prompts and artifacts.
- Treat context packs, memory, metrics, delegated work, and review output as advisory inputs.
- Preserve unrelated changes and protected paths.
- Require explicit operator authority for production effects or writes to another repository.
- Bound repeated work by iterations, timeout, checkpoints, self-stop conditions, and evidence.

## Completion

Report the result, changed files, checks, skipped checks, operator impact, and residual risk. A plan item is complete only when its evidence is recorded.
