---
name: pr-oss
description: Write or revise a pull request title and description (PR 본문, PR 설명, PR 작성, PR本文) from an approved diff, including OSS contributions. Use before writing or updating a PR title or description, or opening a PR. Pinned to PR OSS v2.2.1.
---

Before writing or updating a PR description, read PR OSS v2.2.1 in full and apply it only to the already approved diff, the author's intent and the repository's PR template.

Source (pinned, never replace with a newer commit):
https://raw.githubusercontent.com/taljeon/pr-oss-skill/6931d56c29b2fc31b9c8a113dcdb552f3dc0eb9a/SKILL.md
Expected SHA-256: ee38882c95a7293165f228a0bf67a185e18c2ac613f90ff92ee8795579d1adf0

Use the bundled `references/upstream.md` only when `shasum -a 256` gives the same hash. Resolve it relative to this skill folder.

If no readable source matches the expected hash, hold only that PR description and explain why; do not claim the skill was applied.

Call a test a regression test only when it was shown to fail on the base commit and pass on the change. Otherwise describe what it covers, and if no test exercises the changed behavior, say so in Testing.

Keep the repository's contribution/AI policy and existing approval scope. Reading this skill grants no permission to commit, push, open, edit or comment on a PR.

Do not edit the pinned source. Changing the version means updating this file and the bundled reference together.
