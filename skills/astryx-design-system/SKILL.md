---
name: astryx-design-system
description: Use Meta's Astryx design system for a specific React/StyleX project as a component, theme, template, and agent-readable CLI source. Trigger when the user mentions Astryx, @astryxdesign packages, Astryx components or themes, or asks whether Astryx should be used for a frontend. Start with catalog/source assessment; execute an installed CLI only after local script/config code-execution preflight, and route target mutations through the governing project gate.
---

# Astryx Design System

Use Astryx when a React project benefits from an accessible component system, coherent theming, application templates, or structured component documentation for agents.

## Route

1. Read the target project's `AGENTS.md`, package manifest, existing design system, tokens, components, and `DESIGN.md` first.
2. If another design system is already established, preserve it unless the user explicitly approves migration or coexistence.
3. Before executing an installed Astryx CLI, inspect the target project's package manager, `package.json` scripts (`preastryx`, `astryx`, `postastryx`), `astryx.config.*`, and configured integration module paths. Astryx can import and execute user-authored config/integration code even on commands with no intended file writes. If that code is untrusted or cannot be reviewed, stop at catalog/source assessment.
4. Before recommending adoption, verify Node.js `>=22.13.0`, React and ReactDOM `>=19`, and `@stylexjs/stylex ^0.19` against the target project. Treat a mismatch as `reference only` unless a separately approved migration resolves it.
5. After that preflight, inspect the installed CLI capability manifest first, then use typed JSON output instead of scraping docs or assuming a command shape. Use the project's existing package manager; the examples below use a previously reviewed npm script:

```bash
npm run astryx -- manifest --json
npm run astryx -- search "<need>" --json
npm run astryx -- component <Name> --json
npm run astryx -- template --list --json
npm run astryx -- docs <topic> --json
npm run astryx -- doctor --json
```

6. If the project has no reviewed script, use a physical `node_modules/@astryxdesign/cli/bin/astryx.mjs` only when that exact dependency already exists and its package metadata has been inspected. If the package manager uses another layout, stop rather than synthesizing a global, floating `npx`, or network-backed invocation. Re-check the manifest when the installed version differs from the audited snapshot below.
7. Select the smallest relevant component, pattern, or template. Translate the result into the project's own design constraints rather than making every product look like the demo site.
8. Before implementation, render the exact package/file change plan. Under PlzDo Core, do not mutate a target repository directly: route the plan through `hn 적용 계획`, then use `hn 적용 실행` only after its P5 confirmation and approval checks.
9. Verify the implemented result with screenshots, responsive checks, keyboard navigation, accessibility checks, and the project's normal frontend tests.

## Mutation Boundary

Treat these as project mutations. Under PlzDo Core they require the P5 plan/apply path above, not a direct skill action:

- installing `@astryxdesign/*` packages;
- `astryx init`;
- copying a template into the project;
- `swizzle` or any source ejection;
- `upgrade --apply` or codemods;
- theme builds that write generated files.

Before one of those actions, report the target project, exact package versions, registry provenance/integrity evidence when available, lockfile impact, files to be written, rollback path, browser-support implications, and coexistence or migration plan. Preserve the Astryx MIT copyright and permission notice when copying or swizzling a substantial portion of upstream source.

## Design Rules

- Prefer theme tokens before component wrappers or source ejection.
- Preserve the target product's purpose, density, brand, and existing navigation model.
- Astryx is currently beta; pin compatible package versions and keep all `@astryxdesign/*` packages aligned.
- Check the target audience against Astryx browser-support tiers before adoption.
- Use stable CLI error codes and response `type` fields, never human-readable error text, in automation.
- Do not connect the hosted Astryx MCP endpoint (`https://astryx.atmeta.com/mcp`) or another remote integration by default. It is provider egress and needs an explicit project/provider preflight; the reviewed local CLI path is sufficient for normal agent-readable discovery.
- Do not copy Meta branding, demo assets, or complete examples without checking license and product fit.

## Output

Return:

- `Fit`: adopt, reference only, coexist, or reject, with the reason;
- `Use`: selected components, theme, template, or CLI docs;
- `Mutation`: exact packages/files requiring approval;
- `Verify`: visual, accessibility, responsive, and test evidence;
- `Risk`: beta/version, browser, migration, or source-ejection risk.

Audited snapshot: `facebook/astryx@2e2e960468150aa9373aed9f6b02e3b2a6d8d07b` (observed 2026-07-19), `@astryxdesign/cli@0.1.6`, MIT. Official sources: <https://github.com/facebook/astryx> and <https://astryx.atmeta.com>.
