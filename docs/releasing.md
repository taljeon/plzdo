# Releasing PlzDo Local

This document is for maintainers preparing a public release. Contributors normally need only the integrated gate in `CHECKS.md`.

For an explicitly requested harness-only source preview, publish the reviewed
core source after its exact-commit local gate and privacy/history audit. Label
the GitHub release as a prerelease and source-only. The complete distribution
procedure below, including five repeated gates and installation validation,
applies when certifying installable release artifacts. A source preview does
not certify local-model execution, OS isolation, or deferred companion packages.

## Privacy Gate

Keep the private denylist outside the repository and never print or commit its values:

```bash
release_tmp="$(mktemp -d "${TMPDIR:-/tmp}/plzdo-release.XXXXXX")"
export_root="$release_tmp/plzdo-export"
python3 -B -I scripts/export_worktree.py . "$export_root"
./scripts/check-release-leaks \
  --root "$export_root" \
  --private-denylist /absolute/path/to/private-denylist.json \
  --require-private-denylist
```

The export removes Git metadata before the content scan. The scanner rejects sensitive paths, secret shapes, real email domains, personal paths, provider session identifiers, private repository URLs, binary or oversized artifacts, symlinks, and private denylist values. Evidence contains opaque denylist IDs only.

## Freeze Exact Bytes

After the final file inventory is frozen:

```bash
./scripts/release-manifest --write
./scripts/release-manifest --check
./scripts/check-publication \
  --private-denylist /absolute/path/to/private-denylist.json
```

Any content change after manifest generation invalidates the manifest and all repeated-run evidence.

## Publication Requirements

- the pinned existing public root commit and no side history reachable from local refs;
- a clean worktree and stable HEAD/ref snapshot throughout the audit;
- noreply author, committer, and annotated-tag identities;
- bounded scans of HEAD history, local refs, annotated tags, tree paths, and unique blobs;
- no symlink, gitlink, special file, nested Git metadata, generated cache, or manifest omission;
- five complete integrated-gate runs on the final bytes;
- local core compatibility runs with Python 3.9 and 3.12, recording both versions;
- a Python 3.11+ release/build harness and optional adapter checks; `./scripts/verify --release-matrix` must also run the mandatory core-only Python 3.9 lane, without replacing a failing 3.9 interpreter with a newer one;
- a fresh clone that passes the integrated gate and checksum verification;
- explicit operator authorization to publish.

Record commit, tag, and release facts in Git and the approved publication host.
Do not put future release claims into `TASKS/current.md`.

The core runtime minimum and the maintainer tool minimum are separate. A normal
core installation remains dependency-free on Python 3.9+. The optional adapter
requires Python 3.11+ for its own interpreter and configured core subprocess.
The ordinary `./scripts/verify` gate uses its selected Python 3.11+ interpreter
without requiring an additional Python 3.9 installation. Maintainers use
`--release-matrix` for the required compatibility matrix; exact-commit
`--acceptance` automatically includes that matrix and retains it through the
Git-free export. Preserve failed-interpreter evidence rather than substituting
a different version.
Local runtime source lives in its independently versioned repository; a core-only
checkout must not require that sibling checkout to pass its own gate. Run the
runtime repository's source-bound privacy scanner for its schema namespaces and
its own verification instructions for that package. Neither package's successful
scanner run proves the other repository or a built archive was reviewed.

## Local Acceptance And Pull Requests

The checked-in local gate is authoritative. PlzDo Local does not bundle or
require hosted CI, external AI review, remote validation services, or package
downloads. A remote Git host is a collaboration and publication surface, not a
verification dependency.

For an owner-maintained change:

1. finish and commit the change on a feature branch and run `./scripts/verify --acceptance <full-commit-sha>` plus the privacy and release gates;
2. advance local `main` with `git merge --ff-only <feature-branch>`;
3. rerun acceptance on `main`, then push the exact verified commit;
4. create and push an annotated tag using the configured noreply identity;
5. publish the release from that tag and verify a fresh clone.

For a contributed pull request:

1. the author records the exact branch commit, platform, Python version, and local acceptance result in the pull request;
2. a reviewer fetches that exact commit, inspects the diff, and reruns the local gate;
3. integrate with fast-forward when possible, or use the repository's approved merge method;
4. if integration changes the commit or tree, fetch and locally verify the final result with `--acceptance` before tagging;
5. preserve author and committer privacy with noreply identities and rerun the publication audit.

Only push code to a remote approved for that code. Downstream organizations may
add their own internal checks, but those checks do not weaken or replace the
local acceptance contract.
