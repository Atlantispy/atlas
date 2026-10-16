"""Copy hand-off files into R or C after checking every live and new SHA-256 and before-copy path.

Usage: python -B apply_files.py LABEL SOURCE TARGET LIVE_SHA256 NEW_SHA256 [SOURCE TARGET LIVE NEW ...]

TARGET is relative to R (resumability-r1) and must lie in R or R/compact-geometry-r1.
LIVE_SHA256 '-' adds a new file: the target must not exist yet. Every row is checked
before the first write; any mismatch refuses the whole apply. Each replaced file is
first copied to before-src/<name>.before-LABEL; the record goes to merge-LABEL.json
(exclusive). codec_*, cold_archive* and native/* are refused.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
ALLOWED = (R, R/'compact-geometry-r1')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None


def main():
    label, rest = sys.argv[1], sys.argv[2:]
    if not rest or len(rest) % 4:
        raise SystemExit('rows of SOURCE TARGET LIVE NEW required')
    rows, problems = [], []
    for index in range(0, len(rest), 4):
        source, target, live, new = Path(rest[index]), R/rest[index+1], rest[index+2], rest[index+3]
        if target.parent.resolve() not in {a.resolve() for a in ALLOWED} or target.name.startswith(
                ('codec_', 'cold_archive')) or 'native' in target.parts:
            raise SystemExit('refused target: '+str(target))
        if sha(target) != (None if live == '-' else live) or (live == '-' and target.exists()):
            problems.append(f'{target.name}: live {sha(target)} differs from the expected origin {live}')
        if sha(source) != new:
            problems.append(f'{target.name}: hand-off file {sha(source)} differs from its stated {new}')
        before = HERE/'before-src'/(target.name+'.before-'+label)
        # Windows MAX_PATH (260) is not lifted here: r1-generation-20261016 stopped part-way on it.
        if live != '-' and (len(str(before)) >= 260 or before.exists()):
            problems.append(f'{target.name}: before copy path too long or already present: {before.name}')
        rows.append((source, target, live, new, before))
    if problems:
        raise SystemExit('refused before any write:\n'+'\n'.join(problems))
    # Every before copy exists before the first target is written.
    for _, target, live, _, before in rows:
        if live != '-':
            shutil.copyfile(target, before)
    record = []
    for source, target, live, new, _ in rows:
        shutil.copyfile(source, target)
        if sha(target) != new:
            raise SystemExit('written file differs from its pin: '+target.name)
        record.append({'file': str(target.relative_to(R)), 'before': None if live == '-' else live, 'after': new,
                       'source': str(source)})
        print(f'{target.relative_to(R)}  {"(new)" if live == "-" else live[:8]} -> {new[:8]}')
    with open(HERE/f'merge-{label}.json', 'x', encoding='utf-8') as stream:
        json.dump(record, stream, indent=1)


if __name__ == '__main__':
    main()
