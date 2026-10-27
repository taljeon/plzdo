---
name: design-minimal-blue-pitchdeck
description: Create or restyle editable 16:9 PowerPoint pitch decks in the supplied minimalist blue Korean startup style. Use when the user asks for this reference deck's composition, a simple blue pitch deck, a Jogiyo-style deck, or slides matching the cover, problem, solution, product flow, business model, market size, funding allocation, team, or roadmap layouts bundled with this skill. Prioritize layout and visual fidelity over preserving example content.
---

# Design Minimal Blue Pitchdeck

Recreate the reference's restrained blue-on-mist visual system while replacing its subject matter. Preserve editability, composition, rhythm, and intentional simplicity.

## Required workflow

1. Read the installed `Presentations` skill and follow its authoring and QA requirements. Load workspace dependencies first and use the returned bundled Node.js and Python executables for slide helpers.
2. Read [references/design-spec.md](references/design-spec.md) before choosing layouts.
3. Read [references/layout-library.md](references/layout-library.md) and map each content beat to the closest supported layout.
4. Use only this skill as the visual source. Do not mix in Codex Grid, card-heavy dashboard styling, gradients, stock illustrations, decorative photos, or another theme.
5. Define the deck's communication job and narrative before editing visible copy. Treat the bundled text as demonstration content, not required wording.
6. Copy [assets/minimal-blue-pitchdeck-template.pptx](assets/minimal-blue-pitchdeck-template.pptx) to scratch and treat it as the source deck for the full `Presentations` template-following workflow: inspect all slides, create and validate a frame map, prepare the starter deck, then edit inherited slides with `@oai/artifact-tool`. Duplicate, delete, and reorder layout slides only through the validated map; preserve the original asset.
7. When a layout needs structural changes, use [scripts/build_template.mjs](scripts/build_template.mjs) as the coordinate-level implementation reference. Keep the final source as plain JavaScript ES modules.
8. Render every final slide, inspect each at full size, run overflow checks, and fix clipping, wrapping, connector, and alignment errors before delivery.

## Fidelity rules

- Preserve the 16:9 `960 × 540` coordinate system, `50 px` outer margins, pale blue-gray canvas, thin dark frame, and cobalt/indigo palette.
- Use one flat composition per slide. Keep square corners, minimal or no shadows, fine strokes, and generous negative space.
- Keep titles in the upper-left title rail. Use split regular/bold title treatment only where the selected layout specifies it.
- Match the source's compact type scale even when it is smaller than a default presentation theme; the supplied reference is authoritative.
- Replace sample data, names, and labels with audience-facing copy. Never reuse or infer people, companies, facts, or metrics from the original screenshots.
- Maintain each layout's content budget. Shorten copy or select another layout instead of shrinking type or cramming extra panels.
- Use native PowerPoint text, shapes, charts, and connectors for editable structure. Use photos only when the user's content calls for them.

## Template operations

### Standard nine-beat pitch

Start from the bundled PPTX and keep the relevant slides. Replace text and data in place. Keep the visual order when the story fits: cover → problem → solution → product → business model → market size → funding → team → roadmap.

### Shorter or longer deck

Delete irrelevant layouts for a shorter deck. For a longer deck, duplicate the closest existing layout and vary content density without inventing a new visual language. Prefer reusing the problem/solution card rows, product flow, funding allocation, or roadmap rhythm.

### Rebuild or repair

Copy `scripts/build_template.mjs` into the presentation scratch workspace after initializing `@oai/artifact-tool`, then run:

```bash
node build_template.mjs \
  --out /absolute/path/to/minimal-blue-pitchdeck-template.pptx \
  --preview-dir /absolute/path/to/previews \
  --layout-dir /absolute/path/to/layouts \
  --montage /absolute/path/to/montage.webp
```

Use the rebuilt file as a clean template. Do not overwrite the skill asset while producing a user's deck.

## Delivery gate

- Verify every slide is `960 × 540` and retains the `1 px` canvas frame.
- Verify title rail, left/right margins, card widths, icon or photo frames, and timeline spacing against the chosen layout spec.
- Verify blue/indigo contrast and white text on filled panels.
- Verify no unresolved template labels, private source names, or source photos remain.
- Deliver only the user's final deck; keep scratch previews and layout JSON out of the handoff unless requested.
