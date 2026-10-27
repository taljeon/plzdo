---
name: obsidian-memory-router
description: Route Obsidian, vault, external memory, ai_knowledge, Markdown note, Bases, JSON Canvas, vault search, and Obsidian CLI tasks safely. Use when the user asks Codex to record or retrieve Obsidian memory, work with Obsidian notes, evaluate kepano/obsidian-skills, create Obsidian-flavored Markdown/Bases/Canvas files, or decide whether live vault/CLI/plugin actions are allowed.
---

# Obsidian Memory Router

Use this skill to keep Obsidian useful without making it the source of truth.

## Route

1. For prior context or reusable facts, search memory first:

```bash
$META_HARNESS_ROOT/bin/harness memory 검색 "<query>"
```

2. Read facts/index first. Use `--read-notes` only when a match is relevant; it follows matched active note paths and returns compact, validated `ai_knowledge`, never raw note bodies. Do not full-scan the vault.
3. For successful meaningful work, write sanitized memory:

```bash
$META_HARNESS_ROOT/bin/harness memory 기록 --label "work-complete: short-label" --domain "<domain>" --summary "<sanitized reusable result>"
```

Set `META_HARNESS_ROOT` to the Meta Harness repository root when using these commands outside that repository.

4. For Obsidian syntax work, use Markdown, wikilinks, callouts, properties, `.base`, and `.canvas` patterns from [references/adoption.md](references/adoption.md).
5. For live Obsidian CLI, plugin/theme reload, DOM, screenshots, or vault mutation, stop for explicit approval and confirm exact vault/path.

## Boundaries

- Obsidian is external AI memory, not source of truth.
- Do not store secrets, auth data, cookies, tokens, raw logs, live DB contents, full private documents, or full papers.
- Do not write `.obsidian/` or live plugin/theme state unless explicitly requested and safe.
- Do not use Obsidian CLI as a default memory backend; the harness memory CLI remains the stable path.

## Output

When this skill routes a request, return:

- `Memory:` search, write, skip, or pending replay.
- `Vault Action:` none, read-only note syntax, file write, or approval-required live CLI.
- `Evidence:` memory result, output path, validation command, or blocked reason.
