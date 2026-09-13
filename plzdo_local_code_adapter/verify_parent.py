"""Pinned stdlib-only process entrypoint; never invokes the runtime."""
import sys

if sys.version_info < (3, 11) or not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
    raise SystemExit("plzdo parent verifier requires Python 3.11+ with -I -S -B")

from pathlib import Path
import importlib.util

# Load this one fixed sibling without adding its parent (possibly site-packages)
# to sys.path. Otherwise unpinned sibling modules could shadow the stdlib.
_spec = importlib.util.spec_from_file_location(
    "_plzdo_fixed_adapter_codec", Path(__file__).resolve().parent / "codec.py")
_codec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_codec)
AdapterError, MAX_INPUT = _codec.AdapterError, _codec.MAX_INPUT
canonical, decode, verify = _codec.canonical, _codec.decode, _codec.verify


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Verify one pinned PlzDo parent snapshot")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        envelope = decode(sys.stdin.buffer.read(MAX_INPUT + 1), MAX_INPUT, "verifier input")
        result = verify(envelope, Path(args.config))
        sys.stdout.buffer.write(canonical(result) + b"\n")
        return 0
    except (AdapterError, OSError, TypeError, KeyError) as exc:
        # Do not forward core stderr, document text, paths or exception contents.
        print("plzdo-local-code-adapter: parent verification rejected", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
