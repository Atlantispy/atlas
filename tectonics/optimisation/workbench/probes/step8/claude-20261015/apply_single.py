"""Copy one hand-off file into C after checking live and new SHA-256.

Usage: python -B apply_single.py SOURCE NAME LIVE_SHA256 NEW_SHA256 LABEL
Refuses (changes nothing) unless C/NAME has exactly LIVE_SHA256 and SOURCE has
exactly NEW_SHA256. Saves the live file to premerge-LABEL/NAME, copies, checks
the result and writes merge-LABEL.json with all three hashes.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
C = HERE.parents[2]/'compact-geometry-r1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    source, name, live, new, label = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
    target = C/name
    problems = []
    if sha(target) != live:
        problems.append('live C differs from the expected origin: '+sha(target))
    if sha(source) != new:
        problems.append('hand-off file differs from its stated hash: '+sha(source))
    receipt = dict(label=label, source=str(source), file=name, live_before=sha(target),
                   expected_live=live, new=new, applied=False, problems=problems)
    if problems:
        print(json.dumps(receipt, indent=1))
        raise SystemExit(1)
    saved = HERE/('premerge-'+label)
    saved.mkdir(exist_ok=False)
    shutil.copy2(target, saved/name)
    shutil.copyfile(source, target)
    receipt.update(applied=True, after=sha(target), premerge_copy=str(saved/name))
    if receipt['after'] != new:
        problems.append('bytes after copy differ from the hand-off hash')
    (HERE/('merge-'+label+'.json')).write_text(json.dumps(receipt, indent=1), encoding='utf8')
    print(json.dumps(receipt, indent=1))
    raise SystemExit(1 if problems else 0)


if __name__ == '__main__':
    main()
