---
name: design-spec
description: Upstream design by Claude before any implementation. Use when the user asks to design, architect, plan a feature or system, compare technical approaches, or turn an idea into something buildable (설계, 아키텍처, 구조 잡아줘, 어떻게 만들지). Produces options with trade-offs, a chosen structure, testable acceptance criteria, and a spec packet that codex-implement can hand to a worker. Not for one-line fixes or questions with an obvious answer.
---

# Design → spec

Claude owns this stage. Keep the output short enough to read in two minutes.

## 1. Frame

- Goal in one sentence, and who it is for.
- Constraints: deadline, stack already in use, data, budget, things that must not change.
- Non-goals: one line on what this design leaves out.
- Unknowns that would change the design. Ask only the ones you cannot reasonably assume; state the assumptions you make.

## 2. Options

Two or three real alternatives, not strawmen. For each: how it works in one line, what it costs, what it risks. Pick one and say why in one or two sentences.

## 3. Structure

- Components and what each owns.
- Data flow between them, and the interfaces (function signatures, endpoints, file formats).
- Where it touches existing code, and what stays untouched.
- When the design moves module boundaries: if a module were deleted, where would its complexity go? The interface you draw is also the test surface.
- Migrations and wide refactors: expand, migrate, then contract, so old and new paths coexist; put a data-recovery check in the acceptance criteria.

A diagram only if it makes the flow clearer; simple ones inline, complex ones through `codex-visual`.

## 4. Acceptance criteria

Each one testable by a command or an observable result ("`pytest -q` passes", "page renders at 375px without horizontal scroll"). These become the finish line for the worker and for Claude's final acceptance.

## 5. Spec packet

Split the work into packets for `codex-implement`: objective, numbered requirements, owned files (no overlap when parallel), no-touch paths, tests to add, acceptance command, and blocked-by when one packet needs another first.

Record a decision file only when it is hard to reverse, surprising without context, and a real trade-off. Follow the project's existing ADR location and numbering; otherwise use `docs/decisions/<yyyy-mm-dd>-<topic>.md` (context, decision, consequences). Multi-file work still needs the user's plan approval before workers start.
