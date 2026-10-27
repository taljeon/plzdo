---
name: design-source-router
description: Route frontend and UI design work to the smallest useful external design source, component catalog, DESIGN.md reference, OpenPencil inspection, Lighthouse-style quality gate, or project-local skill. Use when the user asks for vibe-coding UI resources, component inspiration, design-system extraction, DESIGN.md generation, web quality checks, motion/animation references, icon/brand references, or how to choose among many design sites without overloading Codex context.
---

# Design Source Router

Use this skill to choose sources, not to install them. The Meta Harness command is:

```bash
$META_HARNESS_ROOT/bin/harness design-sources 추천 "<goal>"
```

Set `META_HARNESS_ROOT` to the Meta Harness repository root when using this skill outside that repository.

## Route

1. Read the target project's existing `AGENTS.md`, design tokens, components, and `DESIGN.md` first.
2. If the user supplied a `.fig` or `.pen`, use `$openpencil-cli` before browsing inspiration.
3. If the user needs persistent visual identity, use `DESIGN.md` and validate it before implementing UI.
4. If the user needs implementation patterns, choose one or two component libraries from the catalog.
5. If the user needs visual direction, first use the installed `$design-isms-reference` skill to show three unchanged original candidates from Design -isms. This user explicitly wants original images and the source's own selection logic, without reinterpretation. Respect a fixed project identity or a different explicit reference. Use other inspiration galleries when the request calls for them.
6. If the user needs performance/accessibility confidence, use Lighthouse-style gates and the curated UI skills.

Read [references/routing.md](references/routing.md) for source classes and install boundaries.

## Default Safety

- Do not install design MCP servers, browser extensions, Figma plugins, or npm packages from a catalog source without explicit preflight.
- Do not copy branded assets, icons, screenshots, or complete component code without checking license and dependencies.
- Do not let inspiration override the target project's product purpose, density, accessibility, or visual constraints.
- Keep context compact: use the catalog search output and one or two selected sources, not the entire list.

## Output

When recommending sources, return:

- `Use:` one to three sources with why.
- `Avoid:` sources or runtime installs that are not needed.
- `Gate:` verification command or evidence, such as screenshots, accessibility check, OpenPencil lint, DESIGN.md lint, or Lighthouse-style metrics.
