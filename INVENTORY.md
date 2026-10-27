# Inventory

Every piece of the owner's live Claude Code setup, where it came from, its license, and whether you can take it by copying files. An agent can read this file and set up a machine with its own edit tools; no script in this repository has to run.

## Status labels

| Label | Meaning |
|---|---|
| copy-ready | Copy the folder or file. Works in Claude Code with nothing else installed. |
| adapted | The owner's live file depends on Codex, a private path or a private runtime; this repo ships a self-contained Claude version. |
| needs-runtime | Copies fine, but does something only with the CLI or package named in its note. |
| manual-config | A settings fragment you merge by hand. |
| link-only | Not copied. Install it from the upstream link if you want it. |
| excluded | Not shipped and not linked: private, license forbids it, or Codex-only. |

The repository's MIT license covers only the owner's own files. Every third-party skill folder keeps its upstream license file, and every skill folder has a `SOURCE.md` with its origin.

## Company set

Rows with `yes` in the Company column form the Claude-only set: Claude Code, python3 and git, no Codex, no MCP servers, no other runtimes.

1. Rules: copy `harness/CLAUDE.md` to `~/.claude/CLAUDE.md`, or merge it into yours.
2. Skills: copy each company skill folder from `skills/` to `~/.claude/skills/`.
3. Agents: copy each company agent file from `agents/` to `~/.claude/agents/`.
4. Permissions: merge `settings/permissions.snippet.json` into `~/.claude/settings.json` (ask the user first).
5. Hooks (optional, run python3): merge `hooks/settings.hooks.json` into `~/.claude/settings.json`, replacing `{{PLZDO}}` with the absolute path of this clone. Without hooks the workflow-skill rules are advice only. The release gate is not part of the company set: merge `hooks/release-gate.hooks.json` only after listing your company remotes in `<config>/plzdo/release-gate.json`, or every push is blocked (see `docs/hooks.md`).
6. Mods: clone the repository named in `mods.lock` at its commit, check it with `mods.sha256`, and start Claude Code with `--plugin-dir <clone>`. Read the mods README first: `where-am-i` and `duo-quiz` call Haiku every turn with parts of your prompt and answer, `usage-keeper` sends prompts on its own after 55 idle minutes, and `workbench` reads Codex CLI session files from the Codex home folder.
7. Start a new session and check that the skills and agents are listed.

Skip any row whose status is `needs-runtime`, `link-only` or `excluded`.

## Items

<!-- inventory:start -->

### Skill

