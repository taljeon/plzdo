# Command Reference

Invoke the checked-in wrapper from this repository:

```bash
./bin/plzdo version
./bin/plzdo doctor
./bin/plzdo state-root status
./bin/plzdo --help
```

## Project Control

```bash
./bin/plzdo init <target> --id <project-id>
./bin/plzdo check <target>
./bin/plzdo catalog validate|list|show
./bin/plzdo project register|list|show|archive|resolve
./bin/plzdo route "<goal>" [--bounded-loop]
./bin/plzdo render --catalog <file> --dry-run
./bin/plzdo new "<goal>"
```

`init`, `new`, and `render --dry-run` plan target bytes without writing them.
`check`, catalog reads, project reads, `route`, and resolution are read-only.
`project register` and `project archive` update the local registry under the
resolved state root. `render --write` is intentionally unsupported.

Durable command output is written under the resolved state root: `PLZDO_HOME`, then
`XDG_STATE_HOME/plzdo-local`, then `~/.local/state/plzdo-local`. Use
`./bin/plzdo state-root status` to inspect the selected location.

## Durable Work

```bash
./bin/plzdo formalize draft "<goal>" --id <id> [--bounded-loop]
./bin/plzdo formalize approve <id>
./bin/plzdo formalize status [<id>]
./bin/plzdo formalize complete <id> --evidence <local-file>
./bin/plzdo formalize supersede <id> --reason "<reason>"
./bin/plzdo formalize list

./bin/plzdo context render --root <project> --mode compact|full
./bin/plzdo context check [pack] --root <project>
./bin/plzdo context status [--root <project>]

./bin/plzdo state status
./bin/plzdo state record --current "<text>" --next "<text>" --evidence "<text>"
./bin/plzdo state compact [--dry-run]
./bin/plzdo state checkpoint --operator-percent <0-100>
./bin/plzdo state checkpoint --used-tokens <n> --max-tokens <n>
./bin/plzdo state checkpoint --self-estimate <0-100>

./bin/plzdo loop plan --checkpoint <id> --formalization <id> --max-iterations <n> --timeout-seconds <n> --evidence "<text>"
./bin/plzdo loop step --checkpoint <id> --evidence "<text>"
./bin/plzdo loop stop --checkpoint <id> --reason <terminal> --evidence "<text>"
./bin/plzdo loop status --checkpoint <id>
```

## Evidence Stores

```bash
./bin/plzdo memory add --label "<label>" --domain <id> --summary "<summary>"
./bin/plzdo memory search "<query>"
./bin/plzdo memory status
./bin/plzdo memory export <safe-name>
./bin/plzdo memory purge --all|--stable-key <key>

./bin/plzdo findings add <id> --severity <level> --title "<title>" --evidence "<evidence>"
./bin/plzdo findings list [--all]
./bin/plzdo findings close|accept-risk <id> --resolution "<text>" --evidence "<evidence>"
./bin/plzdo findings check

./bin/plzdo metrics record --run-id <id> --route <quick|plan|goal> --status <status> --route-feedback <feedback> --duration-ms <n>
./bin/plzdo metrics summary
```

## Managed Resources

```bash
./bin/plzdo skills list
./bin/plzdo skills install <name> [--root <directory>] [--dry-run] [--force]
./bin/plzdo skills uninstall <name> [--root <directory>] [--dry-run]

./bin/plzdo agents list
./bin/plzdo agents install <name> [--root <directory>] [--dry-run] [--force]
./bin/plzdo agents uninstall <name> [--root <directory>] [--dry-run]

./bin/plzdo sources list|search|show
./bin/plzdo design list|search|show
```

Without `--root`, skill and agent destinations are `$CODEX_HOME/skills` and
`$CODEX_HOME/agents`; when `CODEX_HOME` is unset they are `~/.codex/skills` and
`~/.codex/agents`. Install `--force` repairs only marker-trusted, bounded drift.
Uninstall has no force mode and removes only bytes that still match the managed
snapshot.

Mutation transactions retain a no-follow descriptor for the validated
destination root. Staging, quarantine, publication, rollback, and cleanup are
descriptor-relative, and cleanup requires the lexical root to retain the same
device/inode identity. Agent descriptor and marker publication use atomic
no-replace file creation for each component.

The published managed-install JSON Schema is a structural check only. Marker
consumers must first apply that schema and then call
`plzdo_local.managed_install.validate_managed_install_marker` with the expected
resource type and destination name. The semantic validator enforces unique,
sorted paths, fixed agent descriptor names, destination identity, and the
inventory digest. The conformance corpus in `tests/phase5_check.py` exercises
structurally distinct duplicate paths and other semantic failures; JSON Schema
alone is not used to claim duplicate-path enforcement.

Static catalog entries expose `revisionKind` alongside `reviewedRevision`.
`verified-open` requires an exact commit or digest for Git-derived evidence, or
a fixed non-Git specification version. Tags do not establish `verified-open`.
Unversioned entries remain `review-required`; `HEAD`, branch names,
`refs/heads/*`, `refs/remotes/*`, and remote namespaces such as `origin/*` are
rejected.

## Local Review And Monitoring

```bash
./bin/plzdo review prepare --manifest <file> --root <project> --output <bundle-id>
./bin/plzdo review validate <bundle-file>
./bin/plzdo review import --bundle <bundle-file> --response <response-file>
./bin/plzdo monitor snapshot --project <project-id>
./bin/plzdo repo-preflight [path]
```

Review prepare writes `<bundle-id>.json` beneath the resolved state root. The
project root and source list are always explicit. `repo-preflight` defaults to the
current directory; monitor snapshot requires a registered project.

Use `--json` on any command that exposes it for machine-readable output. No command in this section calls a network provider, installs a package, schedules work, or executes project code.

The separate default-disabled P5 entry point is documented only in
[real-apply.md](real-apply.md). It is foreground-only, fixed-output, and outside
the normal `./bin/plzdo` command surface.
