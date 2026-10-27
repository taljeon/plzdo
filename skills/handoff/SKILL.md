---
name: handoff
description: "Compact the current conversation into a handoff document for another agent or a fresh session to pick up. Use when the user wants to stop and continue later, move to a new session, or hand the work to another agent. Korean cues: 다음 세션에서 이어서 하게 정리해줘, 새 세션으로 넘어가게 정리, 인수인계, 인계 문서, 핸드오프."
argument-hint: "What will the next session be used for?"
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save to the temporary directory of the user's OS (`$TMPDIR`, else `/tmp`; `%TEMP%` on Windows) - not the current workspace.

Include a "suggested skills" section in the document, naming which skills the next agent should call the Skill tool for.

Do not duplicate content already captured in other artifacts (specs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.

Adapted from mattpocock/skills 49dd158 skills/productivity/handoff (MIT, Copyright (c) 2026 Matt Pocock); see LICENSE-mattpocock.md. No text changes.
