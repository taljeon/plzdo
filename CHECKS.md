# PlzDo Checks

This checklist defines expected public-edition invariants.

## Default Gate

Run:

```bash
./scripts/verify
```

The default gate must not call live APIs, send external AI review bundles, mutate target projects, install hooks, start daemons, or depend on credentials.

## Public Release Gate

Before publishing or pushing a release branch:

```bash
./scripts/verify
./scripts/check-release-leaks
./scripts/check-release-leaks --self-test
CODEX_HOME="$HOME/.codex" ./scripts/install-codex-skills --dry-run adaptive-project-harness external-review-router
git add -A
git diff --cached --check
git log --oneline --max-count=5
git log --format='%ae%n%ce' --max-count=1 | sort -u
git ls-remote --heads origin
git status --short
```

For the first public release, publish from a fresh/orphan branch or a squashed first commit. Do not push private-development or pre-public skeleton history.

Release commit metadata must use GitHub noreply author and committer email only. The expected account-local value is the GitHub noreply address for this repository owner; do not publish a personal mailbox in commit metadata.

```text
169621860+taljeon [at] users.noreply.github.com
```

Remote evidence must show the public branch points at the clean release commit and does not expose pre-public history.

## Guard Map

| Guard | Evidence |
| --- | --- |
| Required public files exist | `scripts/verify` checks the canonical v0.1 tree |
| PlzDo target template initializes and checks | `scripts/verify` runs `scripts/plzdo init` and `scripts/plzdo check` in temp state |
| Leak scanner rejects known-bad content | `scripts/check-release-leaks --self-test` |
| Release scan covers skill files | `scripts/check-release-leaks` scans release candidate files including `resources/codex-skills/**` |
| Installer has no default side effects | `scripts/install-codex-skills --dry-run ...` |
| CI runs the local gate | `.github/workflows/verify.yml` runs `./scripts/verify` |
| Skill install is opt-in | Installer requires explicit skill names |
| External review is advisory-only | `docs/external-review-policy.md` and `resources/codex-skills/external-review-router/SKILL.md` |
| Memory is non-source-of-truth | `AGENTS.md` and `docs/architecture.md` |
| Bounded work has stop conditions | `AGENTS.md` and `docs/what-not-to-automate.md` |

## Manual Review

Humans should still review:

- whether README value is understandable in 60 seconds;
- whether the example project feels copyable in five minutes;
- whether skill prose is public-native rather than redacted private workflow;
- whether external review prompts include only public release files.
