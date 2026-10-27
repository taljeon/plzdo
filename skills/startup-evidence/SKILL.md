---
name: startup-evidence
description: Create evidence-grounded startup strategy and investor materials with claim provenance and an independent verification pass. Use for competitor deep dives, pricing and feature comparisons, battle cards, April Dunford-style positioning, investor IR, 30-day plans, or customer-interview validation. Do not use for generic business prose that needs no research or for live outreach, fundraising, publishing, or account actions.
---

# Startup Evidence

Produce decision-ready startup work without turning guesses into facts.

## Route the request

1. Identify only the requested deliverable modes:
   - competitor deep dive, price/feature comparison, or battle card: read [competitive-intelligence.md](references/competitive-intelligence.md)
   - positioning, 30-day validation plan, or customer interviews: read [positioning-validation.md](references/positioning-validation.md)
   - investor memo, IR deck, or fundraising narrative: read [investor-ir.md](references/investor-ir.md)
   - verification-only request: do not rewrite the artifact unless the user asks for corrections
2. Always read [independent-verification.md](references/independent-verification.md).
3. Establish the decision frame before research: decision, audience, company and product stage, geography, currency, comparison set, artifact format, and an explicit `as of` date. Infer only low-risk details and label them.
4. For claims that can change, research current primary sources. Prefer official pricing, product documentation, regulatory filings, customer-authored evidence, and first-party announcements. Use secondary sources only to locate or triangulate primary evidence.
5. Build one shared claim ledger and reuse it across every requested artifact. Do not run separate research passes that silently use different scopes or dates.
6. Draft the requested deliverable, then run the independent verification gate. One correction and recheck is the normal limit; further rounds require a bounded, approved Goal/UW loop.

## Keep a claim ledger

Give every decision-relevant claim a stable ID. Record:

| Field | Required meaning |
| --- | --- |
| `claim_id` | Stable identifier used by the deliverable and review report |
| `claim` | Atomic statement; split compound claims |
| `kind` | `observed_fact`, `inference`, `recommendation`, `estimate`, `forecast`, `target`, or `unknown` |
| `source` | Direct URL, local evidence path, or `not publicly available` |
| `observed_at` | Date the source was checked |
| `scope` | Plan, region, currency, segment, version, period, or other qualifier |
| `confidence` | `high`, `medium`, or `low`, with a short reason when not high |
| `status` | Latest verifier verdict |
| `supporting_claim_ids` | Required for an inference; IDs of the facts or prior inferences it depends on |
| `reasoning` | Required for an inference; concise explanation of how the supporting claims imply it |
| `decision_criterion` | Required for a recommendation; the named objective or threshold it optimizes |

Facts need evidence. Inferences need both supporting claim IDs and reasoning. Recommendations need the decision criterion they optimize. Estimates, forecasts, and targets must never be rendered as actual results. Preserve `unknown` instead of filling a gap with plausible prose.

## Apply the independent gate

- Separate producer and verifier contexts. Prefer a fresh read-only subagent that receives the frozen request, artifact, sources, ledger, formulas, and rubric—not the producer's intended verdict or suspected defects.
- If no independent context is available, report `self-check only`; do not call it independent review.
- Run deterministic checks before judgment: arithmetic, units, currency and billing normalization, repeated-number consistency, required fields, links, citations, and artifact parsing/rendering.
- Use project-native architecture or policy checks when the deliverable includes implementation claims. Add tools such as dependency-cruiser only when the target is appropriate, the tool is already governed or preflighted, and the user authorized any installation. AI agreement is not an architecture test.
- External AI review is optional and advisory. Route it through the governing external-review workflow; never treat invocation as permission to upload private material.
- A verifier may return `PASS`, `PASS_WITH_NOTES`, `FAIL`, or `BLOCKED`. Do not suppress disagreement or uncertainty to make the result look complete.

## Respect boundaries

- Never invent competitor prices or features, customer quotes, traction, market size, conversion, revenue, partnerships, or investor interest.
- Treat `contact sales`, missing plan details, roadmap items, beta features, and inferred capabilities as distinct states.
- Do not bypass authentication, scrape against access controls, upload private documents, contact customers or investors, publish, update a CRM, spend money, or make financial commitments without explicit authorization through a safe tool path.
- Forecasts and fundraising materials are decision support, not financial or legal advice. Surface material assumptions and recommend qualified review where stakes require it.
- Route `.docx` IR work through the document skill and presentation/Slides work through the presentation skill so the final artifact is rendered and visually checked.
- Store only sanitized, reusable decisions or workflow lessons in memory. Never store raw interviews, investor lists, private decks, credentials, or full source packets.

## Return a complete handoff

Return, in the user's requested language and format:

1. the requested deliverable;
2. a compact claim index or ledger link;
3. the independent verification report and independence status;
4. explicit gaps, contradictions, and stale evidence;
5. the `as of` date, checks run, and any skipped checks.
