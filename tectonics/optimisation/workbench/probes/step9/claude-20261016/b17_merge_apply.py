"""B17 rev4 + item 14: apply the cleared merge into the live compact folder as one unit, or revert it.

Usage: python -B b17_merge_apply.py check|apply|revert

check  prints the live sha256 of each of the seven paths and whether it is the origin or the candidate.
apply  refuses before the first write unless each of the four existing files still hashes to its origin, the
       three new files are absent, and every source hashes to its candidate. It then writes a before-copy of
       each existing file (refusing to overwrite one), copies all seven (each through a temporary file and
       os.replace) and re-hashes all seven. A failure after the first copy restores the before-copies and
       removes the new files, so the folder is never left half-merged.
revert undoes only this merge's own bytes: each existing file must hash to its candidate and its before-copy to
       its origin; each new file must hash to its candidate. Anything else refuses before the first write.
Paths are derived from this file's place (probes/step9/<chat> inside the resumability folder).
"""
from hashlib import sha256
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
RESUMABILITY = HERE.parents[2]
COMPACT = RESUMABILITY/'compact-geometry-r1'
BEFORE = RESUMABILITY/'probes'/'step8'/'claude-20261015'/'before-src'
BACKLOG = RESUMABILITY.parents[2]/'claude-review-steps1-7-20261015'/'fixes'/'backlog'
B17 = BACKLOG/'b17-dir'/'candidate'
ITEM14 = BACKLOG/'item14-pagefix'

# (live name, source, origin sha256 or None for a new file, candidate sha256)
MERGE = [
    ('segment_store.py', B17/'segment_store.py',
     '1f503604cbe76e39c80ae2260a2e485d70c2ee047326488aa8d2baa620cde53a',
     'a90ef8f3e519ee77ea4332380428ce2694c16134ec69603ccaf93ce95cea6cd9'),
    ('storage_codec_integration_patch.py', B17/'storage_codec_integration_patch.py',
     '5102778b86e2c9f28c3cb051365807c44a63ade04a26b4a0ca847b347576a40c',
     '39d71ed0ec7c0ba3f2d65169b3642308e57cc0a8436b27d330cf18d3e6bfbe0f'),
    ('test_s1_sealed_read.py', B17/'test_s1_sealed_read.py',
     '3c1cf7c1114a4c78ed6fb4a3dae32a115108e4e7757ef5381ec4d74794afc8bb',
     '54edda3ff75629f466ae5e9619102771e7d9e9176f1f907b0e3aae75318e95c6'),
    ('test_b17_binding_directory.py', B17/'test_b17_binding_directory.py', None,
     '25e7339b456511277f5c28f99198249224d11b7079f6dfc09810f23f49929908'),
    ('record_views.py', ITEM14/'candidate'/'record_views.py',
     'e0a2a8453f494e50cacded7de06e275b1e36f526c220df611bbedb69248e0f9b',
     'a6bbb81dcc88c7f4b84272929922a8e4f702694163b18d18c26d3b76a86f89bd'),
    ('test_item14_page_layer.py', ITEM14/'candidate'/'test_item14_page_layer.py', None,
     'abd3bbd466fcca61dd7632e0bb3178df5bd589bd133c71a1b8d9a5f35bcfbd60'),
    ('item14_origin_record_views.py', ITEM14/'origin'/'record_views.py', None,
     'e0a2a8453f494e50cacded7de06e275b1e36f526c220df611bbedb69248e0f9b'),
]
SUFFIX = '.before-b17'


def digest(path):
    return sha256(path.read_bytes()).hexdigest() if path.exists() else None


def place(data, target):
    temporary = target.with_name(target.name + '.b17-merge-tmp')
    if temporary.exists():
        raise SystemExit(f'{temporary} exists; refusing')
    temporary.write_bytes(data)
    os.replace(temporary, target)


def check():
    for name, _, origin, new in MERGE:
        value = digest(COMPACT/name)
        state = 'absent' if value is None else 'origin' if value == origin else 'candidate' if value == new else 'OTHER'
        print(f'{name:38s} {(value or "-")[:8]:8s} {state}')
    return 0


def apply():
    problems = []
    for name, source, origin, new in MERGE:
        live = digest(COMPACT/name)
        if live != origin:
            problems.append(f'{name}: live {(live or "absent")[:8]} is not the origin {(origin or "absent")[:8]}')
        if digest(source) != new:
            problems.append(f'{name}: source {source} is not the candidate {new[:8]}')
        if origin is not None and (BEFORE/(name + SUFFIX)).exists():
            problems.append(f'{name}: before-copy {name + SUFFIX} exists')
    if problems:
        print('REFUSED before any write:', *problems, sep='\n  ')
        return 1
    BEFORE.mkdir(parents=True, exist_ok=True)
    for name, _, origin, _ in MERGE:
        if origin is not None:
            (BEFORE/(name + SUFFIX)).write_bytes((COMPACT/name).read_bytes())
            if digest(BEFORE/(name + SUFFIX)) != origin:
                print(f'REFUSED: the before-copy of {name} does not hash to its origin; nothing merged')
                return 1
    placed = []
    try:
        for name, source, _, new in MERGE:
            place(source.read_bytes(), COMPACT/name)
            placed.append(name)
        wrong = [name for name, _, _, new in MERGE if digest(COMPACT/name) != new]
        if wrong:
            raise RuntimeError(f'merged files do not hash to their candidates: {wrong}')
    except BaseException as error:
        for name, _, origin, _ in MERGE:
            if name not in placed:
                continue
            if origin is None:
                (COMPACT/name).unlink()
            else:
                place((BEFORE/(name + SUFFIX)).read_bytes(), COMPACT/name)
        print('ROLLED BACK after', repr(error))
        check()
        return 1
    print('MERGED all', len(MERGE), 'files')
    return check()


def revert():
    problems = []
    for name, _, origin, new in MERGE:
        if digest(COMPACT/name) != new:
            problems.append(f'{name}: live is not the candidate {new[:8]}')
        if origin is not None and digest(BEFORE/(name + SUFFIX)) != origin:
            problems.append(f'{name}: before-copy is not the origin {origin[:8]}')
    if problems:
        print('REFUSED before any write:', *problems, sep='\n  ')
        return 1
    for name, _, origin, _ in MERGE:
        if origin is None:
            (COMPACT/name).unlink()
        else:
            place((BEFORE/(name + SUFFIX)).read_bytes(), COMPACT/name)
    print('REVERTED all', len(MERGE), 'files')
    return check()


if __name__ == '__main__':
    actions = {'check': check, 'apply': apply, 'revert': revert}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        print(__doc__)
        sys.exit(2)
    sys.exit(actions[sys.argv[1]]())
