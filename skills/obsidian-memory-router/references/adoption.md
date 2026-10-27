# Obsidian Skills Adoption

## Reviewed Source

`kepano/obsidian-skills` was cloned under `/private/tmp/meta-harness-source-audit/obsidian-skills`.

The repo contains five skills:

- `obsidian-markdown`: Obsidian-flavored Markdown, wikilinks, embeds, callouts, properties.
- `obsidian-bases`: `.base` YAML views, filters, formulas, summaries.
- `json-canvas`: `.canvas` JSON nodes, edges, groups, validation.
- `obsidian-cli`: live Obsidian CLI for read/create/search/properties plus plugin/theme development.
- `defuddle`: clean markdown extraction from web pages to save tokens.

## Meta Harness Decision

Absorb syntax and routing patterns. Do not globally install all Obsidian skills by default because:

- `obsidian-cli` can mutate the focused vault and plugin/theme state;
- the Meta Harness already has a stable memory CLI and vault write guards;
- full vault operations can accidentally read or store private material.

Use this router for safe default behavior:

- memory retrieval: facts/index first, active matching notes only;
- memory write: sanitized `ai_knowledge`, no full documents;
- note authoring: allowed only for user-requested files and safe paths;
- live Obsidian CLI: approval-required.

## Useful Patterns

- Use Obsidian wikilinks only for internal vault note links.
- Validate `.canvas` as JSON and ensure all edge node IDs exist.
- Validate `.base` as YAML and quote formula/filter strings carefully.
- Use Defuddle-like extraction as a context optimization pattern, but do not install npm packages by default.
