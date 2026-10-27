# PlzDo

PlzDo mirrors one person's (the owner's) Claude Code setup so a company machine or a new laptop can take it by copying files. It contains rules, skills, Claude agents, optional hooks, settings fragments, and a pointer to the owner's mods. There is no installer, and taking the rules, skills, and agents does not require running repository scripts. [INVENTORY.md](INVENTORY.md) describes each item's status and the company set.

## Requirements

- Claude Code for the rules, skills, and agents. Copying these files needs no additional runtime.
- `python3` and `git` for the hooks/mods setup. Hooks require permission to execute scripts; mods run code when loaded.
- Git is also used by the clone route below and by the implementation workflow's worktrees. Individual projects still need their own development tools.

The company set needs no Codex, MCP servers, or other runtimes. Outside that set, check each item's status and dependency note. Skip `needs-runtime`, `link-only`, and `excluded` items when following the company setup.

## Three ways to take it

### Copy one skill or agent

Choose an item in the inventory. Copy a whole skill folder from `skills/<name>/` to `~/.claude/skills/<name>/`, including its references, `SOURCE.md`, and license. Agents are individual Markdown files: copy the selected file from `agents/` to `~/.claude/agents/`. Start a new Claude Code session and check that the item is listed.

Check the item's dependencies before using it on its own. For example, `review-change` calls both `reviewer` and `code-reviewer`; copying only the skill does not copy those agents.

### Clone a release and take the company set

Choose a published tag from [Releases](https://github.com/taljeon/plzdo/releases), replacing `<release-tag>` below:

```sh
git clone --branch <release-tag> --depth 1 https://github.com/taljeon/plzdo.git
cd plzdo
```

Follow the [Company set](INVENTORY.md#company-set) steps in order. Copy or merge the rules, copy the company skills and agents, and merge settings by hand. Enable hooks only where scripts are allowed. Record the tag you applied; see [Updating](docs/updating.md) for later changes.

### Ask an agent to copy it

Give an agent access to the checkout and this instruction:

> Read INVENTORY.md and set up the company set; ask me before changing settings.json

The agent can copy files with its own edit tools. No repository installer or export script is needed. It should report what it copied, merged, or skipped, and ask before settings changes.

## Layers

Rules in `harness/CLAUDE.md` -> skills in `skills/` -> Claude agents in `agents/` -> optional hooks in `hooks/` -> mods from a separate repository.

Rules define the lead engineer's responsibilities and when to act or ask. Skills define task workflows, agents handle delegated work, hooks check tool actions, and mods add session behavior. The [architecture guide](docs/architecture.md) explains the flow and the `hn` method. [Hook setup](docs/hooks.md) explains enforcement; `settings/` holds fragments to merge, and `maintainer/` holds owner-side export tools.

## Mods and data flow

The mods come from [taljeon/plzdo-claude-mods](https://github.com/taljeon/plzdo-claude-mods), pinned in `mods.lock`. All 8 mods load by default. Company set step 6 states:

> Mods: clone the repository named in `mods.lock` at its commit, check it with `mods.sha256`, and start Claude Code with `--plugin-dir <clone>`. Read the mods README first: `where-am-i` and `duo-quiz` call Haiku every turn with parts of your prompt and answer, `usage-keeper` sends prompts on its own after 55 idle minutes, and `workbench` reads Codex CLI session files from the Codex home folder.

## What is not included

- Codex delegation and its adapter: the kit uses Claude agents, so second-model review becomes same-model review.
- The owner's memory runtime and private hooks: they depend on private infrastructure. The rules point to Claude Code's built-in auto-memory instead.
- Private projects, storage configuration, and personal project data: they are outside the portable setup.
- Anthropic's proprietary synced skills: their licenses forbid redistribution. This exclusion does not cover separately licensed open-source skills listed in the inventory.

## Licensing

The repository's MIT license applies only to the owner's files. Each third-party skill folder keeps its upstream license, and each skill folder carries a `SOURCE.md` describing its origin and adaptations. Check the inventory's license and origin fields before copying material.

`attention-span` is AGPL-3.0 and stays in its own folder. Its text is not inlined into the shipped rules. `academic-research-suite` is link-only because its CC BY-NC-4.0 license restricts commercial use; it is not bundled with the company set.

The export manifest marks the origin and license of `design-minimal-blue-pitchdeck` and `remove-ai-marks` as unknown. Neither belongs to the company set; the repository MIT license does not resolve those unknowns.

## Earlier versions

The 0.x releases were **PlzDo Local**. Version 1.0.0 replaces that content with this copy-based Claude Code setup. See [CHANGELOG.md](CHANGELOG.md) for the rewrite and [Updating](docs/updating.md) before moving an existing local copy.
