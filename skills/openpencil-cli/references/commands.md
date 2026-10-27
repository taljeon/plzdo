# OpenPencil CLI Commands

Binary:

```bash
${OPENPENCIL_BIN:-$HOME/.local/bin/openpencil}
```

Use absolute file paths when possible.

## Baseline Inspection

```bash
${OPENPENCIL_BIN:-$HOME/.local/bin/openpencil} info /path/to/design.fig
${OPENPENCIL_BIN:-$HOME/.local/bin/openpencil} pages /path/to/design.fig
${OPENPENCIL_BIN:-$HOME/.local/bin/openpencil} tree --depth 3 /path/to/design.fig
```

## Lint

```bash
${OPENPENCIL_BIN:-$HOME/.local/bin/openpencil} lint --preset recommended /path/to/design.fig
${OPENPENCIL_BIN:-$HOME/.local/bin/openpencil} lint --preset accessibility /path/to/design.fig
${OPENPENCIL_BIN:-$HOME/.local/bin/openpencil} lint --json /path/to/design.fig
```

Prefer JSON when Codex needs to aggregate many findings.

## Query And Node Details

```bash
${OPENPENCIL_BIN:-$HOME/.local/bin/openpencil} find /path/to/design.fig --help
${OPENPENCIL_BIN:-$HOME/.local/bin/openpencil} query /path/to/design.fig --help
${OPENPENCIL_BIN:-$HOME/.local/bin/openpencil} node /path/to/design.fig --help
```

Check command-specific help before using selectors because selector syntax and argument order may vary by OpenPencil release.

## Tokens And Patterns

```bash
${OPENPENCIL_BIN:-$HOME/.local/bin/openpencil} variables /path/to/design.fig
${OPENPENCIL_BIN:-$HOME/.local/bin/openpencil} analyze /path/to/design.fig
```

Use these for design systems, colors, typography, spacing, variables, and repeated component patterns.

## Export

```bash
${OPENPENCIL_BIN:-$HOME/.local/bin/openpencil} export /path/to/design.fig --help
```

Run help first, then export to an explicit output path or directory. Do not overwrite the source document.

## Avoid By Default

Avoid these unless explicitly requested and approved:

- `selection`: can read live app state when no file is provided.
- `eval`: executes JavaScript with Figma plugin API.
- `convert`: can create writable design documents and should use explicit output paths.
