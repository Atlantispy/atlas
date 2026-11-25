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
    options = parser.parse_args()
    return run(options.operation, options.settings)


if __name__ == "__main__":
    raise SystemExit(main())
