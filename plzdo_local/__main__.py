import sys

if not (sys.flags.isolated and sys.flags.no_site):
    raise SystemExit("plzdo: use the isolated plzdo launcher")

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
