# Changelog

## Unreleased

### Security

- `skills/media-use`: recipe freeze now rejects an invalid stored `version` before changing any file, never deletes an existing archive, and refuses a recipe folder that is a symbolic link. The fix lives in `maintainer/patches/media-use/` so exports keep it.
- `checks/scan.py`: a release pass skips only history that each push URL reports having (`git ls-remote`), not history known from local remote-tracking refs.
- `hooks/release-gate.py`: private URL prefixes are compared by scheme, host, port and path segments, so a user name before `@` can no longer pose as a private host.
- `hooks/release-gate.py` and `checks/scan.py`: an effective `push.followTags=true` is refused, since it would send tags the pass did not scan.
- `maintainer/export.py`: private identifiers in output file and folder names stop the export before anything is written.
- Mods pinned to a new `plzdo-claude-mods` commit with workbench's safe git reads, symlink-aware blast-radius file checks, and approvals bound to the fully shown held command.

## 1.0.0 (unreleased)

### Added

- A `skills/` mirror with per-folder `SOURCE.md` provenance and upstream license files, plus inventory statuses, origins, dependency notes, and company-set eligibility.
- Claude-only `review-change` and `implement-change` skills and adapted agent roles in `agents/`.
- `maintainer/export.py`, the owner's export tool (its config and private identifier list stay outside the repository), for checking changed sources, re-copying sanitized files, and regenerating inventory tables.
- A separate mods dependency from `taljeon/plzdo-claude-mods`, with 8 mods pinned through `mods.lock`, integrity data in `mods.sha256`, and data-flow guidance.
- English guides for copying the kit, request flow, hook setup, and manual three-way updates in `README.md` and `docs/`.

### Changed

- Replaced the 0.x PlzDo Local content with a copy-based mirror of the owner's Claude Code setup, using top-level `skills/`, `agents/`, `hooks/`, `harness/`, `settings/`, and `maintainer/` directories.
- Folded shared rules into `harness/CLAUDE.md`, with Claude delegation and a document-based `hn` method that needs no private harness runtime.
- Replaced `skill-nudge` with `workflow-skill-gate`: a prompt nudge plus a gate before the first code edit. Kept the adapted public `release-gate` for checkable canonical publishing forms, in its own settings file outside the company set.
- Made hook and permission settings manual merges, with hooks optional where scripts are forbidden.
- Scoped repository MIT licensing to the owner's files; retained upstream licenses, isolated `attention-span` under AGPL-3.0, and made `academic-research-suite` link-only under CC BY-NC-4.0.

### Removed

- The 0.x installer and its managed setup flow.
- The Codex adapter, Codex delegation integration, and `codex-worker` agent.
- The owner's private memory runtime, private project configuration, and proprietary Anthropic synced skills from the distributed kit.
