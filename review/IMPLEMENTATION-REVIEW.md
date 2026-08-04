# PlzDo Local 0.2.0 Implementation Review

## Evidence Boundary

- Review authority: advisory
- Source of truth: false
- Private denylist: external-only
- Provider sends: none in runtime
- Publication status: authorized release candidate
- External advisory review: PASS_WITH_NOTES, blocking issues 0

This record summarizes release evidence. Code, schemas, tests, and final public
Git objects remain authoritative for implementation facts.

## Release Scope

The candidate is a dependency-free, local-first control plane for macOS and
Linux with Python 3.9 or newer. It includes:

- deterministic catalog, registry, and execution routing;
- exact managed project-frame planning and validation;
- formalization, context, bounded state, checkpoint, and loop contracts;
- sanitized local memory, findings, and metrics;
- local review prepare/validate/import, manual monitoring, and repository
  preflight;
- repository-owned skills, agent role files, and static reference catalogs;
- a default-disabled, fixed-output P5 local apply path;
- privacy, release inventory, and bounded Git-history publication checks.

It excludes provider transports, credentials, browser automation, telemetry,
package downloads, hooks, daemons, schedules, auto-update, and Obsidian.

## Focused P5 Review

P5 focused review: PASS

The focused review verified the following against implementation and Phase 4
fixtures:

- default policy remains disabled;
- index gitlinks and submodules are refused before status;
- worktree, Git directory, common directory, and HEAD identities are rebound
  across authorization, execution, status, and rollback;
- interruption evidence is persisted before target mutation;
- created directories require run-bound path, device, and inode evidence before
  removal;
- local Git subprocesses are allowlisted, bounded, isolated, and cleaned up as
  process groups;
- the published schema is structural and runtime semantic validation is
  stricter;
- caller-supplied commands, output sets, and renderer bytes are rejected;
- incomplete rollback cannot be reported as complete.

Residual P5 limits are documented in `docs/real-apply.md`: same-user hostile
processes are outside the HMAC threat model, and an interruption before a newly
created directory is journaled may require manual cleanup while rollback stays
incomplete.

## Local Verification

Current pre-freeze evidence:

- integrated contract: PASS;
- Phase 1 smoke: 9 checks PASS;
- Phase 2 project control: 12 checks PASS;
- Phase 3 durable work: 13 checks PASS;
- Phase 4 P5: 13 checks PASS;
- Phase 5 managed resources: 13 checks PASS;
- local operations: 6 checks PASS;
- release integration: 12 checks PASS;
- leak scanner self-test: PASS;
- external private denylist scan with required-input mode: PASS.

The exact release bytes still require five integrated runs, manifest
verification, real-Git publication auditing, GitHub CI, and fresh-clone
verification. Those are release-procedure outcomes, not claims established by
this pre-publication document.

### Final Local Audit Closure

A final independent local audit initially stopped publication. It found one
stale generated cache/manifest snapshot and three durable release-path issues:
CI ran direct contracts inside checkout Git metadata, the integrated verifier
did not itself check `SHA256SUMS`, and project registry writes were described as
read-only. The cache was removed, CI now exports source before direct tests,
`scripts/verify` checks the frozen manifest before all suites, the command
reference names the registry writes, and the release contract binds all three
fixes. A disposable stale-manifest probe then changed one tracked document and
confirmed that `scripts/verify` failed before the test suites with exit 1.
The first real publication command then exposed a fourth integration defect:
isolated Python could not import the sibling leak scanner. The entry point now
binds its own script directory, and the release suite executes the real wrapper
under `-I` and requires the typed usage failure. Final evidence is generated
only after these changes.

## Privacy Review

The current gate detected no personal home path, real email address,
credential shape, provider session identifier, symlink, special file, binary
artifact, database, log, browser state, or private-denylist value. The private
denylist remains outside the release tree; only opaque finding IDs may be
emitted.

## External Review Integration

### Grok

- Transport: operator-owned Grok CLI, sanitized public candidate bundle only
- Bundle: 435,552 bytes
- Bundle SHA-256: `790a9d07b38560cad8d674218be30ec6cba1167ccd174dccb91894c6488f09bb`
- Runtime model observation: Grok 4.5 after the configured legacy alias fell
  back; no model pin is claimed
- Verdict: PASS_WITH_NOTES
- Blocking issues: 0

Grok reviewed the full public documentation, complete release/privacy scripts,
and critical control-plane, P5, schema, and test source. Its notes were accepted
as already-declared residual risk: heuristic leak detection, the same-user P5
threat-model ceiling, and the distinction between the normal CLI and the
separate apply entry point. No provider statement was promoted to source of
truth.

### ChatGPT Web

- Transport: managed in-app browser, sanitized summary only
- Prompt size: 7,159 characters
- Model observation: signed-out current ChatGPT web model; strict GPT Pro use
  was not available and is not claimed
- Verdict: PASS_WITH_NOTES
- Blocking issues: 0

ChatGPT found the architecture, authority separation, local-only wording, P5
model, and release procedure internally coherent. It explicitly limited its
answer to summary consistency and did not claim code verification. Its requested
documentation emphasis is present in `SECURITY.md`,
`docs/local-only-boundary.md`, and `docs/real-apply.md`: tested properties are
not formal proof, local-only is not an OS firewall, same-user hostility is out
of scope, and incomplete rollback may require manual cleanup.

### Integration Decision

- Accepted: keep threat-model and rollback limitations prominent; preserve the
  summary-versus-source review distinction.
- Rejected: none.
- Deferred: strict GPT Pro model verification. It is not a release gate because
  ChatGPT received only summary evidence, while implementation claims remain
  covered by local source/tests, a focused P5 reality check, and Grok's critical
  source bundle.

## Residual Risk

- Local-only behavior is not an operating-system firewall.
- A privileged process running as the same user can inspect local state.
- Secret detection is heuristic and cannot recognize every encoded or novel
  format.
- Manual movement of a prepared review bundle is an operator-owned egress
  event.
- P5 proves bounded authority, exact bytes, and recovery evidence, not semantic
  correctness of a requested change.
