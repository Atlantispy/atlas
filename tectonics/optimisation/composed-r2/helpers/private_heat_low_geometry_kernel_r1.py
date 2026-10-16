"""Private LOW rows from an already issued exact native metric complex.

No probe imports, payload revalidation, solver, native issuance or full resource
admission. The caller owns the immutable geometry and must prospectively admit
the output Python/exact workset. This is the same harmonic-normal LOW, not a
claim of high-order accuracy on skew cells. No alternative geometry is built.
"""
from concurrent.futures import CancelledError
from fractions import Fraction as Q
import math


def _binary(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('Finite represented scalar required')
    return Q(value)


def _check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Issued-metric LOW preparation cancelled')


def prepare_geometry(geometry, conductivity, boundary, *, cancel=None):
    from atlas_tectonics.integration_mimetic_heat import MimeticGeometry
    from atlas_tectonics import exact_arithmetic
    if type(geometry) is not MimeticGeometry:
        raise TypeError('Actual issued native metric complex required')
    G = exact_arithmetic.library()
    if G is None:
        raise RuntimeError('The private LOW extraction requires the selected GMP backend')
    _check(cancel)
    count = len(geometry._cells)
    try:
        values = list(conductivity)
    except TypeError:
        values = [conductivity]*count
    if len(values) != count:
        raise ValueError('One positive scalar conductivity per actual cell required')
    k = list(map(_binary, values))
    if any(value <= 0 for value in k):
        raise ValueError('Conductivity must be strictly positive')
    face_ids, incidence = geometry._face_ids, geometry._incidence
    exposed = {fid for fid, linked in zip(face_ids, incidence, strict=True) if len(linked) == 1}
    if not set(boundary) <= exposed:
        raise ValueError('Boundary conditions must name actual exterior faces')
    normalised = {}
    for fid in exposed:
        kind, value = boundary.get(fid, ('power', 0.))
        if kind not in ('temperature', 'power'):
            raise ValueError('Only prescribed temperature or outward power is supported')
        normalised[fid] = (kind, float(_binary(value)))
    rows = []
    for fi, (fid, linked) in enumerate(zip(face_ids, incidence, strict=True)):
        _check(cancel)
        i, sign = linked[0]
        first = geometry._cells[i]
        slot = first[2].index(fi)
        normal = first[5][slot]
        area_squared = sum(value*value for value in normal)
        distances = [geometry._cells[owner][6][geometry._cells[owner][2].index(fi)]
                     for owner, _ in linked]
        if any(distance <= 0 for distance in distances):
            raise ValueError('Strict positive owner-to-face normal distances required')
        if len(linked) == 2:
            j, _ = linked[1]
            conductance = area_squared/(distances[0]/k[i]+distances[1]/k[j])
            weights = [(('cell', i), sign*conductance), (('cell', j), -sign*conductance)]
            kind = 'interior'
        elif normalised[fid][0] == 'temperature':
            conductance = k[i]*area_squared/distances[0]
            weights = [(('cell', i), sign*conductance), (('wall', fid), -sign*conductance)]
            kind = 'temperature'
        else:
            conductance, weights, kind = Q(0), [(('power', fid), Q(sign))], 'power'
        rows.append(dict(face_id=fid, owners=list(linked), kind=kind,
            weights=[(key, G.mpq(value.numerator, value.denominator)) for key, value in weights],
            conductance=conductance, owner_normal_distances=distances))
    _check(cancel)
    return dict(rows=rows, boundary=normalised, conductivity=k, cells=count,
                face_ids=list(face_ids), geometry_id=geometry.geometry_id)


def ledger(prepared, temperature, dt, *, cancel=None):
    """Exact original E/C face transfers, same order as frozen LOW r5."""
    raw, faces = [], []
    for row in prepared['rows']:
        _check(cancel)
        i, _ = row['owners'][0]
        kind, fid = row['kind'], row['face_id']
        if kind == 'interior':
            j = row['owners'][1][0]
            amount = dt*row['conductance']*(temperature[i]-temperature[j])
        elif kind == 'temperature':
            j = None
            amount = dt*row['conductance']*(temperature[i]-Q(prepared['boundary'][fid][1]))
        else:
            j = None
            amount = dt*Q(prepared['boundary'][fid][1])
        raw.append([(owner, owner_sign, amount if owner == i else -amount)
                    for owner, owner_sign in row['owners']])
        faces.append((i, j, amount))
    return raw, faces
