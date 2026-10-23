"""R2 decision 6 as ruled at R3, revision 3: limb differences are order-determined, so a repeat of either arm must give
the same sizes. For each pair of runs this lists every rational allocation row bookings.py ties (site, snapshot,
table, kind) with the two recorded sizes, and sums them up as a class: values equal, size differences in whole 8-byte
limbs, and the largest growth in limbs per value against the one-limb-per-eight-values cap.

    python -B limbs_r3.py BOOKINGS_DIR MANIFEST_H OUT_JSON A_LAYOUT A_OUT A2_LAYOUT A2_OUT B_LAYOUT B_OUT B2_LAYOUT B2_OUT

BOOKINGS_DIR holds v27's bookings.py, which reads arms_r7 output (each rationals row carries the gmpy2 tight sum and
the distinct objects). Pairs: A vs A' and B vs B' (two runs of one arm), and A vs B (the fold). Each arm is evaluated
on its own with bookings.evaluate, as bookings.check does; A' is read as an A arm and B' as a B arm. All of them
translate their tables with the fold manifest, as bookings.py does. Nothing is tied across a pair here except the
rationals: the full booking check is bookings.py itself.

Exit 0 iff three things hold:
- every pair reads cleanly, and each pair's two gmpy2 build records are equal;
- in every row the values are equal and so are the tight sums; every size difference is whole limbs on a gmpy row;
  and no row grows by more than the cap;
- both repeat pairs have no size difference at all.

Changes from r2 (FOLD.md §13 items 3 and 5):
- The cap is one-sided. It applies to a row's NET growth y - x, so a smaller y passes; the tight floor that
  bookings.py checks on each arm bounds it from below. The net form is kept, because an absolute cap per value would
  fail the probe's benign reuse.
- Totals are labelled as booked values. One object can be booked in several rows. The interval inventory's singleton
  pairs count each object twice, and the LOW ledger books the same objects at its initial and ledger stages
  (R3-STEP-NOTE.md item 5).
- Each row also carries the change in its distinct objects (by id, within that row's walk). Aliasing across rows is
  not resolved, because ids are not stable across separate walks.
- Each arm's over-allocation (size minus tight sum, in limbs) is listed per row.
The cap is a memory-accounting bound; correctness rests on the value digests.
"""
import importlib
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

B: Any = None


def rows(tr, x_layout, x_out, x_name, y_layout, y_out, y_name):
    x, y = B.Arm(x_name, x_layout, x_out, tr), B.Arm(y_name, y_layout, y_out, tr)
    if set(x.bookings) != set(y.bookings):
        raise B.BookingError('booking sites differ: %s' % sorted(set(x.bookings) ^ set(y.bookings)))
    if x.gmp is None or x.gmp != y.gmp:
        raise B.BookingError('gmpy2 build records missing or different: %s / %s' % (x.gmp, y.gmp))
    out, errors = [], []
    for site in sorted(x.bookings):
        rx, ry = x.bookings[site], y.bookings[site]
        if len(rx['snapshots']) != len(ry['snapshots']):
            raise B.BookingError('%s: snapshots %d / %d' % (site, len(rx['snapshots']), len(ry['snapshots'])))
        links = (None, None)
        if site in B.LINKS:
            links = (x.bookings[B.LINKS[site]]['snapshots'], y.bookings[B.LINKS[site]]['snapshots'])
        for i, (sx, sy) in enumerate(zip(rx['snapshots'], ry['snapshots'], strict=True)):
            where = '%s #%d' % (site, i)
            lx, ly = ((None, None) if links[0] is None else
                      (B.Env(links[0][i], where + ' x link'), B.Env(links[1][i], where + ' y link')))
            try:
                ex, _ = B.evaluate(x, site, sx, where + ' x', lx)
                ey, _ = B.evaluate(y, site, sy, where + ' y', ly)
            except (B.BookingError, KeyError, TypeError, ValueError, OSError) as e:
                errors.append('%s: %s: %s' % (where, type(e).__name__, str(e)[:200]))
                continue
            for name in sorted(set(ex.alloc) | set(ey.alloc)):
                if name not in ex.alloc or name not in ey.alloc:
                    errors.append('%s %s on one arm only' % (where, name))
                    continue
                (cx, sx_, dx, gmpy, tx, nx, nsx), (cy, sy_, dy, _, ty, ny, nsy) = ex.alloc[name], ey.alloc[name]
                out.append(dict(site=site, snapshot=i, name=name, gmpy=gmpy, values=cx,
                                values_equal=(cx, dx) == (cy, dy), tight_equal=tx == ty,
                                size_x=sx_, size_y=sy_, delta=sy_ - sx_,
                                over_x=None if tx is None else (sx_ - tx) // 8,
                                over_y=None if ty is None else (sy_ - ty) // 8,
                                distinct_x=nx, distinct_y=ny, distinct_delta=nsy - nsx))
    return out, errors


