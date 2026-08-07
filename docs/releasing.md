# Releasing PlzDo Local

This document is for maintainers preparing a public release. Contributors normally need only the integrated gate in `CHECKS.md`.

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
- a fresh clone that passes the integrated gate and checksum verification;
- explicit operator authorization to publish.

Record commit, tag, CI, and GitHub release facts in Git/GitHub. Do not put future release claims into `TASKS/current.md`.
