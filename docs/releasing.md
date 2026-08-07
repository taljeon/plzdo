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

## Single-Maintainer Integration

For the owner-operated repository, keep CI without asking GitHub to create a merge commit:

1. finish the change on a feature branch and run the full local privacy and release gates;
2. push the feature branch and wait for its GitHub Actions checks;
3. advance local `main` with `git merge --ff-only <feature-branch>` and push `main`;
4. create and push an annotated tag using the configured GitHub noreply identity;
5. publish the GitHub release from that tag and verify a fresh clone.

Do not use GitHub-generated merge commits for this repository. When collaboration needs a pull request, use it for review and CI, then integrate the already-reviewed commit with a rebase or fast-forward path that preserves its noreply author identity.
