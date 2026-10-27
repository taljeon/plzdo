---
name: academic-research-router
description: Route academic research, literature review, citation checking, paper planning, manuscript review, systematic review, meta-analysis, experiment planning, or ARS-style requests to the smallest safe workflow. Use when the user mentions academic research skills, ARS, papers, manuscripts, citations, PRISMA, peer review, research questions, claim verification, thesis/report research, or asks whether to install/adapt Imbad0202 academic research skills.
---

# Academic Research Router

Use this skill to route academic work safely, not to install the full ARS suite by default.

## Route

1. If the task is current or factual, use primary/authoritative sources and cite links.
2. If the user has only a broad topic, start with Socratic research-question narrowing before drafting.
3. If the user asks for literature review or systematic review, define search scope, inclusion/exclusion criteria, evidence table, and citation verification gate.
4. If the user asks for paper writing, require the research question, audience/venue, source set, citation style, and allowed output format before drafting.
5. If the user asks for review, keep source material read-only unless they explicitly request edits.
6. If the user asks to install ARS, read [references/adoption.md](references/adoption.md) and produce a preflight first.

## Boundaries

- Do not fabricate citations or claim that a source supports text you did not verify.
- Do not upload unpublished manuscripts, reviewer letters, private notes, full corpora, or raw data to external APIs/models without explicit consent.
- Do not enable ARS hooks, cross-model verification, API-backed citation checks, caches, or experiment execution by default.
- Do not treat the upstream ARS workflow as source of truth for this repo; use it as a reference pattern.
- Store only reusable sanitized research workflow memory, never full papers or raw notes.

## Output

For routed academic work, return:

- `Route:` scoping, literature review, citation check, paper plan, manuscript review, or full pipeline.
- `Evidence Gate:` source links, citation existence check, claim-support table, PRISMA-like selection log, or reviewer rubric.
- `Install Decision:` use built-in router, opt-in ARS preflight, or skip.
