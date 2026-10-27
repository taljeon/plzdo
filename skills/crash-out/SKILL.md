---
name: crash-out
description: Check an answer by trying to disprove it before sending it. Use on factual questions, research, numbers, laws and limits that change by year, API behavior, and debugging conclusions, where a confident wrong answer costs more than a slower right one. Also when the user asks to "검증", "확인해봐", "crash out", or "틀린 데 없는지 봐".
---

# Crash out

A first draft tends to defend itself. This skill reverses that: after drafting, the job is to break the draft, and only what survives is sent.

## Steps

1. Draft the answer, but do not send it yet.
2. List every claim the answer depends on: facts, numbers, dates, names, versions, limits, API behavior, cause-and-effect statements. If the answer would change when the claim is wrong, it goes on the list.
3. Try to disprove each claim with evidence, not by rereading your own reasoning.
   - Run the code, command or query when one exists.
   - Read the actual source: the file, the official docs, the statute, the changelog.
   - Search for evidence against the claim, not for it.
   - For anything that changes over time (tax limits, prices, versions, rules), find the current value and its effective date.
   - Check the claims the answer leans on hardest from two independent angles.
4. Give each claim one verdict:
   - **Held**: attacked and still standing. Note the evidence.
   - **Unverified**: could not confirm or refute. Keep it only with a visible "확인 못 함" label and what would confirm it.
   - **Broken**: disproved. Fix it or remove it.
5. Rewrite the answer from held claims only, with unverified ones labeled.
6. If a central claim broke, say plainly that the first answer was wrong and what changed. Do not smooth it over.

## Output

The checked answer, with unverified points labeled where they appear. Then a short list of the claims that broke and what replaced them. If nothing broke, say so in one line.

## Not for

Opinions, style choices, and small tasks with nothing to check. There, a crash-out only slows the answer.
