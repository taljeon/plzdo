# Independent Verification Contract

Every startup deliverable receives a separate verification artifact. Verification is read-only unless the user explicitly asks the verifier to make corrections.

## Create a neutral handoff bundle

Give the verifier:

- frozen request, audience, scope, and `as of` date;
- complete draft or artifact;
- claim ledger and primary source set;
- formulas and normalized source tables;
- required output schema and rubric;
- known tool limits and any side effects already taken.

Do not give the producer's desired verdict, defense, or suspected defects. Record whether the verifier is a fresh context, a different model/provider, or the producer performing a self-check. Context separation and model diversity are different properties; claim only what the receipt proves.

## Verify claims and freshness

For each material claim, return one verdict:

- `supported` — source directly supports the scoped claim;
- `partially_supported` — only part of the claim or scope is supported;
- `unsupported` — no sufficient evidence was supplied or found;
- `stale` — evidence is too old for the claim's volatility;
- `contradicted` — credible evidence conflicts with the claim;
- `unverifiable` — access, data, or method prevents a reliable check;
- `not_applicable` — no evidence claim is being made.

Reopen or independently inspect a risk-based sample of primary sources. Check source identity, date, plan/version, geography, and whether the source proves the statement rather than merely mentioning the topic. Never upgrade an inference to fact because multiple AI reviewers agree.

## Run deterministic checks first

Select applicable checks and preserve their output or a compact evidence record:

- table and required-field completeness;
- arithmetic, percentages, totals, growth, runway, and formulas;
- currency, tax, billing period, seat, usage, allowance, minimum, and overage normalization;
- duplicate or contradictory metrics across files;
- URLs, source dates, citation-to-claim mapping, and artifact parsing;
- document/slide render, overflow, clipping, contrast, and editable-source inspection;
- project-native tests, schemas, or architecture rules for implementation claims.

Dependency-cruiser is one optional JavaScript/TypeScript boundary checker, not a universal default. Use it only after repository preflight and authorization for any installation; prefer an already governed project check. AI review does not replace executable architecture constraints.

## Review decision quality

Look specifically for:

- a biased or incomplete comparison set;
- apples-to-oranges pricing or feature states;
- fear, uncertainty, doubt, cherry-picking, or unsupported superlatives;
- a feature-to-value leap without evidence;
- actuals mixed with estimates, forecasts, or targets;
- a 30-day plan with activity but no threshold or stop condition;
- leading interviews, hypothetical promises, or quotes treated as prevalence;
- contradictions between the narrative, tables, appendix, and ask;
- unsafe outreach, publishing, data handling, or financial authority.

## Return the verification artifact

Use this structure:

```markdown
# Verification Report
Overall: PASS | PASS_WITH_NOTES | FAIL | BLOCKED
Independence: <fresh context / different provider / self-check only, with receipt>
As of: YYYY-MM-DD

| Finding | Severity | Claim IDs | Verdict | Evidence | Required correction |
| --- | --- | --- | --- | --- | --- |

Deterministic checks: <commands or methods and results>
Residual uncertainty: <material unknowns>
Skipped checks: <check and reason>
```

- `PASS`: no material unsupported claim and all required checks passed.
- `PASS_WITH_NOTES`: only non-material caveats remain.
- `FAIL`: a material claim, calculation, scope, or safety rule failed.
- `BLOCKED`: required evidence or access was unavailable; this is not a pass.

The producer may correct once and return a change-only bundle for recheck. The verifier rechecks affected claims plus cross-artifact consistency. If material failure remains, stop and report it; further repair loops require a bounded Goal/UW plan with evidence and stopping conditions.
