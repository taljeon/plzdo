---
name: adaptive-project-harness
description: "Route AI-assisted project work into the smallest safe workflow: quick task, planned feature, or bounded long-running work with evidence-first completion."
---

# Adaptive Project Harness

Use this skill when a coding agent needs a lightweight operating frame for project work.

## Before Acting

1. Read the target project's local `AGENTS.md` or equivalent instructions.
2. Read the current task file if one exists.
3. Identify the smallest safe route:
   - quick task;
   - planned feature;
   - bounded long-running work.
4. Define completion evidence before editing.

## Route Rules

### Quick Task

Use for small, reversible work that can be checked immediately.

Evidence examples:

- tests pass;
- lint passes;
- one file diff is reviewed;
- a report path is produced.

### Planned Feature

Use for multi-step work that still fits in one session.

Requirements:

- short plan;
- affected files;
- checks to run;
- residual risks.

### Bounded Long-Running Work

Use for repeated review, migration, repair, or large cleanup.

Requirements:

- max iteration count;
- timeout or stop rule;
- checkpoint state;
- evidence per pass;
- explicit stop when evidence no longer supports more changes.

## Safety Rules

- Do not run unbounded loops.
- Do not mutate production or target repositories without an explicit apply path.
- Do not treat memory, summaries, worker output, or external reviewer output as source of truth.
- Do not store secrets, cookies, private keys, raw private logs, live database contents, or full private documents.
- Keep edits scoped and preserve unrelated user changes.

## Completion Report

Report:

- route used;
- changed files;
- checks run;
- skipped checks and why;
- evidence;
- residual risk.
