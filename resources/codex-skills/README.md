# Public Codex Skills

This directory contains optional Codex-compatible skills for PlzDo.

Read each `SKILL.md` before installing. Skills are instruction files and should be treated as supply-chain content.

Rules:

- Install only explicit skill names.
- Do not install hooks, daemons, MCP servers, browser extensions, provider tools, or background automation.
- Skills must not run network, shell, provider, or install commands unless the operator explicitly approves in the active session.
- The bundled installer only copies files into `$CODEX_HOME/skills`; it does not grant runtime authority.

Available v0.1 skills:

- `adaptive-project-harness`
- `external-review-router`
