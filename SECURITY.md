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

PlzDo Local is a control plane, not an operating-system sandbox. Its local-only claim applies to checked-in PlzDo commands, not to unrelated software or a hosted AI model.

Use PlzDo Local from a reviewed Git checkout through `./bin/plzdo`. The project does not provide a prefix installer, modify shell startup files, or write a global launcher.
