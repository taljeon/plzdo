---
name: team-patterns
description: Choose how to split work across subagents and verify their output. Use for large audits, migrations, multi-source research, codebase-wide reviews, or design work with several viable options, especially when a Meta Harness route is Plan/Goal/UW. Not for small single-step tasks.
---

# Team patterns

Meta Harness (`hn`) decides how big the work is. This skill decides the team shape inside it. Do not generate per-project agents or CLAUDE.md files; the harness owns project guides.

## Pick the shape from the control flow

| Pattern | Use when | Run it here |
|---|---|---|
| Pipeline | each step needs the previous output | sequential `Agent` calls; a human check between steps only if asked |
| Fan-out / fan-in | same input, independent angles | parallel background `Agent` calls, then merge yourself |
| Expert pool | input type decides the specialist | call only the matching agent (code-reviewer, coding-test-coach, ...) |
| Producer / reviewer | output must pass objective criteria | worker (Claude or `codex-implement`) then a reviewer of the other model; max 2-3 rounds |
| Supervisor | work amount changes while running | named agents + `SendMessage`; reassign as results come in |
| Hierarchical | problem splits into sub-problems | at most 2 levels deep |

Mix patterns per phase, e.g. analysis (pipeline) → implementation (fan-out with Codex workers) → integration test (pipeline).

## Quality patterns (for audits, reviews, research)

- **Adversarial check:** for each finding, independent checkers try to refute it; keep it only if most confirm with evidence.
- **Split perspectives:** give checkers different lenses (correctness, security, reproducibility) instead of the same prompt.
- **Judge panel:** for open design questions, build N different options in parallel, pick the best, borrow strengths from the rest.
- **Loop until dry:** keep searching until K rounds in a row find nothing new; record rejected items so they are not re-proposed.
- **Completeness critic:** before merging, one agent asks only: which lens was unused, which claim unverified, which source unread.
- **Disclose exclusions:** when sampling or top-N limits coverage, report how many items were skipped.

## Six lenses and a judge (`/67`)

The judge panel in its fixed form, for high-stakes or open-ended deliverables (a pitch, an architecture, a pricing page). Run it only when the user asks for it by name; it costs six attempts plus a judge.

1. Write one brief every attempt gets word for word: the task, the deliverable format, the constraints. Tight enough that the six results compare directly.
2. Run six attempts, each locked to one lens. Lenses 1-3 go to Claude `Agent` calls, lenses 4-6 to `codex-worker` (two groups of three, so the three-worker limit holds per model):
   1. Minimal: the smallest thing that fully works.
   2. Complete: every edge case and objection covered.
   3. First principles: ignore convention, derive it from scratch.
   4. Prior art: find the best existing versions and adapt their strongest pattern.
   5. Adversarial: ask what breaks each choice, keep what survives.
   6. Wildcard: one bold bet, done seriously.
   Each attempt returns a complete answer with decisions made, not "it depends".
3. Judge (Claude, without writing its own answer first): score each attempt 1-10 on correctness, completeness and taste, rank all six with a one-line verdict, and name the single strongest element of each, losers included.
4. Build the final on the winner, add every strongest element worth taking, and list what came from which lens.

Output: the ranking (rank, score, one line each), the final answer, then the list of borrowed parts.

## Scale and limits

- Match scale to the ask: "any bugs?" is a few searchers and one checker; "audit thoroughly" is more searchers and 3-5 checkers per finding.
- At most 3 workers at once. One owner per file. Every worker gets a self-contained brief (goal, owned files, no-touch paths, acceptance).
- Check each worker's evidence before accepting it. Keep progress in TASKS.md for long runs.

Adapted from revfactory/harness (Apache-2.0) @ 92d9f1b, skills/harness/references/team-patterns.md.
