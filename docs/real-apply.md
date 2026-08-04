# Real Apply

P5 is the only PlzDo Local path allowed to mutate an explicitly registered target repository. It is disabled by default and is not an arbitrary command runner.

## Required Policy

The catalog entry must be active and declare all of the following:

- `workflowLane=operational`;
- `rolloutTier=enforced`;
- `realApply.enabled=true`;
- `realApply.operatorOnly=true`;
- valid catalog approval metadata.

Catalog approval metadata is a policy prerequisite, not execution authority. An agent cannot set or infer these values for itself.

## Operator Authorization

Planning accepts one exact JSON project object with only `id`, `name`, and `objective`. P5 invokes the bundled repository templates internally. The API does not accept a `ProjectFramePlan`, custom template root, binary frame, caller confirmation string, or caller evidence directory.

Authorization is a separate foreground operation:

1. P5 re-renders the bundled templates and revalidates the target.
2. The operator types the exact 64-character `planFingerprint` at the controlling foreground TTY. Standard input and environment variables cannot provide the confirmation.
3. P5 writes a five-minute HMAC authorization grant under the canonical PLZDO state root.
4. The grant binds repository id and canonical path, root fingerprint, Git HEAD, catalog fingerprint, exact plan fingerprint, expiry, and a random one-time nonce.
5. Execution prompts for the same exact fingerprint and atomically moves the grant to consumed state before any target mutation.

The integrity key is a random 32-byte owner-only file in canonical PLZDO state. P5 fails closed where stdlib filesystem ownership and foreground-TTY checks cannot be enforced.

## Flow

```text
render exact bytes in memory
    -> build apply plan
    -> bind project input, bundled templates, target root, Git top-level, Git-dir/common-dir identities, HEAD, and clean status
    -> operator authorizes the exact plan fingerprint at the foreground TTY
    -> execute confirms the same fingerprint and consumes the one-time grant
    -> write a MACed rollback-in-progress report with deterministic target-temp identities
    -> journal each actual P5-created directory path/device/inode immediately after creation
    -> atomically replace only listed files
    -> verify exact bytes and Git diff
    -> write the MACed final report
```

The target-global lock is derived only from the canonical target path, so alternate catalog identifiers cannot split it. Reports bind the consumed grant, plan, target lock, exact backups, HMAC-derived temporary artifact names, and the path/device/inode identity of each parent directory P5 actually created.

Rollback persists `rollback-in-progress` before restoring anything. On resume, every frame file must be either its planned state or exact backup state. Journaled temporary artifacts left by abrupt process termination are removed before status inspection. P5 removes a created directory only when its current path/device/inode exactly matches the MACed journal and it is empty. An unjournaled, replaced, or non-empty directory is left untouched and rollback remains incomplete until the operator resolves that drift. Repeated rollback is idempotent, including after process interruption or failure to write the final report.

Status and rollback accept only the report's canonical path under PLZDO state. Reports and grants are HMAC verified before use.

## Git Process Safety

Before every Git status operation, P5 rejects all index gitlinks/submodules, repository-local filters, process-capable config, `core.worktree`, `extensions.worktreeConfig`, every `.gitattributes` file, and Git-dir/common-dir `info/attributes`. Status uses `--ignore-submodules=all`; submodules are refused rather than inspected. The canonical show-toplevel and path/device/inode identities of both Git-dir and common-dir are rebound during authorization, execution, status, and rollback.

Git runs in a separate process group with a fixed timeout, bounded stdout/stderr readers, no prompts, no hooks, and isolated global/system configuration. On POSIX, P5 retains the process-group id and kills that group after the original Git process exits, including descendants that closed both output pipes.

## Schema Boundary

`schemas/apply-plan.schema.json` is the structural JSON contract. It fixes exact keys, frame prefix/order, Git identity shape, sorted directory combinations, and previous-state/action conditionals. `plzdo_local.apply_gate.validate_apply_plan` is additionally authoritative for canonical Base64, content hashes, self-fingerprints, renderer-owned bytes, path relationships, and other runtime semantics. A shared regression corpus exercises both layers; full equivalence is intentionally not claimed.

## Refusal Cases

Apply stops before target mutation when policy is disabled, authorization is absent/expired/consumed, the foreground TTY is unavailable, Git is dirty, a gitlink/submodule or process/worktree-redirection configuration exists, HEAD or Git metadata identity moved, the root or a file changed, a symlink or special file is present, protected paths are selected, bundled templates drifted, or rollback evidence cannot be prepared.

## Trust Boundary

The HMAC provides same-user integrity and provenance for PLZDO state. It does not prove human identity and does not defend against a hostile process running as the same OS user, which can read the key, alter the target, or drive the terminal. The foreground prompt proves only that this process owns a controlling TTY at that moment.

P5 reduces accidental and cross-process mutation risk; it does not make every planned change correct. Use small plans, inspect diffs, run project checks, and keep normal version-control recovery available.

## CLI

The focused interface is available as `python -m plzdo_local.apply_cli`. Its `plan`, `authorize`, `execute`, `status`, and `rollback` commands read bounded JSON files only; authorization, execution, and rollback confirmations are read directly from the controlling TTY. Execute output contains only status and the canonical report path, never backup contents.
