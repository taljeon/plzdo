# What Not To Automate

PlzDo Local automates repeatable local bookkeeping. It deliberately keeps irreversible or authority-bearing decisions with the operator.

Do not automate:

- approval of a Goal, bounded loop, or real apply policy;
- production writes, deployment, billing, mail, or account changes;
- secret, credential, cookie, browser-profile, or live-database collection;
- external AI review sends or uploads;
- background context checkpoints, memory writes, or monitoring;
- package, plugin, MCP, hook, daemon, scheduler, or shell-profile installation;
- acceptance of worker or reviewer output as source of truth;
- removal of drifted or unmanaged user files;
- retries that consume a bounded attempt without recording the failure.

Prefer an explicit plan, a visible local command, typed evidence, and a stop condition. A future wrapper may make an approved command easier to invoke, but it must not widen the command's authority or turn active-session work into an unattended lane.
