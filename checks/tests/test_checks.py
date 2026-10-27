from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from checks import manifest, scan, validate


REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "checks" / "fixtures"
# Secret-shaped samples are split in source and assembled at run time, so the
# published tree holds nothing an outside leak scanner would flag.
SAMPLE_TEXT = {
    "aws-access-key": "AKIA" + "FAKE000000000000",
    "codex-path": "." + "codex/fake-config",
    "email": "fake-person" + "@invalid.test",
    "github-pat": "github_" + "pat_FAKE0123456789FAKE0123456789FAKE0123456789",
    "github-token": "ghp" + "_FAKE0123456789FAKE0123456789FAKE0123456789",
    "google-api-key": "AIza" + "FAKE0123456789FAKE0123456789FAKE0123456789",
    "home-path": "/ho" + "me/fake-person/project/",
    "local-path": "/Use" + "rs/fake-person/project/",
    "memory-term": "memory" + "_fake_fixture",
    "openai-key": "sk" + "-FAKE0123456789FAKE0123456789FAKE0123456789",
    "password-field": "pass" + 'word: "fake-placeholder"',
    "private-key": "-----BEGIN " + "FAKE PRIVATE KEY-----",
    "safe-emails": "\n".join(local + "@" + domain for local, domain in (
        ("123+fake", "users.noreply.github.com"), ("fake", "example.com"),
        ("fake", "example.org"), ("fake", "example.net"))),
    "sensitive-token-field": "access" + "_token: fake-placeholder",
    "slack-token": "xo" + "xb-FAKE0123456789012345",
    "stripe-live-key": "sk_" + "live_FAKE0123456789FAKE0123456789FAKE0123456789",
    "tilde-path": "~/" + "Documents/fake-project",
    "unsafe-subdomain": "fake" + "@sub.example.com",
    "windows-path": "C:\\Us" + "ers\\fake-person\\project",
}
_SAMPLE_HOME = tempfile.TemporaryDirectory()
# Kept under checks/fixtures/ so tests that scan the folder directly see fixture paths.
SAMPLES = Path(_SAMPLE_HOME.name) / "checks" / "fixtures" / "samples"
SAMPLES.mkdir(parents=True)
for _name, _text in SAMPLE_TEXT.items():
    (SAMPLES / (_name + ".txt")).write_text(_text + "\n", encoding="utf-8")
SKILL = "skills/sample/SKILL.md"
AGENT = "agents/sample.md"
SNIPPET = "settings/permissions.snippet.json"


class TreeCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "tree"
        shutil.copytree(FIXTURES / "valid", self.root)

    def run_tool(self, script, *args):
        return subprocess.run(
            [sys.executable, str(REPO / "checks" / script), *args, "--root", str(self.root)],
            text=True, capture_output=True, check=False,
        )

    def write_manifest(self):
        result = self.run_tool("manifest.py", "write")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def copy_sample(self, name, destination="README.md"):
        target = self.root / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SAMPLES / (name + ".txt"), target)

    def assert_invalid(self, rule, refresh=True, detail=None):
        if refresh:
            self.write_manifest()
        result = self.run_tool("validate.py")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("FAIL " + rule + " ", result.stdout)
        self.assertRegex(result.stdout, r"validate: [1-9][0-9]* problems\n$")
        self.assertNotIn("Traceback", result.stderr)
        if detail:
            self.assertIn(detail, result.stdout)
        return result.stdout

    def set_skill_values(self, description, when_to_use=""):
        self.put(SKILL, "---\nname: sample\ndescription: " + json.dumps(description) +
                 "\nwhen_to_use: " + json.dumps(when_to_use) + "\n---\n")


