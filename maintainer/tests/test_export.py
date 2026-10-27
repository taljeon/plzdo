from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from maintainer import export
from checks import validate


REPO = Path(__file__).resolve().parents[2]


class ExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.home = self.base / "home"
        self.source = self.home / "sources/sample"
        self.source.mkdir(parents=True)
        self.root = self.base / "repo"
        (self.root / "maintainer").mkdir(parents=True)
        shutil.copyfile(REPO / "maintainer/export.py", self.root / "maintainer/export.py")
        self.ids = self.home / ".config/plzdo/private-ids.txt"
        self.ids.parent.mkdir(parents=True)
        self.ids.write_text("# identifiers\n\nprivate-example-one\nprivate-example-two\n")
        self.env = dict(os.environ, HOME=str(self.home))
        self.env.pop("PLZDO_PRIVATE_IDS", None)
        self.env["PLZDO_EXPORT_CONFIG"] = str(self.home / "export.json")
        self.entry = dict(name="sample", kind="skill", source="~/sources/sample", dest="skills/sample",
                          origin="vendored", upstream="github.com/example/sample", commit="a" * 40,
                          upstream_path="skills/sample", license="MIT", status="copy-ready", company=True,
                          exclude=["assets/upstream/**"], note="A | note")
        self.config = {"version": 1, "replacements": [], "entries": [self.entry]}
        self.config_path = self.home / "export.json"
        self.put("SKILL.md", "---\nname: sample\ndescription: Fixture\n---\nold value\n")

    def put(self, relative, text):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_cli(self, command="export", *args, expected=0, config=True):
        if config:
            self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", str(self.root / "maintainer/export.py"), command, *args],
                                cwd=self.root, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def lock(self):
        return json.loads((self.root / "maintainer/export.lock.json").read_text())

    def test_config_collects_all_problems_before_copy(self):
        self.config["extra"] = 1
        self.config["version"] = 2
        self.config["replacements"] = [["only one"], [1, "x"]]
        self.entry.update(extra=True, kind="bad", origin="bad", status="bad", company="yes", exclude="bad")
        del self.entry["note"]
        self.config["entries"].append(dict(self.entry))
        result = self.run_cli(expected=2)
        for text in ("unknown key", "version must be 1", "expected two strings", "missing note",
                     "invalid kind", "invalid origin", "invalid status", "company must be boolean",
                     "exclude must be a list", "duplicate name", "duplicate dest"):
            self.assertIn(text, result.stderr)
        self.assertNotIn("private identifiers file", result.stderr)
        self.assertFalse((self.root / "skills").exists())

    def test_config_wrong_shapes_and_missing_keys(self):
        for value in ([], {}, {"version": True, "entries": "bad", "replacements": None},
                      {"version": 1, "entries": [None, {"name": [], "status": [], "dest": 2}], "replacements": []}):
            with self.subTest(value=value):
                self.config = value
                self.run_cli(expected=2)

    def test_config_rejects_escaping_and_duplicate_normalized_destinations(self):
        for dest in ("/absolute/path", "../escape", "skills/../escape", ".", ""):
            with self.subTest(dest=dest):
                self.entry["dest"] = dest
                self.run_cli(expected=2)
        self.entry["dest"] = "skills/sample"
        self.config["entries"].append(dict(self.entry, name="other", dest="skills/./sample"))
        self.assertIn("duplicate dest", self.run_cli(expected=2).stderr)

    def test_config_rejects_symlink_and_overlapping_destinations(self):
        (self.root / "skills").symlink_to(self.home, target_is_directory=True)
        self.assertIn("without symlinks", self.run_cli(expected=2).stderr)
        (self.root / "skills").unlink()
        self.config["entries"].append(dict(self.entry, name="nested", dest="skills/sample/nested"))
        self.assertIn("overlapping dests", self.run_cli(expected=2).stderr)

    def test_status_source_dest_constraints(self):
        for status in ("copy-ready", "needs-runtime"):
            for field in ("source", "dest"):
                with self.subTest(status=status, field=field):
                    saved = self.entry[field]
                    self.entry.update(status=status)
                    self.entry[field] = None
                    self.assertIn("requires source and dest", self.run_cli(expected=2).stderr)
                    self.entry[field] = saved
        for status in ("link-only", "excluded"):
            self.entry["status"] = status
            self.assertIn("must not have dest", self.run_cli(expected=2).stderr)

    def test_copy_replacements_binary_excludes_and_source_note(self):
        self.config["replacements"] = [["old", "middle"], ["middle", "new"]]
        binary = b"\xff\x00old\n\x80"
        (self.source / "image.bin").write_bytes(binary)
        self.put("assets/upstream/skip.txt", "skip")
        self.put("assets/keep.txt", "old")
        for name in ("__pycache__/x.pyc", ".pytest_cache/v/cache/nodeids", ".git/config", ".DS_Store", "nested/.DS_Store"):
            self.put(name, "skip")
        self.put("SOURCE.md", "stale provenance")
        (self.source / "empty").mkdir()
        self.run_cli()
        dest = self.root / "skills/sample"
        self.assertIn("new value", (dest / "SKILL.md").read_text())
        self.assertEqual((dest / "assets/keep.txt").read_text(), "new")
        self.assertEqual((dest / "image.bin").read_bytes(), binary)
        self.assertTrue((dest / "empty").is_dir())
        for name in ("assets/upstream/skip.txt", "__pycache__", ".pytest_cache", ".git", ".DS_Store", "nested/.DS_Store"):
            self.assertFalse((dest / name).exists(), name)
        note = (dest / "SOURCE.md").read_text()
        for line in ("name: sample", "origin: vendored", "upstream: github.com/example/sample", "commit: " + "a" * 40,
                     "upstream_path: skills/sample", "license: MIT", "status: copy-ready", "company: yes",
                     "note: A | note", "Exported from the owner's live setup by maintainer/export.py."):
            self.assertIn(line + "\n", note)

    def test_source_note_none_values_and_no_company(self):
        self.entry.update(upstream=None, commit=None, upstream_path=None, company=False)
        self.run_cli()
        note = (self.root / "skills/sample/SOURCE.md").read_text()
        for value in ("upstream: none", "commit: none", "upstream_path: none", "company: no"):
            self.assertIn(value, note)

    def test_top_and_nested_symlinks_are_materialized(self):
        self.put("nested/real.txt", "linked")
        (self.source / "file-link.txt").symlink_to("nested/real.txt")
        (self.source / "directory-link").symlink_to("nested", target_is_directory=True)
        outside_file = self.home / "outside.txt"
        outside_file.write_text("outside file")
        (self.source / "nested/outside-link.txt").symlink_to(outside_file)
        alias = self.home / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        self.entry["source"] = "~/alias"
        self.run_cli()
        dest = self.root / "skills/sample"
        self.assertEqual((dest / "file-link.txt").read_text(), "linked")
        self.assertEqual((dest / "directory-link/real.txt").read_text(), "linked")
        self.assertEqual((dest / "nested/outside-link.txt").read_text(), "outside file")
        self.assertFalse(any(p.is_symlink() for p in dest.rglob("*")))

    def test_external_directory_symlink_and_cycle_are_skipped(self):
        (self.home / "outside").mkdir()
        (self.home / "outside/secret.txt").write_text("private-example-one")
        (self.source / "external").symlink_to(self.home / "outside", target_is_directory=True)
        (self.source / "loop").symlink_to(self.source, target_is_directory=True)
        result = self.run_cli()
        self.assertIn("skipped directory symlink: external", result.stdout)
        self.assertIn("skipped directory symlink: loop", result.stdout)
        self.assertFalse((self.root / "skills/sample/external").exists())
        self.run_cli("check")

    def test_dangling_symlink_or_missing_source_errors_without_deleting_dest(self):
        self.run_cli()
        previous = (self.root / "skills/sample/SKILL.md").read_bytes()
        link = self.source / "broken"
        link.symlink_to("missing")
        self.run_cli(expected=2)
        self.assertEqual((self.root / "skills/sample/SKILL.md").read_bytes(), previous)
        link.unlink()
        self.entry["source"] = "~/missing"
        self.run_cli(expected=2)

    def test_stale_files_removed_only_from_listed_dest(self):
        self.run_cli()
        stale = self.root / "skills/sample/stale.txt"
        stale.write_text("stale")
        for path in ("skills/unlisted/keep.txt", "agents/unlisted.md", "hooks/unlisted.py", "rules/keep.txt"):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("keep")
        result = self.run_cli()
        self.assertFalse(stale.exists())
        for path in ("skills/unlisted/keep.txt", "agents/unlisted.md", "hooks/unlisted.py", "rules/keep.txt"):
            self.assertEqual((self.root / path).read_text(), "keep")
        for path in ("skills/unlisted", "agents/unlisted.md", "hooks/unlisted.py"):
            self.assertIn("orphan: " + path, result.stdout)
        self.assertNotIn("orphan: skills/sample", result.stdout)

    def test_directory_outside_removal_roots_preserved(self):
        for dest in ("rules/sample", "skills", "agents", "hooks"):
            with self.subTest(dest=dest):
                self.entry["dest"] = dest
                target = self.root / dest
                target.mkdir(parents=True, exist_ok=True)
                (target / "keep.txt").write_text("keep")
                self.run_cli(expected=2)
                self.assertEqual((target / "keep.txt").read_text(), "keep")

    def test_dest_file_folder_type_changes_inside_allowed_root(self):
        dest = self.root / "skills/sample"
        dest.parent.mkdir()
        dest.write_text("old file")
        self.run_cli()
        self.assertTrue(dest.is_dir())
        self.entry["source"] = "~/sources/sample/SKILL.md"
        self.run_cli()
        self.assertTrue(dest.is_file())

    def test_file_dest_and_needs_runtime_preserve_mode(self):
        script = self.put("gate.py", "print('old')\n")
        script.chmod(0o755)
        self.entry.update(source="~/sources/sample/gate.py", dest="hooks/gate.py", kind="hook", status="needs-runtime")
        self.run_cli()
        target = self.root / "hooks/gate.py"
        self.assertEqual(target.read_bytes(), script.read_bytes())
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)
        self.assertFalse((self.root / "hooks/SOURCE.md").exists())

    def test_file_dest_outside_removal_roots_is_overwritten_without_deletion(self):
        self.entry.update(source="~/sources/sample/SKILL.md", dest="CLAUDE.md", kind="rule")
        target = self.root / "CLAUDE.md"
        target.write_text("old")
        inode = target.stat().st_ino
        self.run_cli()
        self.assertEqual(target.read_bytes(), (self.source / "SKILL.md").read_bytes())
        self.assertEqual(target.stat().st_ino, inode)

    def test_optional_excludes_and_normalized_orphan_destination(self):
        del self.entry["exclude"]
        self.entry["dest"] = "skills/./sample/"
        result = self.run_cli()
        self.assertNotIn("orphan: skills/sample", result.stdout)

    def test_exclude_globs_match_posix_paths_and_directory_names(self):
        self.entry["exclude"] = ["nested/*.txt", "assets"]
        self.put("nested/skip.txt", "private-example-one")
        self.put("assets/deeper/skip.md", "private-example-two")
        self.put("nested/keep.md", "keep")
        self.run_cli()
        dest = self.root / "skills/sample"
        self.assertFalse((dest / "nested/skip.txt").exists())
        self.assertFalse((dest / "assets").exists())
        self.assertEqual((dest / "nested/keep.md").read_text(), "keep")

    def test_private_identifier_reports_index_not_literal_and_keeps_files(self):
        self.put("secret.txt", "safe\nprivate-example-two\nprivate-example-one\n")
        result = self.run_cli(expected=1)
        self.assertIn("skills/sample/secret.txt:2: private-id 2", result.stdout)
        self.assertIn("skills/sample/secret.txt:3: private-id 1", result.stdout)
        for identifier in ("private-example-one", "private-example-two"):
            self.assertNotIn(identifier, result.stdout + result.stderr)
        self.assertTrue((self.root / "skills/sample/secret.txt").exists())
        self.assertFalse((self.root / "maintainer/export.lock.json").exists())

    def test_private_scan_case_sensitive_and_binary(self):
        self.put("case.txt", "PRIVATE-EXAMPLE-ONE")
        self.run_cli()
        (self.source / "binary.bin").write_bytes(b"\xffprivate-example-one")
        result = self.run_cli(expected=1)
        self.assertIn("binary.bin:1: private-id 1", result.stdout)
        self.assertNotIn("case.txt:", result.stdout)

    def test_home_path_hit_and_replacement_rerun(self):
        self.put("home.txt", "path\n" + str(self.home) + "/files\n")
        result = self.run_cli(expected=1)
        self.assertIn("skills/sample/home.txt:2: home-path", result.stdout)
        self.assertNotIn(str(self.home), result.stdout + result.stderr)
        self.config["replacements"] = [[str(self.home), "~"]]
        self.run_cli()
        self.assertEqual((self.root / "skills/sample/home.txt").read_text(), "path\n~/files\n")

    def test_generated_source_note_is_replaced_and_scanned(self):
        self.entry["note"] = "private-example-one"
        self.assertIn("SOURCE.md:", self.run_cli(expected=1).stdout)
        self.config["replacements"] = [["private-example-one", "public"]]
        self.run_cli()
        self.assertIn("note: public", (self.root / "skills/sample/SOURCE.md").read_text())

    def test_missing_private_ids_blocks_every_command(self):
        self.ids.unlink()
        self.config["version"] = 2
        for command in ("export", "check", "inventory"):
            with self.subTest(command=command):
                result = self.run_cli(command, expected=2)
                self.assertIn("private identifiers file", result.stderr)
                self.assertNotIn("version must be 1", result.stderr)
        self.assertFalse((self.root / "skills").exists())

    def test_private_ids_env_and_cli_precedence(self):
        alternate = self.home / "alternate.txt"
        alternate.write_text("# empty list is deliberate\n")
        self.ids.unlink()
        self.env["PLZDO_PRIVATE_IDS"] = str(alternate)
        self.run_cli()
        self.env["PLZDO_PRIVATE_IDS"] = str(self.home / "missing")
        self.run_cli("export", "--private-ids", str(alternate))

    def test_lock_hash_format_sorted_and_source_note_excluded(self):
        self.run_cli()
        lock_path = self.root / "maintainer/export.lock.json"
        raw = lock_path.read_bytes()
        lock = self.lock()
        pairs = [["SKILL.md", hashlib.sha256((self.source / "SKILL.md").read_bytes()).hexdigest()]]
        expected = hashlib.sha256(json.dumps(pairs, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(lock, {"version": 1, "entries": {"sample": {"source_sha256": expected, "dest_sha256": expected}}})
        self.assertEqual(raw, (json.dumps(lock, indent=2, sort_keys=True) + "\n").encode())
        self.entry["note"] = "a different note"
        self.run_cli()
        self.assertEqual(self.lock(), lock)

    def test_hash_sorted_relative_paths_and_excludes(self):
        self.put("z.txt", "z")
        self.put("nested/a.txt", "a")
        self.put("assets/upstream/ignored.txt", "one")
        self.run_cli()
        before = self.lock()
        self.put("assets/upstream/ignored.txt", "two")
        self.put(".git/config", "ignored")
        self.run_cli("check")
        self.run_cli()
        self.assertEqual(self.lock(), before)
        (self.source / "z.txt").rename(self.source / "renamed.txt")
        self.assertIn("changed: sample", self.run_cli("check", expected=1).stdout)

    def test_check_changed_new_removed_adapted_source_changed_and_no_writes(self):
        adapted_source = self.home / "adapted.py"
        adapted_source.write_text("upstream")
        adapted_dest = self.root / "hooks/adapted.py"
        adapted_dest.parent.mkdir()
        adapted_dest.write_text("local adapted")
        adapted = dict(self.entry, name="adapted", source="~/adapted.py", dest="hooks/adapted.py", status="adapted")
        removed = dict(self.entry, name="removed", dest="skills/removed")
        self.config["entries"] += [adapted, removed]
        self.run_cli()
        self.assertEqual(adapted_dest.read_text(), "local adapted")
        self.assertIn("adapted", self.lock()["entries"])
        self.run_cli("check")
        self.put("SKILL.md", "changed source")
        adapted_source.write_text("changed upstream")
        self.config["entries"].remove(removed)
        self.config["entries"].append(dict(self.entry, name="added", dest="skills/added"))
        self.config_path.write_text(json.dumps(self.config))
        before = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.root.rglob("*") if p.is_file()}
        result = self.run_cli("check", expected=1, config=False)
        self.assertEqual(result.stdout.splitlines(), ["adapted-source-changed: adapted", "new: added", "changed: sample", "removed: removed"])
        after = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_check_missing_and_malformed_lock(self):
        self.assertEqual(self.run_cli("check", expected=1).stdout, "new: sample\n")
        path = self.root / "maintainer/export.lock.json"
        for value in ("{", "[]", '{"version":2,"entries":{}}'):
            path.write_text(value)
            self.run_cli("check", expected=2)

    def test_default_config_lives_outside_repo(self):
        self.env.pop("PLZDO_EXPORT_CONFIG")
        outside = self.home / ".config/plzdo/export.json"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text(json.dumps(self.config), encoding="utf-8")
        self.run_cli(config=False)
        self.assertTrue((self.root / "skills/sample/SKILL.md").exists())

    def test_adapted_missing_dest_is_problem_and_not_copied(self):
        self.entry["status"] = "adapted"
        result = self.run_cli(expected=1)
        self.assertIn("missing adapted dest: sample", result.stdout)
        self.assertFalse((self.root / "skills/sample").exists())
        self.assertFalse((self.root / "maintainer/export.lock.json").exists())

    def test_unshipped_sources_have_null_dest_hash_and_null_sources_omit_lock(self):
        self.entry.update(status="link-only", dest=None)
        self.config["entries"].append(dict(self.entry, name="excluded", status="excluded", source=None))
        self.config["entries"].append(dict(self.entry, name="manual", status="manual-config", source=None))
        self.run_cli()
        self.assertEqual(set(self.lock()["entries"]), {"sample"})
        self.assertIsNone(self.lock()["entries"]["sample"]["dest_sha256"])
        self.assertFalse((self.root / "skills").exists())
        self.run_cli("check")

    def test_inventory_preserves_outside_bytes_and_escapes_cells(self):
        path = self.root / "INVENTORY.md"
        prefix = b"\xef\xbb\xbf# Inventory\r\nunchanged  \r\n<!-- inventory:start -->\r\n"
        suffix = b"<!-- inventory:end -->\r\nfooter\x00\xff"
        path.write_bytes(prefix + b"old generated content\r\n" + suffix)
        self.config["entries"].append(dict(self.entry, name="aaa", company=False, commit="v1", dest="skills/aaa"))
        for kind in reversed(export.KINDS[1:]):
            self.config["entries"].append(dict(self.entry, name=kind, kind=kind, status="link-only", source=None,
                                               dest=None, upstream=None, commit=None))
        self.run_cli("inventory")
        data = path.read_bytes()
        self.assertTrue(data.startswith(prefix))
        self.assertTrue(data.endswith(suffix))
        region = data[len(prefix):-len(suffix)].decode()
        self.assertIn("A \\| note", region)
        self.assertIn("github.com/example/sample@" + "a" * 12 + " |", region)
        self.assertIn("github.com/example/sample@v1 |", region)
        self.assertIn("`skills/sample`", region)
        self.assertIn("| aaa |  |", region)
        self.assertIn("| sample | yes |", region)
        self.assertLess(region.index("| aaa |"), region.index("| sample |"))
        self.assertEqual([line for line in region.splitlines() if line.startswith("### ")],
                         ["### " + kind.title() for kind in export.KINDS])
        self.run_cli("inventory")
        self.assertEqual(path.read_bytes(), data)

    def test_inventory_skips_empty_kinds_and_requires_marker_lines(self):
        path = self.root / "INVENTORY.md"
        self.run_cli("inventory", expected=2)
        for data in (b"no markers", b"<!-- inventory:end -->\n<!-- inventory:start -->\n",
                     b"prefix <!-- inventory:start -->\n<!-- inventory:end -->\n",
                     b"<!-- inventory:start -->\n<!-- inventory:start -->\n<!-- inventory:end -->"):
            path.write_bytes(data)
            self.run_cli("inventory", expected=2)
            self.assertEqual(path.read_bytes(), data)
        path.write_text("<!-- inventory:start -->\n<!-- inventory:end -->")
        self.run_cli("inventory")
        self.assertIn("### Skill\n", path.read_text())
        self.assertNotIn("### Agent", path.read_text())

    def test_config_inside_repo_refused(self):
        inside_repo = self.root / "maintainer/export.json"
        inside_repo.write_text(json.dumps(self.config))
        result = self.run_cli("export", "--config", str(inside_repo), expected=2, config=False)
        self.assertIn("export config must be outside the repo", result.stderr)
        link = self.home / "link.json"
        link.symlink_to(inside_repo)
        self.run_cli("export", "--config", str(link), expected=2, config=False)
        self.assertFalse((self.root / "skills/sample").exists())

    def test_custom_config_and_malformed_json(self):
        alternate = self.home / "config.json"
        alternate.write_text(json.dumps(self.config))
        self.run_cli("export", "--config", str(alternate), config=False)
        alternate.write_text("{")
        self.run_cli("export", "--config", str(alternate), expected=2, config=False)

    def test_overlap_with_source_prevents_removal(self):
        self.entry.update(source=str(self.root / "skills/sample"))
        dest = self.root / "skills/sample"
        dest.mkdir(parents=True)
        (dest / "keep").write_text("keep")
        self.run_cli(expected=2)
        self.assertEqual((dest / "keep").read_text(), "keep")

    def test_resolved_file_overlap_preserves_all_destinations(self):
        for other_dest in ("skills/sample", "skills/other"):
            with self.subTest(dest=other_dest):
                self.config["entries"] = [self.entry]
                if other_dest != self.entry["dest"]:
                    self.config["entries"].append(dict(self.entry, name="other", dest=other_dest))
                dest = self.root / other_dest
                dest.mkdir(parents=True, exist_ok=True)
                keep = dest / "keep.txt"
                keep.write_text("irreplaceable")
                link = self.source / "linked.txt"
                if link.is_symlink():
                    link.unlink()
                link.symlink_to(keep)
                result = self.run_cli(expected=2)
                self.assertIn("overlap", result.stderr)
                self.assertEqual(keep.read_text(), "irreplaceable")
                self.assertFalse((self.root / "skills/sample/SKILL.md").exists())
                link.unlink()

    def test_cross_entry_source_ancestor_prevents_any_removal(self):
        dest = self.root / "skills/sample"
        dest.mkdir(parents=True)
        (dest / "keep").write_text("keep")
        self.config["entries"].append(dict(self.entry, name="other", source=str(self.root / "skills"),
                                           dest="agents/other"))
        self.run_cli(expected=2)
        self.assertEqual((dest / "keep").read_text(), "keep")

    def test_private_identifier_config_keys_are_not_echoed(self):
        self.config["private-example-one"] = "sensitive value"
        self.entry["private-example-two"] = "sensitive value"
        result = self.run_cli(expected=2)
        self.assertIn("config: unknown key", result.stderr)
        self.assertIn("config: entries[1]: unknown key", result.stderr)
        for private in ("private-example-one", "private-example-two", "sensitive value"):
            self.assertNotIn(private, result.stdout + result.stderr)

    def test_private_identifiers_redacted_in_symlinks_orphans_and_findings(self):
        (self.source / "prefix-private-example-one-link").symlink_to(self.home, target_is_directory=True)
        orphan = self.root / "skills/private-example-two-orphan"
        orphan.mkdir(parents=True)
        self.put("private-example-one.txt", "private-example-two")
        result = self.run_cli(expected=1)
        self.assertIn("skipped directory symlink: prefix-[private]-link", result.stdout)
        self.assertIn("orphan: skills/[private]-orphan", result.stdout)
        self.assertIn("skills/sample/[private].txt:1: private-id 2", result.stdout)
        self.assertNotIn("private-example-one", result.stdout + result.stderr)
        self.assertNotIn("private-example-two", result.stdout + result.stderr)

    def test_private_identifiers_redacted_in_all_check_labels(self):
        self.entry["name"] = "prefix-private-example-one-suffix"
        result = self.run_cli("check", expected=1)
        self.assertEqual(result.stdout, "new: prefix-[private]-suffix\n")
        self.config["replacements"] = [["private-example-one", "public"]]
        self.run_cli()
        self.put("new.txt", "changed")
        self.assertEqual(self.run_cli("check", expected=1).stdout, "changed: prefix-[private]-suffix\n")
        self.entry["status"] = "adapted"
        self.assertEqual(self.run_cli("check", expected=1).stdout,
                         "adapted-source-changed: prefix-[private]-suffix\n")
        self.config["entries"] = []
        self.assertEqual(self.run_cli("check", expected=1).stdout, "removed: prefix-[private]-suffix\n")

    def test_private_identifiers_redacted_in_cli_help_and_errors(self):
        self.ids.write_text("export\nprivate-example-one\n")
        result = self.run_cli("--help")
        self.assertIn("[private].py", result.stdout)
        self.assertNotIn("export", result.stdout + result.stderr)
        result = self.run_cli("private-example-one", expected=2)
        self.assertEqual(result.stderr, "[private]: invalid command line\n")

    def test_private_identifiers_redacted_in_missing_adapted_and_config_errors(self):
        self.entry.update(name="private-example-one", status="adapted")
        self.assertEqual(self.run_cli(expected=1).stdout, "missing adapted dest: [private]\n")
        self.ids.write_text("version\n")
        self.config["version"] = 2
        self.assertEqual(self.run_cli(expected=2).stderr, "config: [private] must be 1\n")

    def test_private_ids_must_resolve_outside_repo(self):
        internal = self.root / "private-example-one.txt"
        internal.write_text("private-example-one\n")
        alias = self.home / "alias.txt"
        alias.symlink_to(internal)
        for path in (internal, alias):
            for command in ("export", "check", "inventory"):
                with self.subTest(path=path, command=command):
                    result = self.run_cli(command, "--private-ids", str(path), expected=2)
                    self.assertEqual(result.stderr, "private identifiers file must be outside the repo\n")
        self.assertFalse((self.root / "skills").exists())

    def test_add_copies_unmodified_files_and_updates_dest_digest_and_license(self):
        source = self.root / "maintainer/licenses/sample.LICENSE"
        source.parent.mkdir()
        source.write_text("old license")
        source.chmod(0o640)
        self.config["replacements"] = [["old", "new"]]
        for status, origin in (("copy-ready", "vendored"), ("needs-runtime", "modified")):
            with self.subTest(status=status, origin=origin):
                self.entry.update(status=status, origin=origin)
                self.entry.pop("add", None)
                self.run_cli()
                before = self.lock()["entries"]["sample"]
                self.assertTrue(any(p.rule == "license" for p in validate.validate(self.root)))
                self.entry["add"] = {"LICENSE": "maintainer/licenses/sample.LICENSE",
                                     "legal/COPYING": "maintainer/licenses/sample.LICENSE"}
                self.run_cli()
                dest = self.root / "skills/sample"
                self.assertEqual((dest / "LICENSE").read_text(), "old license")
                self.assertEqual((dest / "legal/COPYING").read_text(), "old license")
                self.assertEqual((dest / "LICENSE").stat().st_mode & 0o777, 0o640)
                after = self.lock()["entries"]["sample"]
                self.assertEqual(before["source_sha256"], after["source_sha256"])
                self.assertNotEqual(before["dest_sha256"], after["dest_sha256"])
                self.assertEqual(after["dest_sha256"], export.digest(export.files_at(dest), exclude_source=True))
                self.assertFalse(any(p.rule == "license" for p in validate.validate(self.root)))

    def test_add_invalid_values_rejected_before_removal(self):
        self.run_cli()
        keep = self.root / "skills/sample/SKILL.md"
        before = keep.read_bytes()
        source = self.root / "maintainer/license.txt"
        source.write_text("license")
        for addition in (None, [], "bad", {"LICENSE": 1}, {"LICENSE": "missing"},
                         {"LICENSE": "maintainer"}, {"LICENSE": str(source)},
                         {"LICENSE": "../outside/sources/sample/SKILL.md"},
                         {"LICENSE": "skills/sample/SKILL.md"},
                         {"../LICENSE": "maintainer/license.txt"},
                         {"/LICENSE": "maintainer/license.txt"},
                         {"a/../LICENSE": "maintainer/license.txt"},
                         {"": "maintainer/license.txt"}, {".": "maintainer/license.txt"}):
            with self.subTest(addition=addition):
                self.entry["add"] = addition
                self.assertIn("add", self.run_cli(expected=2).stderr)
                self.assertEqual(keep.read_bytes(), before)

    def test_add_requires_copy_status_and_folder_source(self):
        source = self.root / "maintainer/license.txt"
        source.write_text("license")
        self.entry["add"] = {"LICENSE": "maintainer/license.txt"}
        for status in ("adapted", "manual-config", "link-only", "excluded"):
            self.entry["status"] = status
            self.assertIn("add", self.run_cli(expected=2).stderr)
        self.entry.update(status="copy-ready", source="~/sources/sample/SKILL.md")
        self.assertIn("add", self.run_cli(expected=2).stderr)

    def test_add_overlays_tree_before_generated_source_note_and_is_scanned(self):
        source = self.root / "maintainer/license.txt"
        source.write_text("private-example-one")
        self.put("LICENSE", "upstream license")
        self.config["replacements"] = [["private-example-one", "public"]]
        self.entry["add"] = {"LICENSE": "maintainer/license.txt", "SOURCE.md": "maintainer/license.txt"}
        result = self.run_cli(expected=1)
        self.assertIn("skills/sample/LICENSE:1: private-id 1", result.stdout)
        self.assertNotIn("private-example-one", result.stdout + result.stderr)
        self.assertEqual((self.root / "skills/sample/LICENSE").read_text(), "private-example-one")
        self.assertIn("origin: vendored", (self.root / "skills/sample/SOURCE.md").read_text())

    def test_add_target_cannot_escape_through_existing_symlink(self):
        dest = self.root / "skills/sample"
        dest.mkdir(parents=True)
        (dest / "legal").symlink_to(self.home, target_is_directory=True)
        source = self.root / "maintainer/license.txt"
        source.write_text("license")
        self.entry["add"] = {"legal/LICENSE": "maintainer/license.txt"}
        self.assertIn("add target must stay inside dest", self.run_cli(expected=2).stderr)
        self.assertTrue((dest / "legal").is_symlink())
        self.assertFalse((self.home / "LICENSE").exists())

    def test_add_resolves_source_links_and_checks_all_destinations(self):
        alias = self.root / "maintainer/license.txt"
        self.entry["add"] = {"LICENSE": "maintainer/license.txt"}
        alias.symlink_to(self.source / "SKILL.md")
        self.run_cli(expected=2)
        alias.unlink()
        other = self.root / "skills/other"
        other.mkdir(parents=True)
        keep = other / "LICENSE"
        keep.write_text("keep license")
        alias.symlink_to(keep)
        self.config["entries"].append(dict(self.entry, name="other", dest="skills/other", add={}))
        self.run_cli(expected=2)
        self.assertEqual(keep.read_text(), "keep license")


if __name__ == "__main__":
    unittest.main()
