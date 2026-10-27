---
name: understand
description: "Use when the user wants to understand existing code, structure, or a past decision: \"how does X work\", walkthroughs before changing something, where something should live, \"why does X work this way\", design rationale, regressions, thresholds. Korean cues: 설명해줘, 어떻게 동작해, 흐름 설명, 구조 파악, 구조 설명, 왜 이렇게 돼 있어, 왜 이렇게 만들었어, 이해가 안 가, 뭐 하는 코드야. Explains architecture and runtime flow, with a cited read on decisions and tradeoffs from git and gh. Skip one-fact lookups such as a line count or a single value."
---

# Understand

Two modes. **How** answers what the code does and how it works. **Why** answers what forces led to its shape. If the scope is ambiguous, state your interpretation and explore. The user can redirect.

Every spawn is a read-only subagent, using the host's usual subagent tool and models.

## How

Explore the codebase to answer "how does X work?" questions. Produce architectural explanations at the level of a senior engineer onboarding onto a subsystem, enough to build a working mental model, not so much that it reads like annotated source code.

### 1. Assess complexity

- **Simple** (a single module, a small utility, a narrow question such as "how does function X work"): no explorers. Spawn one explainer that explores and explains in one pass, built from `references/explainer-prompt.md` without the explorer-findings section. Go to step 4.
- **Complex** (a subsystem spanning multiple files or services, a cross-cutting feature, a full architectural overview): go to step 2.

When in doubt, take the simple path.

### 2. Explore (complex only)

Decompose the question into 2 to 4 angles, each a distinct slice of the subsystem. Spawn all explorers in a single message, each with `references/explorer-prompt.md` and its angle filled in.

### 3. Synthesize (complex only)

Once all explorers have returned, spawn one explainer with `references/explainer-prompt.md` and every explorer's findings filled in.

### 4. Present

Present the explainer's output. Light edits for clarity or context from the conversation are fine. Do not substantially rewrite it.

The explanation uses the sections defined in `references/explainer-prompt.md`, dropping any that do not apply: Overview, Key Concepts, How It Works, Where Things Live, Gotchas.

## Why

Operate as a **careful, cautious, and precise investigator**. Be honest about what you know vs what you're inferring. Read `references/epistemics.md` for the full confidence framework and phrasing guide. The synthesizer must follow it.

### 1. Understand the target and the question

The **target** is usually a chunk of code, a pattern, a feature, or a named design decision. The **question** is usually a design rationale, a tradeoff, a motivating edge case, an external constraint, dead code, or a broad history sweep.

If the target is vague, make your best guess from conversation context (open files, recent edits, what was just discussed). State your interpretation briefly, then proceed.

### 2. Establish the code anchor

Before spawning investigators, build the seed context inline: file paths and line ranges, key symbols, the last few commits touching the target, PR numbers from merge commits (pattern `(#1234)` in the subject line), and any linked issue IDs. Run `git blame -L <start>,<end> <file>` for last-touch commits, `git log --follow -p -- <file>` for full history with patches through renames, `git log --oneline -20 -- <file>` for recent commits with PR numbers visible, and `git log -1 --format=%B <commit>` to extract PR numbers. Then pull the PR bodies and discussion for any substantive commit: `gh pr view <number> --json title,body,author,createdAt,mergedAt,labels,closingIssuesReferences,comments,reviews`. This anchor goes to every investigator and to the synthesizer.

### 3. Spawn investigators

Evidence comes from source control. Spawn one investigator with `references/investigator-prompt.md` filled in, the code anchor, and the user's question.

**Source control** (git history, `gh` for PRs and issues, code comments, tests). Always spawn. Append `references/sources/code-archaeology.md`. Best at *implementation-time rationale captured during review*.

If a source is unavailable (no repo or `gh` not authenticated), say so in Sources Consulted as a gap. For a single-commit trivial target where the PR description already contains the complete answer, you may answer inline. Say so explicitly.

### 4. Synthesize

Spawn one synthesizer with the investigator findings (including null results), the code anchor, the user's question, `references/epistemics.md`, and `references/synthesizer-prompt.md`.

### 5. Present

Present the synthesizer's output. You may lightly edit for clarity or add context from the conversation, but **do not rewrite the confidence language**.

The structure is the one in `references/synthesizer-prompt.md`: The Question, The Code in Question, What We Found, What We Can Reasonably Infer, Competing Hypotheses, What We Don't Know, Sources Consulted, Confidence Summary. Keep the confidence separation intact, and keep Sources Consulted as one line per source, including ones that returned nothing, with the reason.

After Sources Consulted, if the `why` question is a precursor to changing this code, convert the lineage findings into a Preserve / Change / Avoid / Risk constraint set for planning the change.

### Common failure mode

- **Recency bias**. Assuming the most recent commit is authoritative. The current shape is often the accretion of many earlier decisions. Trace back.

Adapted from cursor/plugins pstack v0.15.25 skills `how` and `why` (MIT, Copyright (c) 2026 Lauren Tan); see LICENSE-pstack.md.
