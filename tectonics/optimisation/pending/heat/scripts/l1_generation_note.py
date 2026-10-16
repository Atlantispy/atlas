"""Write the explicit L1 generation note: old -> new sha for low_ledger and each of its pinners.

Usage: python -B l1_generation_note.py BEFORE_HELPERS AFTER_HELPERS OUT.md
BEFORE = le/helpers (H1a+H1c+H2), AFTER = lf/helpers (+L1). Refuses unless exactly the source file and
the 5 CASCADE pinners differ, each pinner by exactly one line naming the pinned file's new digest.
"""
import sys
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'transforms'))
import l1_low_ledger_op as X  # noqa: E402

SOURCE = 'private_heat_low_ledger_inventory_r1.py'


def main():
    before, after, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    names = sorted(p.name for p in before.iterdir() if p.is_file())
    if names != sorted(p.name for p in after.iterdir() if p.is_file()):
        raise SystemExit('helper file sets differ')
    digest = {side: {n: sha256((d/n).read_bytes()).hexdigest() for n in names} for side, d in (('b', before), ('a', after))}
    changed = [n for n in names if digest['b'][n] != digest['a'][n]]
    expected = sorted({SOURCE} | {p for p, _ in X.CASCADE})
    if sorted(changed) != expected:
        raise SystemExit('unexpected changed files: %s' % changed)
    if digest['b'][SOURCE] not in X.KNOWN_INPUT_SHA256:
        raise SystemExit('source before L1 is not the reviewed input')
    rows = []
    for pinner, pinned in X.CASCADE:
        old = (before/pinner).read_bytes().decode('utf8').splitlines()
        new = (after/pinner).read_bytes().decode('utf8').splitlines()
        diff = [(x, y) for x, y in zip(old, new, strict=True) if x != y]
        if len(diff) != 1:
            raise SystemExit('%s: expected one changed line, got %d' % (pinner, len(diff)))
        line_old, line_new = diff[0]
        if (digest['b'][pinned] not in line_old or digest['a'][pinned] not in line_new
                or line_old.replace(digest['b'][pinned], digest['a'][pinned]) != line_new):
            raise SystemExit('%s: changed line is not exactly the %s pin' % (pinner, pinned))
        rows.append((pinner, pinned, digest['b'][pinner], digest['a'][pinner]))
    text = ['# L1 generation note (explicit pin rewrites)', '',
            'Before: `%s` (H1a+H1c+H2). After: `%s` (+L1).' % (before, after), '',
            '| file | role | sha before | sha after |', '|---|---|---|---|',
            '| %s | source (L1 transform) | %s | %s |' % (SOURCE, digest['b'][SOURCE], digest['a'][SOURCE])]
    text += ['| %s | pins %s (one line) | %s | %s |' % r for r in rows]
    text += ['', 'Every other helper is byte-identical. Each pinner changed only its one pin line,',
             'from the pinned file\'s old digest to its new digest (checked here).', '',
             'D-b basis: L1 changes no number. The issuer binds absolute helper paths and digests at run',
             'time, so record and result IDs change by digest only. The same-call control compares le and',
             'lf: every array and metadata leaf must be identical apart from 64-hex digests and layout',
             'paths (scripts/compare_ab.py).']
    out.write_text('\n'.join(text)+'\n', encoding='utf8')
    print('\n'.join(text))


if __name__ == '__main__':
    main()
