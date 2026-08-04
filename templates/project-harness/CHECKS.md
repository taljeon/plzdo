<!-- BEGIN PLZDO-LOCAL:project-frame.checks.v1 -->
# Project Checks

## Frame Check

- Run `scripts/verify` to verify that the six project-frame control files exist as regular, non-symlink files with their expected managed markers.
- Rendering the same project inputs twice must produce byte-identical managed content.
- Dry-run must leave the target tree unchanged.

## Project Checks

Add deterministic project-specific commands here before implementation relies on them. Checks must run locally, avoid credentials and network access by default, and use fixtures or temporary state instead of production data.

## Completion Evidence

Record each command, exit status, relevant output summary, skipped checks, and residual risk in the completion report. A missing required check is incomplete work, not a passing result.
<!-- END PLZDO-LOCAL:project-frame.checks.v1 -->
