# Design Source Routing Reference

## Command

```bash
$META_HARNESS_ROOT/bin/harness design-sources 검색 <query>
$META_HARNESS_ROOT/bin/harness design-sources 추천 <goal>
$META_HARNESS_ROOT/bin/harness design-sources 목록 [category]
$META_HARNESS_ROOT/bin/harness design-sources 상태
```

Set `META_HARNESS_ROOT` to the Meta Harness repository root before running these commands outside the repository.

## Source Classes

- `component-marketplace`, `component-library`, `component-gallery`: choose for concrete UI primitives, sections, or React/Tailwind examples.
- `motion-inspiration`, `motion-component`: choose for micro-interactions; require `prefers-reduced-motion` and compositor-friendly properties.
- `inspiration-gallery`, `brand-reference`, `product-ui-reference`: choose for direction and flow patterns, not direct copying.
- `design-md`, `design-md-catalog`, `design-md-tool`: choose when a durable visual identity or agent-readable design system is needed.
- `design-extractor`, `design-agent-tool`: inspect first; do not install by default.
- `web-quality`, `web-quality-tool`: choose when performance/accessibility/best-practices evidence matters.
- `icons`: choose only after license and brand constraints are clear.

## Common Matches

- Landing/SaaS: `landing.love`, `onepagelove.com`, `saaspo.com`, `cta.gallery`, `godly.website`.
- Components: `21st.dev`, `daisyui.com`, `magicui.design`, `reactbits.dev`, `ui.aceternity.com`, `smoothui.dev`.
- Accessible React design system with an agent-readable local CLI: Astryx by Meta; use `$astryx-design-system`, preflight project scripts/config before CLI execution, route install/init/template/swizzle/upgrade through the target-mutation gate, and keep its hosted MCP endpoint behind provider-egress preflight.
- Design-search reference: UI UX Pro Max; use its taxonomy, anti-patterns, and accessibility checklist as reference only, and do not install or vendor it until component-level license signals are consistent.
- Design-critique patterns: Taste; paraphrase only brief-first assessment, variance/motion/density separation, design-system-versus-style labeling, and redesign preservation of information architecture, accessibility, and product intent. Do not install the bundle or inherit its framework and network defaults.
- Motion: `60fps.design`, Magic UI, React Bits, BundUI.
- Motion recipes: Transitions.dev; link one pinned recipe at a time, review current terms and dependencies, preserve reduced-motion behavior, and do not install Pro/Refine or redistribute the collection.
- Persistent design system: Google `design.md`, Stitch DESIGN.md docs, `VoltAgent/awesome-design-md`.
- Runtime design file inspection: `$openpencil-cli`.
- Web quality: curated `web-quality-audit` skill plus Lighthouse docs/tooling.

## Skill And Context Policy

Prefer project-scoped skill visibility:

```bash
CODEX_HOME=/path/to/project/.codex $META_HARNESS_ROOT/bin/harness ui-skills 연결 frontend-design
```

Use symlinks for curated skills when possible so each project sees only the skills it needs while the canonical source stays in the Meta Harness repository.

Avoid bulk global installs. More skills increase context noise and accidental invocation risk.
