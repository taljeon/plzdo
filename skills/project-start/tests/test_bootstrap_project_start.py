from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap_project_start.py"


STANDARD_FILES = {
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
}


class BootstrapProjectStartTest(unittest.TestCase):
    def run_bootstrap(self, root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--root",
                str(root),
                "--project-name",
                "HarnessProbe",
                "--goal",
                "Build a deterministic probe harness.",
                *extra,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    def test_empty_bootstrap_generates_expected_safe_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            completed = self.run_bootstrap(root)

            self.assertIn("skipped_existing=none", completed.stdout)
            generated = {
                str(path.relative_to(root))
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(generated, STANDARD_FILES)

            for rel in (
                "scripts/harness-env.sh",
                "scripts/validate-local.sh",
                "scripts/verify-harness.sh",
            ):
                mode = (root / rel).stat().st_mode
                self.assertTrue(mode & stat.S_IXUSR, rel)

            agents = (root / "AGENTS.md").read_text(encoding="utf-8")
            for token in (
                "Source Of Truth Order",
                "complete Karpathy-style guideline set",
                "Think Before Coding",
                "Simplicity First",
                "Surgical Changes",
                "Goal-Driven Execution",
                "Every changed line should trace directly",
                "./scripts/verify-harness.sh",
            ):
                self.assertIn(token, agents)

            validate = (root / "scripts" / "validate-local.sh").read_text(encoding="utf-8")
            self.assertIn("python3 harness/contract_check.py", validate)
            for forbidden in ("npm run", "curl ", "wget ", "gh ", "gcloud ", "firebase "):
                self.assertNotIn(forbidden, validate)

    def test_generated_final_gate_runs_without_network_or_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as harness:
            root = Path(tmp)
            self.run_bootstrap(root)
            env = dict(os.environ)
            env["HARNESS_DIR"] = harness

            completed = subprocess.run(
                [str(root / "scripts" / "verify-harness.sh")],
                cwd=root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )

            self.assertIn("harness verification passed", completed.stdout)

    def test_idempotence_preserves_user_edits_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.run_bootstrap(root)
            target = root / "AGENTS.md"
            sentinel = "# user-owned edits\n"
            target.write_text(sentinel, encoding="utf-8")

            completed = self.run_bootstrap(root)

            self.assertEqual(target.read_text(encoding="utf-8"), sentinel)
            self.assertIn("AGENTS.md", completed.stdout)
            self.assertIn("skipped_existing=", completed.stdout)

    def test_force_backs_up_existing_managed_files_before_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.run_bootstrap(root)
            target = root / "AGENTS.md"
            sentinel = "# user-owned edits\n"
            target.write_text(sentinel, encoding="utf-8")

            completed = self.run_bootstrap(root, "--force")

            self.assertNotEqual(target.read_text(encoding="utf-8"), sentinel)
            backups = list((root / ".project-start-backup").rglob("AGENTS.md"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), sentinel)
            self.assertIn("backed_up=", completed.stdout)


if __name__ == "__main__":
    unittest.main()
