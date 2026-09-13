# Changelog

## 0.3.0

Harness source preview. Local-model runtime and external AI integration publication are deferred.

- Preserve valid approval reuse and early deterministic apply-gate denials.
- Bind new P5 writes to the complete approved repository profile while preserving legacy status and rollback.
- Preserve standalone core Python 3.9+ support; the optional adapter and release harness require Python 3.11+.
- Package core and the fixed parent adapter together, with an optional exact-version local runtime.
- Keep core-only installation provider-free and carry the compact Ponytail minimality guidance.
- Provide the fixed read-only parent adapter without model/provider dispatch in core.
- Distinguish source verification from local-model execution and OS-isolation validation.

## 0.2.2

- Make the checked-in local gate authoritative for changes and releases.
- Remove the bundled hosted-CI workflow and remote status-check dependency.
- Add restricted-environment setup guidance using only repository-owned skills and agents.
- Add an evidence-oriented pull-request template and reviewer-local verification flow.
- Keep Git remotes as explicit operator-owned collaboration surfaces rather than runtime dependencies.
- Fix first-time managed agent installation and create missing local roots with no-follow descriptor traversal.
- Bind acceptance evidence to a clean exact commit and reject staged, unstaged, untracked, or mismatched states.

## 0.2.1

- Pin GitHub Actions to immutable commit SHAs.
- Separate contributor checks from maintainer-only privacy and release procedures.
- Scan a Git-free export with an external private denylist before publication.
- Keep release state in `VERSION`, Git, and GitHub instead of `TASKS/current.md`.
- Make generated requirements and technical-design files product-specific while retaining safety policy in `AGENTS.md`.
- Add executable template/example parity and release-document separation checks.

## 0.2.0

- First full local release of the PlzDo control plane.
- Deterministic project routing, formalization, context, bounded state, local memory, findings, metrics, and manual monitoring.
- Repository-owned public skills and agent role files, local review preparation/import, monitoring, static reference catalogs, and repository-local runtime use.
- Default-disabled real-apply workflow with exact planning, confirmation, backup, verification, and rollback evidence.
- Bounded Git-object publication auditing plus integrated privacy, portability, contract, negative-test, and release gates.

## 0.1.0

- Initial public policy kernel, project template, and local verification preview.
