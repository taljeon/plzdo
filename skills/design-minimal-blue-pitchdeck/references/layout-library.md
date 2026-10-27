# Nine-Layout Library

Select the smallest set of layouts that supports the narrative. Coordinates use the `960 × 540` canvas from `design-spec.md`.

## L01 — Centered cover

- Use for: deck opening.
- Composition: centered wordmark/title at `(330, 209, 300, 68)`; centered one-line subtitle at `(280, 294, 400, 50)`; presenter block at lower left `(50, 438)`.
- Budget: one short brand/project name, one subtitle line, presenter label and name.
- Preserve: severe simplicity and the off-axis presenter block.

## L02 — Three outlined problem cards

- Use for: three parallel problems, risks, or unmet needs.
- Title: split regular/bold, `Our` + `Problems` pattern.
- Cards: `(50,197,279,98)`, `(340,197,279,98)`, `(630,197,280,98)`.
- Budget per card: header up to 18 Korean characters; body up to roughly 55 Korean characters over three lines.
- Preserve: outlined surfaces, compact vertical density, wide empty area below.

## L03 — Three filled solution cards

- Use for: three solution pillars, features, or product promises.
- Cards: `(50,198,279,128)`, `(340,198,279,128)`, `(630,198,280,128)`.
- Fill: indigo; text: white.
- Budget per card: one-line header and up to four body lines.
- Preserve: same grid as L02 with stronger mass and taller cards.

## L04 — Product flow with three outcomes

- Use for: one input → one core action → three outputs.
- Nodes: left and center circles at `y = 213`; three output circles near `y = 41`, `213`, and `388`.
- Connect: left to center, then center to each output. Keep connectors behind circles.
- Budget: two short stage labels and three short outcome labels.
- Preserve: large white space and asymmetric branch to the right.

## L05 — Free-to-paid business model

- Use for: free-to-paid, current-to-future, or tier comparison.
- Composition: large left keyword, thin arrow at center, cobalt circle with currency mark on right.
- Supporting copy: two centered blocks beneath the main symbols.
- Budget: one dominant word or short metric per side; one subheading and two body lines per side.
- Preserve: symbol scale and horizontal transition; do not turn it into pricing cards.

## L06 — Direct-labeled market pie

- Use for: three adjacent market segments or a simple share breakdown.
- Chart: centered pie near `(342,157,276,276)` with dotted cobalt perimeter `(313,127,334,334)`.
- Labels: one left, one upper-right, one inside the dominant lower segment.
- Budget: exactly three segments, each with one metric and one descriptor.
- Preserve: no legend or axes; use violet-light, violet-mid, and indigo segments.

## L07 — Funding amount and proportional allocation

- Use for: investment ask, annual budget, or resource allocation.
- Top bar: `(50,159,860,79)`, cobalt, centered amount.
- Allocation row: `(50,247,860,106)`, white fill, dashed cobalt borders, widths proportional to the declared percentages.
- Labels: percentage centered in each partition; category and note beneath.
- Budget: three categories totaling 100%, one short note each.
- Preserve: the top amount reads first; allocation follows as one continuous strip.

## L08 — Five-person team row

- Use for: three to five key people.
- Frames: five `100 × 100 px` portraits or placeholders centered across the top content band.
- Labels: name beneath, then role in indigo. Add one short team capability sentence in the lower-left area.
- Budget: five people maximum; role should remain one line.
- Preserve: consistent crop/scale and calm spacing. Never use the source portraits or names.

## L09 — Alternating roadmap timeline

- Use for: seven to nine chronological milestones.
- Baseline: horizontal at approximately `y = 316`.
- Nodes: evenly spaced; milestone cards alternate above and below the line.
- Budget per milestone: compact date, short heading, one or two micro-copy lines.
- Preserve: alternating rhythm and one continuous chronology. Use only this layout at its intentionally small text scale.

## Adaptation limits

- Two items: adapt L02/L03 with two equal columns centered in the `860 px` frame.
- Four items: use two rows only if the user accepts a denser derivative; otherwise split across two slides.
- More than five team members: create a second L08 slide.
- More than nine roadmap milestones: split by phase or year instead of reducing type.
- Non-pie market data: retain L06's central direct-label composition with one simple native chart; do not add a dashboard legend.
