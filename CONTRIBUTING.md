# Contributing

PlzDo Local accepts focused changes that preserve its local-first boundary and keep evidence proportional to risk.

## Before Editing

1. Read `AGENTS.md`, `CHECKS.md`, and the relevant document under `docs/`.
2. Keep the change scoped. Do not add network transports, telemetry, background services, hooks, package downloads, or provider credentials.
3. Use synthetic fixtures. Never commit personal paths, real email addresses, client names, tokens, logs, databases, screenshots, browser state, or private documents.

## Verification

Run the integrated gate:

```bash
./scripts/verify
```

Maintainers preparing a public release must follow the separate [release procedure](docs/releasing.md).

## Pull Requests

Describe:

- the problem and intended behavior;
- the files and authority surfaces changed;
- the checks executed and their results;
- any skipped checks or accepted residual risk.

Changes to real apply, privacy boundaries, durable schemas, installers, or release scanning require focused negative tests. Documentation-only corrections do not need the same ceremony unless they alter a safety or authority claim.
