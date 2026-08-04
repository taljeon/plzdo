---
name: leak-check
description: Review a release tree for credentials, private identities, local paths, unsafe artifacts, and unreviewed metadata.
---

# Leak Check

Use this skill before publishing, packaging, or sharing a repository.

## Review Order

1. Enumerate tracked and candidate release files without reading excluded private stores.
2. Reject credentials, auth material, personal addresses, private hostnames, and machine-specific paths.
3. Reject databases, logs, browser state, archives, media evidence, and symbolic links unless the release contract explicitly allows them.
4. Inspect examples and fixtures for synthetic-only identities and reserved domains.
5. Check commit and package metadata separately from source files.
6. Run scanner self-tests so a scanner failure cannot count as a clean result.

Report findings by path and category. Do not print or preserve a detected secret value.
