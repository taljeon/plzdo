from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
# Split so the published tree holds no token-shaped string.
TOKEN_SAMPLE = ("ghp" + "_FAKE0123456789FAKE0123456789FAKE0123456789\n").encode()


class HookCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.config = self.base / "config"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "PLZDO_", "GH_"))}
        self.env.update(CLAUDE_CONFIG_DIR=str(self.config), HOME=str(self.base),
                        GIT_CONFIG_NOSYSTEM="1", XDG_CONFIG_HOME=str(self.base / "xdg"), TMPDIR=str(self.base))
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test Worker")
        self.git("config", "user.email", "worker@example.com")
        (self.repo / "file.txt").write_text("clean\n")
        self.git("add", ".")
        self.git("commit", "-m", "initial")
        self.remote = self.base / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)], env=self.env,
                       capture_output=True, check=True)
        self.git("remote", "add", "origin", str(self.remote))
        self.pass_file = self.config / "plzdo" / "state" / "release-pass.json"

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], env=self.env,
                              text=True, capture_output=True, check=True).stdout.strip()

    def invoke(self, script, payload):
        raw = json.dumps(payload) if not isinstance(payload, str) else payload
        return subprocess.run([sys.executable, str(ROOT / "hooks" / script)],
                              input=raw, env=self.env, text=True, capture_output=True, timeout=10)

    def gate(self, command="git push origin main", cwd=None):
        result = self.invoke("release-gate.py", {"tool_name": "Bash", "cwd": str(cwd or self.repo),
                                               "tool_input": {"command": command}})
        if result.stdout:
            decision = json.loads(result.stdout)["hookSpecificOutput"].get("permissionDecision")
            self.assertNotIn(decision, ("allow", "ask"))
        return result

    def deny(self, command="git push origin main", cwd=None):
        result = self.gate(command, cwd)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(value["permissionDecision"], "deny")
        self.assertIn("canonical form: git push <remote> <branch>", value["permissionDecisionReason"])
        return value

    def quiet(self, command="git push origin main", cwd=None):
        result = self.gate(command, cwd)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def write_pass(self, **updates):
        value = {"version": 2, "repo": str(self.repo.resolve()), "commit": self.git("rev-parse", "HEAD"),
                 "ref": "refs/heads/main", "remote": "origin",
                 "push_urls": sorted(self.git("remote", "get-url", "--push", "--all", "origin").splitlines()), "created": time.time()}
        value.update(updates)
        self.pass_file.parent.mkdir(parents=True, exist_ok=True)
        self.pass_file.write_text(json.dumps(value))

    def scan(self, *args, root=None):
        return subprocess.run([sys.executable, str(ROOT / "checks" / "scan.py"), "--release-pass",
                               "--root", str(root or self.repo), *args], env=self.env,
                              text=True, capture_output=True, timeout=10)


