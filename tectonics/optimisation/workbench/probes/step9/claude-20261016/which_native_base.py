"""Read-only: which native tree a run record's clone matches, file by file (I, RC1, composed-r2, ...).

Usage: python -B which_native_base.py RUN_JSON

Reads native_source.clone_source_hashes (atlas_tectonics/<file> -> sha256) from a run record such
as heat-original-connected-20261013-r9.json and compares every file with I, RC1 and composed-r2.
Prints the match counts and, for the files that match neither I nor RC1, their names.
"""
import json
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
TREES = {'I': R.parent/'runtime-integration-r1'/'runtime-src', 'RC1': R/'composed-r1'/'runtime-src',
         'composed-r2': R/'composed-r2'/'src'}


def tree_hashes(root):
    return {path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in (root/'atlas_tectonics').rglob('*.py')}


def main():
    record = json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
    clone = record['native_source']['clone_source_hashes']
    trees = {name: tree_hashes(root) for name, root in TREES.items()}
    print('clone files', len(clone), '| changed_existing_files', record['native_source'].get('changed_existing_files'))
    for name, hashes in trees.items():
        same = sum(1 for key, value in clone.items() if hashes.get(key) == value)
        print(f'{name}: {same}/{len(clone)} identical ({len(hashes)} files in the tree)')
    neither = sorted(key for key, value in clone.items()
                     if trees['I'].get(key) != value and trees['RC1'].get(key) != value)
    print('matching neither I nor RC1:', neither)
    i_only = sorted(key for key, value in clone.items() if trees['I'].get(key) == value != trees['RC1'].get(key))
    rc1_only = sorted(key for key, value in clone.items() if trees['RC1'].get(key) == value != trees['I'].get(key))
    print('match I but not RC1:', i_only)
    print('match RC1 but not I:', rc1_only)


if __name__ == '__main__':
    main()
