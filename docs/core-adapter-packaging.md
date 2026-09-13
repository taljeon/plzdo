# Core and parent adapter candidate

`plzdo==0.3.0` contains the provider-free `plzdo_local` core and the fixed,
read-only `plzdo_local_code_adapter`. It has no default runtime dependency.
The `local` extra requires exactly `plzdo-local-runtime==0.3.0`; installing that
extra does not make the core CLI import or dispatch the runtime. The runtime
distribution owns `plzdo-local-code`.

Standalone core supports Python 3.9+ on macOS/Linux. The optional parent adapter
requires Python 3.11+ for both its verifier and configured core subprocess.
The installed `plzdo` and `plzdo-local-code-adapter` commands are shell scripts, not Python console
entry points. They select an interpreter beside the launcher, then fixed system
locations, and start it with `-I -S -B` **before** application code. The loader
checks fixed source, prefix, and user-install locations under its own prefix,
requires one unambiguous package, and loads that package by its exact path.
It never adds the checkout or all of site-packages to `sys.path`.

Ordinary `python -m` is not an isolated entry and is refused. Checking flags or
re-executing from a console entry would be too late to prevent `.pth` and
site-customization startup. Library imports remain available to authorized
compositions. Editable installs and unsupported/custom installation layouts
are outside this launcher contract and fail instead of searching arbitrary
locations. A virtual environment is the straightforward candidate install.

## Resource and pin API

| Value | Source checkout | Installed distribution |
| --- | --- | --- |
| `coreRoot` | Checkout directory containing `VERSION` and `bin/plzdo_entry.py` | Exact `plzdo_local` package directory |
| Core package | `coreRoot/plzdo_local` | `coreRoot` |
| `repository_root()` compatibility API | Checkout root | `plzdo_local/_bundled` |
| Bundled resources | `schemas/`, `templates/`, `resources/`, `VERSION` | The same relative paths inside `_bundled/` |
| Verifier entry | `plzdo_local_code_adapter/verify_parent.py` | The same fixed package-owned file |

Setuptools stages the existing data into `_bundled` without moving or editing
source data. Both core and adapter import roots are exact package directories.
Adapter descriptors pin all executable core/adapter files and all bundled core
resources; source descriptors cover only their fixed directories, not the
monorepo or runtime. Roots and no-follow file identities are rechecked before
and after the bounded core reads. Pin bundles must be recreated explicitly
after code, resources, or installation paths change.

## Parent protocol

The v2 wire uses `plzdo.parent-request.v2`,
`plzdo.parent-scope-request.v2`, `plzdo.parent-verifier-input.v2`, and
`plzdo.parent-verifier.v2`; configuration is
`plzdo-parent-adapter.config.v2` with `coreVersion: 0.3.0`.
Markers are `plzdo-delegation:v2:` and `plzdo-scope-delegation:v2:` followed
by the canonical request hash. Old wire/configuration and mixed legacy markers
are rejected. Execution data is opaque canonical JSON: the concrete runtime
or private composition validates its meaning.

The adapter invokes only core version, state-root status, project show, and
formalization status. It does not approve, reserve, execute, or import a runtime.
`atomicLease` is false: the result is a fresh local-record snapshot, not a lease.

## Focused evidence

Run the component checks from the source checkout:

```sh
python3.9 -I -S -B tests/core_packaging_check.py --core-only
python3.12 -I -S -B tests/core_packaging_check.py --core-only
python3 -I -S -B tests/core_packaging_check.py
python3 -I -S -B tests/adapter_check.py
```

The last two commands require Python 3.11+. The core-only mode imports neither
adapter fixtures nor `tomllib`; it tests core launchers and resources with poisoned
optional modules. Actual Python 3.9 also checks that optional entry files refuse
the unsupported interpreter. Each mode prints its executable and version.

Default `./scripts/verify` uses the selected Python 3.11+ interpreter. The explicit
`--release-matrix` mode and exact-commit `--acceptance` additionally require the
Python 3.9 lane. A missing or failing 3.9 interpreter fails either release mode;
ordinary contributors do not need a second interpreter for the default gate.

The packaging check stages only core and adapter in a temporary virtual
environment, exercises their launchers and resources, and verifies a synthetic
approved parent. It also plants `.pth`, site-customization, and sibling-module
sentinels and confirms they do not run. This is focused installed-layout
evidence; final wheel/sdist builds and the installation matrix are separate
integration checks. Legacy `test_runtime_bridge.py` is historical compatibility
coverage, not evidence for the new concrete runtime contracts.

The static core gate includes core code, fixed bootstraps, adapter code, and the
core verification files. Its source-bound exceptions record exact file bytes,
import/API symbols, and subprocess purposes in `tests/contract_check.py`.
Changing those bytes or adding an unreviewed call fails the gate; mutation
fixtures check this. The independent runtime repository uses its own runtime
gate. Core verification requires no sibling runtime source. There is no blanket
documentation or test exemption, and repository-wide symlink and leak checks
still apply.

Core has no runtime namespace exemptions and no runtime-source dependency in
its leak scanner. The independent runtime repository owns its corresponding
scanner and exact protocol-file pins. Hostname and private-denylist checks remain
active; the core static audit pins its scanner implementation.

The existing compact `ponytail` skill is included among managed public resources.
Generated project guidance reuses its minimality rule without copying the whole
policy or setting a test-count target. Safety and required evidence remain intact.

The harness retains the repository's original MIT notice in `LICENSE`.
The local runtime and external integration projects are not included in this
harness source preview. Installable companion artifacts and their provenance
remain a separate release; this preview supplies no wheelhouse or live-model
execution certification.