def summary(rs, errors):
    diff = [r for r in rs if r['delta']]
    growth = [r['delta'] / 8 / r['values'] for r in diff if r['values'] and r['delta'] > 0]
    return dict(rows=len(rs), errors=errors[:8], error_count=len(errors), values_equal=all(r['values_equal'] for r in rs),
                tight_equal=all(r['tight_equal'] for r in rs),
                rows_differing=len(diff), gmpy_only=all(r['gmpy'] for r in diff),
                whole_limbs=all(r['delta'] % 8 == 0 for r in diff),
                within_cap=all(r['delta'] <= 8 * -(-r['values'] // 8) for r in diff),
                booked_limbs_net=sum(r['delta'] for r in diff) // 8,
                booked_limbs_abs=sum(abs(r['delta']) for r in diff) // 8,
                distinct_limbs_net=sum(r['distinct_delta'] for r in rs) // 8,
                max_growth_limbs_per_value=round(max(growth), 4) if growth else 0.0,
                signs=sorted({(r['delta'] > 0) - (r['delta'] < 0) for r in diff}),
                over_limbs_x=sum(r['over_x'] or 0 for r in rs), over_limbs_y=sum(r['over_y'] or 0 for r in rs),
                names=sorted({r['name'] for r in diff}))


def main(argv):
    global B
    if len(argv) != 11:
        print(__doc__)
        return 2
    sys.path.insert(0, str(Path(argv[0]).resolve()))
    B = importlib.import_module('bookings')
    if sys.version_info[:2] != (3, 12):
        raise B.BookingError('getsizeof rules are for CPython 3.12, not %s' % sys.version.split()[0])
    tr = B.Translation(json.loads(Path(argv[1]).read_text(encoding='utf-8')))
    out = Path(argv[2])
    a, a2, b, b2 = (tuple(map(Path, argv[k:k + 2])) for k in (3, 5, 7, 9))
    pairs = {}
    for label, (x, x_name), (y, y_name) in (("A vs A'", (a, 'A'), (a2, 'A')), ("B vs B'", (b, 'B'), (b2, 'B')),
                                            ('A vs B', (a, 'A'), (b, 'B'))):
        try:
            rs, errors = rows(tr, x[0], x[1], x_name, y[0], y[1], y_name)
        except B.BookingError as error:
            rs, errors = [], ['%s' % error]
        pairs[label] = dict(summary=summary(rs, errors), rows=rs)
    s = {label: p['summary'] for label, p in pairs.items()}
    clean = all(x['error_count'] == 0 and x['values_equal'] and x['tight_equal'] and x['gmpy_only'] and x['whole_limbs']
                and x['within_cap'] for x in s.values())
    repeats_identical = all(s[label]['rows'] > 0 and s[label]['rows_differing'] == 0 for label in ("A vs A'", "B vs B'"))
    ok = clean and repeats_identical
    report = dict(schema='rm.fold.limbs.r3', status='PASS' if ok else 'FAIL', repeats_identical=repeats_identical,
                  bookings_sha256=hashlib.sha256(Path(B.__file__).read_bytes()).hexdigest(), pairs=pairs)
    out.write_text(json.dumps(report, indent=1) + '\n', encoding='utf8', newline='\n')
    for label in pairs:
        print(label, json.dumps({k: v for k, v in s[label].items() if k not in ('errors', 'names')}))
    print(json.dumps(dict(status=report['status'], repeats_identical=repeats_identical, out=out.name)))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
