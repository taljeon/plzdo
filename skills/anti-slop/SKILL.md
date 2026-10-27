---
name: anti-slop
description: Use for code changes in any language. Preserve behavior, types and boundary validation, keep edits scoped, and verify with the project's declared checks and fresh evidence.
---

# Code quality

Preserve behavior unless the request changes it. Use the language's types and runtime input validation, keep changes within scope, and retain error handling. Increase an existing dependency's minimum supported version only when requested; otherwise report manifest and lockfile mismatches.

Run the project's declared checks in their required order. Where applicable, check lint, types or build (syntax for shell), then targeted tests. Read every exit code. A missing required tool or failed stage leaves the task incomplete. Distinguish lint, syntax checks and compilation; one does not prove another passed.

Avoid unnecessary type escapes. Validate boundary inputs at runtime and use cohesive typed objects when the domain calls for them. Apply language-specific rules only to that language. Before rewriting an expression, check presence versus falsy values, evaluation order and the type contract.

Do not add inline disables or weaken configuration to make checks pass. If semantics require a policy exception, request a narrow review specifying the rule, path, source hash, reason, owner and expiry; do not grant it yourself.

A removed, skipped or loosened test, including a dropped assertion or lowered threshold, is a behavior change. Report the reason and the check that now covers it; if the requirement itself was removed, identify that requirement. Passing checks after weakening them is not evidence that the original behavior remains covered.
