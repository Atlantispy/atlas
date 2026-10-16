"""Apply the storage generation hand-off (S1 + G8 + 9(a) + WP10 rev2) with hash checks, as one generation.

Usage: python -B apply_gen1.py [--dry-run]

Reads fixes/handoff-gen-r1a-storage/manifest.json. Before the first write, every row
must hold: 'already applied' rows have live == new; 'clean' rows have live == origin
and package file == new; 'new' rows have no live file and package file == new. Any
mismatch refuses the whole apply. Every replaced file is first copied to
before-src/<name>.before-gen1. codec_*, cold_archive* and native/* are never written
(the coordinator's merge conditions; none is listed). The record goes to apply-gen1.json.
"""
import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
HANDOFF = R.parents[2]/'claude-review-steps1-7-20261015'/'fixes'/'handoff-gen-r1a-storage'
FORBIDDEN = ('codec_', 'cold_archive')
CAPTURED = {'segment_store.py', 'interval_store_set.py', 'record_views.py'}


def digest(path):
    return sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def plan():
    manifest = json.loads((HANDOFF/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema') != 'atlas.review.generation-handoff.v1':
        raise SystemExit('refused: unknown hand-off schema')
    rows, problems = [], []
    for row in manifest['files']:
        target, source = Path(row['live_path']), Path(row['package_file'])
        name = target.name
        if name.startswith(FORBIDDEN) or 'native' in target.parts or target.parent != C:
            raise SystemExit('refused: target outside the agreed compact files: '+str(target))
        live, new = digest(target), row['new_sha256']
        if row['apply'] == 'already applied (live == new)':
            ok, write = live == new, False
        elif row['apply'] == 'clean':
            ok, write = live == row['origin_sha256'] and digest(source) == new, True
        elif row['apply'] == 'new':
            ok, write = live is None and row['origin_sha256'] is None and digest(source) == new, True
        else:
            raise SystemExit('refused: unknown apply kind '+row['apply'])
        if not ok:
            problems.append(f"{name}: live {(live or 'absent')[:8]} origin {(row['origin_sha256'] or 'absent')[:8]} "
                            f"package {(digest(source) or 'absent')[:8]} new {new[:8]} ({row['apply']})")
        rows.append({'package': row['package'], 'file': name, 'target': target, 'source': source, 'write': write,
                     'before': live, 'after': new, 'kind': row['apply']})
    return rows, problems


def main():
    dry = '--dry-run' in sys.argv[1:]
    rows, problems = plan()
    if problems:
        raise SystemExit('refused before any write:\n'+'\n'.join(problems))
    result = []
    for row in rows:
        if row['write'] and not dry:
            if row['before'] is not None:
                shutil.copyfile(row['target'], HERE/'before-src'/(row['file']+'.before-gen1'))
            shutil.copyfile(row['source'], row['target'])
            if digest(row['target']) != row['after']:
                raise SystemExit('written file differs from its pin: '+row['file'])
        result.append({'package': row['package'], 'file': row['file'], 'kind': row['kind'],
                       'target': str(row['target'].relative_to(R)), 'before': row['before'], 'after': row['after'],
                       'heat_captured': row['file'] in CAPTURED})
        print(f"{row['package']:22} {row['file']:36} {row['kind']:30} "
              f"{(row['before'] or '-')[:8]} -> {row['after'][:8]}{'  (dry run)' if dry else ''}")
    if not dry:
        with open(HERE/'apply-gen1.json', 'x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=1)


if __name__ == '__main__':
    main()
