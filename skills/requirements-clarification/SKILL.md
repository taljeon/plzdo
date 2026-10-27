---
name: requirements-clarification
description: Clarify missing decisions before approving behavior changes, new features, entities, lifecycles, states or contracts. Use for 요구사항 정리, 애매한 요청, 새 기능, 기능 추가해줘, 되게 만들어줘. Skip small fixes with explicit requirements, behavior-preserving refactors, docs, typos and fully specified one-off work.
---

# Requirements clarification

Use this sequence: draft, clarify, update the existing draft, obtain approval, implement. Never guess a missing decision and record it as settled. If a consequential unknown appears after approval, pause only the behavior it affects and follow the change rule below.

## Find missing decisions

1. Read the request, the source priority in `AGENTS.md`, `docs/requirements.md`, `TASKS.md`, decision records, the approved plan and relevant code. Code establishes current behavior, not approval of its rationale.
2. List only affected entities, actors, state owners and external systems; check once for an omitted participant.
3. For each entity and interacting pair, examine structure (one/many, identity, containment), behavior (creation, change, ending, failure, cancellation, retry), technical requirements (storage, concurrency, consistency) and contracts (states, inputs, outputs, duplicates, conflicts, rejection). This candidate list is working material, not a required permanent artifact.
4. Drop unrequested additions when the agreed behavior is complete without them. They need neither a question nor a pending item nor confirmation as a non-goal. If useful, report one line saying they are not covered.
5. Respect explicitly requested values, names and wording without asking whether they are appropriate. Updating affected tests and docs is a mechanical consequence within scope, following the latest request and project source priority. Unrequested operations prohibited by project rules, such as deployment or external transmission, stay outside scope. This excludes performing those operations, not deciding a requested feature's recipients, destination or delivery method. Do not use this shortcut to dismiss questions involving data structures, security, money or irreversible actions.

## Resolve each candidate in order

Stop at the first applicable rule:

1. An authoritative document, decision record, approved plan or explicit user statement answers it: settle it and cite the location.
2. A project rule or convention invisible to users applies: follow it and record the reference.
3. Existing code shows the behavior: retain it as evidence of current behavior; for a consequential decision continue checking the remaining rules.
4. It is an internal adjustment within an already decided mechanism, such as retry count, batch size or cache time: state a tunable default. User-visible limits, participant counts, pricing, permissions, visibility and retention never qualify merely because their numbers can change later.
5. Otherwise it is a question candidate.

Consequential decisions concern data structures, lifecycle, security, money, deployment, irreversible actions, choices costly to rebuild later, or choices users may reasonably have a preference about. Never put these in the tunable-default category.

## Ask only grounded questions

Each candidate needs three checks:

1. Name the requirement, entity or behavior it concerns. If you cannot, narrow the target and reassess.
2. Explain why it is unresolved. A cited answer removes the question; for a consequential perspective record “not applicable: <evidence>” in the decision log. If checked sources lack an answer, ask. If evidence is insufficient, mark it unverified, inspect a few named sources narrowly, then resolve or ask. Insufficient evidence alone never removes a question.
3. State what could go wrong if left open. If there is no consequence, do not ask, unless it has already been classified as consequential.

Use `AskUserQuestion`. Put the recommended choice first with its reason. Ask the highest-impact independent questions together; defer questions dependent on an unanswered choice to the next round. Include the subject, why existing sources do not settle it and the consequence of leaving it open. Never repeat answered questions or fill a question quota. If none remain, report “No questions; evidence: <location>”.

## Record and stop conditions

- Settled rules go in the project's `docs/requirements.md` as short, verifiable statements. Put “Tunable default: <value>” beside the relevant rule; existing conventions need only their source reference.
- Open items go in the project's `TASKS.md`. If project documents are unavailable, keep settled rules and open items in the plan and final report.
- Use one line per open item: `[미결정] <entity/behavior> | unresolved because: … | consequence: … | recommendation: … | handling: settle before implementation / proposed scope exclusion`.
- An open-item list is neither proof that review is complete nor required to be empty. Preserve its unresolved lines when requesting plan approval.
- A consequential open item blocks only implementation that depends on it; continue independent work.
- Removing already requested or agreed behavior requires user confirmation before recording it as a non-goal. Until then keep it as a proposed scope exclusion. Unrequested additions need no such confirmation.
- When requirements change, update both `docs/requirements.md` and the existing plan, reflect remaining open items in `TASKS.md`, and obtain renewed approval for the changed behavior before implementing it.
