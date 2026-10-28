# Updating

PlzDo has no installer or automatic updater. The company keeps its own copies, and the owner maintains the exported source. Update each copied item deliberately so local changes survive.

## Company copies

Record the release tag you applied and which items you copied or skipped. Keep the old release available for comparison. For mods, also retain the pin from that release's `mods.lock`.

When updating:

1. Read every [CHANGELOG](../CHANGELOG.md) entry after your recorded tag. Note additions, changes, removals, and any renamed paths.
2. Obtain the new release separately from your active Claude configuration. Read its [INVENTORY](../INVENTORY.md) for status, company eligibility, license, and dependency changes.
3. For each changed path you use, compare three versions: the old release, the new release, and your local copy. The old-to-new diff shows upstream changes; the old-to-local diff shows your changes.
4. Merge by hand. Never overwrite a locally changed file without diffing it. Resolve conflicting edits explicitly; inspect a renamed or removed item before changing or deleting the local copy.
5. Merge rule and settings changes into your existing files. Preserve unrelated settings and hooks, obtain approval for `settings.json` changes, and update hook placeholders if the clone location changes.
6. For a changed mods pin, read the mods README and the data-flow warning in Company set step 6 again. Check the pinned checkout with the new release's `mods.sha256` before loading it.
7. Start a new Claude Code session, check that the intended skills and agents are listed, and verify the workflows and enabled hooks you rely on. Record the new tag only for the items actually updated; note any items left on the previous version.

Keep skill references, provenance, and upstream license files with their skill. A `copy-ready` status does not make every item part of the company set, and the repository's MIT license does not replace third-party licenses.

## Moving from 0.x

The 0.x releases were PlzDo Local. Version 1.0.0 replaces that content with a copy-based Claude Code kit, including removal of the old installer and Codex adapter. Treat the move as selecting and merging the new company set, not as running the old installer over the new tree. Preserve and compare any rules or settings you customized.

## Owner export workflow

From the repository root, the owner uses:

```sh
python3 maintainer/export.py check
python3 maintainer/export.py export
python3 maintainer/export.py inventory
```

`check` lists changed sources. `export` re-copies the selected sources and sanitizes them. It stops before writing anything when a private identifier appears in an output file or folder name, and it writes no new lock when any check fails. Repository fixes to a copied source live under `maintainer/patches/<name>/` and are applied on every export through the entry's `add` map; the matching `SOURCE.md` marks the folder as modified. `inventory` regenerates the inventory tables. The source list, statuses, company flags, origins, licenses, and adaptation notes live in the owner's export config outside the repository (`$PLZDO_EXPORT_CONFIG`, default `~/.config/plzdo/export.json`), because it names the owner's private source folders. The private identifier list sits next to it. INVENTORY.md is the public view of that config.

Review the resulting diff, provenance files, and any changed documentation. Add a changelog entry naming the affected paths or file groups, then run the leak scan and required release preflight. The owner pushes after review. Company users do not need to run these maintainer tools.
