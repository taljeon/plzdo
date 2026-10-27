---
name: taste-guided-ui
description: Improve frontend visual direction, typography, spacing, and composition while preserving the user's specified content and behavior. Use when the user asks for Taste Skill, less generic AI-generated UI, or a visual refinement of a landing page, portfolio, or existing interface. Also use when building the look of a new page or component, before writing any styles. For design-source discovery use design-source-router; ordinary bug fixes do not require this skill.
---

# Taste-guided UI

Apply deliberate visual choices to the requested screen. This is locally authored guidance inspired by selected Taste ideas, not the upstream bundle.

## Establish the brief

Read the relevant project instructions, existing components and tokens, and any supplied reference. Identify the screen's audience, primary action, and information priority. Reuse an existing DESIGN.md when present; do not create a new design system for a small styling task.

Distinguish what the user fixed from what remains open. Preserve specified copy, labels, brand assets, image slots, required sections, data, routes, and behavior. Do not replace a requested screenshot with illustrative cards, invent a brand, or remove content to make a composition easier. An explicit redesign may change the requested visual structure while retaining the product's functional requirements.

For a broad design task, state a short direction before implementation. For a narrow refinement, use the existing direction without a new approval ceremony. Ask only when a material product choice cannot be inferred.

## Choose the visual treatment

Consider three independent choices:

- Composition: familiar and ordered, or more exploratory. A simple grid may be the right answer; asymmetry is not an automatic improvement.
- Motion: choose movement that communicates state or relationships. Keep keyboard access and reduced-motion behavior intact. Static presentation is a valid choice.
- Density: fit the task. Give a marketing message room; retain useful rows, filters, and scanning patterns in an operational screen.

If the user requests Taste-style numbers, express these as 1–10 preferences, not measured quality scores or mandatory defaults. Choose one coherent direction; do not accumulate conflicting style skills.

Use type scale, line length, grouping, spacing, and a restrained accent to establish hierarchy. Question repeated decorative cards, oversized empty areas, and gradients when they obscure the message. Keep any of those patterns when the reference or product purpose supports them. Prefer the project's existing fonts, icons, components, and styling tools. Do not add an animation framework or fetch remote assets merely to apply this guidance.

Default avoid list, unless the user, the brief or a supplied reference asks for it: purple-to-blue gradients, grids of identical icon-title-text cards, centering everything, a shadow on every element, emoji as bullets, filler copy ("elevate", "unlock", "seamless", "supercharge"), and fake testimonials or ratings. Pick one direction, two typefaces at most, one dominant color and one accent.

## Implement within the requested scope

Follow the project's existing coding workflow. Source selection can use design-source-router when needed; it does not need to run on every styling task. If the deliverable is a raster concept, use the available image-generation workflow. A concept image does not count as a functioning interface.

For existing screens, improve the identified visual weakness without rebuilding unrelated components, changing API contracts, or replacing functioning interactions. In a dense application, refine alignment and hierarchy before changing information architecture.

## Verify the rendered result

Use the project's appropriate preview and checks. Inspect the changed screen at useful desktop and narrow widths, including text wrapping and overflow. Check affected focus, keyboard, disabled, empty, or error states when the change touches them. Judge the actual render against the brief and supplied reference, not just the source code.

Report what improved, which requirements were preserved, and what was actually verified. If no rendered preview was available, state that limit. Stop when the requested refinement is met; an optional aesthetic preference is not a reason for an open-ended redesign loop.

For provenance or upstream maintenance decisions, read [references/source-notes.md](references/source-notes.md).
