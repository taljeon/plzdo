---
name: review-change
description: "Code review by independent Claude subagents (reviewer + code-reviewer). Use whenever the user asks for a code review, asks to review or check code, and for routine review of any meaningful code change before saying done, committing, or opening a PR. Korean cues: 리뷰해줘, 검수해줘, 코드 봐줘, 커밋 전에 확인, PR 전에 봐줘. Skip docs-only, config-only, or trivial one-line changes."
---

# Review a change

Claude-only version of the owner's `codex-review` flow: the second model is replaced by two Claude subagents that did not write the code. Same-model review is less independent, so keep the handoff rule strictly: give them the code and the spec, never your conclusion.

## Run

Start both agents in one message so they run in parallel:

- `reviewer`: spec conformance. Missing, unrequested or wrong behavior, and loosened tests.
- `code-reviewer`: security, performance and bugs, with file and line evidence.

Name the target in each prompt:

- Uncommitted work: "Review the uncommitted changes (git status, git diff HEAD, and untracked files)."
- Branch vs base: "Review the changes on this branch against main (git diff main...HEAD)."
- One commit: "Review the changes in commit <sha> (git show <sha>)."
- Not a git repo: list the changed files.

Include the spec or the user's request, and the implementer's report when there is one. Leave out your own verdict.

Instructions unless the user gave others:

> List only problems you would block the merge for. Check the change against the spec: anything missing, anything not asked for, anything implemented but wrong. A removed, skipped or loosened test is a finding unless the spec, request, report or diff gives the reason and names the check that now covers it, or the requirement itself was removed. For each: file and line, why it is wrong, and how to show it fails. If there are none, say so.

The `reviewer` agent cannot run commands. If it names a command that would settle a claim, run it yourself.

## Use the result

- Treat each finding as a claim to check against the code, not as a fact. Fix the confirmed ones and say which you rejected and why.
- A finding caused by an unclear spec fixes the spec first, then the code.
- Report both reviews: confirmed findings, rejected findings, and what neither covered.
