"""Copy pre-edit originals of the files this chat changed, verified by hash.

Sources are read-only copies taken before any Step 8 edit by this chat (the
Steps 1-7 review snapshot at 21:20). Each copy must equal the SHA-256 this
chat recorded at takeover (baseline-hashes-takeover.json) or it is refused.
Usage: python -B recover_originals.py NAME [NAME ...]
"""
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
T = os.path.normpath(os.path.join(R, '..', '..', '..', '..'))
REVIEW = os.path.join(T, 'fidelity-integration-20261005', 'claude-review-steps1-7-20261015', 'snapshot-start')
OUT = os.path.join(HERE, 'before-src')


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    with open(os.path.join(HERE, 'baseline-hashes-takeover.json'), encoding='utf-8') as f:
        recorded = json.load(f)
    os.makedirs(OUT, exist_ok=True)
    candidates = []
    for root, _, files in os.walk(REVIEW):
        for name in files:
            candidates.append(os.path.join(root, name))
    for name in sys.argv[1:]:
        key = 'compact-geometry-r1/'+name
        want = recorded[key]['sha256']
        found = [p for p in candidates if os.path.basename(p) == name and sha(p) == want]
        if not found:
            print('MISSING', name, want)
            continue
        target = os.path.join(OUT, name)
        shutil.copyfile(found[0], target)
        assert sha(target) == want
        print('OK', name, want, 'from', os.path.relpath(found[0], T))


if __name__ == '__main__':
    main()
