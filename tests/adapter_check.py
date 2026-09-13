"""Fixed core/adapter checks; runtime integration has its own package gate."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        "tests.adapter.test_codec", "tests.adapter.test_integration"])
    runner = unittest.TextTestRunner()
    result = runner.run(suite)
    raise SystemExit(not result.wasSuccessful())
