"""Apply a review-chat patch wave to C, verified file by file.

Usage: python -B merge_wave.py HANDOFF_DIR LABEL [--apply]
Without --apply: verify only and print the plan. With --apply: copy, then
re-verify. Every live file that will be replaced is first saved to
premerge-LABEL/ here, and a receipt merge-LABEL.json records each file's live
hash before, the handoff hash and the hash after. Refuses (changes nothing) if
any handoff file differs from its manifest hash, any clean file's live hash
differs from its origin, the 3-way file's live hash differs from the manifest's
live hash, or a new file already exists in C.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else None


def main():
    handoff, label, apply = Path(sys.argv[1]), sys.argv[2], '--apply' in sys.argv
    manifest = json.loads((handoff/'manifest.json').read_text(encoding='utf8'))
    plan, problems = [], []
    for name, row in sorted(manifest['files'].items()):
        source, target = handoff/'files'/name, C/name
        live = sha(target)
        if sha(source) != row['new_sha256']:
            problems.append(name+': handoff file differs from its manifest hash')
        if row['origin'] == 'new':
            if live is not None and live != row['new_sha256']:
                problems.append(name+': new file already exists in C with other bytes')
        elif row['apply'].startswith('clean'):
            if live != row['origin_sha256']:
                problems.append(name+': live C moved since origin ('+str(live)+')')
        elif row['apply'].startswith('3-way'):
            if live != row['live_sha256_now']:
                problems.append(name+': live C differs from the manifest live hash ('+str(live)+')')
        else:
            problems.append(name+': unknown apply rule '+row['apply'])
        plan.append({'file': name, 'rule': row['apply'], 'live_before': live, 'new': row['new_sha256']})
    receipt = {'handoff': str(handoff), 'label': label, 'applied': False, 'problems': problems, 'files': plan}
    if problems or not apply:
        print(json.dumps(receipt, indent=1))
        raise SystemExit(1 if problems else 0)
    saved = HERE/('premerge-'+label)
    saved.mkdir(exist_ok=False)
    for row in plan:
        target = C/row['file']
        if target.exists():
            shutil.copy2(target, saved/row['file'])
    for row in plan:
        shutil.copyfile(handoff/'files'/row['file'], C/row['file'])
        row['after'] = sha(C/row['file'])
        if row['after'] != row['new']:
            problems.append(row['file']+': bytes after copy differ from the handoff hash')
    receipt.update(applied=True, problems=problems, premerge_copies=str(saved))
    (HERE/('merge-'+label+'.json')).write_text(json.dumps(receipt, indent=1), encoding='utf8')
    print(json.dumps({'applied': True, 'files': len(plan), 'problems': problems}))
    raise SystemExit(1 if problems else 0)


if __name__ == '__main__':
    main()
