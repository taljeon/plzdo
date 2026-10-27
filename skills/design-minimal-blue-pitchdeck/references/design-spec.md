# Minimal Blue Pitch Deck Design Specification

## Contents

- Canvas and grid
- Color tokens
- Typography
- Shape and data language
- Composition rules
- Fidelity tolerances

## Canvas and grid

- Slide size: `960 × 540 px` (`16:9`).
- Background: `#F1F5F9` on every slide.
- Canvas frame: transparent rectangle at `(0, 0, 960, 540)` with `1 px` solid `#797B7D` stroke.
- Standard side margins: `50 px`; usable width `860 px`.
- Title rail: left `50 px`, top `50–57 px`, height `42 px`.
- Primary content band: usually begins at `y = 154–198 px`.
- Alignment cadence: `10 px` micro-unit, `20 px` text gap, `~290 px` three-column pitch.
- Keep large empty zones. The source uses negative space as structure, not as room for extra copy.

## Color tokens

| Token | Hex | Use |
| --- | --- | --- |
| canvas | `#F1F5F9` | slide background |
| cobalt | `#364EF0` | titles, metrics, key labels, funding bar |
| indigo | `#3A3CB6` | filled solution cards, secondary emphasis |
| violet-mid | `#7A80D6` | chart segment |
| violet-light | `#B9C3F6` | chart segment |
| cobalt-soft | `#93A1F4` | secondary metric, fine rules |
| ink | `#333333` | strong body copy |
| graphite | `#606264` | subtitles and supporting copy |
| gray | `#797B7D` | canvas frame and neutral text |
| rule | `#A8ABAE` | fine card borders |
| timeline | `#DDE3EA` | baseline and quiet separators |
| paper | `#FFFFFF` | white panels and inverse text |

Use exact hex values. Do not introduce gradients. Use cobalt and indigo as flat fills.

## Typography

- Latin display: `Avenir Next`; fallback `Arial`.
- Korean: `Apple SD Gothic Neo`; fallback `Arial`.
- Cover wordmark: `52 px`, bold, cobalt, centered.
- Cover subtitle: `31–34 px`, regular, graphite, centered.
- Slide title: `31–32 px`, regular or bold according to the layout.
- Card or diagram label: `18–21 px`, bold.
- Body: `12.5–14 px`, regular, `1.12–1.2` line spacing.
- Roadmap title/body: `10 px` / `7.5–8 px`; this density is unique to the roadmap.
- Funding amount: `34–36 px`, bold, white.
- Major metric: `31–52 px`, bold.

Use separate text boxes for mixed regular/bold slide titles so the split remains stable. Use no text shadow, outline, or gradient. Keep line breaks intentional and inspect Korean wrapping at full size.

## Shape and data language

- Corners: square by default. Avoid rounded cards and pills.
- Strokes: `1 px` neutral borders; `2–4 px` cobalt emphasis; dashed or dotted only for funding partitions and market perimeter.
- Shadows: none.
- Cards: flat rectangles with either no fill and a gray border, or indigo fill with no border.
- Icon frames: `80 × 80 px` white circles with `1 px` neutral outline.
- Team frames: `100 × 100 px`; first may be square and the rest circular to match the reference rhythm.
- Connectors: black `2 px` lines with restrained arrowheads. Route behind nodes and labels.
- Charts: direct-labeled; no legend box, chart title, axes, grid, or decorative effects.
- Timeline: thin horizontal baseline, soft cobalt vertical stems, small cobalt nodes with white halo.

## Composition rules

- Use a single dominant horizontal or radial gesture per slide.
- Use one visual emphasis: cobalt bar, indigo card row, central pie, icon flow, or timeline. Do not combine several.
- Align text edges and object centers precisely; almost-symmetry is visibly wrong in this style.
- Keep labels close to the objects they describe. Do not use floating badges or UI chrome.
- Keep the palette sparse: canvas + cobalt + one of indigo/black/gray/white.
- Use photographs only for people or a product image explicitly supplied by the user. Crop team portraits consistently and never reuse source portraits.

## Fidelity tolerances

- Outer margin and title position: within `±4 px`.
- Repeated card widths and gaps: within `±3 px`.
- Baseline alignment of repeated labels: within `±2 px`.
- Color channels: exact hex values for core tokens.
- Title size: within `±1 px`; body size within `±0.5 px`.
- No one-line title may wrap.
- No body box may shrink below the layout's declared minimum size.
