# State, Context, and Local Memory

PlzDo Local stores durable runtime data only under the resolved state root:

1. `PLZDO_HOME` when set to an absolute path.
2. `$XDG_STATE_HOME/plzdo-local` when available.
3. `~/.local/state/plzdo-local` otherwise.

The repository remains code and templates. Local project paths, formalizations, state, memory, findings, metrics, loop checkpoints, and context packs do not belong in the public repository.

## Two-Layer Validation Contract

Published schemas are Draft 2020-12 structural interchange contracts. Runtime validators are the authoritative semantic layer for chronology, hashes, derived identities, cross-field relations, credential rejection, and exact host-language types. Schema acceptance alone does not guarantee runtime acceptance.

JSON Schema treats a JSON number with no fractional part, including `0.0`, as an integer and does not treat a boolean as a number. Runtime count and limit fields are intentionally stricter: the Python value must have exact type `int`, so both booleans and every float, including an integral float such as `0.0`, are rejected with the field's typed runtime error.

## Formalization

Goal-weighted work and bounded loops require an approved formalization. The approval hash binds the objective, criteria, non-goals, constraints, route, plan, and evidence contract. An approved governed edit returns the record to draft. Completed and superseded records are immutable.

Approval requires an interactive terminal phrase. Redirected standard input cannot approve a record. Completion stores an evidence digest rather than the local evidence path.

## Context Pack

Compact and full packs use the same generator and the same fixed project-control allowlist:

- `AGENTS.md`
- `CHECKS.md`
- `TASKS/current.md`
- `docs/requirements.md`
- `docs/technical-design.md`

Compact mode stores hashes and bounded summaries. Full mode additionally contains those five control documents. Both modes are local-only and non-authoritative. Freshness is recomputed from current file bytes. Recursive project scans, ignored data, logs, databases, credentials, browser state, and arbitrary files are outside the generator.

## Work State

Work state is a bounded recovery cache with current, next, constraints, recent evidence, an optional context checkpoint, and an optional loop summary. When count or byte caps are crossed, the full pre-compaction state is written to an archive before the compact active state is replaced.

Checkpoint source is derived from the selected input branch and cannot be supplied as a label:

- an operator-observed integer requires an interactive terminal;
- token counts require positive used and maximum values;
- a self-estimate is stored explicitly as an estimate;
- unattended CI, schedule, watcher, hook, and daemon contexts are rejected;
- a below-threshold decision is returned as typed evidence and does not write state.

## Bounded Loops

A loop file tracks an approved formalization hash, maximum iterations, timeout, checkpoint iteration, evidence, stagnation, and terminal reason. It does not start, supervise, or terminate an AI process. Advancing a terminal loop, changing approval binding, or skipping a checkpoint iteration is rejected. An advance at or beyond the timeout records canonical automatic exhaustion with reason `timeout`; callers cannot select early exhaustion.

## Local Memory

Memory is local JSON and always `sourceOfTruth=false`. It accepts bounded reusable summaries only. Credential shapes, private paths, network locations, raw log blocks, authorization headers, and full-document-like content are rejected rather than masked. A stable key has exactly one active item; replacement supersedes history. Search is bounded and non-recursive. Purge is explicit.

## Findings and Metrics

Findings have immutable IDs and may move only from `open` to `closed` or `accepted-risk` with a resolution and additional evidence. They cannot disappear through the supported transition API.

Metrics are bounded JSON Lines metadata: route, status, route feedback, duration, counts, and timestamp. They contain no prompts, code, logs, provider sessions, or authoritative decisions.
