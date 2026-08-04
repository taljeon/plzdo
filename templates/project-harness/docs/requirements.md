<!-- BEGIN PLZDO-LOCAL:project-frame.requirements.v1 -->
# {{PROJECT_NAME}} Requirements

## Objective

{{PROJECT_OBJECTIVE}}

## Functional Baseline

- Keep the operator's latest approved request as the highest task intent below hard safety boundaries.
- Make project behavior explicit, testable, and traceable to this document or an approved task.
- Preserve deterministic local operation for control-plane functions.

## Safety And Privacy

- Do not expose secrets, credentials, auth state, private logs, live databases, or full private documents.
- Keep default checks local and free of network, credential, production, deployment, and background-process dependencies.
- Require explicit approval and evidence for any separately designed high-risk write gate.
- Reject unsafe paths, symlink escapes, and unvalidated persistent bytes.

## Acceptance

- Required checks are declared in `CHECKS.md` and pass with recorded evidence.
- Documentation and implementation agree before completion is claimed.
- Changed files, skipped checks, operator impact, and residual risk are reported.

## Non-Goals

- This frame does not choose a language, framework, hosting provider, or model provider.
- This frame does not grant deployment, production, remote-service, or cross-repository write authority.
<!-- END PLZDO-LOCAL:project-frame.requirements.v1 -->
