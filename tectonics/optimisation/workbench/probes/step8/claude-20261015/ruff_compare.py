"""Introduced Ruff findings: same executable and rules for base and candidate.

Usage: python -B ruff_compare.py OUT.json FILE [FILE ...]
Base = the pre-edit copy in before-src (if the file existed at takeover),
candidate = the current file in C. Both are checked with --no-cache --isolated,
once with the default rule set and once with --select F821,F841,B905 (the set
Codex's receipts used). Check-only: never --fix, never format. A finding is
introduced when its (rule, message) count rises from base to candidate.
"""
from collections import Counter
import json
import os
import subprocess
import sys
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
C = os.path.join(R, 'compact-geometry-r1')
RUFF = 'C:/Users/LOCAL_USER/AppData/Local/Microsoft/WinGet/Packages/astral-sh.ruff_Microsoft.Winget.Source_8wekyb3d8bbwe/ruff.exe'
RULES = {'default': [], 'f821-f841-b905': ['--select', 'F821,F841,B905']}


def findings(path, extra):
    # Same file name in a private directory, so path-dependent rules match.
    with tempfile.TemporaryDirectory(prefix='ruff-cmp-') as directory:
        target = os.path.join(directory, os.path.basename(path))
        shutil.copyfile(path, target)
        result = subprocess.run([RUFF, 'check', '--no-cache', '--isolated', '--output-format', 'json', *extra, target],
                                capture_output=True, text=True)
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr)
        return Counter((row['code'], row['message']) for row in json.loads(result.stdout))


def main():
    out, names = sys.argv[1], sys.argv[2:]
    report = dict(ruff=RUFF, rules=RULES, files={})
    for name in names:
        # 'R:name' is a file in R itself (for example geometry_transfer.py).
        folder, plain = (R, name[2:]) if name.startswith('R:') else (C, name)
        current = os.path.join(folder, plain)
        base = os.path.join(HERE, 'before-src', plain)
        row = {}
        for label, extra in RULES.items():
            after = findings(current, extra)
            before = findings(base, extra) if os.path.exists(base) else Counter()
            introduced = after-before
            row[label] = dict(base_count=sum(before.values()), candidate_count=sum(after.values()),
                              base_existed=os.path.exists(base),
                              introduced=[dict(code=code, message=message, count=count)
                                          for (code, message), count in sorted(introduced.items())])
        report['files'][name] = row
        print(name, {label: (v['base_count'], v['candidate_count'], len(v['introduced'])) for label, v in row.items()})
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=1)


if __name__ == '__main__':
    main()
