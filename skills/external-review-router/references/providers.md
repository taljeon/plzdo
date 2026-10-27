# External Review Providers

## Provider Table

| Provider | Transport | Use For | Runtime Status |
| --- | --- | --- | --- |
| `gpt-web` | `agbrowse` -> Chrome/CDP -> ChatGPT Web UI | Normal Web review using the model already selected by the operator in the UI. | Preferred Web path. It omits `--model`, records model observations when exposed, and does not claim a specific model otherwise. |
| `gpt-pro-web` | `agbrowse` -> Chrome/CDP -> GPT Pro Web UI | Reviews that specifically require verified Pro provenance. | Optional strict path. It requests Pro and blocks completion when the model cannot be observed as Pro. |
| `grok-cli` | `grok` CLI | Fast external critique, repeatable command-line review, code/design counterarguments, second-opinion summaries. | Optional. `grok` is expected to be checked at runtime; model selection is delegated to the operator-configured CLI default and recorded when observed. |
| `grok-cli-composer2.5` | `grok` CLI | Historical label for older admissions and reports. | Not accepted for new sends; reissue the admission as `grok-cli` with `modelPolicy=cli-configured`. |

## ChatGPT Web via agbrowse

Use `gpt-web` for normal ChatGPT Web review. It deliberately uses the model already selected in the UI because selector labels and menu structure can change independently of successful answer capture. Use `gpt-pro-web` only when strict Pro verification is specifically valuable.

Runtime expectations:

```text
Codex -> admitted prompt-only temp Git workspace -> agbrowse -> Chrome/CDP -> GPT Pro Web UI -> poll/result
```

Before use:

- check whether `agbrowse` is installed;
- resolve and fingerprint the exact provider executable, reject group/world-writable binaries, pass only the runner's fixed-key environment, and record post-reservation drift as a consumed failed run;
- use standing permission for normal sanitized review through the existing operator-owned ChatGPT account; ask only for a new account/provider, exceptional data, or material cost;
- set `AGBROWSE_WEB_AI_AUTO_START=0` in the admission runner so startup is visible; the active-session agent starts Chrome/CDP, navigates to ChatGPT, verifies `web-ai status=ready`, executes the review, and stops only the session it owns;
- send only sanitized text or explicitly approved files;
- store any session id or returned answer as external review evidence, not source of truth.
- approve provider retention explicitly and keep local prompt/result artifacts in the fixed external-review quarantine through no-follow directory-handle writes.
- do not claim that a `gpt-web` result used Pro merely because the account is a Pro account; record Pro only when the provider output exposes that observation.

Do not make this a default verification gate. Web UI provider behavior depends on login state, UI/DOM stability, account limits, and latency.

Local HTML/browser inspection and provider readiness checks are not themselves evidence that a review was sent. Keep browser readiness, external egress, and returned-review evidence as separate states.

## Grok CLI Configured Model

Use this provider when CLI review is enough or when repeatability matters.

Runtime expectations:

```text
Codex -> admitted prompt-only temp Git workspace -> grok CLI -> provider answer -> advisory evidence
```

Preferred command shape:

```bash
grok -p "<sanitized review prompt>" --no-memory --disable-web-search
```

Do not pass a fixed `--model` by default. The operator owns the Grok CLI model selection, so changing from composer2.5 to Grok 4.5 or a later model should not require a Meta Harness code change. Do not silently claim a specific Grok model was used; record the observed model when the CLI output exposes it, otherwise record the model policy as `cli-configured`.

Safe defaults:

- `--no-memory`
- `--disable-web-search` unless live search is explicitly useful and approved
- `--output-format plain` unless a structured answer is needed
- exact approval-bound manifest/prompt bytes and one locked run reservation before provider start
- an isolated temporary Git repository containing only the byte-identical in-memory admitted assembled prompt, created under host/global Git-config isolation because the Grok CLI may collect codebase context from its working directory
- a resolved, hashed, non-group/world-writable executable that is rechecked before spawn, plus a fixed-key environment with undeclared `GROK_*`/`XAI_*` variables omitted
- a non-empty stdout answer before a Grok run can be marked complete

Observed provider/network surfaces:

- `agbrowse` stores browser/profile/session state under `BROWSER_AGENT_HOME`, default `~/.browser-agent`.
- GPT Pro Web review uses `chatgpt.com` through the logged-in Chrome/CDP profile; conversations may persist in the provider account.
- `grok` CLI may contact provider session/model/settings/bundle endpoints even when `--no-memory` is used; do not treat `--no-memory` as a network-offline flag. Provider retention may include session metadata and submitted bundle content.
- The observed post-title session-registry/summary synchronization HTTP 404 is declared provider metadata behavior. The CLI did not expose its exact URL; a different newly observed host or category reopens N1.

Do not use:

- `--always-approve`
- `--permission-mode bypassPermissions`
- `--experimental-memory`
- repo mutation, shell tool execution, or autonomous agent permissions for review-only prompts

## Provider Selection

Use this order unless the operator asks otherwise:

1. `grok-cli` for normal critique and quick external review.
2. `gpt-web` for normal browser review using the operator's current ChatGPT UI selection.
3. `gpt-pro-web` only when verified Pro provenance is required.
4. multiple providers only for high-impact decisions where disagreement itself is useful evidence.
