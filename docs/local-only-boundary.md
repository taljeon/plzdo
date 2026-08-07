# Local-Only Boundary

The default PlzDo Local runtime contains no network transport and starts no background process. Commands operate on repository files, explicit local targets, temporary fixtures, or the resolved PlzDo state root.

## Included

- local catalog and registry reads;
- deterministic project-frame planning;
- local formalization, context, state, memory, findings, and metrics;
- manual read-only monitoring and repository preflight;
- local review preparation, validation, and import;
- repository-owned skill and role-file installation;
- default-disabled P5 apply to an explicitly registered local Git repository.

## Excluded

- HTTP, socket, browser, or provider adapters;
- cloud accounts, API keys, login sessions, or telemetry;
- package-manager downloads or auto-update;
- hooks, launch agents, daemons, cron, scheduled lanes, or watchers;
- mail, deployment, production, or remote-service mutation;
- arbitrary shell commands in an apply plan.

## Verification Model

The release gate combines source inspection and behavioral tests. It runs default commands with an empty temporary home, explicit local state, cleared Python startup variables, and a restricted executable path. It checks for generated caches and lingering process surfaces.

The same gate is the acceptance contract for local changes and pull requests.
No hosted CI or external review service is required. Git clone, fetch, push, and
pull-request operations are explicit operator-owned network events against an
approved remote; they are outside the runtime and never occur from a PlzDo
command.

This evidence shows what the shipped code does under the tested environments. It does not claim to be a kernel sandbox or packet filter. Operators needing mandatory egress prevention should run PlzDo Local inside an OS sandbox or network-restricted environment.
