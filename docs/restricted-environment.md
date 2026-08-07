# Restricted Environment Setup

PlzDo Local can be verified and used from a reviewed checkout with no package
download, hosted CI, external AI reviewer, MCP server, browser session, daemon,
or telemetry service. Git transport is separate: clone, fetch, push, and pull
requests are explicit operator actions and must use an approved remote.

## Requirements

- macOS or Linux;
- Python 3.9 or newer available as a system executable;
- Git 2.30 or newer;
- Bash 3.2 or newer;
- a reviewed PlzDo Local tag or commit obtained through an approved channel.

No Python virtual environment or third-party package installation is required.

## Verify The Checkout

From the reviewed checkout:

```bash
git status --short --branch
./scripts/release-manifest --check
./scripts/verify
./bin/plzdo doctor
./bin/plzdo state-root status --json
```

`./scripts/verify` exports a Git-metadata-free copy, uses temporary synthetic
state, and runs the complete local acceptance contract. It does not contact a
remote service.

## Choose Local State

Set an explicit state root when the default home location is not appropriate:

```bash
export PLZDO_HOME="$HOME/.local/state/plzdo-local"
./bin/plzdo state-root status --json
```

The selected directory contains PlzDo-owned local state. Do not place it inside
a shared repository or synchronize it to an unapproved service.

## Use Repository-Owned Skills And Agents

The release contains four reviewed skills and five reviewed agent role files.
Listing and installation read only repository bytes and the explicit local
destination.

```bash
./bin/plzdo skills list --json
./bin/plzdo agents list --json
./bin/plzdo skills install plzdo-project-harness --dry-run
./bin/plzdo agents install explorer --dry-run
```

After reviewing the dry-run, repeat the selected command without `--dry-run`.
Install only the resources needed for the current environment. Do not use
`--force` to replace an unmanaged file; resolve the ownership conflict first.

The source and design catalogs contain reference URLs as inert metadata. Local
catalog commands search checked-in JSON and do not fetch those URLs.

## Work With Pull Requests

1. create a branch from the reviewed base;
2. make a scoped change using local tools and repository-owned skills;
3. commit the candidate and run `./scripts/verify --acceptance <full-commit-sha>`;
4. push only to a remote approved for the code and open a pull request;
5. have a reviewer fetch that commit and rerun the same local gate;
6. verify the final integrated commit locally before release.

Remote status checks are optional downstream policy. They are not the PlzDo
local acceptance contract and cannot replace it.

## Boundary

PlzDo commands do not upload project content, call model providers, install
packages, or configure Git remotes. The surrounding coding agent may have its
own inference transport, and Git operations intentionally communicate with the
configured remote. Use operating-system and organizational controls when those
surfaces require stronger enforcement.
