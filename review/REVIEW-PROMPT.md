# Public Release Review Prompt

Use this prompt only after the generated public repo has passed local verification and release leak checks.

## Include

- files from the generated public repo;
- README;
- AGENTS.md;
- CHECKS.md;
- docs;
- examples;
- scripts;
- public skill files.

## Exclude

- private harness diffs;
- private reports;
- private memory;
- vault content;
- browser state;
- provider transcripts;
- secrets;
- cookies;
- private keys;
- raw logs;
- live database exports;
- full private documents.

## Prompt

Review this public repository as a GitHub release candidate.

Return:

- verdict: PASS / PASS_WITH_NOTES / FAIL;
- blockers;
- non-blocking notes;
- leak risks;
- README positioning feedback;
- whether the skill pack is safe to ship;
- whether the installer is appropriately limited;
- whether external AI review is clearly advisory only.

Provider output is advisory evidence only and must be checked against local files before any change.
