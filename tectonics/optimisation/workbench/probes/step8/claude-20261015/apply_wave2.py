"""Apply the wave-2 storage and non-storage hand-offs with hash checks (one generation).

Usage: python -B apply_wave2.py [--dry-run]
Every target's live sha256 must equal its expected value before anything is
written: the manifest origin for clean files, absent for new files, and my own
current live hash for the three 3-way files (their merged text comes from
merge-wave2/, made with git merge-file against the origin copies in before-src/).
Any mismatch refuses the whole apply before the first write. Every replaced
file is copied to before-src/<name>.before-wave2 first. codec_*, cold_archive*
and native/* are never touched (none is in either package).
"""
import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
FIXES = R.parents[2]/'claude-review-steps1-7-20261015'/'fixes'
PACKAGES = (FIXES/'handoff-wave2-storage', FIXES/'handoff-wave2')
MERGED = HERE/'merge-wave2'
# The three files the packages could not apply cleanly: my live hash at merge time.
THREE_WAY = {'spatial_validation_patch.py': '2cd042cdf8a8af181a3c2eda953d9d1096ce25c9ec20c952612025d35ac0aff3',
             'mesh_tables.py': 'e0393b14942e8a355ebbf511d66cda7de4e88bb02b2f9ca7fd27630637d07f65',
             'compact_restart_store.py': '434988714d20e88b3f65e7eb18a50d8a965f287881465cbaa68843431a9901fd'}
FORBIDDEN = ('codec_', 'cold_archive', 'native')


def digest(path):
    return sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def plan():
    rows = []
    for package in PACKAGES:
        manifest = json.loads((package/'manifest.json').read_text(encoding='utf-8'))
        for name, row in sorted(manifest['files'].items()):
            plain = Path(name).name
            if plain.startswith(FORBIDDEN):
                raise SystemExit('refused: forbidden WP10 file in package: '+name)
            target = (R if row.get('level') == 'R' else C)/plain
            if plain in THREE_WAY:
                source, expected_live = MERGED/(Path(plain).stem+'.merged.py'), THREE_WAY[plain]
            else:
                source, expected_live = package/row['path_in_handoff'], row.get('origin_sha256')
                if digest(source) != row['new_sha256']:
                    raise SystemExit('refused: package file differs from manifest: '+name)
            rows.append((name, target, source, expected_live, row.get('captured_by_heat_issuer') == 'yes'))
    return rows


def main():
    dry = '--dry-run' in sys.argv[1:]
    rows = plan()
    problems = [f'{name}: live {(digest(target) or "absent")[:8]} expected {(expected or "absent")[:8]}'
                for name, target, _, expected, _ in rows if digest(target) != expected]
    if problems:
        raise SystemExit('refused before any write:\n'+'\n'.join(problems))
    result = []
    for name, target, source, expected, captured in rows:
        if not dry:
            if expected is not None:
                shutil.copyfile(target, HERE/'before-src'/(target.name+'.before-wave2'))
            shutil.copyfile(source, target)
        result.append(dict(file=name, target=str(target.relative_to(R)), before=expected,
                           after=digest(source), captured=captured))
        print(f"{'C' if target.parent == C else 'R'} {target.name:36} {'CAPTURED' if captured else '        '} "
              f"{(expected or '-')[:8]} -> {digest(source)[:8]}{'  (dry run)' if dry else ''}")
    if not dry:
        (HERE/'apply-wave2.json').write_text(json.dumps(result, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