class ReleaseGateTests(HookCase):
    def test_canonical_push_options(self):
        self.write_pass()
        for command in ("git push origin main", "git push -u origin main",
                        "git push --set-upstream origin refs/heads/main"):
            with self.subTest(command=command):
                self.quiet(command)

    def test_wrappers_and_compound_commands_denied_with_pass(self):
        self.write_pass()
        commands = (
            "git add . && git commit -qm x && git push origin main",
            "command git push origin main", "env git push origin main",
            "(git push origin main)", "{ git push origin main; }",
            'sh -c "git push origin main"', "echo $(git push origin main)",
            "git${IFS}push origin main", "git$IFS push origin main",
            "git pu\\\nsh origin main", ": a#b; git push origin main",
            "git -c alias.p=push p origin main", "git --attr-source HEAD push origin main",
            "cd ../other && git push origin main", "GIT_DIR=x git push origin main",
            "git pu\\sh origin main", "'git' push origin main",
            "git push origin main # comment", "git push origin main > out",
            "git push origin main < input", "git push origin main &",
            "git push origin main | cat", "git push origin main\n",
            "git push origin `echo main`",
        )
        for command in commands:
            with self.subTest(command=command):
                self.deny(command)

    def test_noncanonical_push_arguments(self):
        self.write_pass()
        for args in ("--mirr origin", "--al origin", "origin", "origin HEAD",
                     "origin main:other", "-f origin main", "-- origin main",
                     str(self.remote) + " main"):
            with self.subTest(args=args):
                self.deny("git push " + args)

    def test_normalized_publish_intent(self):
        for command in ("echo push", "echo 'git push'", "gh pr view",
                        "gh repo edit --description hi", "g'h' api repos/o/r",
                        "gh --hostname example.com release list"):
            with self.subTest(command=command):
                self.deny(command)

    def test_git_environment_denied(self):
        self.write_pass()
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG_COUNT",
                     "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_GLOBAL"):
            with self.subTest(name=name):
                self.env[name] = ""
                self.deny()
                del self.env[name]

    def test_destination_config_denied(self):
        self.write_pass()
        for key, value in (("remote.origin.pushurl", str(self.base / "other.git")),
                           ("url.https://example.com/.pushInsteadOf", str(self.base)),
                           ("url.https://example.com/.insteadOf", str(self.base)),
                           ("remote.origin.push", "other"),
                           ("remote.origin.mirror", "true"), ("push.default", "matching")):
            with self.subTest(key=key):
                self.git("config", key, value)
                self.write_pass()
                self.deny()
                self.git("config", "--unset-all", key)

    def test_push_urls_bind_all_destinations(self):
        self.git("remote", "set-url", "origin", str(self.base / "z.git"))
        self.git("config", "--add", "remote.origin.url", str(self.base / "a.git"))
        result = self.scan("--remote", "origin")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(self.pass_file.read_text())["push_urls"],
                         [str(self.base / "a.git"), str(self.base / "z.git")])
        self.quiet()
        self.write_pass(push_urls=[str(self.base / "a.git")])
        self.deny()

    def test_tag_cannot_shadow_branch(self):
        self.write_pass()
        self.git("tag", "main")
        (self.repo / "file.txt").write_text("ahead\n")
        self.git("commit", "-am", "ahead")
        self.deny("git push origin refs/heads/main")

    def test_gh_noncanonical_commands(self):
        self.write_pass()
        for command in ("gh pr new", "gh release create v1", "gh repo create x --public=true",
                        "gh api -X PATCH repos/o/r -f visibility=public", "gh pr create -R o/r",
                        "gh pr create --repo o/r", "gh pr create -H other",
                        "gh pr create --head other", "gh pr create --web",
                        "gh pr create --title", "gh pr create extra"):
            with self.subTest(command=command):
                self.deny(command)
        self.env["GH_REPO"] = "o/r"
        self.deny("gh pr create")

    def test_gh_canonical_options(self):
        self.write_pass()
        self.quiet('gh pr create --title "two words" --body b --base main --draft --fill')
        self.quiet("gh pr create -t t -b b -B main -d -F body.txt")
        self.quiet("gh pr create --body-file body.txt")

    def test_private_prefix_boundary(self):
        self.private_config({"private_url_prefixes": ["https://git.corp.example"]})
        for url in ("https://git.corp.example", "https://git.corp.example/x",
                    "https://git.corp.example:443/x"):
            self.git("remote", "set-url", "origin", url)
            self.quiet()
        self.git("remote", "set-url", "origin", "https://git.corp.example.attacker.com/x")
        self.deny()

    def test_private_skip_requires_every_push_url(self):
        self.private_config({"private_hosts": ["git.corp.example"]})
        self.git("remote", "set-url", "origin", "https://git.corp.example/x")
        self.git("config", "--add", "remote.origin.url", "https://git.corp.example/a")
        self.quiet()
        self.git("config", "--add", "remote.origin.url", "https://example.com/public")
        self.deny()

    def test_symlink_loop_and_git_exception_fail_closed(self):
        loop = self.base / "loop"
        loop.symlink_to("loop")
        self.deny("git -C loop/x push")
        result = self.gate(cwd=loop / "x")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(result.stderr.splitlines()), 1)

    def test_non_publish_is_quiet(self):
        for command in ("git status", "pushd /tmp", "popd", "echo '", "echo gh", "echo repo"):
            with self.subTest(command=command):
                self.quiet(command)

    def test_missing_pass_denied(self):
        self.deny()

    def test_stale_pass_denied(self):
        self.write_pass(created=time.time() - 1900)
        self.deny()

    def test_each_binding_must_match(self):
        for field, value in (("commit", "0" * 40), ("ref", "refs/heads/other"), ("push_urls", ["https://example.org/other.git"]),
                             ("remote", "other"), ("repo", str(self.base)), ("version", 1), ("version", True)):
            with self.subTest(field=field):
                self.write_pass(**{field: value})
                self.deny()

    def test_fresh_pass_is_silent(self):
        self.write_pass()
        self.quiet()

    def test_custom_ttl_and_future_timestamp(self):
        self.env["PLZDO_PASS_TTL"] = "5"
        for created in (time.time() - 6, time.time() + 60, "yesterday", float("nan")):
            with self.subTest(created=created):
                self.write_pass(created=created)
                self.deny()
        self.write_pass()
        self.quiet()

    def test_malformed_pass_denied(self):
        self.write_pass()
        for text in ("{", "[]", "null"):
            self.pass_file.write_text(text)
            self.deny()

    def private_config(self, value):
        path = self.config / "plzdo" / "release-gate.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def test_private_host_exact_match(self):
        self.private_config({"private_hosts": ["git.corp.example"]})
        self.git("remote", "set-url", "origin", "https://git.corp.example/team/repo.git")
        self.quiet()
        self.git("remote", "set-url", "origin", "https://git.corp.example.attacker.example/team/repo.git")
        self.deny()

    def test_private_scp_host_and_prefix(self):
        url = "git@example.com:private/repo.git"
        self.git("remote", "set-url", "origin", url)
        self.private_config({"private_hosts": ["example.com"]})
        self.quiet()
        self.private_config({"private_url_prefixes": ["git@example.com:private/"]})
        self.quiet()
        self.private_config({"private_url_prefixes": [""]})
        self.deny()

    def test_unreadable_private_config_is_public(self):
        self.private_config({})
        path = self.config / "plzdo" / "release-gate.json"
        for text in ("{", "[]", '{"private_hosts": "example.com"}'):
            path.write_text(text)
            self.deny()

    def test_publish_variants_are_caught(self):
        commands = [f"git -C {shlex.quote(str(self.repo))} push", "FOO=1 git push",
                    "echo x && git push origin main", "echo x || git push", "echo x; git push", "echo x | git push",
                    "echo x\ngit push", "git -c core.quotepath=false push", "git --git-dir=.git push",
                    "gh pr create", "gh repo edit --visibility public", "gh repo edit --visibility=public",
                    "gh release create", "gh release upload", "gh release edit", "gh repo create --public"]
        for command in commands:
            with self.subTest(command=command):
                self.deny(command)

    def test_git_c_from_another_directory(self):
        command = f"git -C {shlex.quote(str(self.repo))} push origin main"
        self.deny(command, self.base)
        self.write_pass()
        self.deny(command, self.base)
        self.deny("git -C repo push origin main", self.base)

    def test_head_and_full_refspec(self):
        self.write_pass()
        for ref in ("main", "refs/heads/main"):
            self.quiet("git push origin " + ref)
        for ref in ("HEAD", "+refs/heads/main:refs/heads/published"):
            self.deny("git push origin " + ref)

    def test_configured_remote(self):
        self.git("remote", "add", "company", "https://example.org/team/repo.git")
        self.git("config", "branch.main.remote", "company")
        self.write_pass(remote="company", push_urls=[self.git("remote", "get-url", "company")])
        self.quiet("git push company main")
        self.deny("git push origin main")

    def test_ref_source_commit_is_resolved(self):
        self.git("branch", "old")
        (self.repo / "file.txt").write_text("new\n")
        self.git("commit", "-am", "second")
        self.write_pass()
        self.deny("git push origin old")
        self.write_pass(ref="refs/heads/old", commit=self.git("rev-parse", "old"))
        self.quiet("git push origin old")

    def test_gh_matching_pass(self):
        self.write_pass()
        for command in ("gh pr create", "gh pr create --title t --body b"):
            self.quiet(command)

    def test_shlex_failure_is_closed_for_publish(self):
        self.deny("git push '")
        self.quiet("echo '")

    def test_git_resolution_error_denies(self):
        self.write_pass()
        value = self.deny("git push missing main")
        self.assertIn("configured remote", value["permissionDecisionReason"])
        self.deny("git push origin missing")
        self.deny(cwd=self.base)

    def test_quoted_separator_is_a_git_argument(self):
        self.deny("git -C ';' push")
        self.deny("echo 'x && y'; git push")
        self.quiet("echo ';'")

    def test_multiple_refs_and_bulk_push_denied(self):
        self.write_pass()
        for args in ("origin main main:other", "--mirror", "--all", "--tags", "origin :main", "origin '*:*'"):
            self.deny("git push " + args)

    def test_invalid_stdin_crashes(self):
        for payload in ("{", "[]", "null", {"tool_name": "Bash"}):
            with self.subTest(payload=payload):
                result = self.invoke("release-gate.py", payload)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertEqual(len(result.stderr.splitlines()), 1)
                self.assertNotIn("Traceback", result.stderr)

    def test_settings_contract(self):
        text = (ROOT / "hooks" / "settings.hooks.json").read_text()
        self.assertNotIn("allow", text)
        value = json.loads(text)
        [entry] = value["hooks"]["PreToolUse"]
        self.assertEqual(entry["hooks"][0]["timeout"], 10)
        self.assertEqual(entry["hooks"][0]["command"],
                         'python3 -I -B "{{PLZDO}}/hooks/workflow-skill-gate.py" hook')
        self.assertEqual(entry["matcher"], "Edit|Write|MultiEdit|NotebookEdit|Bash")
        prompt = value["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        self.assertEqual(prompt["command"], 'python3 -I -B "{{PLZDO}}/hooks/workflow-skill-gate.py" nudge')
        self.assertEqual(prompt["timeout"], 10)
        self.assertNotIn("permissions", value)

    def test_release_gate_settings_contract(self):
        text = (ROOT / "hooks" / "release-gate.hooks.json").read_text()
        self.assertNotIn("allow", text)
        value = json.loads(text)
        [entry] = value["hooks"]["PreToolUse"]
        self.assertEqual(entry["matcher"], "Bash")
        self.assertEqual(entry["hooks"][0]["command"], 'python3 "{{PLZDO}}/hooks/release-gate.py"')
        self.assertEqual(entry["hooks"][0]["onFailure"], "block")
        self.assertEqual(entry["hooks"][0]["timeout"], 30)
        # Edit rules cover every built-in file tool; a Write rule only triggers a settings warning.
        self.assertEqual(value["permissions"]["deny"], ["Edit({{CONFIG}}/plzdo/state/**)"])


class ReleasePassTests(HookCase):
    def add_token(self, path="secret.txt", prefix=b""):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(prefix + TOKEN_SAMPLE)
        self.git("add", "-f", path)
        self.git("commit", "-m", "sample")
        return self.git("rev-parse", "HEAD")

    def test_hidden_index_flags_refused(self):
        for flag in ("assume-unchanged", "skip-worktree"):
            with self.subTest(flag=flag):
                self.git("update-index", "--" + flag, "file.txt")
                self.assertEqual(self.git("status", "--porcelain"), "")
                result = self.scan("--remote", "origin")
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("index flags", result.stdout)
                self.assertFalse(self.pass_file.exists())
                self.git("update-index", "--no-" + flag, "file.txt")

    def test_earlier_unpushed_commit_scanned(self):
        self.git("push", "origin", "main")
        commit = self.add_token()
        self.git("rm", "secret.txt")
        self.git("commit", "-m", "remove sample")
        result = self.scan("--remote", "origin")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("github-token " + commit[:7] + ":secret.txt:1", result.stdout)
        self.assertFalse(self.pass_file.exists())

    def test_history_without_remote_tracking_refs_scanned(self):
        commit = self.add_token()
        self.git("rm", "secret.txt")
        self.git("commit", "-m", "remove sample")
        result = self.scan("--remote", "origin")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(commit[:7] + ":secret.txt:", result.stdout)
        self.assertFalse(self.pass_file.exists())

    def test_foreign_repo_has_no_path_exceptions(self):
        for path in ("checks/fixtures/x", "__pycache__/x", "checks/scan.py",
                     "checks/tests/x", ".DS_Store"):
            with self.subTest(path=path):
                self.add_token(path)
        result = self.scan("--remote", "origin")
        self.assertEqual(result.returncode, 1, result.stdout)
        for path in ("checks/fixtures/x", "__pycache__/x", "checks/scan.py",
                     "checks/tests/x", ".DS_Store"):
            self.assertIn(":" + path + ":1", result.stdout)
        self.assertFalse(self.pass_file.exists())

    def test_binary_blob_scanned(self):
        commit = self.add_token(prefix=b"\0")
        result = self.scan("--remote", "origin")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("github-token " + commit[:7] + ":secret.txt:1", result.stdout)
        self.assertFalse(self.pass_file.exists())

    def test_earlier_modified_blob_scanned(self):
        self.git("push", "origin", "main")
        commit = self.add_token("file.txt")
        (self.repo / "file.txt").write_text("clean again\n")
        self.git("commit", "-am", "clean")
        result = self.scan("--remote", "origin")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(commit[:7] + ":file.txt:1", result.stdout)

    def test_exceptions_only_for_scanner_own_repo(self):
        checks = self.repo / "checks"
        checks.mkdir()
        for name in ("scan.py", "tree.py"):
            shutil.copyfile(ROOT / "checks" / name, checks / name)
        for path in ("checks/fixtures/x", "__pycache__/x", "checks/tests/x", ".DS_Store"):
            self.add_token(path)
        self.git("add", "checks")
        self.git("commit", "-m", "scanner")
        result = subprocess.run([sys.executable, str(checks / "scan.py"), "--release-pass",
                                 "--root", str(self.repo), "--remote", "origin"],
                                env=dict(self.env, PYTHONDONTWRITEBYTECODE="1"),
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.quiet()

    def test_foreign_repo_codex_exception_disabled(self):
        path = self.repo / "codex" / "x"
        path.parent.mkdir()
        path.write_text(".cod" + "ex/\n")
        self.git("add", ".")
        self.git("commit", "-m", "path")
        result = self.scan("--remote", "origin")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("codex-path ", result.stdout)
        self.assertIn(":codex/x:1", result.stdout)

    def test_full_ref_resolves_bound_commit_not_head(self):
        commit = self.add_token()
        self.git("branch", "unsafe")
        self.git("reset", "--hard", "HEAD~1")
        result = self.scan("--remote", "origin", "--ref", "refs/heads/unsafe")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(commit[:7] + ":secret.txt:", result.stdout)
        self.assertFalse(self.pass_file.exists())

    def test_full_tree_scanned_even_when_already_pushed(self):
        commit = self.add_token()
        self.git("push", "origin", "main")
        result = self.scan("--remote", "origin")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(commit[:7] + ":secret.txt:", result.stdout)

    def test_clean_other_branch_binds_its_commit(self):
        old = self.git("rev-parse", "HEAD")
        self.git("branch", "release")
        (self.repo / "file.txt").write_text("new\n")
        self.git("commit", "-am", "new")
        result = self.scan("--remote", "origin", "--ref", "refs/heads/release")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(self.pass_file.read_text())["commit"], old)
        self.quiet("git push origin release")

    def test_token_scan_writes_nothing_and_gate_denies(self):
        (self.repo / "sample.txt").write_bytes(TOKEN_SAMPLE)
        self.git("add", ".")
        self.git("commit", "-m", "sample")
        result = self.scan("--remote", "origin")
        self.assertEqual(result.returncode, 1)
        self.assertIn("github-token " + self.git("rev-parse", "HEAD")[:7] + ":sample.txt:", result.stdout)
        self.assertFalse(self.pass_file.exists())
        self.deny()

    def test_clean_scan_writes_private_atomic_pass_and_gate_passes(self):
        result = self.scan("--remote", "origin")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "scan: release pass written for " + self.git("rev-parse", "HEAD")[:7] + " -> origin\n")
        self.assertEqual(stat.S_IMODE(self.pass_file.stat().st_mode), 0o600)
        for path in (self.pass_file.parent, self.pass_file.parent.parent):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        value = json.loads(self.pass_file.read_text())
        self.assertEqual(set(value), {"version", "repo", "commit", "ref", "remote", "push_urls", "created"})
        self.assertEqual(value["repo"], str(self.repo.resolve()))
        self.assertEqual(value["version"], 2)
        self.assertEqual(value["ref"], "refs/heads/main")
        self.assertEqual(value["remote"], "origin")
        self.assertEqual(value["push_urls"], [str(self.remote)])
        self.assertEqual(list(self.pass_file.parent.iterdir()), [self.pass_file])
        self.quiet("git push origin main")

    def test_dirty_tree_refused(self):
        (self.repo / "file.txt").write_text("changed\n")
        result = self.scan("--remote", "origin")
        self.assertEqual(result.returncode, 1)
        self.assertIn("scan: release pass refused: working tree is dirty", result.stdout)
        self.assertFalse(self.pass_file.exists())

    def test_detached_head_missing_remote_and_non_repo_refused(self):
        for args, root in ((("--remote", "missing"), None), (("--remote", "origin"), self.base), ((), None)):
            result = self.scan(*args, root=root)
            self.assertEqual(result.returncode, 1)
            self.assertIn("scan: release pass refused:", result.stdout)
        self.git("checkout", "--detach")
        self.assertEqual(self.scan("--remote", "origin").returncode, 1)

    def test_unborn_repo_refused(self):
        empty = self.base / "empty"
        subprocess.run(["git", "init", str(empty)], env=self.env, capture_output=True, check=True)
        self.assertEqual(self.scan("--remote", "origin", root=empty).returncode, 1)

    def test_explicit_ref(self):
        self.git("branch", "release")
        result = self.scan("--remote", "origin", "--ref", "release")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.quiet("git push origin release")
        self.deny("git push origin main")

    def test_partial_scan_refused(self):
        result = self.scan("--remote", "origin", "file.txt")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.pass_file.exists())

    def test_subdirectory_cannot_authorize_unscanned_files(self):
        folder = self.repo / "subdir"
        folder.mkdir()
        result = self.scan("--remote", "origin", root=folder)
        self.assertEqual(result.returncode, 1)
        self.assertIn("root must be the repository root", result.stdout)


class WorkflowSkillGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.transcript = self.root / "transcript.jsonl"
        self.transcript.write_text("")
        self.env = dict(os.environ, HOME=str(self.root), CLAUDE_CONFIG_DIR=str(self.root / "custom"),
                        WORKFLOW_SKILL_GATE="on")
        self.event = {"tool_name": "Edit", "tool_input": {"file_path": "/x/app.py"},
                      "transcript_path": str(self.transcript)}

    def invoke(self, mode, payload=None):
        return subprocess.run([sys.executable, "-I", "-B", str(ROOT / "hooks/workflow-skill-gate.py"), mode],
                              input=payload if isinstance(payload, str) else json.dumps(payload or self.event),
                              text=True, capture_output=True, env=self.env, timeout=10)

    def test_selftest(self):
        result = self.invoke("selftest")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "workflow-skill-gate selftest: ok\n")

    def test_unloaded_skills_block(self):
        result = self.invoke("hook")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn(str(self.root / "custom/skills/ponytail/SKILL.md"), result.stderr)
        self.assertIn("CLAUDE.md", result.stderr)

    def test_successful_skill_tool_calls_allow(self):
        entries = []
        for name in ("ponytail", "anti-slop", "verification-before-completion"):
            entries += [
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": name,
                    "name": "Skill", "input": {"skill": name}}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": name,
                    "content": "loaded"}]}}
            ]
        self.transcript.write_text("\n".join(json.dumps(e) for e in entries))
        result = self.invoke("hook")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_nudge_never_blocks(self):
        for payload in (self.event, {"prompt": "review"}, "[]", "null", "{"):
            result = self.invoke("nudge", payload)
            self.assertIn(result.returncode, (0, 1))
        result = self.invoke("nudge", {"prompt": "review"})
        self.assertIn("review-change", result.stdout)

    def test_malformed_json_allows(self):
        result = self.invoke("hook", "{")
        self.assertIn(result.returncode, (0, 1))
        self.assertNotIn("Traceback", result.stderr)
