import sys

if sys.version_info < (3, 9) or not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
    raise SystemExit("plzdo: use the launcher (Python 3.9+ with -I -S -B is required)")

import importlib
import importlib.util
from pathlib import Path
import sysconfig


def package_path(name):
    """Only examine fixed source/installation paths below this launcher's prefix."""
    prefix = Path(__file__).resolve().parent.parent
    roots = {prefix}
    variables = {"base": str(prefix), "platbase": str(prefix), "userbase": str(prefix)}
    for scheme in ("posix_prefix", "posix_user", "osx_framework_user"):
        if scheme in sysconfig.get_scheme_names():
            roots.add(Path(sysconfig.get_path("purelib", scheme=scheme, vars=variables)))
    packages = []
    for root in sorted(roots):
        package = root / name
        if package.exists() or package.is_symlink():
            if not package.is_relative_to(prefix) or package.resolve(strict=True) != package:
                raise ValueError("package path crosses a symlink or escapes the launcher prefix")
            if not package.is_dir() or not (package / "__init__.py").is_file() or (package / "__init__.py").is_symlink():
                raise ValueError("package path is not a regular package")
            packages.append(package)
    if len(packages) != 1:
        raise ValueError("exactly one source or installed package is required")
    return packages[0]


def main(argv=None, *, package_name="plzdo_local"):
    if package_name not in {"plzdo_local", "plzdo_local_code_adapter"}:
        raise ValueError("unsupported entry")
    package = package_path(package_name)
    spec = importlib.util.spec_from_file_location(package_name, package / "__init__.py",
                                                 submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    spec.loader.exec_module(module)
    return importlib.import_module(package_name + ".cli").main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
