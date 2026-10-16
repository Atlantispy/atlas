"""Introduced Ruff findings between explicit (base, candidate) file pairs.

Usage: python -B ruff_pairs.py OUT.json BASE CANDIDATE [BASE CANDIDATE ...]
BASE may be '-' for a new file (every finding counts as introduced). Same
executable and rule sets as ruff_compare.py (native ruff 0.16.9, --no-cache
--isolated, default rules and --select F821,F841,B905). The base is checked
under the candidate's basename, so path-dependent rules match. Check-only.
"""
import json
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

from ruff_compare import RULES, findings


def base_findings(base, name, extra):
    if base == '-':
        return Counter()
    with tempfile.TemporaryDirectory(prefix='ruff-base-') as directory:
        renamed = Path(directory)/name
        shutil.copyfile(base, renamed)
        return findings(str(renamed), extra)


def main():
    out, items = Path(sys.argv[1]), sys.argv[2:]
    if not items or len(items) % 2:
        raise SystemExit('pairs of BASE CANDIDATE required')
    report = {}
    for base, candidate in zip(items[0::2], items[1::2], strict=True):
        name = Path(candidate).name
        row = {}
        for label, extra in RULES.items():
            after = findings(candidate, extra)
            before = base_findings(base, name, extra)
            introduced = after-before
            row[label] = {'base_count': sum(before.values()), 'candidate_count': sum(after.values()),
                          'introduced': [[*key, count] for key, count in introduced.items()]}
        report[name] = row
        print(name, {label: (v['base_count'], v['candidate_count'], len(v['introduced'])) for label, v in row.items()})
    out.write_text(json.dumps(report, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
