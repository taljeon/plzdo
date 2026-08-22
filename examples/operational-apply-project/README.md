# Operational Apply Example

This example documents the policy and project-input shapes required for P5 without shipping an executable authorization. Replace every `REPLACE_*` value, validate the catalog, and review the resulting plan before authorization.

The template is intentionally invalid until an operator supplies:

- a canonical absolute path to a local Git worktree;
- a unique repository and catalog approval identity;
- reviewed catalog approval metadata;
- `approval.profileSha256` computed from the final reviewed repository profile.

After replacing every other profile value, an operator can print the candidate
digest without writing the catalog:

```bash
python -c 'import json; from pathlib import Path; from plzdo_local.catalog import repository_profile_digest; p=Path("catalog.json"); r=json.loads(p.read_text())["repositories"][0]; print(repository_profile_digest(r))'
```

Place that digest in `profileSha256`, then validate and review the complete
entry again. The digest detects stale profile approval; computing it is not
itself approval and does not authorize an agent to enable P5.

Catalog approval metadata alone cannot execute a plan. Run the focused flow with absolute paths:

```text
python -m plzdo_local.apply_cli plan --catalog CATALOG --project PROJECT --repository operational-example --force --output PLAN
python -m plzdo_local.apply_cli authorize --catalog CATALOG --plan PLAN
python -m plzdo_local.apply_cli execute --catalog CATALOG --plan PLAN
```

Authorization and execution each require the exact plan fingerprint at the controlling foreground TTY. The short-lived one-time grant, target-global lock, integrity key, and MACed evidence are created only under canonical owner-only PLZDO state; no evidence-root argument exists.

`project.template.json` is exact input, not a rendered frame. P5 always invokes its bundled templates itself and rejects caller-built renderer plans or custom template roots.

The target must not contain Git index gitlinks/submodules, `.gitattributes`, external filters, or worktree-redirection config. The apply-plan schema checks structure; the runtime validator additionally verifies all hashes, fingerprints, renderer bytes, and live Git/filesystem bindings before authorization or execution.
