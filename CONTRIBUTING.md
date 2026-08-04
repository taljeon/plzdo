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

For a proposed public release, also run the leak scanner with a private denylist stored outside the repository:

```bash
./scripts/check-publication \
  --private-denylist /absolute/path/to/private-denylist.json
```

The publication check pins the audited public root commit, requires noreply commit and annotated-tag metadata, and scans the exact paths and blobs in every reachable commit. It also scans ref names and raw commit/tag objects, rejects Git indirection and non-file tree entries, and revalidates HEAD and refs before returning. Git archive attributes cannot omit or transform the audited evidence. The denylist itself must never be committed.

## Pull Requests

Describe:

- the problem and intended behavior;
- the files and authority surfaces changed;
- the checks executed and their results;
- any skipped checks or accepted residual risk.

Changes to real apply, privacy boundaries, durable schemas, installers, or release scanning require focused negative tests. Documentation-only corrections do not need the same ceremony unless they alter a safety or authority claim.