| Name | Company | Status | Origin | Upstream | License | Repo path | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| academic-research-router |  | needs-runtime | own | - | MIT | `skills/academic-research-router` | router into the owner's harness catalogs |
| academic-research-suite |  | link-only | vendored | github.com/Imbad0202/academic-research-skills | CC-BY-NC-4.0 | - | non-commercial license; a company's use is commercial |
| accessibility | yes | copy-ready | vendored | github.com/addyosmani/web-quality-skills | MIT | `skills/accessibility` | upstream LICENSE added |
| adaptive-project-harness | yes | adapted | own | - | MIT | `skills/adaptive-project-harness` | hn method as a document; no CLI, registry or memory runtime |
| anthropic-synced-skills |  | excluded | vendored | - | Anthropic proprietary | - | pdf, docx, pptx, xlsx and other synced skills; license forbids redistribution |
| anti-slop | yes | adapted | own | - | MIT | `skills/anti-slop` | harness quality-gate lines removed |
| apple-design | yes | copy-ready | vendored | github.com/emilkowalski/skill@2d228630ba14 | MIT | `skills/apple-design` | byte-identical; upstream LICENSE added |
| arena |  | copy-ready | modified | github.com/cursor/plugins@99743e9c151c | MIT | `skills/arena` | paths adapted |
| aside-browser |  | link-only | vendored | aside.com | proprietary | - | entry stub that installs the Aside CLI |
| astryx-design-system |  | needs-runtime | own | - | MIT | `skills/astryx-design-system` | wrapper for @astryxdesign/cli (facebook/astryx, MIT) |
| attention-span |  | copy-ready | vendored | github.com/alexgreensh/attention-span@2714c965e6be | AGPL-3.0 | `skills/attention-span` | AGPL-3.0 applies to this folder only |
| codex-primary-runtime |  | excluded | own | - | - | - | empty, Codex-only |
| copywriting |  | copy-ready | vendored | github.com/coreyhaines31/marketingskills@2.0.2 | MIT | `skills/copywriting` |  |
| crash-out | yes | copy-ready | own | - | MIT | `skills/crash-out` |  |
| cro |  | copy-ready | vendored | github.com/coreyhaines31/marketingskills@2.0.0 | MIT | `skills/cro` |  |
| cybersecurity-skill-router |  | needs-runtime | own | - | MIT | `skills/cybersecurity-skill-router` | router into mukul975/Anthropic-Cybersecurity-Skills |
| design-isms-reference | yes | copy-ready | own | - | MIT | `skills/design-isms-reference` | skill text only; download the snapshot from github.com/lidge-jun/design-isms into assets/upstream (upstream has no license) |
| design-minimal-blue-pitchdeck |  | copy-ready | unknown | - | unknown | `skills/design-minimal-blue-pitchdeck` | reference .pptx origin unconfirmed; shipped per owner decision |
| design-source-router |  | needs-runtime | own | - | MIT | `skills/design-source-router` | router into the owner's design-source catalog |
| design-spec | yes | copy-ready | own | - | MIT | `skills/design-spec` |  |
| dev-release-split |  | link-only | vendored | github.com/taljeon/plzdo-claude-mods | MIT | - | ships in the mods repo shared-skills/ |
| diagnosing-bugs | yes | copy-ready | vendored | github.com/mattpocock/skills@49dd158d1076 | MIT | `skills/diagnosing-bugs` | minimal edits, footnoted |
| emil-design-eng | yes | copy-ready | vendored | github.com/emilkowalski/skill@2d228630ba14 | MIT | `skills/emil-design-eng` | byte-identical; upstream LICENSE added |
| external-review-router |  | needs-runtime | own | - | MIT | `skills/external-review-router` | opt-in external AI review via agbrowse |
| frontend-design | yes | copy-ready | vendored | Anthropic | Apache-2.0 | `skills/frontend-design` | LICENSE.txt in folder |
| gh-address-comments |  | copy-ready | vendored | github.com/openai/skills | Apache-2.0 | `skills/gh-address-comments` |  |
| handoff | yes | copy-ready | vendored | github.com/mattpocock/skills@49dd158d1076 | MIT | `skills/handoff` | minimal edits, footnoted |
| humanize-japanese | yes | copy-ready | modified | github.com/epoko77-ai/im-not-ai | MIT | `skills/humanize-japanese` | Japanese version built on im-not-ai patterns |
| humanize-korean-codex |  | excluded | modified | - | MIT | - | Codex port of epoko77-ai/im-not-ai; Claude uses the plugin |
| hyperframes |  | needs-runtime | vendored | github.com/heygen-com/hyperframes | Apache-2.0 | `skills/hyperframes` | needs the hyperframes CLI; upstream LICENSE added |
| hyperframes-animation |  | needs-runtime | vendored | github.com/heygen-com/hyperframes | Apache-2.0 | `skills/hyperframes-animation` | needs the hyperframes CLI; upstream LICENSE added |
| hyperframes-audio |  | needs-runtime | vendored | github.com/heygen-com/hyperframes | Apache-2.0 | `skills/hyperframes-audio` | needs the hyperframes CLI; upstream LICENSE added |
| hyperframes-cli |  | needs-runtime | vendored | github.com/heygen-com/hyperframes | Apache-2.0 | `skills/hyperframes-cli` | needs the hyperframes CLI; upstream LICENSE added |
| hyperframes-core |  | needs-runtime | vendored | github.com/heygen-com/hyperframes | Apache-2.0 | `skills/hyperframes-core` | needs the hyperframes CLI; upstream LICENSE added |
| hyperframes-creative |  | needs-runtime | vendored | github.com/heygen-com/hyperframes | Apache-2.0 | `skills/hyperframes-creative` | needs the hyperframes CLI; upstream LICENSE added |
| hyperframes-keyframes |  | needs-runtime | vendored | github.com/heygen-com/hyperframes | Apache-2.0 | `skills/hyperframes-keyframes` | needs the hyperframes CLI; upstream LICENSE added |
| hyperframes-registry |  | needs-runtime | vendored | github.com/heygen-com/hyperframes | Apache-2.0 | `skills/hyperframes-registry` | needs the hyperframes CLI; upstream LICENSE added |
| hyperframes-studio |  | needs-runtime | vendored | github.com/heygen-com/hyperframes | Apache-2.0 | `skills/hyperframes-studio` | needs the hyperframes CLI; upstream LICENSE added |
| impeccable | yes | copy-ready | vendored | github.com/pbakaus/impeccable@4.5.0 | Apache-2.0 | `skills/impeccable` | upstream LICENSE added |
| implement-change | yes | adapted | own | - | MIT | `skills/implement-change` | kit-only: Claude version of the owner's codex-implement flow |
| japanese-assignment-delivery |  | excluded | own | - | - | - | personal coursework workflow |
| laya-archive |  | excluded | own | - | - | - | private project storage |
| leak-check | yes | adapted | own | - | MIT | `skills/leak-check` | bundled scanner kept; private gate paragraph removed |
| library-docs |  | copy-ready | own | - | MIT | `skills/library-docs` | patterns paraphrased from addyosmani/agent-skills and upstash/context7 (MIT) |
| local-first-coding |  | excluded | own | - | MIT | - | needs the owner's private local-model runner |
| loop-library |  | copy-ready | vendored | github.com/Forward-Future/loop-library | MIT | `skills/loop-library` | upstream LICENSE added |
| media-use |  | needs-runtime | vendored | github.com/heygen-com/hyperframes | Apache-2.0 | `skills/media-use` | needs the hyperframes CLI; upstream LICENSE added |
| motion-graphics |  | needs-runtime | vendored | github.com/heygen-com/hyperframes | Apache-2.0 | `skills/motion-graphics` | needs the hyperframes CLI; upstream LICENSE added |
| obsidian-memory-router |  | needs-runtime | own | - | MIT | `skills/obsidian-memory-router` | needs the owner's memory runtime |
| oh-my-mermaid |  | link-only | vendored | github.com/oh-my-mermaid/oh-my-mermaid | MIT | - | comes with the npm package |
| openpencil-cli |  | needs-runtime | own | - | MIT | `skills/openpencil-cli` | wrapper for the open-pencil CLI |
| ponytail | yes | copy-ready | vendored | github.com/DietrichGebert/ponytail@09c434ab73ca | MIT | `skills/ponytail` | byte-identical |
| pr-oss | yes | adapted | own | github.com/taljeon/pr-oss-skill@6931d56c29b2 | MIT | `skills/pr-oss` | pinned upstream text bundled in references/ so it works offline |
| product-marketing |  | copy-ready | vendored | github.com/coreyhaines31/marketingskills@2.1.0 | MIT | `skills/product-marketing` |  |
| project-start |  | copy-ready | own | - | MIT | `skills/project-start` |  |
| remove-ai-marks |  | copy-ready | unknown | - | unknown | `skills/remove-ai-marks` | origin unconfirmed; shipped per owner decision |
| requirements-clarification | yes | adapted | own | - | MIT | `skills/requirements-clarification` | harness source-of-truth doc inlined |
| retro | yes | copy-ready | vendored | github.com/mattpocock/skills@49dd158d1076 | MIT | `skills/retro` | minimal edits, footnoted |
| review-change | yes | adapted | own | - | MIT | `skills/review-change` | kit-only: Claude version of the owner's codex-review flow |
| screenshot |  | needs-runtime | vendored | github.com/openai/skills | Apache-2.0 | `skills/screenshot` |  |
| security-audit | yes | copy-ready | modified | github.com/cloudflare/security-audit-skill@c1c8a8c14710 | MIT | `skills/security-audit` | SKILL.md edited; other files identical |
| startup-evidence |  | copy-ready | own | - | MIT | `skills/startup-evidence` | paraphrase of ferdinandobons/startup-skill (MIT) |
| taste-guided-ui | yes | copy-ready | own | - | MIT | `skills/taste-guided-ui` | own text inspired by Leonxlnx/taste-skill (MIT) |
| team-patterns | yes | copy-ready | modified | github.com/revfactory/harness@92d9f1b | Apache-2.0 | `skills/team-patterns` | adapted text; upstream Apache-2.0 LICENSE added |
| understand | yes | adapted | modified | github.com/cursor/plugins@99743e9c151c | MIT | `skills/understand` | harness-memory source removed |
| verification-before-completion | yes | copy-ready | vendored | github.com/obra/superpowers@3be5aad3dd24 | MIT | `skills/verification-before-completion` | byte-identical |
| vision-click |  | link-only | vendored | github.com/lidge-jun/agbrowse | MIT | - | part of the agbrowse npm package (needs its browser runtime) |
| web-ai |  | link-only | vendored | github.com/lidge-jun/agbrowse | MIT | - | part of the agbrowse npm package (needs its browser runtime) |

