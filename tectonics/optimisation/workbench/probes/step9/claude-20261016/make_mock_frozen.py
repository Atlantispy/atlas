"""Mock frozen tree for validating frozen_route1_profile.py (test only, never a production composition).

Usage: python -B make_mock_frozen.py TARGET

TARGET/src/atlas_tectonics = a copy of the s1 smoke's native package; TARGET/helpers = the top-level
.py files of R, C, composed-r1/helpers and composed-r1/ram flattened in s1's import order (first
found wins, as on the s1 path). TARGET must not exist.
"""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
ROOTS = (R, R/'compact-geometry-r1', R/'composed-r1'/'helpers', R/'composed-r1'/'ram')


def main():
    target = Path(sys.argv[1])
    target.mkdir()
    shutil.copytree(R/'s1'/'src'/'atlas_tectonics', target/'src'/'atlas_tectonics',
                    ignore=shutil.ignore_patterns('__pycache__'))
    helpers = target/'helpers'
    helpers.mkdir()
    taken = {}
    for root in ROOTS:
        for path in sorted(root.glob('*.py')):
            if path.name not in taken:
                shutil.copyfile(path, helpers/path.name)
                taken[path.name] = root.name
    print(json.dumps({'target': str(target), 'helpers': len(taken)}))


if __name__ == '__main__':
    main()
