#!/usr/bin/env python3
"""Workflow skill gate.

Claude Code PreToolUse(Edit|Write|MultiEdit|NotebookEdit|Bash) hook. Blocks the
first code edit of a session (or subagent) until ponytail, anti-slop and
verification-before-completion have been loaded, as CLAUDE.md asks.

Modes:
  hook      Reads the hook JSON on stdin. Exit 2 + stderr refuses, exit 0 allows.
            Internal errors exit 1 with one stderr warning, allowing the edit.
  nudge     UserPromptSubmit hook. While a skill is still unloaded, prints a
            one-line reminder (stdout becomes context) so the skills load
            before Claude plans the change, not after the gate refuses it.
            It also adds one skill-suggest line per SUGGEST pattern the prompt
            matches (review-change, handoff, humanize), unless already loaded.
            Success exits 0; internal errors exit 1 with one stderr warning.
            Never exits 2, which would reject the prompt.
  selftest  Runs the built-in checks.

A Bash command counts as a code edit when it redirects or tees into a code
file, runs sed/perl -i on one, or writes a file (open(..., 'w'), write_text)
while naming one. A subagent is checked against its own transcript, which
sits at <session>/subagents/agent-<agent_id>.jsonl next to the parent's.

Fails open: invalid input warns and allows; a missing transcript allows.
WORKFLOW_SKILL_GATE=off in Claude Code's environment turns the gate off, for
baseline measurements of a single `claude -p` run, and exits 0 in both modes.

settings.json commands (without exit-code translation wrappers):
  python3 -I -B "<PLZDO>/hooks/workflow-skill-gate.py" hook
  python3 -I -B "<PLZDO>/hooks/workflow-skill-gate.py" nudge
Keep the script at this path: Python exits 2 if it is missing.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

SKILLS = ("ponytail", "anti-slop", "verification-before-completion")
SKILL_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))) / "skills"
CODE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".kt",
    ".swift", ".rb", ".php", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".sh", ".bash",
    ".zsh", ".sql", ".vue", ".svelte", ".ipynb",
}
READER = re.compile(r"(?:^|[\s;&|(])(?:cat|head|tail|sed|less|bat)\s")
REFUSE = 2
SUFFIX = "|".join(sorted(s[1:] for s in CODE_SUFFIXES))
CODE_PATH = re.compile(rf"(?<![\w./~$-])[\w./~$-]+\.(?:{SUFFIX})\b")  # token start keeps it linear
REDIRECT = re.compile(rf"(?:>>?|\btee(?:\s+-a)?)\s*['\"]?[\w./~$-]+\.(?:{SUFFIX})\b")
IN_PLACE = re.compile(r"\b(?:sed|perl)\s+(?:-\w+\s+)*-[a-zA-Z]*i")
FILE_WRITE = re.compile(r"open\([^)]{0,200}?['\"][wax]b?\+?['\"]|write_text\(|write_bytes\(|writeFileSync\(")


def loaded_in(transcript: Path, sidechain: bool = False, skills: tuple[str, ...] = SKILLS) -> set[str]:
    """Skills loaded by an actual tool call or slash command.

    Counts Read of the file, the Skill tool, a reader command (cat, head, sed...)
    naming the skill and SKILL.md, and a user slash command. A tool call counts
    only once its result arrives without an error or permission refusal; result
    text itself never counts, since this gate's own refusal names the paths.
    Stops at the first point where all of `skills` are found.
    """
    wanted = set(skills)
    found: set[str] = set()
    pending: dict[str, set[str]] = {}
    with transcript.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or (entry.get("isSidechain") and not sidechain):
                continue
            message = entry.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if entry.get("type") == "user" and isinstance(content, str):
                found.update(re.findall(r"<command-name>/?(?:[\w-]+:)?([\w-]+)</command-name>", content))
                if found >= wanted:
                    break
                continue
            if entry.get("type") == "user" and isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        names = pending.pop(str(block.get("tool_use_id")), set())
                        if names and not failed(block):
                            found |= names
                if found >= wanted:
                    break
                continue
            if entry.get("type") != "assistant" or not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                tool_input = block.get("input") or {}
                name = block.get("name")
                names: set[str] = set()
                if name == "Skill":
                    names = {str(tool_input.get("skill", "")).split(":")[-1]}
                elif name == "Read":
                    names = set(re.findall(r"skills/([\w-]+)/SKILL\.md$", str(tool_input.get("file_path", ""))))
                elif name == "Bash":
                    command = str(tool_input.get("command", ""))
                    if "SKILL.md" in command and READER.search(command):
                        # also covers loops like `for f in ponytail anti-slop ...; do head .../$f/SKILL.md`
                        names = {n for n in wanted if re.search(rf"(?<![\w-]){n}(?![\w-])", command)}
                if names & wanted:
                    pending[str(block.get("id"))] = names & wanted
    return found & wanted


def failed(result: dict) -> bool:
    """An errored or permission-refused tool result (Claude Code marks most with is_error).

    The shell messages catch a reader loop whose last command succeeded after an
    earlier cat failed: the loop exits 0, but its output still names the miss.
    """
    if result.get("is_error"):
        return True
    text = json.dumps(result.get("content"), ensure_ascii=False)
    return any(m in text for m in ("haven't granted", "blocked by permission", "No such file or directory", "Permission denied"))


def writes_code(command: str) -> bool:
    if REDIRECT.search(command):
        return True
    names_code = CODE_PATH.search(command) is not None
    return names_code and bool(IN_PLACE.search(command) or FILE_WRITE.search(command))


def check(data: dict) -> str | None:
    """Return the refusal message, or None to allow."""
    tool_input = data.get("tool_input") or {}
    if data.get("tool_name") == "Bash":
        if not writes_code(str(tool_input.get("command") or "")):
            return None
    else:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if Path(path).suffix.lower() not in CODE_SUFFIXES:
            return None
    transcript = Path(data.get("transcript_path") or "")
    agent = re.sub(r"[^\w-]", "", str(data.get("agent_id") or ""))
    if agent:
        transcript = transcript.with_suffix("") / "subagents" / f"agent-{agent}.jsonl"
    if not transcript.is_file():
        return None
    loaded = loaded_in(transcript, sidechain=bool(agent))
    missing = [name for name in SKILLS if name not in loaded]
    if not missing:
        return None
    # The Skill tool needs no file permission; a Read of the skills directory is refused where nobody can approve it (claude -p).
    skills = "\n".join(f"- {name}" + (" (args: lite)" if name == "ponytail" else "") for name in missing)
    files = "\n".join(f"- {SKILL_DIR / name / 'SKILL.md'}" for name in missing)
    return (
        "workflow-skill-gate: before the first code edit, load the workflow skills "
        "(CLAUDE.md, Workflow skills) with the Skill tool, then retry the same edit or command:\n"
        f"{skills}\nOnly if the Skill tool is unavailable, read the files instead:\n{files}\n"
        "ponytail runs at lite level unless the user named another level."
    )


# Claude skipped the three skills in 6 of 10 measured runs without this gate.
# (loaded name, prompt pattern, excluded pattern, hint). A hint, not a gate: the model decides.
SUGGEST = (
    ("review-change", re.compile(r"리뷰해|리뷰 ?좀|코드 ?리뷰|검수|검토해|\breview", re.I), re.compile(r"(리뷰|코멘트) ?반영"),
     "this may ask for a code review: if it reviews a code change, load review-change with the Skill tool"),
    ("handoff", re.compile(r"(다음|새) ?세션.{0,20}(정리|이어|넘어|인계)|인수인계|인계 ?문서|핸드 ?오프|hand-?off", re.I), None,
     "this may ask for a handoff: load handoff with the Skill tool to write the handoff document"),
    ("humanize-korean", re.compile(r"AI ?티|사람이 쓴|학생이 쓴|번역투|윤문", re.I), None,
     "this may ask to remove AI writing patterns: for Korean text load humanize-korean:humanize-korean, "
     "for Japanese text humanize-japanese, with the Skill tool"),
)


def nudge(data: dict) -> str | None:
    """Return the prompt-time reminder, or None when nothing is missing or suggested."""
    transcript = Path(data.get("transcript_path") or "")
    exists = transcript.is_file()
    loaded = loaded_in(transcript) if exists else set()
    missing = [name for name in SKILLS if name not in loaded]
    lines = []
    if missing:
        skills = ", ".join(name + (" (args: lite)" if name == "ponytail" else "") for name in missing)
        lines.append(
            "workflow-skill-gate: if this turn will change code, load these with the Skill tool "
            f"before planning the change: {skills}. Skip them for questions, reviews and docs-only work."
        )
    prompt = str(data.get("prompt") or "")
    hits = [s for s in SUGGEST if s[1].search(prompt) and not (s[2] and s[2].search(prompt))]
    if hits:
        done = loaded_in(transcript, skills=tuple(s[0] for s in hits)) if exists else set()
        lines += [f"skill-suggest: {hint}; skip it if it does not fit." for name, _, _, hint in hits if name not in done]
    return "\n".join(lines) or None


def run_hook(mode: str) -> int:
    if os.environ.get("WORKFLOW_SKILL_GATE") == "off":
        return 0
    try:
        data = json.load(sys.stdin)
        message = nudge(data) if mode == "nudge" else check(data)
        if message and mode == "nudge":
            print(message)
        elif message:
            print(message, file=sys.stderr)
            return REFUSE
        return 0
    except Exception as exc:  # fail open, but make the error visible
        detail = " ".join(str(exc).splitlines())
        print(f"workflow-skill-gate: internal error, allowing ({type(exc).__name__}: {detail})", file=sys.stderr)
        return 1


def selftest() -> int:
    import contextlib
    import io
    import time
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        ids = iter(range(10**6))

        def lines(entries: list[dict]) -> str:
            """Each tool call is followed by its result; `fail` marks a refused one, `pending` none yet."""
            out = []
            for e in entries:
                if not isinstance(e, dict):
                    out.append(e)
                    continue
                out.append({k: v for k, v in e.items() if k not in ("fail", "pending")})
                if e.get("type") != "assistant" or e.get("pending"):
                    continue
                result = {"type": "tool_result", "tool_use_id": e["message"]["content"][0]["id"], "content": "ok"}
                if e.get("fail") == "flag":
                    result.update(is_error=True, content="Error: file not found")
                elif e.get("fail"):
                    result["content"] = "Claude requested permissions to read from x, but you haven't granted it yet."
                out.append({"type": "user", "isSidechain": e.get("isSidechain", False), "message": {"content": [result]}})
            return "\n".join(json.dumps(x) for x in out) + "\nnot json\n"

        def transcript(name: str, entries: list[dict]) -> str:
            path = root / f"{name}.jsonl"
            path.write_text(lines(entries), encoding="utf-8")
            return str(path)

        def use(tool: str, **tool_input: str) -> dict:
            return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{next(ids)}", "name": tool, "input": tool_input}]}}

        refusal = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "\n".join(
            f"- {SKILL_DIR / n / 'SKILL.md'}" for n in SKILLS)}]}}
        all_three = [
            use("Bash", command=f"cat {SKILL_DIR}/ponytail/SKILL.md"),
            use("Read", file_path=str(SKILL_DIR / "anti-slop/SKILL.md")),
            use("Skill", skill="verification-before-completion"),
        ]

        def event(session: str, path: str, entries: list[dict], **extra: str) -> dict:
            return {"session_id": session, "transcript_path": transcript(session, entries),
                    "tool_name": "Edit", "tool_input": {"file_path": path}, **extra}

        assert check(event("none", "/x/models.py", [])) is not None, "unread skills must block"
        odd = [{"type": "system", "message": "text"}, [1], all_three[0]]
        assert check(event("odd", "/x/m.py", odd)) is not None, "odd lines must not make the gate fail open"
        assert check(event("refused", "/x/models.py", [refusal])) is not None, "refusal text must not count"
        partial = check(event("partial", "/x/a.ts", all_three[:2]))
        assert partial and "verification-before-completion" in partial and "anti-slop" not in partial
        assert check(event("ok", "/x/models.py", all_three)) is None, "all three loaded must allow"
        loop = use("Bash", command=f"for f in ponytail anti-slop verification-before-completion; do head {SKILL_DIR}/$f/SKILL.md; done")
        assert check(event("loop", "/x/m.py", [loop])) is None, "reader loop over the names counts"
        fakes = [use("Write", file_path="/x/notes.md", content=" ".join(f"skills/{n}/SKILL.md" for n in SKILLS)),
                 use("Bash", command=f"rg -l x {SKILL_DIR}/*/SKILL.md # ponytail anti-slop verification-before-completion"),
                 use("Read", file_path=str(SKILL_DIR / "anti-slop/SKILL.md.bak"))]
        assert check(event("fake", "/x/m.py", fakes)) is not None, "mentions are not loads"
        slash = {"type": "user", "message": {"content": "<command-name>/anti-slop</command-name>"}}
        assert check(event("slash", "/x/m.py", [all_three[0], slash, all_three[2]])) is None
        slashes = [{"type": "user", "message": {"content": f"<command-name>/{n}</command-name>"}} for n in SKILLS]
        many = root / "many.jsonl"
        many.write_text("\n".join(json.dumps(x) for x in slashes) + "\n" + "not json\n" * 50000, encoding="utf-8")
        started = time.monotonic()
        assert loaded_in(many) == set(SKILLS) and time.monotonic() - started < 0.05, "slash commands stop the scan early"
        assert check(event("doc", "/x/README.md", [])) is None, "non-code files pass"
        assert check({"session_id": "gone", "transcript_path": "/nonexistent", "tool_input": {"file_path": "/x/m.py"}}) is None
        sidechain = dict(all_three[1], isSidechain=True)
        assert check(event("side", "/x/m.py", [all_three[0], sidechain, all_three[2]])) is not None

        parent = event("parent", "/x/m.py", all_three, agent_id="a1")
        assert check(parent) is None, "missing subagent transcript fails open"
        sub_dir = root / "parent" / "subagents"
        sub_dir.mkdir(parents=True)
        (sub_dir / "agent-a1.jsonl").write_text("", encoding="utf-8")
        assert check(parent) is not None, "parent's loads do not cover a subagent"
        (sub_dir / "agent-a1.jsonl").write_text(lines([dict(e, isSidechain=True) for e in all_three]), encoding="utf-8")
        assert check(parent) is None, "subagent's own sidechain loads count"

        denied = [dict(e, fail=True) for e in all_three]
        assert check(event("denied", "/x/m.py", denied)) is not None, "permission-refused reads do not count"
        errored = [dict(all_three[0], fail="flag"), all_three[1], all_three[2]]
        assert check(event("errored", "/x/m.py", errored)) is not None, "an errored read does not count"
        retried = denied + [use("Skill", skill=n) for n in SKILLS]
        assert check(event("retried", "/x/m.py", retried)) is None, "a successful retry counts"
        partial_loop = root / "partial-loop.jsonl"
        partial_loop.write_text("\n".join(json.dumps(x) for x in [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "L1", "name": "Bash", "input": {
                "command": f"for f in ponytail anti-slop verification-before-completion; do cat {SKILL_DIR}/$f/SKILL.md; done"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "L1", "content": [
                {"type": "text", "text": "cat: /x/ponytail/SKILL.md: No such file or directory\n---\nname: anti-slop"}]}]}},
        ]), encoding="utf-8")
        assert loaded_in(partial_loop) == set(), "a reader loop that printed a miss does not count"
        waiting = [all_three[0], all_three[1], dict(all_three[2], pending=True)]
        assert check(event("waiting", "/x/m.py", waiting)) is not None, "a call without a result yet does not count"

        first = nudge({"transcript_path": "/nonexistent"})
        assert first and all(n in first for n in SKILLS), "a session without a transcript yet gets the reminder"
        some = nudge({"transcript_path": transcript("nudge-partial", all_three[:2])})
        assert some and "verification-before-completion" in some and "anti-slop" not in some
        assert nudge({"transcript_path": transcript("nudge-ok", all_three)}) is None, "no reminder once loaded"

        def hint(prompt: str, entries: list[dict] = all_three) -> str | None:
            return nudge({"transcript_path": transcript(f"hint{next(ids)}", entries), "prompt": prompt})

        review = hint("cart.py 방금 고친 거 리뷰해줘")
        assert review and "review-change" in review and "workflow-skill-gate" not in review
        assert hint("리뷰해줘", all_three + [use("Skill", skill="review-change")]) is None, "loaded skills are not suggested again"
        assert "handoff" in (hint("다음 세션에서 바로 이어서 할 수 있게 정리해줘") or "")
        assert "humanize-japanese" in (hint("이 답안 AI티 안나게 다듬어줘") or "")
        for prompt in ("PR 리뷰 반영해줘", "새 세션에서 확인해줘", "파일 줄 수만 알려줘", ""):
            assert hint(prompt) is None, prompt
        both = nudge({"transcript_path": "/nonexistent", "prompt": "검수해봐"})
        assert both and "workflow-skill-gate" in both and "review-change" in both, "a new session gets both lines"

        def bash(session: str, command: str, entries: list[dict]) -> dict:
            return dict(event(session, "", entries), tool_name="Bash", tool_input={"command": command})

        writes = [
            "cat > report/load.py <<'EOF'\nx = 1\nEOF",
            "python3 - <<'EOF'\np='report/load.py'; s=open(p).read()\nopen(p,'w').write(s)\nEOF",
            "sed -i '' 's/a/b/' models.py",
            "python3 - <<'EOF'\nopen(\n  'a.py',\n  'w',\n).write('x')\nEOF",
            "echo x | tee -a src/app.ts",
            "python3 -c \"import pathlib; pathlib.Path('a.go').write_text('x')\"",
        ]
        reads = ["python3 monthly_report.py > out.txt 2>&1", "git diff models.py", "cat models.py | grep x",
                 "python3 -c \"print(open('a.py').read())\"", "echo hi | tee notes.md"]
        for i, command in enumerate(writes):
            assert check(bash(f"bw{i}", command, [])) is not None, command
            assert check(bash(f"bwok{i}", command, all_three)) is None, command
        for i, command in enumerate(reads):
            assert check(bash(f"br{i}", command, [])) is None, command

        def invoke(mode: str, payload: str, off: bool = False) -> tuple[int, str, str]:
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, {"WORKFLOW_SKILL_GATE": "off" if off else "on"}), \
                    patch.object(sys, "stdin", io.StringIO(payload)), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = run_hook(mode)
            return code, stdout.getvalue(), stderr.getvalue()

        refusing = event("exit-refusal", "/x/app.py", [])
        code, stdout, stderr = invoke("hook", json.dumps(refusing))
        assert code == 2 and stdout == "" and stderr == check(refusing) + "\n", "refusals must use Claude's blocking exit 2"
        assert invoke("hook", json.dumps(event("exit-allow", "/x/app.py", all_three))) == (0, "", "")
        for mode in ("hook", "nudge"):
            code, stdout, stderr = invoke(mode, "{invalid")
            assert code == 1 and stdout == "" and len(stderr.splitlines()) == 1, "malformed JSON must warn and allow"
            assert stderr.startswith("workflow-skill-gate: internal error, allowing (JSONDecodeError: ")
            assert invoke(mode, "{invalid", off=True) == (0, "", ""), "off bypasses input parsing in both modes"
        code, stdout, stderr = invoke("nudge", json.dumps({"transcript_path": "/nonexistent"}))
        assert code == 0 and stdout == first + "\n" and stderr == "", "nudge success preserves stdout context"

        def broken(data: dict) -> str:
            raise RuntimeError("injected\ninternal error")

        for mode, name in (("hook", "check"), ("nudge", "nudge")):
            with patch.dict(globals(), {name: broken}):
                assert invoke(mode, "{}") == (
                    1, "", "workflow-skill-gate: internal error, allowing (RuntimeError: injected internal error)\n"
                ), "internal errors must fail open with one warning line"
                assert invoke(mode, "{}", off=True) == (0, "", ""), "off bypasses internal work"

        started = time.monotonic()
        writes_code("python3 - <<'EOF'\n" + "a" * 262144 + ".py\nopen(p,'w')\nEOF")
        writes_code("cat x " + "open(" * 65536)
        writes_code("> " + "a/" * 131072)
        assert time.monotonic() - started < 1, "regexes must stay linear on long heredocs"
    print("workflow-skill-gate selftest: ok")
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode in ("hook", "nudge"):
        sys.exit(run_hook(mode))
    if mode == "selftest":
        sys.exit(selftest())
    print("usage: workflow-skill-gate.py hook|nudge|selftest", file=sys.stderr)
    sys.exit(64)
