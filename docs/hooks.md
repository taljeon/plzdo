# Hooks

Hooks are optional executable checks. Copying rules, skills, and agents does not enable them. The company setup merges `hooks/settings.hooks.json` (workflow-skill-gate) into the user's Claude settings only with approval. `release-gate` has its own file, `hooks/release-gate.hooks.json`, and is not part of the company set. Hooks require `python3`; release checks also use Git.

## workflow-skill-gate

Script: `hooks/workflow-skill-gate.py`.

- `PreToolUse`, matcher `Edit|Write|MultiEdit|NotebookEdit|Bash`: blocks the first code edit until `ponytail`, `anti-slop`, and `verification-before-completion` have been loaded.
- `UserPromptSubmit`: adds a nudge to load the workflow skills.
- Internal errors: fails open, so an internal hook failure does not itself block work.

Load all three skills at the start of a code task. The rules use `ponytail` lite before editing, `anti-slop` while editing, and `verification-before-completion` before a completion claim. Loading them is not evidence that the resulting code meets its specification; the agent still has to run and inspect the project's checks.

[harness/CLAUDE.md](../harness/CLAUDE.md#workflow-skills) reports that without the gate Claude skipped the skills in 6 of 10 measured runs.

## release-gate

Script: `hooks/release-gate.py`.

- `PreToolUse`, matcher `Bash`: checks publishing commands before execution.
- Allows publishing only in the canonical forms it can check.
- Fails closed: a publishing action that cannot pass its checks is blocked.

Publishing commands with compound syntax or shell expansion are refused; publish those by hand or use `git push <remote> <branch>`. The public hook is an adapted canonical-push gate. It does not reproduce the owner's larger gate tied to private configuration.

How a push gets through:

- Only `git push <remote> <branch>` (and simple `gh pr`/`gh release` forms) are recognized. Mirror pushes, `push.default=matching` and remotes without a push URL are refused.
- A remote listed as private passes without a scan. List your company remotes in `<config>/plzdo/release-gate.json`, for example `{"private_hosts": ["github.example.com"], "private_url_prefixes": ["https://github.com/your-org/"]}`.
- Any other remote needs a release pass for that exact repository, branch, commit, remote and push URL, at most 30 minutes old (`PLZDO_PASS_TTL` seconds): run `python3 <PLZDO>/checks/scan.py --root . --release-pass --remote <remote>` from the repository, which scans the tree and writes the pass only when it is clean.

Warning: with the hook on and no `release-gate.json`, every push to any remote needs a scan pass first, and PlzDo's scanner flags absolute home-folder paths, Codex config paths and memory-tool names, so some repositories can never get a pass. Configure the private remotes before merging `hooks/release-gate.hooks.json` at work.

Passing the hook does not replace the user's approval to push, open a PR, deploy, or send data. Run the required `leak-check` preflight before public publishing as directed by the rules. This hook is scoped to Bash tool calls; it is not a claim that every possible publishing route is covered.

## Merge settings by hand

1. Keep a copy of your existing `~/.claude/settings.json` before editing it. Ask the user before changing global settings.
2. Open `hooks/settings.hooks.json`, and `hooks/release-gate.hooks.json` if you want the release gate, from the release you selected. Read its commands and the referenced scripts.
3. Replace every `{{PLZDO}}` with the absolute path of your PlzDo clone, and every `{{CONFIG}}` with your Claude config folder. In permission rules an absolute path must start with `//` (for example `Edit(//<absolute config path>/plzdo/state/**)`); `~/.claude` works for the default folder. Preserve valid JSON escaping and shell quoting for those paths.
4. Merge the hook entries into the existing `hooks` object in `settings.json`. Preserve existing events and handlers; append the selected entries to the appropriate event arrays instead of replacing the whole settings file. Avoid duplicate handlers if updating a prior copy.
5. Merge the relevant permissions from `settings/permissions.snippet.json` by hand as well, preserving existing permission rules.
6. Start a new Claude Code session. Confirm that the configured hooks can run before relying on enforcement. If a check cannot be confirmed, report it as unverified.

The hook settings reference this clone. Keep it at the configured location, or update the settings paths when moving it. See [Updating](updating.md) before changing either the scripts or their settings entries.

## If scripts are forbidden

Leave the hooks disabled. The `CLAUDE.md` text rules remain, and skills and agents can still be copied and used. There is no executable workflow-skill or release-gate enforcement.

With approval, merge the `permissions.ask` rules for `git push` from `settings/permissions.snippet.json`. They ask before the matched push commands; they do not perform the release gate's checks. Review the actual snippet rather than substituting an unverified permission pattern.
