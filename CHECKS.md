# PlzDo Local Checks

## Integrated Gate

Run:

```bash
./scripts/verify
```

The gate must pass from a checked-out Git tree and from its sanitized exported worktree. It must not require credentials, a network provider, browser state, target project execution, a package download, hook, daemon, scheduler, or production data.

Before running any suite, the integrated gate verifies the current
`SHA256SUMS`; a stale or incomplete manifest is a hard failure.

The gate runs these executable contracts:

1. `tests/contract_check.py`: required files, executable bits, version parity, runtime AST restrictions, shell restrictions, and named test binding.
2. `tests/smoke_check.py`: base CLI, path containment, atomic writes, startup isolation, and scanner execution.
3. `tests/phase2_check.py`: catalog, registry, routing, deterministic project-frame planning, marker safety, and target-write refusal.
4. `tests/phase3_check.py`: formalization, context, state, checkpoint provenance, bounded loops, memory, findings, metrics, and exact schema/runtime conformance cases.
5. `tests/phase4_check.py`: default-disabled P5 planning, authorization, execution, interruption, drift, verification, rollback, Git identity, process cleanup, and structural/semantic conformance.
6. `tests/phase5_check.py`: managed skills and agents, descriptor-relative containment, atomic no-replace publication, drift handling, static catalog policy, and dependency-free auditing.
7. `tests/local_ops_check.py`: sanitized local review bundles, advisory import, read-only monitoring, and repository preflight.
8. `tests/release_check.py`: exact Git-object fixture audits, Git environment isolation, isolated publication-wrapper startup, metadata and ref scanning, manifest refusal cases, scanner coverage, and absence of the optional prefix installer.
9. `scripts/check-release-leaks --self-test`: fail-closed synthetic privacy and credential cases.

## Core Invariants

- Project resolution is exact and ambiguous matches stop.
- Goal and bounded-loop work require approved formalization.
- Context is rendered from one fixed local allowlist and stale packs fail.
- State compaction archives first and preserves newest evidence plus current/next fields.
- Checkpoint provenance distinguishes operator input, token counts, and self-estimates.
- Memory, metrics, review output, and delegated work remain non-source-of-truth.
- Review preparation sanitizes before persistence and never sends a provider request.
- Monitoring is manual and read-only.
- Managed resource install/uninstall remains inside a bound destination root.
- P5 accepts only the fixed managed frame and an operator-enabled exact plan; it is not an arbitrary command runner.

## Privacy Gate

Run a public-tree scan with a private denylist stored outside the repository:

```bash
./scripts/check-release-leaks \
  --root . \
  --private-denylist /absolute/path/to/private-denylist.json \
  --require-private-denylist
```

The scanner rejects sensitive paths, secret shapes, real email domains, personal paths, provider session identifiers, private repository URLs, binary or oversized artifacts, symlinks, and private denylist values. It reports only opaque denylist IDs, never the private values.

## Release Gate

After the final file inventory is frozen:

```bash
./scripts/release-manifest --write
./scripts/release-manifest --check
./scripts/check-publication \
  --private-denylist /absolute/path/to/private-denylist.json
```

Publication requires:

- the pinned existing public root commit and no side history reachable from local refs;
- a clean worktree and stable HEAD/ref snapshot throughout the audit;
- noreply author, committer, and annotated-tag identities;
- bounded scans of HEAD history, local refs, annotated tags, tree paths, and unique blobs;
- no symlink, gitlink, special file, nested Git metadata, generated cache, or manifest omission;
- five complete integrated-gate runs on the final bytes;
- a fresh clone that passes the integrated gate and checksum verification;
- explicit operator authorization to publish.

Any content change after manifest generation invalidates the manifest and the five-run evidence.
