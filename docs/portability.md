# Portability

## Supported V1 Environments

- macOS with Bash 3.2+, Python 3.9+, and Git 2.30+;
- mainstream Linux with Bash, Python 3.9+, and Git 2.30+;
- Windows through WSL.

Native PowerShell and `cmd.exe` are not supported in v1.

These requirements apply to standalone core. The optional parent adapter needs
Python 3.11+ for both its verifier and configured core subprocess. The independent
local runtime has its own macOS requirements and verification gate.

## Repository-Local Use

No installation is required:

```bash
./bin/plzdo doctor
./bin/plzdo version
./scripts/verify
```

The application wrappers select Python beside the launcher or from fixed system
locations, clear Python startup variables, and start with `-I -S -B`. The core
distribution has no default third-party dependency.

The default integrated gate uses Python 3.11+ for adapter and build-metadata
checks. `./scripts/verify --release-matrix` additionally requires an exact Python
3.9 core lane; exact-commit `--acceptance` always includes this matrix.
`./scripts/verify --core-python39` runs the compatibility lane alone. Every mode
records the selected executable and version. Release verification fails if no
Python 3.9 is found in the fixed supported locations.

## State Root

The state root is resolved in this order:

1. `PLZDO_HOME`;
2. `${XDG_STATE_HOME}/plzdo-local`;
3. `${HOME}/.local/state/plzdo-local`.

Run `./bin/plzdo state-root status --json` to inspect the resolved location. The source tree contains no compiled personal path.

## Upgrade

There is no auto-update. Use a reviewed checkout or the candidate distribution
in a virtual environment; see [packaging](core-adapter-packaging.md) for the
fixed installed layout and isolated launchers. PlzDo never edits shell startup
files itself. Durable documents are schema-versioned; unsupported schema changes
fail closed.
