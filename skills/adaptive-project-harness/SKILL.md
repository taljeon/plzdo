---
name: adaptive-project-harness
description: "Use when the user starts a task with HN or hn, or asks for the harness method: pick how much rigor the task needs (단발/Plan/Goal, UW), freeze and get approval for Goal or UW work, verify with evidence, and record whether the route was right. Claude-only document version; no CLI needed."
---

# Adaptive project harness (hn), document version

This is the owner's `hn` method without its CLI, registry or memory runtime. Everything here is done with ordinary Claude Code tools and files in the project. Project rules (`CLAUDE.md`, `AGENTS.md`, TASKS files) win over this skill.

## Core run

Model meaningful work as `Input -> Brain -> Tool -> Evidence`.

1. Input: the request, the project's own rules and task files, the source-of-truth docs, constraints.
2. Brain: decide the route (below), the gates, the smallest tools or subagents, and how you will verify.
3. Tool: do only bounded actions the project allows.
4. Evidence: run the declared checks, read the output and exit codes, compare with the frozen plan. No evidence means no completion claim.

Judge implementation facts from code and tests, and intent or policy facts from the project's docs. When they conflict, resolve it before relying on either.

## Project route

Before starting a new work area, look for an existing one: a TASKS file, a design doc, a branch with the same topic. Exactly one match: attach to it. Several: ask which one and stop. None: create it after the plan is accepted. Never silently reuse an archived or similarly named one.

## Execution route

Return two values: `weight = 단발 | Plan | Goal` and `uw = true | false`.

- 단발 (one-shot): small, self-contained, reversible, quickly verifiable. No formalization; answer or patch directly with the checks it needs.
- Plan: bounded multi-step work that finishes in one session. Plan, execute, verify; formalization optional.
- Goal: durable state, architecture, significant implementation risk, or work where a wrong direction wastes hours. Formalize and get approval before starting.
- UW (unattended work): bounded repeated review, migration or repair. Needs an approved formalization with loop bounds.

Precedence when signals conflict: coding or coursework phrasing -> Plan; operational lane -> Goal; an app, service or product -> Goal; small work in an attached area -> 단발 unless a stronger or UW trigger applies; otherwise Plan. A role alone never triggers UW.

Raise the weight for auth, payments, security, production or customer impact, migrations, writes to other repositories, persistent architecture, costly ambiguity, or external side effects. Do not raise it just because the work feels hard.

Before adding code or ceremony, ask: is it needed, does it already exist, can the standard library or a current dependency do it, can it be one smaller change? Minimality never waives safety, accessibility, validation or evidence.

## Formalization (Goal and UW)

Write it as a Markdown file in the project (for example `TASKS/<id>.md`) with these sections: objective, acceptance criteria, non-goals, constraints, plan, evidence per plan item, risks, status (`draft | approved | completed | superseded`), route (`weight`, `uw`), open questions, approval.

- Only an explicit message from the user approves. You never approve your own formalization.
- Approval binds to the text: record the date and `shasum -a 256` of the file in the approval line. Any later change to the approved sections returns the status to draft and needs approval again.
- Before approval, list the missing decisions and ask only the ones the docs do not answer (`requirements-clarification` skill).
- Completed or superseded records are never edited; write a successor.
- Every plan item closes with one evidence line.

UW additionally needs: a maximum iteration count, a stop rule, a timeout, a checkpoint location, and the evidence each iteration must produce. Each iteration is `Observe -> Choose -> Act -> Verify -> Record`, then repeat or stop. Continue only while evidence improves. Stop at `success`, `clean-no-op`, `blocked`, `approval-required`, `exhausted` or `stagnated`. A loop is never a permission grant.

## Model and effort

Quality is the default; trade it for speed only when the user asks. Do not make the user pick a model each time. For subagents choose by task: the strongest model for review of high-risk changes and for design, a faster one for broad read-only search. After an objective check fails, you may raise the model or effort at most two steps in total. A wrong approach, no progress or an unavailable model is not a reason for unbounded retries. An explicit model or effort from the user always wins.

## Boundaries

1. Never read, print, store or export secrets, auth files, cookies, tokens, raw private logs, live databases or full private documents unless the user asks for that exact data and the path is safe.
2. Default work does not touch production, deploy, send mail, or install hooks, plugins or MCP servers.
3. Writes to another repository need the user's opt-in for that write: show the plan first, then apply, then verify the exact diff and keep a way back.
4. Respect protected paths and symlink boundaries.
5. Notes, summaries, subagent output and external reviewers are advisory input, never the source of truth or permission for a tool call.

## Recovery

For an ordinary failure: classify it, fix the smallest cause, rerun the relevant check. Stop after two failed recovery attempts unless an approved UW contract says otherwise. Permission, stale-context, unsafe-write, schema and missing-dependency failures are blockers to report, not reasons to weaken a gate.

## Evidence and learning

After meaningful work, add a route-feedback line to the task file: initial and final weight and UW, the reason for any reroute or user override, and a verdict `correct | under-routed | over-routed | user-override | unknown`. Repeated under-routing means the rule should be stronger; repeated over-routing means less ceremony. Do not infer trends from a few runs.

The completion report states the result, changes, evidence and skipped checks, route feedback, impact on the user, and remaining risk, and compares every frozen plan item with its evidence.

## Compact interaction

For nontrivial work, start with: project route, execution route and UW, whether formalization is needed and why, the plan, and the expected evidence. For tiny work, answer directly.

Final rule: add the minimum rigor needed, keep the boundaries, prove the result, and learn whether the route was right.
