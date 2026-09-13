"""Fixed adapter entry; no site-packages search path or runtime import."""
import sys

if sys.version_info < (3, 11) or not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
    raise SystemExit("plzdo-local-code-adapter: use the isolated launcher")

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("_plzdo_launch", Path(__file__).parent / "plzdo_entry.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
raise SystemExit(module.main(package_name="plzdo_local_code_adapter"))
