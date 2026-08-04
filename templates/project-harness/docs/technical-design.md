<!-- BEGIN PLZDO-LOCAL:project-frame.technical-design.v1 -->
# {{PROJECT_NAME}} Technical Design

## System Boundary

The project is identified as `{{PROJECT_ID}}`. Its current objective is: {{PROJECT_OBJECTIVE}}

The project frame governs local agent behavior and evidence. Product architecture belongs below this section once requirements are approved.

## Control Flow

```text
Operator request
    -> Layer 0 boundaries
    -> Ordered source of truth
    -> Judgment: Quick | Plan | Goal, bounded loop yes/no
    -> Bounded local tools
    -> Verification evidence
```

## Components

- `AGENTS.md`: compact policy and working loop.
- `TASKS/current.md`: current task, plan, and evidence pointer.
- `docs/requirements.md`: product intent and acceptance criteria.
- `docs/technical-design.md`: implementation architecture and boundaries.
- `CHECKS.md`: executable verification contract.
- `scripts/verify`: Python standard-library project-frame integrity check with descriptor-relative, no-follow reads.

## Change Discipline

- Update requirements or this design before implementing changed behavior.
- Keep generated managed markers paired, unique, and unnested.
- Preserve manual content outside managed blocks during a managed re-render.
- Validate the complete render before atomic writes and fail closed on path or ownership ambiguity.

## Project Architecture

Document product components, interfaces, durable schemas, data flow, failure behavior, and test strategy here before implementation depends on them.
<!-- END PLZDO-LOCAL:project-frame.technical-design.v1 -->