### Agent

| Name | Company | Status | Origin | Upstream | License | Repo path | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| code-reviewer | yes | adapted | modified | github.com/msitarzewski/agency-agents | MIT | `agents/code-reviewer.md` | rules from the owner's Codex role inlined; read-only |
| coding-test-coach | yes | adapted | own | - | MIT | `agents/coding-test-coach.md` | rules from the owner's Codex role inlined |
| document-generator | yes | adapted | modified | github.com/msitarzewski/agency-agents | MIT | `agents/document-generator.md` | Claude version of the Codex role |
| explorer |  | adapted | own | - | MIT | `agents/explorer.md` | kit-only read-only search agent |
| implementer | yes | adapted | own | - | MIT | `agents/implementer.md` | kit-only worktree implementer used by implement-change |
| luna-worker | yes | adapted | own | - | MIT | `agents/luna-worker.md` | Claude version of the Codex role (live uses a fast Codex model; here haiku) |
| reality-checker | yes | adapted | modified | github.com/msitarzewski/agency-agents | MIT | `agents/reality-checker.md` | Claude version of the Codex role; read-only |
| reviewer | yes | adapted | own | - | MIT | `agents/reviewer.md` | kit-only spec reviewer used by review-change |
| technical-writer | yes | adapted | modified | github.com/msitarzewski/agency-agents | MIT | `agents/technical-writer.md` | Claude version of the Codex role |

