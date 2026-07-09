# Case Study

PlzDo is extracted from an internal control-plane workflow that was hardened through repeated cold reviews.

The private predecessor started as a useful but overgrown local harness. Review rounds focused on one question: which agent behaviors were actually governed by code, tests, and explicit evidence, and which were merely policy prose?

The useful public lessons were:

- keep source-of-truth order short and visible;
- treat memory and external reviewers as evidence, not authority;
- require bounded long-running work to carry stop conditions;
- keep default checks local and credential-free;
- make release hygiene runnable, not just documented;
- avoid scheduled automation for irreversible writes or external provider sends;
- prefer explicit operator-reviewed apply paths over agent self-approval.

Private paths, local automation details, vault state, provider transcripts, and project-specific reports are intentionally not included here.

## Public Result

This repository keeps only the portable pieces:

- `AGENTS.md` for agent operating rules;
- `CHECKS.md` for release and verification expectations;
- `scripts/verify` as the default local gate;
- `scripts/check-release-leaks` as a conservative public-release scanner;
- `scripts/plzdo` as a minimal project bootstrap/check tool;
- optional Codex-compatible skills that preserve advisory-only boundaries.

This is not a benchmark claim. It is a reproducible template for adding agent governance to a repository without installing a runtime service.
