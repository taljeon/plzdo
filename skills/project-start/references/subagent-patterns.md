# Subagent Pattern Notes

Use these as background when choosing an agent split. They are not dependencies.

## Patterns To Borrow

- Supervisor or manager pattern: one orchestrator controls task flow, delegates to specialists, and validates outputs. CrewAI documents sequential and hierarchical processes, where a manager delegates tasks and reviews outcomes.
  Sources: https://docs.crewai.com/en/concepts/processes and https://docs.crewai.com/en/learn/hierarchical-process

- Conversable agents: agents can exchange messages, use tools, and collaborate with or without human feedback. AutoGen frames this as customizable, conversable agents in automated multi-agent chat.
  Source: https://microsoft.github.io/autogen/0.2/docs/Use-Cases/agent_chat/

- Role-based software team: MetaGPT assigns different roles such as product, architecture, engineering, and QA under structured SOPs. Borrow the role split, not the full framework.
  Source: https://docs.deepwisdom.ai/main/en/guide/get_started/introduction.html

- Handoff and specialization: LangGraph describes supervisor and swarm architectures. Supervisor is better for Codex project work because one main agent should keep final control; swarm is useful only when dynamic handoff is itself the product behavior.
  Sources: https://langchain-ai.lang.chat/langgraph/agents/multi-agent/ and https://github.com/langchain-ai/langgraph-swarm-py

## Codex Mapping

- Main agent: orchestrator/supervisor, final scope, final integration, final report.
- Explorer: read-only structure and behavior analysis.
- Worker: scoped code or document edits with clear file ownership.
- Reviewer: security, regression, deletion, duplicate-write, public-release, and drift risks.
- Tester: deterministic checks from `CHECKS.md`, smoke tests, fixture validation, skipped-check report.
- Release-preflight: leak/security gate before public exposure.

## When To Avoid Subagents

- The task is a direct answer or one tiny edit.
- Delegation would duplicate the main agent's immediate next step.
- The task requires sensitive data that should stay local to the main agent.
- File ownership cannot be separated safely.
