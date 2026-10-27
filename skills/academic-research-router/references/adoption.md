# Academic Research Source Adoption

## Reviewed Sources

- `Imbad0202/academic-research-skills`: cloned for inspection under `/private/tmp/meta-harness-source-audit/academic-research-skills`.
- `Imbad0202/academic-research-skills-codex`: cloned for inspection under `/private/tmp/meta-harness-source-audit/academic-research-skills-codex`.

## Findings

- The Claude-oriented ARS repo contains multiple workflows, agents, scripts, hooks, plugin metadata, optional Python tools, optional bibliographic API settings, and a CC BY-NC license.
- The Codex sibling packages ARS as a single `academic-research-suite` router skill and explicitly says not to load the whole suite by default.
- Useful patterns: Socratic topic narrowing, Material Passport/reset boundaries, claim/citation verification, PRISMA-style review gates, reviewer independence, source provenance, and human confirmation checkpoints.
- Risk surfaces: hook packs, cross-model verification, external API upload, local caches, experiment execution, unpublished manuscript handling, and very large vendored context.

## Meta Harness Decision

Do not install the full suite globally by default. Keep this router as the active Codex surface and treat the full Codex suite as an opt-in preflight candidate.

Use ARS patterns inside Meta Harness as:

- `research question -> evidence plan -> source verification -> synthesis -> review`;
- claim-support tables instead of unsupported prose;
- citation existence and claim-faithfulness checks when citation quality matters;
- explicit user checkpoints before advancing full paper pipelines;
- sanitized memory only for reusable research workflow facts.

## Preflight For Full Install

Before installing `academic-research-skills-codex`, report:

- exact skill path to install;
- license and non-commercial restriction implications;
- whether hooks/full-runtime mode remain disabled;
- whether API-backed checks will send data externally;
- how to remove the skill;
- expected context impact.
