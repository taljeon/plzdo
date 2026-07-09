# What Not To Automate

Automation is useful only when the authority boundary is clear. This template defaults to observation, verification, and evidence. It does not default to mutation or external egress.

Do not automate:

- reading or exporting secrets, auth stores, cookies, private keys, raw private logs, live databases, or full private documents;
- scheduled external-provider sends;
- browser sessions with logged-in accounts;
- provider output as a default verification gate;
- watchers, hooks, launch agents, daemons, MCP servers, or browser extensions;
- memory writes that claim source-of-truth status;
- target repository mutation without an explicit apply path;
- self-expanding loops with no max iteration count, timeout, checkpoint, or stop condition.

Allowed by default:

- local read-only verification;
- deterministic scripts with no credentials;
- toy examples;
- advisory reports that do not mutate targets;
- explicit operator-approved actions in the active session.

External AI can be helpful, but it must stay advisory. A reviewer can say "this looks risky"; it cannot become the source of truth or directly trigger edits.
