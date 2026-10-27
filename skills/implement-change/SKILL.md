---
name: implement-change
description: "Claude writes the spec, the implementer agent builds and tests it in a git worktree, review-change reviews it, and Claude gives final acceptance. Use for approved multi-file features, new modules, or refactors. Skip for small single-file edits (do them directly) and for coding-test practice (coding-test-coach)."
---

# Spec -> implementer -> review -> acceptance

Claude-only version of the owner's `codex-implement` flow. Claude owns the design, the spec and the final acceptance; the `implementer` agent writes the code in its own worktree.

## 1. Record the base

A worktree starts from a commit and never sees uncommitted work.

1. Commit the work the implementer needs (ask the user if committing is not already approved).
2. Record `git rev-parse HEAD` as the base commit, and `git status --porcelain` so you can tell later which changes are yours.

## 2. Write the spec packet

The implementer cannot see this conversation, so the packet must stand alone. Use the `design-spec` output when there is one.

```
You are the implementation worker. Follow this spec exactly.
Base commit: <sha>. Branch: <name>.
Objective: <one line>
Requirements:
1. <behavior, with edge cases and error types>
2. ...
Allowed paths: <paths>. Do not touch anything else.
Tests: reuse existing checks; test each required behavior (normal, edge, error) at the interface named above, not internals.
Acceptance: run '<command>' from the repository root; it must exit 0.
Reply with: branch, diffstat, the exact test summary line you observed, the acceptance exit code, status (completed | partial | unknown | not_started), and any spec ambiguity you resolved.
```

## 3. Run

Start the `implementer` agent with the packet. At most 3 implementers in parallel, and their allowed paths must not overlap. Wait for every one to finish before reporting.

## 4. Review

Run the `review-change` skill on the implementer's branch against the base commit, with the spec and the implementer's reply. Leave out your own verdict.

## 5. Final acceptance

1. `git diff --stat <base>..<branch>`: only allowed paths changed.
2. Read the diff against the spec, requirement by requirement.
3. Check out the branch, rerun the acceptance command yourself, and read the exit code.
4. Weigh each review finding: fix confirmed ones (or send them back), note rejected ones with the reason.
5. Merge only when the user approved merging for this task.

## 6. If something fails

Send the implementer one correction packet with the exact failures. Fix small leftovers yourself. After two failed rounds, stop and report what failed and why.

Report to the user: files changed, test results (implementer and your rerun), review findings, and anything you corrected.
