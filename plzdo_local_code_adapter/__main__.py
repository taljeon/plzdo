import sys

if not (sys.flags.isolated and sys.flags.no_site):
    raise SystemExit("plzdo-local-code-adapter: use the isolated launcher")

from .cli import main

raise SystemExit(main())
