"""Rebuild compact-geometry-r1 exactly as it was at takeover, inside R/L.

Usage: python -B takeover_tree.py OUT_NAME
Writes R/L/OUT_NAME/compact-geometry-r1/ with every takeover file: unchanged
files are copied from live C, changed ones from before-src/ or premerge-wave1/,
and files added since takeover are left out. Every written file's SHA-256 must
equal the takeover snapshot, or the script refuses. Tests can then be run from
that copy (it sits beside the real R siblings via relative paths only where the
tests use HERE-relative lookups) to tell pre-existing failures from new ones.
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
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    out = R/'L'/sys.argv[1]/'compact-geometry-r1'
    out.mkdir(parents=True, exist_ok=False)
    recorded = json.loads((HERE/'baseline-hashes-takeover.json').read_text(encoding='utf8'))
    prefix = 'compact-geometry-r1/'
    rows = {key[len(prefix):]: value for key, value in recorded.items()
            if key.startswith(prefix) and '/' not in key[len(prefix):]}
    sources, problems = {}, []
    for name, row in sorted(rows.items()):
        for candidate in (C/name, HERE/'before-src'/name, HERE/'premerge-wave1'/name):
            if candidate.exists() and sha(candidate) == row['sha256']:
                sources[name] = candidate
                break
        else:
            problems.append(name)
    if problems:
        raise SystemExit('no takeover-identical copy for: '+', '.join(problems))
    for name, source in sources.items():
        shutil.copyfile(source, out/name)
    # Non-Python files and subfolders the tests read (fixtures, json, native/).
    for item in C.iterdir():
        if item.name in sources or item.name == '__pycache__' or item.suffix == '.py':
            continue
        if item.is_dir():
            shutil.copytree(item, out/item.name, ignore=shutil.ignore_patterns('__pycache__'))
        else:
            shutil.copyfile(item, out/item.name)
    print(json.dumps({'tree': str(out), 'python_files': len(sources),
                      'from_live': sum(1 for s in sources.values() if s.parent == C)}))


if __name__ == '__main__':
    main()
