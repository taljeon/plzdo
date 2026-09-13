"""Invoke the supported core CLI without adding its checkout to sys.path.

The verifier supplies a validated/pinned core root and a literal allowed command.
Only the fixed `plzdo_local` package gets a search path; stdlib discovery stays
under the isolated interpreter's -I -S environment.
"""
import sys

if sys.version_info < (3, 11) or not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
    raise SystemExit("plzdo parent core entry requires Python 3.11+ with -I -S -B")

from pathlib import Path
import importlib
import importlib.util
import re


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 4 or args[0] != '--core-root':
        return 2
    root = Path(args[1])
    command = args[2:]
    allowed = command in (['version', '--json'], ['state-root', 'status', '--json'])
    if len(command) == 4 and command[0:2] in (['project', 'show'], ['formalize', 'status']):
        allowed = bool(re.fullmatch(r'[a-z][a-z0-9-]{1,63}', command[2])) and command[3] == '--json'
    if not allowed or not root.is_absolute() or root.resolve(strict=True) != root:
        return 2
    package = root if root.name == 'plzdo_local' else root / 'plzdo_local'
    if package.resolve(strict=True) != package or (package / '__init__.py').is_symlink():
        return 2
    spec = importlib.util.spec_from_file_location('plzdo_local', package / '__init__.py',
                                                 submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    sys.modules['plzdo_local'] = module
    spec.loader.exec_module(module)
    # This is the same public CLI main used by the core's own launcher. No core
    # lifecycle or state API is called directly.
    return importlib.import_module('plzdo_local.cli').main(command)


if __name__ == '__main__':
    raise SystemExit(main())