class ValidationTests(TreeCase):
    def test_valid_fixture(self):
        self.write_manifest()
        result = self.run_tool("validate.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "validate: ok\n")

    def test_scan_valid_fixture(self):
        self.assertEqual(scan.scan(self.root), [])

    def test_empty_tier_one_folders(self):
        for folder in ("skills", "agents", "harness"):
            shutil.rmtree(self.root / folder)
            (self.root / folder).mkdir()
        (self.root / "style").mkdir()
        self.put("NOTICE.md", "# Notices\n\n## Vendored\n")
        self.write_manifest()
        self.assertEqual(self.run_tool("validate.py").stdout, "validate: ok\n")

    def test_unknown_skill_keys_allowed(self):
        text = (self.root / SKILL).read_text()
        self.put(SKILL, text.replace("name: sample", "name: sample\nshell: x\ncontext: x"))
        self.write_manifest()
        self.assertEqual(self.run_tool("validate.py").stdout, "validate: ok\n")

    def test_snippet_allow(self):
        self.put(SNIPPET, '{"permissions": {"allow": []}}')
        self.assert_invalid("snippet")

    def test_snippet_third_key(self):
        self.put(SNIPPET, '{"permissions": {"ask": [], "deny": [], "other": []}}')
        self.assert_invalid("snippet")

    def test_snippet_extra_top_level_key(self):
        self.put(SNIPPET, '{"permissions": {"ask": []}, "extra": true}')
        self.assert_invalid("snippet")

    def test_snippet_invalid_json(self):
        self.put(SNIPPET, '{')
        self.assert_invalid("snippet")

    def test_snippet_missing(self):
        (self.root / SNIPPET).unlink()
        self.assert_invalid("snippet")

    def test_inline_bang(self):
        self.put("harness/sample.md", "Read !`date` inline.\n")
        self.assert_invalid("bang-block")

    def test_bang_inside_code_span_punctuation_allowed(self):
        self.put("skills/sample/references/style.md", "Snap (`?` -> `?!`, or fill snaps to `accent`).\n")
        self.write_manifest()
        result = self.run_tool("validate.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bang_after_list_marker(self):
        self.put("harness/sample.md", "- !`date`\n")
        self.assert_invalid("bang-block")

    def test_bang_fence(self):
        self.put("harness/sample.md", "```!bash\necho fake\n```\n")
        self.assert_invalid("bang-block")

    def test_tier_two_not_subject_to_tier_one_rules(self):
        self.put("hooks/sample.py", "pip install example\n!`date`\n")
        self.put("codex/sample.md", "pip install example\n!`date`\n")
        self.write_manifest()
        self.assertEqual(self.run_tool("validate.py").stdout, "validate: ok\n")

    def test_python_in_skills(self):
        self.put("skills/sample/run.py", "print('example')\n")
        self.write_manifest()
        self.assertEqual(self.run_tool("validate.py").stdout, "validate: ok\n")

    def test_other_settings_file(self):
        self.put("settings/other.json", "{}\n")
        self.assert_invalid("tier1-file")

    def test_nested_settings_snippet(self):
        self.put("settings/nested/permissions.snippet.json", "{}\n")
        self.assert_invalid("tier1-file")

    def test_license_and_notice_names_allowed(self):
        self.put("skills/sample/LICENSE.txt", "Fixture license.\n")
        self.put("skills/sample/NOTICE.txt", "Fixture notice.\n")
        self.write_manifest()
        self.assertEqual(self.run_tool("validate.py").stdout, "validate: ok\n")

    def test_harness_characters(self):
        self.put("harness/core.md", "x" * 30000)
        self.assert_invalid("harness-budget")

    def test_harness_aggregate_characters(self):
        self.put("harness/core.md", "x" * 15000)
        self.put("harness/other.md", "y" * 15000)
        self.assert_invalid("harness-budget")

    def test_harness_lines(self):
        self.put("harness/core.md", "line\n" * 400)
        self.assert_invalid("harness-budget")

    def test_harness_below_character_limit(self):
        self.put("harness/core.md", "x" * 29999)
        self.write_manifest()
        self.assertEqual(self.run_tool("validate.py").stdout, "validate: ok\n")

    def test_harness_line_limit(self):
        self.put("harness/core.md", "line\n" * 399)
        self.write_manifest()
        self.assertEqual(self.run_tool("validate.py").stdout, "validate: ok\n")

    def test_description_length(self):
        self.set_skill_values("x" * 1025)
        self.assert_invalid("skill-length")

    def test_combined_description_length(self):
        self.set_skill_values("x" * 1024, "y" * 513)
        self.assert_invalid("skill-length")

    def test_description_length_boundaries(self):
        self.set_skill_values("x" * 1024, "y" * 512)
        self.write_manifest()
        self.assertEqual(self.run_tool("validate.py").stdout, "validate: ok\n")

    def test_block_description_length(self):
        self.put(SKILL, "---\nname: sample\ndescription: |-\n  " + "x" * 1025 + "\n---\n")
        self.assert_invalid("skill-length")

    def test_explicit_indent_description_rejected(self):
        self.put(SKILL, "---\nname: sample\ndescription: |2-\n" + " " * 1100 + "x\n---\n")
        self.assert_invalid("skill-frontmatter", detail="explicit block indentation")

    def test_multiline_plain_description_length(self):
        self.put(SKILL, "---\nname: sample\ndescription: start\n  " + "x" * 1025 + "\n---\n")
        self.assert_invalid("skill-length")

    def test_pycache_in_tier_one_is_not_hidden(self):
        self.put("harness/__pycache__", "payload\n")
        self.assert_invalid("tier1-file", detail="harness/__pycache__")

    def test_pycache_folder_in_tier_one_is_not_hidden(self):
        self.put("harness/__pycache__/x.pyc", "payload\n")
        self.assert_invalid("tier1-file", detail="harness/__pycache__/x.pyc")

    def test_vendored_without_license(self):
        (self.root / "skills/sample/LICENSE").unlink()
        self.assert_invalid("license")

    def test_skill_source_missing(self):
        (self.root / "skills/sample/SOURCE.md").unlink()
        self.assert_invalid("license")

    def test_notice_is_ignored(self):
        self.put("NOTICE.md", "## Vendored\n- absent: irrelevant\n")
        self.write_manifest()
        self.assertEqual(self.run_tool("validate.py").stdout, "validate: ok\n")

    def test_modified_licence_any_extension_nested(self):
        self.put("skills/sample/SOURCE.md", "ORIGIN: MoDiFiEd\n")
        (self.root / "skills/sample/LICENSE").unlink()
        self.put("skills/sample/legal/LICENCE.txt", "Fixture license\n")
        self.write_manifest()
        self.assertEqual(self.run_tool("validate.py").stdout, "validate: ok\n")

    def test_modified_without_license(self):
        self.put("skills/sample/SOURCE.md", "origin: modified\n")
        (self.root / "skills/sample/LICENSE").unlink()
        self.assert_invalid("license")

    def test_own_without_license(self):
        self.put("skills/sample/SOURCE.md", "origin: own\n")
        (self.root / "skills/sample/LICENSE").unlink()
        self.write_manifest()
        self.assertEqual(self.run_tool("validate.py").stdout, "validate: ok\n")

    def test_settings_example_allowed(self):
        self.put("settings/settings.example.json", "{}\n")
        self.write_manifest()
        self.assertEqual(self.run_tool("validate.py").stdout, "validate: ok\n")

    def test_python_in_harness_and_agents_rejected(self):
        for folder in ("harness", "agents"):
            self.put(folder + "/run.py", "pass\n")
        self.assert_invalid("tier1-file")

    def test_setup_commands_in_skills_allowed(self):
        self.put("skills/sample/references/setup.md", "pip install example\n")
        self.write_manifest()
        self.assertEqual(self.run_tool("validate.py").stdout, "validate: ok\n")

    def test_setup_commands_in_agents_rejected(self):
        text = (self.root / AGENT).read_text()
        self.put(AGENT, text + "\npip install example\n")
        self.assert_invalid("setup-command")

    def test_nested_skill_bang_rejected(self):
        self.put("skills/sample/references/setup.md", "!`date`\n")
        self.assert_invalid("bang-block")

    def test_nested_harness_budget(self):
        self.put("harness/nested/core.md", "line\n" * 400)
        self.assert_invalid("harness-budget")

    def test_harness_license_counts_toward_budget(self):
        self.put("harness/LICENSE.txt", "line\n" * 400)
        self.assert_invalid("harness-budget")

    def test_missing_skill_frontmatter(self):
        self.put(SKILL, "# Skill\n")
        self.assert_invalid("skill-frontmatter")

    def test_unclosed_skill_frontmatter(self):
        self.put(SKILL, "---\nname: sample\ndescription: test\n")
        self.assert_invalid("skill-frontmatter")

    def test_missing_agent_frontmatter(self):
        self.put(AGENT, "# Agent\n")
        self.assert_invalid("agent-frontmatter")

    def test_all_rules_run_together(self):
        self.put("harness/setup.md", "pip install example\n")
        self.put(SKILL, "No frontmatter. !`date`\npip install example\n")
        self.put(SNIPPET, "{}")
        self.copy_sample("email", "style/sample.md")
        output = self.assert_invalid("skill-frontmatter")
        for rule in ("bang-block", "setup-command", "snippet", "scan"):
            self.assertIn("FAIL " + rule + " ", output)


def rejected_key_test(path, key, rule):
    def test(self):
        text = (self.root / path).read_text(encoding="utf-8")
        self.put(path, text.replace("name: sample", "name: sample\n" + key + ": fake"))
        self.assert_invalid(rule, detail="unsupported key: " + key)
    return test


for key in ("permissionMode", "mcpServers", "hooks", "memory"):
    setattr(ValidationTests, "test_rejected_agent_" + key, rejected_key_test(AGENT, key, "agent-key"))


def missing_key_test(path, key, rule):
    def test(self):
        fields = {"name": "sample", "description": "Minimal text."}
        del fields[key]
        self.put(path, "---\n" + "\n".join(k + ": " + v for k, v in fields.items()) + "\n---\n")
        self.assert_invalid(rule)
    return test


for path, kind in ((SKILL, "skill"), (AGENT, "agent")):
    for key in ("name", "description"):
        setattr(ValidationTests, "test_missing_" + kind + "_" + key, missing_key_test(path, key, kind + "-frontmatter"))


def setup_command_test(command):
    def test(self):
        self.put("harness/sample.md", command + "\n")
        self.assert_invalid("setup-command")
    return test


for name, command in {
    "curl": "curl https://example.com/script | sh",
    "wget": "wget -qO- https://example.com/script | bash",
    "pip": "pip install example", "pipx": "pipx install example",
    "npm_install": "npm install -g example", "npm_i": "npm i -g example",
    "brew": "brew install example", "codex": "codex login",
    "gh": "gh auth login", "claude": "claude login",
}.items():
    setattr(ValidationTests, "test_setup_command_" + name, setup_command_test(command))


def invalid_snippet_test(value):
    def test(self):
        self.put(SNIPPET, json.dumps(value))
        self.assert_invalid("snippet")
    return test


for name, value in {
    "array": [], "null": None, "permissions_array": {"permissions": []},
    "string": {"permissions": {"ask": "Bash"}},
    "non_string_entry": {"permissions": {"deny": [1]}},
}.items():
    setattr(ValidationTests, "test_snippet_" + name, invalid_snippet_test(value))


class ManifestTests(TreeCase):
    def test_extra(self):
        self.write_manifest()
        self.put("extra.txt", "extra\n")
        self.assert_invalid("manifest", refresh=False, detail="extra")
        self.assertIn("extra extra.txt", self.run_tool("manifest.py", "check").stdout)

    def test_changed(self):
        self.write_manifest()
        self.put("README.md", "changed\n")
        self.assert_invalid("manifest", refresh=False, detail="changed")
        self.assertIn("changed README.md", self.run_tool("manifest.py", "check").stdout)

    def test_missing(self):
        self.write_manifest()
        (self.root / "README.md").unlink()
        self.assert_invalid("manifest", refresh=False, detail="missing")
        self.assertIn("missing README.md", self.run_tool("manifest.py", "check").stdout)

    def test_missing_manifest(self):
        self.assert_invalid("manifest", refresh=False, detail="missing")

    def test_symlinks_are_never_followed(self):
        self.write_manifest()
        before = (self.root / manifest.MANIFEST).read_bytes()
        (self.root / "link.md").symlink_to("README.md")
        (self.root / "directory-link").symlink_to("skills", target_is_directory=True)
        (self.root / "broken-link").symlink_to("absent")
        (self.root / "loop").symlink_to(".", target_is_directory=True)
        result = self.run_tool("manifest.py", "write")
        self.assertEqual(result.returncode, 1)
        for name in ("link.md", "directory-link", "broken-link", "loop"):
            self.assertIn("symlink " + name, result.stdout)
        self.assertEqual((self.root / manifest.MANIFEST).read_bytes(), before)
        self.assert_invalid("manifest", refresh=False, detail="symlink")

    def test_manifest_symlink(self):
        self.write_manifest()
        saved = self.root / "saved.txt"
        (self.root / manifest.MANIFEST).rename(saved)
        (self.root / manifest.MANIFEST).symlink_to(saved.name)
        result = self.run_tool("manifest.py", "check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("symlink MANIFEST.sha256", result.stdout)

    def test_manifest_malformed(self):
        self.write_manifest()
        self.put(manifest.MANIFEST, "invalid\n")
        self.assert_invalid("manifest", refresh=False, detail="invalid")

    def test_manifest_unsafe_entry(self):
        self.write_manifest()
        with (self.root / manifest.MANIFEST).open("a") as target:
            target.write("0" * 64 + "  ../outside\n")
        self.assert_invalid("manifest", refresh=False, detail="invalid")

    def test_manifest_duplicate_entry(self):
        self.write_manifest()
        text = (self.root / manifest.MANIFEST).read_text()
        self.put(manifest.MANIFEST, text + text.splitlines()[0] + "\n")
        self.assert_invalid("manifest", refresh=False, detail="invalid")

    def test_inventory_ignores_only_declared_entries(self):
        self.put(".git/ignored", "ignored\n")
        self.put("nested/__pycache__/ignored", "ignored\n")
        self.put("nested/.DS_Store", "ignored\n")
        self.put(".hidden", "included\n")
        self.put("checks/fixtures/included.txt", "included\n")
        (self.root / "binary").write_bytes(b"\0binary")
        self.write_manifest()
        entries = (self.root / manifest.MANIFEST).read_text()
        for path in (".git/ignored", "__pycache__", ".DS_Store", manifest.MANIFEST):
            self.assertNotIn(path, entries)
        for path in (".hidden", "checks/fixtures/included.txt", "binary"):
            self.assertIn("  " + path + "\n", entries)
        self.assertEqual(self.run_tool("manifest.py", "check").returncode, 0)

    def test_manifest_sorted_and_repeatable(self):
        self.put("file with spaces.txt", "content\n")
        self.write_manifest()
        before = (self.root / manifest.MANIFEST).read_bytes()
        names = [line.split("  ", 1)[1] for line in before.decode().splitlines()]
        self.assertEqual(names, sorted(names))
        self.write_manifest()
        self.assertEqual(before, (self.root / manifest.MANIFEST).read_bytes())

    @unittest.skipUnless(shutil.which("shasum"), "shasum is not installed")
    def test_shasum(self):
        self.put("file with spaces.txt", "content\n")
        self.write_manifest()
        result = subprocess.run(["shasum", "-a", "256", "-c", manifest.MANIFEST], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class ScanTests(TreeCase):
    def test_safe_email_addresses(self):
        self.copy_sample("safe-emails")
        self.assertEqual(scan.scan(self.root), [])

    def test_quoted_and_ip_literal_emails(self):
        for text in ('"fake user"@mail.invalid\n', "fake@[192.0.2.1]\n"):
            self.put("README.md", text)
            self.assertEqual([f.rule for f in scan.scan(self.root)], ["email"], text)

    def test_vendored_exception(self):
        self.copy_sample("codex-path", "skills/impeccable/reference/hooks.md")
        self.assertEqual(scan.scan(self.root), [])

    def test_vendored_exception_is_file_specific(self):
        for other in ("skills/other/reference/hooks.md", "skills/impeccable/reference/other.md",
                      "skills/hyperframes-custom/SKILL.md"):
            self.copy_sample("codex-path", other)
            self.assertEqual([f.rule for f in scan.scan(self.root)], ["codex-path"], other)
            (self.root / other).unlink()

    def test_media_use_token_exception_is_file_specific(self):
        self.copy_sample("sensitive-token-field", "skills/media-use/session.txt")
        self.assertEqual([f.rule for f in scan.scan(self.root)], ["sensitive-token-field"])

    def test_vendored_exception_is_rule_specific(self):
        self.copy_sample("email", "skills/impeccable/reference/hooks.md")
        self.assertEqual([f.rule for f in scan.scan(self.root)], ["email"])

    def test_fixture_default_exclusion_and_explicit_directory(self):
        self.copy_sample("github-token", "checks/fixtures/fake.txt")
        self.assertEqual(scan.scan(self.root), [])
        findings = scan.scan(self.root, ["checks/fixtures"])
        self.assertEqual([f.rule for f in findings], ["github-token"])

    def test_explicit_fixture_file(self):
        self.copy_sample("email", "checks/fixtures/fake.txt")
        self.assertEqual([f.rule for f in scan.scan(self.root, ["checks/fixtures/fake.txt"])], ["email"])

    def test_root_inside_fixtures(self):
        self.assertIn("github-token", {f.rule for f in scan.scan(SAMPLES)})

    def test_exceptions_table(self):
        for path in ("checks/scan.py", "checks/tests/sample.txt"):
            self.copy_sample("github-token", path)
        self.assertEqual(scan.scan(self.root), [])

    def test_output_never_contains_matched_content(self):
        self.copy_sample("github-token")
        result = self.run_tool("scan.py")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "github-token README.md:1\n")
        self.assertNotIn((SAMPLES / "github-token.txt").read_text().strip(), result.stdout + result.stderr)

    def test_scan_clean_count(self):
        result = self.run_tool("scan.py")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "scan: clean (7 files)\n")

    def test_binary_and_invalid_utf8(self):
        data = (SAMPLES / "github-token.txt").read_bytes()
        (self.root / "README.md").write_bytes(b"\0" + data)
        self.assertEqual(scan.scan(self.root), [])
        (self.root / "README.md").write_bytes(b"\xff\n" + data)
        findings = scan.scan(self.root)
        self.assertEqual([(f.rule, f.line) for f in findings], [("github-token", 2)])

    def test_binary_probe_is_first_eight_kib(self):
        data = (SAMPLES / "github-token.txt").read_bytes()
        (self.root / "README.md").write_bytes(b"x" * 8191 + b"\0\n" + data)
        self.assertEqual(scan.scan(self.root), [])
        (self.root / "README.md").write_bytes(b"x" * 8192 + b"\0\n" + data)
        self.assertEqual([f.rule for f in scan.scan(self.root)], ["github-token"])

    def test_scan_every_extension_including_tier_two(self):
        for path in ("hooks/fake.bin", "mods.lock", ".hidden"):
            self.copy_sample("email", path)
        self.assertEqual({f.path for f in scan.scan(self.root)}, {"hooks/fake.bin", "mods.lock", ".hidden"})

    def test_skip_git_cache_and_ds_store(self):
        for path in (".git/data", "nested/__pycache__/data", "nested/.DS_Store"):
            self.copy_sample("email", path)
        self.assertEqual(scan.scan(self.root), [])

    def test_explicit_paths_only(self):
        self.copy_sample("email")
        self.assertEqual(scan.scan(self.root, [SKILL]), [])
        self.assertEqual(scan.scan(self.root, []), [])

    def test_invalid_explicit_paths(self):
        for path in ("absent.txt", "../outside"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                scan.scan(self.root, [path])


def leak_test(sample, rule):
    def test(self):
        self.copy_sample(sample)
        self.assertEqual([f.rule for f in scan.scan(self.root)], [rule])
        self.assert_invalid("scan", detail=rule)
    return test


for sample, rule in {
    "local-path": "local-path", "home-path": "local-path", "windows-path": "local-path", "tilde-path": "local-path",
    "github-token": "github-token", "github-pat": "github-token", "private-key": "private-key",
    "openai-key": "openai-key", "google-api-key": "google-api-key", "aws-access-key": "aws-access-key",
    "slack-token": "slack-token", "stripe-live-key": "stripe-live-key", "sensitive-token-field": "sensitive-token-field",
    "password-field": "password-field", "email": "email", "unsafe-subdomain": "email",
    "memory-term": "memory-term", "codex-path": "codex-path",
}.items():
    setattr(ScanTests, "test_leak_" + sample.replace("-", "_"), leak_test(sample, rule))


class ParserTests(unittest.TestCase):
    def test_literal_and_chomping(self):
        for indicator, expected in (("|", "First\nSecond\n"), ("|-", "First\nSecond"), ("|+", "First\nSecond\n\n")):
            with self.subTest(indicator=indicator):
                values, keys, error = validate.frontmatter("---\nname: sample\ndescription: " + indicator + "\n  First\n  Second\n\n---\n")
                self.assertIsNone(error)
                self.assertEqual(values["description"], expected)
                self.assertEqual(keys, [("name", 2), ("description", 3)])

    def test_folded_block(self):
        values, _, error = validate.frontmatter("---\nname: sample\ndescription: >-\n  First\n  Second\n---\n")
        self.assertIsNone(error)
        self.assertEqual(values["description"], "First Second")

    def test_quoted_values(self):
        values, _, error = validate.frontmatter('---\nname: "sample"\ndescription: \'It\'\'s short.\'\n---\n')
        self.assertIsNone(error)
        self.assertEqual(values, {"name": "sample", "description": "It's short."})

    def test_quoted_values_with_comments(self):
        values, _, error = validate.frontmatter('---\nname: "sample" # comment\ndescription: \'It\'\'s # short.\' # comment\n---\n')
        self.assertIsNone(error)
        self.assertEqual(values, {"name": "sample", "description": "It's # short."})

    def test_folded_paragraphs(self):
        values, _, error = validate.frontmatter("---\nname: sample\ndescription: >-\n  First\n  Second\n\n  Third\n---\n")
        self.assertIsNone(error)
        self.assertEqual(values["description"], "First Second\nThird")

    def test_python_39_syntax(self):
        for path in (REPO / "checks").rglob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()
