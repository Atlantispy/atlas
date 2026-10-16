"""Read-only: module names present in more than one route (1) import root, with differing bytes.

The s1 profile resolved helpers over (R, C, composed-r1/helpers, composed-r1/ram, H tests), first
match wins. A flattened frozen helpers folder must keep that precedence. Prints every name found
in two or more roots, the root that wins, and whether the copies differ.
"""
from collections import defaultdict
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
WORKSPACE = R.parents[3]
ROOTS = (R, R/'compact-geometry-r1', R/'composed-r1'/'helpers', R/'composed-r1'/'ram',
         WORKSPACE/'fidelity-integration-20261005'/'heat-repair-20261007'/'source'/'tectonics'/'tests')


def main():
    seen = defaultdict(list)
    for root in ROOTS:
        for path in sorted(root.glob('*.py')):
            seen[path.name].append((root, sha256(path.read_bytes()).hexdigest()))
    shared = {name: rows for name, rows in seen.items() if len(rows) > 1}
    differing = {name: rows for name, rows in shared.items() if len({digest for _, digest in rows}) > 1}
    print(f'{sum(map(len, seen.values()))} files, {len(seen)} names; {len(shared)} in two or more roots, '
          f'{len(differing)} of them with differing bytes')
    for name, rows in sorted(differing.items()):
        winner = rows[0][0].relative_to(R.parent) if rows[0][0].is_relative_to(R.parent) else rows[0][0]
        print(f'  {name}: wins {winner}; ' + ', '.join(f'{root.name}={digest[:8]}' for root, digest in rows))


if __name__ == '__main__':
    main()
