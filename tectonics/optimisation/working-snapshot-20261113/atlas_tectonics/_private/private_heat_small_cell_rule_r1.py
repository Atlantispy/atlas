"""The heat's small-cell rule with its guard (option B, decision 1192; design heat-small-cell-rule-build-r1).

A cell that holds too little heat for its faces has its faces' high rows replaced by the low stage's own two-point
rows; every other face keeps its certified fitted row, cut back where an owner's capacity cannot hold it. All
arithmetic is exact rational; each changed entry is rounded once to the system's Decimal context.

For a cell i: n_i = its count of fitted faces (every face that is not a prescribed-power face), G_i = the sum of their
low conductances, s_i = capacity_i / (dt x G_i), r_i = 0 at s_i <= RANGE_LOW, 1 at s_i >= RANGE_HIGH, linear between.
A face's range share r_f = min over its owners of r_i. r_f = 0: the low row, exact, and no fit is made. Otherwise, on
the certified rounded system: size_f = sum of |cell and wall entries|, guard_f = min over owners of
capacity_i / (dt x n_i x size_f), fitted share phi_f = min(r_f, guard_f / GUARD); at phi_f < 1 every entry becomes
r80(phi_f x fitted + (1 - phi_f) x low), and each owner's operator row and wall entry are made again as r80 of the
exact sum of sign x its faces' final weights. Every cell's hold is then at least GUARD.
"""
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
import json

RANGE_LOW = 100
RANGE_HIGH = 10000
GUARD = 1000
SCHEMA = 'atlas.heat-small-cell-rule.r1'


def _check(cancel):
    if cancel is not None and cancel():
        raise RuntimeError('Small-cell rule cancelled')


def _q(value):
    """Exact rational of an mpq, Fraction, int, float or finite Decimal."""
    if isinstance(value, (float, Decimal, int)):
        return Fraction(value)
    return Fraction(int(value.numerator), int(value.denominator))


def shares(prepared, capacity, dt, *, cancel=None):
    """From the low stage's prepared rows: each fitted face's range share, each cell's fitted-face count, and the
    exact two-point rows (ordered keys and one-value bounds) of the faces at share 0, in the low row's key order."""
    dtq = _q(dt)
    cells = len(capacity)
    count, conductance = [0]*cells, [Fraction(0)]*cells
    for row in prepared['rows']:
        _check(cancel)
        if row['kind'] != 'power':
            g = _q(row['conductance'])
            for i, _ in row['owners']:
                count[i] += 1
                conductance[i] += g
    cell_share = {}

    def share_of(i):
        if i not in cell_share:
            s = _q(capacity[i])/(dtq*conductance[i])
            cell_share[i] = (Fraction(0) if s <= RANGE_LOW else Fraction(1) if s >= RANGE_HIGH
                             else (s - RANGE_LOW)/(RANGE_HIGH - RANGE_LOW))
        return cell_share[i]

    face_share, low_rows, exact_rows = {}, {}, {}
    for row in prepared['rows']:
        _check(cancel)
        if row['kind'] == 'power':
            continue
        fid = row['face_id']
        face_share[fid] = r = min(share_of(i) for i, _ in row['owners'])
        low_rows[fid] = row['weights']
        if not r:
            exact_rows[fid] = dict(ordered_keys=[key for key, _ in row['weights']],
                                   bounds={key: (w, w) for key, w in row['weights']})
    return dict(face_share=face_share, counts=count, low_rows=low_rows, exact_rows=exact_rows)


def apply(system, plan, capacity, dt, boundary, *, cancel=None):
    """A new rounded system with the guard and the range blend applied to the certified one, and the three counts.
    The certified system is not changed; its witness is kept whole inside the new one, marked as derived."""
    prec, rounding, emin, emax, clamp = system.context_signature
    dtq, counts, face_share, low_rows = _q(dt), plan['counts'], plan['face_share'], plan['low_rows']
    rows, changed = list(system.rows), set()
    no_fit = blended = cut = 0
    with localcontext() as context:
        context.prec, context.rounding, context.Emin, context.Emax, context.clamp = prec, rounding, emin, emax, clamp

        def r80(q):
            return Decimal(q.numerator)/Decimal(q.denominator)

        for f, face in enumerate(rows):
            _check(cancel)
            r = face_share.get(face.face_id)
            if r is None:                                   # a prescribed-power face: exact row, untouched
                continue
            if not r:
                no_fit += 1                                 # its row is already the exact low row
                continue
            blended += r < 1
            size = sum(abs(Fraction(w)) for (kind, _), w in face.weights if kind in ('cell', 'wall'))
            phi = r
            if size:
                phi = min(r, min(_q(capacity[i])/(dtq*counts[i]*size) for i, _ in face.owners)/GUARD)
            cut += phi < r
            if phi == 1:
                continue
            # shortcut: proved for a prescribed power of nought only, reopen the design before a route prescribes another
            mix = {}
            for key, w in low_rows[face.face_id]:
                mix[key] = mix.get(key, 0) + (1 - phi)*_q(w)
            for key, w in face.weights:
                mix[key] = mix.get(key, 0) + phi*Fraction(w)
            rows[f] = replace(face, weights=tuple((key, r80(v)) for key, v in mix.items()))
            changed.update(i for i, _ in face.owners)
        operator, wall = list(system.operator), list(system.wall)
        if changed:
            incident = {c: [] for c in changed}
            for face in rows:
                for i, sign in face.owners:
                    if i in incident:
                        incident[i].append((sign, face))
            for c in sorted(changed):
                _check(cancel)
                entries, rhs = {}, Fraction(0)
                for sign, face in incident[c]:
                    for (kind, key), w in face.weights:
                        if kind == 'cell':
                            entries[key] = entries.get(key, 0) + sign*Fraction(w)
                        else:
                            rhs += sign*Fraction(w)*_q(boundary[key][1])
                operator[c] = tuple((j, r80(v)) for j, v in sorted(entries.items()) if v)
                wall[c] = r80(rhs)
    result = dict(schema=SCHEMA, range=[RANGE_LOW, RANGE_HIGH], guard=GUARD, faces_no_fit=no_fit,
                  faces_blended_by_range=blended, faces_cut_by_guard=cut)
    witness = '{"certified":' + system.witness_json + ',"small_cell_rule":' + json.dumps(result, sort_keys=True) + '}'
    derived = replace(system, operator=tuple(operator), wall=tuple(wall), rows=tuple(rows),
                      exact_operator_nnz=sum(map(len, operator)), witness_json=witness)
    return derived, dict(faces_no_fit=no_fit, faces_blended_by_range=blended, faces_cut_by_guard=cut)
