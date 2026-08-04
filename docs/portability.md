# Portability

## Supported V1 Environments

- macOS with Bash 3.2+, Python 3.9+, and Git 2.30+;
- mainstream Linux with Bash, Python 3.9+, and Git 2.30+;
- Windows through WSL.

Native PowerShell and `cmd.exe` are not supported in v1.

## Repository-Local Use

No installation is required:

```bash
./bin/plzdo doctor
./bin/plzdo version
./scripts/verify
```

The wrappers select a Python interpreter only from fixed system locations, clear Python startup variables, and use isolated mode. PlzDo Local has no third-party runtime dependency.

## State Root

The state root is resolved in this order:

1. `PLZDO_HOME`;
2. `${XDG_STATE_HOME}/plzdo-local`;
3. `${HOME}/.local/state/plzdo-local`.

Run `./bin/plzdo state-root status --json` to inspect the resolved location. The source tree contains no compiled personal path.

## Upgrade

There is no prefix installer and no auto-update. Clone or update a checkout, inspect the exact revision, run its verification gate, and use `./bin/plzdo` from that checkout. PlzDo Local never edits shell startup files or a global executable directory. Durable documents are schema-versioned; unsupported schema changes fail closed.
