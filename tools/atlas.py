"""Atlas development commands."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_land import run


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    groups = parser.add_subparsers(required=True)
    land = groups.add_parser("land", help="Capture, compare or prepare an Atlas landing")
    operations = land.add_subparsers(dest="operation", required=True)
    for name in ("capture-compare", "prepare"):
        operation = operations.add_parser(name, allow_abbrev=False)
        operation.add_argument("--settings", required=True, type=Path)
    profile = groups.add_parser("profile", help="Read a finished whole-tree profile (--run-profile tree)")
    profile.add_argument("view", choices=("active", "check-share", "callers", "rows"))
    profile.add_argument("raw", type=Path)
    profile.add_argument("arguments", nargs="*", help="the view's own arguments")
    options = parser.parse_args()
    if "view" in options:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared" / "src"))
        from atlas_shared.execution import profiling
        words = [int(word) if word.isdigit() else word for word in options.arguments]
        if options.view == "rows":      # rows <source root> <output> <code=notes file>...
            words = [*words[:2], words[2:]]
        profiling.report(options.view, options.raw, *words)     # each view prints its own report
        return 0
    return run(options.operation, options.settings)


if __name__ == "__main__":
    raise SystemExit(main())