### Hook

| Name | Company | Status | Origin | Upstream | License | Repo path | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| memory-runtime-hooks |  | excluded | own | - | - | - | private memory runtime (SessionStart, UserPromptSubmit) |
| notification-app-hooks |  | excluded | vendored | - | proprietary | - | a third-party notch notification app's hooks |
| release-gate |  | adapted | own | - | MIT | `hooks/release-gate.py` | optional at work: enable only after listing company remotes in release-gate.json; public canonical-push gate (the owner's live gate is larger and private-config-bound); python3 |
| workflow-skill-gate | yes | adapted | own | - | MIT | `hooks/workflow-skill-gate.py` | PreToolUse + UserPromptSubmit; blocks the first code edit until the three workflow skills load; python3 |

### Rule

| Name | Company | Status | Origin | Upstream | License | Repo path | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| claude-rules | yes | adapted | own | - | MIT | `harness/CLAUDE.md` | live CLAUDE.md with the shared AGENTS.md folded in; Codex routes replaced by Claude agents |
| hook-settings | yes | manual-config | own | - | MIT | `hooks/settings.hooks.json` | workflow-skill-gate entries; replace {{PLZDO}} with your clone path |
| permissions | yes | manual-config | own | - | MIT | `settings/permissions.snippet.json` | ask/deny rules to merge by hand |
| release-gate-settings |  | manual-config | own | - | MIT | `hooks/release-gate.hooks.json` | release-gate entry and its state deny rule; merge only with the release-gate hook |

### Plugin

| Name | Company | Status | Origin | Upstream | License | Repo path | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| codex-bridge |  | excluded | own | - | - | - | Codex delegation plugin; not part of the Claude-only kit |
| humanize-korean |  | link-only | vendored | github.com/epoko77-ai/im-not-ai | MIT | - | plugin 2.3.2, on in the owner's setup |
| hyperframes-plugin |  | link-only | vendored | github.com/heygen-com/hyperframes | Apache-2.0 | - | installed, off |
| inline-next-steps |  | link-only | vendored | github.com/shijieli708-ship-it/claude-mods | MIT | - | installed, off; replaced by the next-steps-pick mod |
| korean-ui |  | link-only | vendored | github.com/KimSuro5773/korean-ui | MIT | - | installed, off |
| oh-my-mermaid-plugin |  | link-only | vendored | github.com/oh-my-mermaid/oh-my-mermaid | MIT | - | installed, off |

### Mod

| Name | Company | Status | Origin | Upstream | License | Repo path | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| plzdo-claude-mods | yes | manual-config | own | github.com/taljeon/plzdo-claude-mods | MIT | `mods.lock` | 8 mods pinned in mods.lock; all load by default |

### Mcp

| Name | Company | Status | Origin | Upstream | License | Repo path | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| aside-mcp |  | link-only | vendored | aside.com | proprietary | - | browser with logins; Claude in Chrome is the substitute |
| memory-mcp |  | excluded | own | - | - | - | owner's local memory server; use Claude auto-memory instead |

<!-- inventory:end -->
