# Data And Privacy

PlzDo Local is designed to keep its runtime data on the machine where it is invoked. Local-only is a behavioral and architectural property, not a universal operating-system firewall guarantee.

## Data Classes

| Data | Default handling |
| --- | --- |
| Catalog and registry | Local JSON, operator-selected paths only |
| Formalizations and findings | Local versioned records |
| Context packs | Fixed allowlist, bounded summaries or audit rendering |
| Work state | Bounded recovery cache with archive-first compaction |
| Memory | Sanitized reusable summaries, non-source-of-truth |
| Metrics | Bounded execution metadata only |
| Monitor output | Read-only observations without raw root paths |
| Review bundles | Explicit file manifest, redaction, exact hashes, no send |
| Apply evidence | Local plan, report, backup, and rollback artifacts |

## Never Store By Default

- secrets, passwords, API keys, access tokens, cookies, or auth stores;
- raw private logs, live database content, browser profiles, or provider sessions;
- full private documents or home-directory scans;
- personal mail, calendar, meeting, or account data;
- arbitrary recursive project content in context or memory;
- credentials or private values in examples, tests, reports, or release artifacts.

Sensitive shapes are rejected before persistence. Review preparation redacts common credentials, personal home paths, email addresses, and sensitive headers before bundle bytes are written.

Review sanitization uses deliberately high-confidence heuristics. It redacts complete PEM private-key blocks; secret-like assignments in shell, JavaScript, JSON, and configuration syntax; three-segment base64url JWT shapes including short segments; inline authorization, API-key, and cookie headers; JavaScript bracket-header assignments and `setRequestHeader` calls; Basic and Bearer values; and recognizable token formats used by major source-control, cloud, AI, package, payment, and collaboration providers. An unmatched private-key boundary fails closed because the secret extent cannot be determined safely. Sanitized bundle and import validation reruns the same checks and rejects any remaining match.

Review manifests reject sensitive path components and filenames before opening a source file. The shared review/monitor classifier covers path controls, email addresses, token and assignment shapes, credential-store directories such as `.ssh`, `.env` variants, `.git-credentials`, `.netrc`, `.npmrc`, `.pypirc`, kubeconfig names, RSA/DSA/ECDSA/Ed25519 private-key variants, service-account and application-default credential files, credential JSON files, and private-key or certificate-container suffixes. Matching is case-insensitive, applies to every path component, and strips common backup suffixes before classification.

These checks are heuristic rather than a general secret classifier. Novel token formats, encoded or split secrets, and confidential prose without a recognizable shape may not be detected. Review manifests should therefore remain narrow and use only files already suitable for bounded human review.

## Local Review Boundary

`plzdo review prepare` creates a local artifact with an explicit source manifest and sanitized contents. `plzdo review validate` validates it locally. `plzdo review import` imports an already-local response as advisory evidence.

PlzDo Local never sends that artifact. If an operator manually uploads or copies it to another service, that action is an operator-owned egress event governed by that service's retention and account policy.

## Release Privacy

The public release gate scans source, docs, examples, metadata candidates, and release artifacts for:

- secret and credential patterns;
- real email addresses and private local paths;
- meeting links, private repository URLs, and provider session identifiers;
- binary, archive, database, log, media, or oversized files;
- operator-specific aliases supplied through a private denylist outside the release tree.

The private denylist never enters the repository, manifest, review bundle, or scanner output. Only opaque finding IDs may be reported.

## Limits

PlzDo Local cannot prevent a privileged local process from reading its files, guarantee disk encryption, erase provider-side data, or enforce network policy for unrelated tools. Use operating-system permissions, encrypted storage, organizational policy, and network controls where those guarantees are required.
