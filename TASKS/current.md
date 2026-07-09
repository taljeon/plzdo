# Current Task

## Goal

Adapt this template to a target project while preserving local safety boundaries.

## Constraints

- No secrets, private logs, live databases, browser profiles, or full private documents.
- No default provider calls.
- No target mutation outside an explicit apply path.
- Memory and external reviews are evidence only, not source of truth.

## Done Criteria

- Project-specific `AGENTS.md` is updated.
- Project-specific checks are documented in `CHECKS.md`.
- Required docs exist.
- `./scripts/verify` passes.
- Residual risk is recorded.

## Checks

```bash
./scripts/verify
```

## Residual Risk

- Fill this in before claiming completion.
