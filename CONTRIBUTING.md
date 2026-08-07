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

The integrated gate is local and network-independent. Do not substitute a
hosted CI result, external AI review, or third-party validation service for this
evidence. If your environment provides additional approved checks, treat them
as supplementary.

Maintainers preparing a public release must follow the separate [release procedure](docs/releasing.md).

## Pull Requests

Work on a branch and open the pull request only on a repository approved to
receive the code. Pushing a branch is an explicit code-transfer event; never
send private or restricted project content to a public fork.

The author must describe:

- the problem and intended behavior;
- the files and authority surfaces changed;
- the exact commit checked and the local checks executed;
- any skipped checks or accepted residual risk.

The author and reviewer should run
`./scripts/verify --acceptance <full-commit-sha>` on the exact clean commit and
record the platform and Python version. If integration creates a different commit or tree,
rerun the local gate on the final result before release. A self-reviewed change
must not be presented as independent review.

Changes to real apply, privacy boundaries, durable schemas, installers, or release scanning require focused negative tests. Documentation-only corrections do not need the same ceremony unless they alter a safety or authority claim.
