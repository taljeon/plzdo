#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


STANDARD_FILES = [
    "docs/inception.md",
    "docs/requirements.md",
    "docs/technical-design.md",
    "docs/harness-generation.md",
    "AGENTS.md",
    "CHECKS.md",
    "TASKS/current.md",
    "harness/contract_check.py",
    ".gitignore",
    "scripts/harness-env.sh",
    "scripts/validate-local.sh",
    "scripts/verify-harness.sh",
]


def write_file(path: Path, content: str, *, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def backup_existing(path: Path, rel_path: str, backup_root: Path | None) -> Path | None:
    if backup_root is None or not path.exists():
        return None
    backup_path = backup_root / rel_path
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_path)
    return backup_path


def script_header() -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n"


def build_files(project: str, goal: str) -> dict[str, str]:
    return {
        "docs/inception.md": f"""# {project} Inception

## Intent

{goal}

## Users

- Primary user and daily workflow to be defined from the current task.
- Operators or maintainers who need predictable local validation.

## Non-Goals

- Do not absorb unrelated product scope.
- Do not make live APIs, credentials, private logs, or production data part of default checks.

## Operating Assumptions

- Specs and harness checks are the source of truth before implementation.
- `AGENTS.md` is the project-wide main prompt.
- `./scripts/verify-harness.sh` is the final local gate.
""",
        "docs/requirements.md": f"""# {project} Requirements

## Goal

{goal}

## Requirements

- Define user-visible behavior before implementation.
- Define acceptance criteria for each behavior.
- Keep default validation deterministic and local.
- Keep project-specific checks in the project-specific quality profile.

## Acceptance Criteria

- `AGENTS.md` names the source-of-truth order and working loop.
- `CHECKS.md` names the final deterministic command.
- `docs/technical-design.md` describes ownership boundaries and risk areas.
- `docs/harness-generation.md` defines the project-specific quality profile.
- `harness/contract_check.py` validates the generated frame.
- `./scripts/verify-harness.sh` passes without secrets, live APIs, private logs, or production data.

## Out Of Scope

- Live integration checks unless the operator explicitly opts in.
- Production writes, mail sends, deploys, or external destructive operations in the default harness.
""",
        "docs/technical-design.md": f"""# {project} Technical Design

## Architecture

- Define core modules and ownership boundaries.
- Keep orchestration, storage, UI, and scripts separated where relevant.

## Data Flow

- Describe collect -> parse -> normalize -> derive -> sync -> serve when relevant.
- Name any external integrations and whether they are mocked in the default harness.

## Harness Profile

- Common base: `AGENTS.md`, source-of-truth order, data safety, subagent routing, and final gate.
- Universal quality gates: deterministic local checks, secret isolation, no live APIs by default, no private logs, and no arbitrary package scripts.
- Project-specific quality profile: add language checks, fixture tests, integration mocks, UI checks, or deployment checks from this project's specs.
- Opt-in live checks: document real APIs, mail, deployments, or production data separately from the default final gate.

## Risks

- Security:
- Data loss:
- Duplicate writes:
- External APIs:
- Context or prompt bloat:
""",
        "docs/harness-generation.md": f"""# {project} Harness Generation

## Generation Model

Project harnesses use a shared base plus a project-specific quality profile:

1. Common base: `AGENTS.md`, source-of-truth order, data safety, subagent routing, and final gate.
2. Universal quality gates: deterministic local checks, secret isolation, no live APIs by default, no private logs, and no arbitrary package scripts.
3. Project-specific quality profile: language checks, fixture tests, integration mocks, UI checks, or deployment checks chosen from the specs.
4. Opt-in live checks: manual commands for real APIs, mail, deployments, or production data, never part of the default final gate.

## Default Safety Rules

- Use temp state from `HARNESS_DIR`.
- Do not read `.env`, auth stores, private logs, live databases, cookies, tokens, or raw personal data.
- Do not call live APIs, send mail, deploy services, or mutate production systems by default.
- Do not run arbitrary package scripts in the generated default harness.

## Project-Specific Quality Profile

- Add checks only after the relevant behavior is specified.
- Prefer fixtures, fake services, temp databases, static contract checks, and deterministic smoke tests.
- Document skipped live checks and the operator action required to run them.
""",
        "AGENTS.md": f"""# {project} Agent Guide

## Read First

- `CHECKS.md`
- `TASKS/current.md`
- `docs/inception.md`
- `docs/requirements.md`
- `docs/technical-design.md`
- `docs/harness-generation.md`

## Source Of Truth Order

1. Latest user request.
2. `TASKS/current.md` for current focus and done criteria.
3. `docs/requirements.md` for user-visible behavior and acceptance criteria.
4. `docs/technical-design.md` for ownership boundaries and validation design.
5. `AGENTS.md` for project-wide operating rules.
6. `CHECKS.md` for deterministic verification commands.

## Product Rules

- Specs are the source of truth.
- Harness checks must be safe and repeatable.
- Manual operations must not be blocked by automation failures.
- Use the common base plus project-specific quality profile in `docs/harness-generation.md`.

## Always-On Engineering Discipline

This section embeds the complete Karpathy-style guideline set as always-on behavior. It is general engineering discipline, not project-specific policy.

Tradeoff: these rules bias toward caution over speed. For trivial one-line tasks, use judgment.

### 1. Think Before Coding

Do not assume. Do not hide confusion. Surface tradeoffs.

Before implementing:

- State assumptions explicitly. If an assumption is unsafe, ask.
- If multiple interpretations exist, present them instead of silently choosing one.
- If a simpler approach exists, say so and push back when warranted.
- If something is unclear, stop, name what is unclear, and ask.

### 2. Simplicity First

Use the minimum code and process that solves the requested problem. Do not add speculative capability.

- Do not add features beyond what was asked.
- Do not add abstractions for single-use code.
- Do not add flexibility or configurability that was not requested.
- Do not add defensive handling for scenarios that cannot happen in this project.
- If the solution is much larger than the problem requires, simplify it before finishing.

### 3. Surgical Changes

Touch only what the task requires. Clean up only work created by this change.

When editing existing code:

- Do not improve adjacent code, comments, or formatting just because it is nearby.
- Do not refactor things that are not broken.
- Match the existing project style, even when a different style would be preferred elsewhere.
- If unrelated dead code or drift is noticed, mention it instead of deleting it.

When this change creates orphans:

- Remove imports, variables, functions, fixtures, or docs made unused by this change.
- Do not remove pre-existing dead code unless explicitly asked.

Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

Define success criteria and loop until they are verified.

- Turn "add validation" into "add checks for invalid inputs, then make them pass."
- Turn "fix the bug" into "reproduce the bug with a check, then make the check pass."
- Turn "refactor this" into "show the behavior still passes before and after."

For multi-step tasks, state a brief plan with a verification target per step:

1. Step: do the scoped change. Verify: named check.
2. Step: update the contract or docs. Verify: named check.
3. Step: run final validation. Verify: final gate.

Strong success criteria let the agent work independently. Weak criteria require clarification before implementation.

## Coach-Inspired Harness Quality

- Prompt quality: specs, acceptance criteria, file references, and clear constraints exist.
- Session hygiene: `TASKS/current.md` is focused and final reports include checks and skipped checks.
- Code review: reviewer checks security, regression, data loss, duplicate writes, and spec drift.
- Tool mastery: use relevant skills/subagents when they materially reduce risk.
- Context management: keep always-on rules useful and move project-specific detail into scoped docs.

## Data Safety

- Do not read or print secrets, credentials, session state, or live personal data unless explicitly requested.
- Do not pass secrets, raw personal data, live DB contents, auth stores, cookies, or token files to subagents unless explicitly requested.
- Prefer fixtures and temp state for checks.

## Working Loop

1. Read the task frame and governing docs.
2. Inspect only needed files.
3. Use subagents automatically for large, risky, or multi-file work; keep small work local.
4. Make scoped edits.
5. Run `./scripts/verify-harness.sh`.
6. Report changed files, checks, skipped checks, operator impact, and residual risk.

## Subagent Operating Model

- Main agent: orchestrator, final scope, final integration, final report.
- `explorer`: read-only structure, architecture, and data-flow analysis.
- `worker`: exact file ownership and non-overlapping implementation scope.
- `reviewer`: security, regression, data loss, duplicate writes, and spec drift.
- `tester`: `CHECKS.md` validation and skipped-check reporting.
- `release-preflight`: public-release leak/security review before GitHub, portfolio, package, or external handoff.

Use subagents by default when a task touches auth, payments, personal data, mail/calendar sync, data migration, deletion, duplicate writes, public release, or several modules.

## Subagent Routing

- `explorer`: structure and flow only.
- `worker`: scoped implementation.
- `reviewer`: security, regression, data loss.
- `tester`: `CHECKS.md` validation.
""",
        "CHECKS.md": """# Checks

## Standard

- `./scripts/verify-harness.sh`

## Local

- `./scripts/validate-local.sh`

## Coverage

- Required project-start source-of-truth files exist.
- Validation scripts source `scripts/harness-env.sh`.
- `python3 harness/contract_check.py` validates the generated frame.
- Scripts are executable.
- Default generated harness avoids arbitrary package scripts, live APIs, credentials, private logs, and production data.
- Project-specific checks should be added to this file when implementation begins.

## Notes

- Checks must not require secrets or live production data by default.
- If a check is skipped, explain why in the final response.
""",
        ".gitignore": """.DS_Store
.env
.env.*
!.env.example
auth/
data/
logs/
playwright/.auth/
*.db
*.sqlite
*.sqlite3
*.zip
env.production*
*token*.json
*credentials*.json
.context_summary.md
.project-start-backup/
__pycache__/
.pytest_cache/
.venv/
node_modules/
dist/
build/
""",
        "TASKS/current.md": f"""# Current Task Frame

## Current Focus

- {goal}

## Done When

- Specs reflect the intended behavior.
- Harness covers the risky behavior through the common base plus project-specific quality profile.
- Relevant checks pass.
- Skipped live checks and remaining risks are called out.

## Recommended Agent Split

- `explorer`: structure and flow only.
- `worker`: scoped implementation.
- `reviewer`: security, regression, data loss.
- `tester`: `CHECKS.md` validation.
""",
        "harness/contract_check.py": """#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


REQUIRED_FILES = [
    "AGENTS.md",
    "CHECKS.md",
    "TASKS/current.md",
    "docs/inception.md",
    "docs/requirements.md",
    "docs/technical-design.md",
    "docs/harness-generation.md",
    ".gitignore",
    "harness/contract_check.py",
    "scripts/harness-env.sh",
    "scripts/validate-local.sh",
    "scripts/verify-harness.sh",
]


TOKEN_CHECKS = {
    "AGENTS.md": [
        "Source Of Truth Order",
        "Always-On Engineering Discipline",
        "complete Karpathy-style guideline set",
        "Think Before Coding",
        "Simplicity First",
        "Surgical Changes",
        "Goal-Driven Execution",
        "Do not add features beyond what was asked",
        "Every changed line should trace directly",
        "Coach-Inspired Harness Quality",
        "Do not pass secrets",
        "./scripts/verify-harness.sh",
    ],
    "CHECKS.md": [
        "./scripts/verify-harness.sh",
        "python3 harness/contract_check.py",
        "Required project-start source-of-truth files exist",
        "Validation scripts source `scripts/harness-env.sh`",
    ],
    "docs/requirements.md": [
        "Acceptance Criteria",
        "Keep default validation deterministic and local",
        "project-specific quality profile",
    ],
    "docs/technical-design.md": [
        "Harness Profile",
        "Universal quality gates",
        "Project-specific quality profile",
        "Opt-in live checks",
    ],
    "docs/harness-generation.md": [
        "Generation Model",
        "Common base",
        "Universal quality gates",
        "Project-specific quality profile",
        "Opt-in live checks",
        "HARNESS_DIR",
        "Do not run arbitrary package scripts",
    ],
}


IGNORE_TOKENS = [
    ".env",
    "auth/",
    "data/",
    "playwright/.auth/",
    "*.db",
    "*token*.json",
    "*credentials*.json",
    "__pycache__/",
    ".venv/",
    "node_modules/",
    "dist/",
    "build/",
    ".project-start-backup/",
]


FORBIDDEN_DEFAULT_COMMANDS = re.compile(
    r"\\b(npm\\s+run|curl\\s|wget\\s|gh\\s|gcloud\\s|firebase\\s|pip\\s+install|sendmail\\s|deploy\\s)",
    re.IGNORECASE,
)


def main() -> int:
    failures: list[str] = []

    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            failures.append(f"missing required file: {rel}")

    for rel, tokens in TOKEN_CHECKS.items():
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for token in tokens:
            if token not in text:
                failures.append(f"{rel} missing token: {token}")

    agents = ROOT / "AGENTS.md"
    if agents.exists() and agents.stat().st_size > 9000:
        failures.append("AGENTS.md exceeds prompt budget of 9000 bytes")

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8") if (ROOT / ".gitignore").exists() else ""
    for token in IGNORE_TOKENS:
        if token not in gitignore:
            failures.append(f".gitignore missing safety ignore: {token}")

    validate = ROOT / "scripts" / "validate-local.sh"
    verify = ROOT / "scripts" / "verify-harness.sh"
    harness_env = ROOT / "scripts" / "harness-env.sh"

    if validate.exists():
        text = validate.read_text(encoding="utf-8")
        if "harness-env.sh" not in text:
            failures.append("scripts/validate-local.sh must source harness-env.sh")
        if "python3 harness/contract_check.py" not in text:
            failures.append("scripts/validate-local.sh must run python3 harness/contract_check.py")
        if FORBIDDEN_DEFAULT_COMMANDS.search(text):
            failures.append("scripts/validate-local.sh contains forbidden default command")

    if verify.exists():
        text = verify.read_text(encoding="utf-8")
        if "scripts/validate-local.sh" not in text:
            failures.append("scripts/verify-harness.sh must call scripts/validate-local.sh")
        if FORBIDDEN_DEFAULT_COMMANDS.search(text):
            failures.append("scripts/verify-harness.sh contains forbidden default command")

    for script in (validate, verify, harness_env):
        if script.exists() and not os.access(script, os.X_OK):
            failures.append(f"script is not executable: {script.relative_to(ROOT)}")

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("contract check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
""",
        "scripts/harness-env.sh": script_header()
        + """ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARNESS_DIR="${HARNESS_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/project-harness.XXXXXX")}"
export HARNESS_DIR
export PROJECT_DB_PATH="$HARNESS_DIR/project.db"
export PROJECT_BLOB_DIR="$HARNESS_DIR/blobs"
mkdir -p "$PROJECT_BLOB_DIR"
""",
        "scripts/validate-local.sh": script_header()
        + """. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/harness-env.sh"
cd "$ROOT_DIR"

python3 -c "import ast, pathlib; ast.parse(pathlib.Path('harness/contract_check.py').read_text(encoding='utf-8'))"
python3 harness/contract_check.py
echo "local validation passed"
""",
        "scripts/verify-harness.sh": script_header()
        + """. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/harness-env.sh"
cd "$ROOT_DIR"

"$ROOT_DIR/scripts/validate-local.sh"
echo "harness verification passed"
""",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap a Codex project-start frame.")
    parser.add_argument("--root", required=True, help="Project root directory")
    parser.add_argument("--project-name", required=True, help="Project display name")
    parser.add_argument("--goal", default="Define the project and make it verifiable.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing managed files after backing them up")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    project = args.project_name.strip()
    goal = args.goal.strip()
    force = bool(args.force)

    files = build_files(project, goal)
    created: list[str] = []
    skipped: list[str] = []
    backups: list[str] = []
    backup_root = None
    if force:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_root = root / ".project-start-backup" / stamp

    for rel_path in STANDARD_FILES:
        path = root / rel_path
        backup_path = backup_existing(path, rel_path, backup_root)
        if backup_path is not None:
            backups.append(str(backup_path.relative_to(root)))
        if write_file(path, files[rel_path], force=force):
            created.append(rel_path)
            if rel_path.startswith("scripts/"):
                path.chmod(0o755)
        else:
            skipped.append(rel_path)

    print(f"root={root}")
    print("created=" + (",".join(created) if created else "none"))
    print("skipped_existing=" + (",".join(skipped) if skipped else "none"))
    print("backed_up=" + (",".join(backups) if backups else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
