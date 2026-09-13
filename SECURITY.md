# Security Policy

Do not include secrets, credentials, private logs, databases, browser state, personal paths, personal mailboxes, client data, or full private documents in a report.

## Threat Model

PlzDo Local reduces accidental authority expansion and cross-process drift. It
does not defend against a hostile process running as the same operating-system
user, because that process can inspect owner-readable state and race local
files. P5 reports incomplete rollback instead of claiming success when an
interruption occurs before a newly created directory can be journaled; that
directory may require manual inspection and cleanup.

Before a public repository exists, keep findings local and sanitized. After publication, use GitHub private vulnerability reporting when available. Do not publish an exploit or sensitive reproduction before maintainers confirm a safe disclosure path.

PlzDo Local is a control plane, not an operating-system sandbox. The core local-only claim applies to `plzdo` control-plane commands. The optional local runtime has its own execution boundary and refuses an unverified server-isolation environment. A hosted coding agent still uses its own provider.

Use a reviewed checkout or an explicitly selected isolated package installation. The core, local runtime and private composition are separate installation choices. Product commands do not modify shell startup files or automatically install/activate optional execution tools. Candidate packaging does not grant publication rights or prove live isolation.
