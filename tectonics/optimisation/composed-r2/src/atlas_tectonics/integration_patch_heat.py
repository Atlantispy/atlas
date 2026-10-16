"""Exact I05 heat attached to retained I03 material positions, not sampling means.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction
import math

from . import integration_support as S
from . import integration_transfer as T
from .integration_ledger import _exact, _exact_text
from .resources import MemoryLimitError


RATIONAL_CODEC = 'signed-hex-over-positive-hex-v1'


def restore_workspace(patch_count, encoded_bytes):
    """JSON decoding envelope from actual bytes; do not assume 32 layers/patch.

    Each encoded numeric character is charged 32 bytes for decoded scalar/list
    overhead and transient copies, plus 1024 bytes per row. Subsequent rational
    parsing and issuing have separate, nested actual-width/actual-layer charges.
    """
    return 65536+1024*patch_count+32*encoded_bytes


def field_workspace(values):
    """Accounted copies, rational operations and serialisation, including growing integers."""
    layers = sum(len(c[0]) for c in values.values())
    integer_bytes = sum((abs(q.numerator).bit_length()+q.denominator.bit_length()+7)//8
                        for _, u, b in values.values() for q in (*u, *b))
    return 65536+16384*layers+64*integer_bytes


def rational_text(value):
    """Canonical general rational, with no decimal conversion or arbitrary bit ceiling."""
    if type(value) is not Fraction:
        raise S.SupportError('physical column energy must be an exact rational')
    try:
        finite = math.isfinite(float(value))
    except OverflowError:
        finite = False
    if not finite:
        raise S.SupportError('physical column rational is outside finite binary64 evaluation')
    return '%s/%s' % (hex(value.numerator), hex(value.denominator))


def _rational(text):
    if type(text) is not str or text.count('/') != 1:
        raise S.SupportError('canonical physical column rational required')
    n, d = text.split('/')
    value = Fraction(int(n, 16), int(d, 16))
    if rational_text(value) != text:
        raise S.SupportError('noncanonical physical column rational')
    return value


def half_ulp(value):
    return Fraction(math.ulp(float(value)))/2


def split_bounds(value, areas):
    """The exact forward bound of T._split: one rounding except the remainder."""
    total, largest = sum(areas, Fraction(0)), T._largest(areas)
    bounds = [Fraction(0) if k == largest else half_ulp(float(value*area/total))
              for k, area in enumerate(areas)]
    bounds[largest] = sum(bounds, Fraction(0))
    return bounds


def capacity_area(record_, heights, *, budget=None):
    from .integration_material import volume_per_area
    return tuple(Fraction(s.reference_density_kg_m3)*Fraction(s.heat_capacity_j_kg_k)*weight
                 for s, weight in zip(record_.sublayers, volume_per_area(record_, heights, budget=budget)))


def field_temperature(record_, column, reference, *, budget=None):
    heights, energy, _ = column
    return [float(Fraction(reference)+u/c) for u, c in zip(energy, capacity_area(record_, heights, budget=budget))]


def field_record(values):
    return [[key, list(h), [rational_text(q) for q in u], [rational_text(q) for q in bound]]
            for key, (h, u, bound) in sorted(values.items())]


def field_restore(rows, *, expected=None, budget=None):
    try:
        from .integration_material import MAX_SUBLAYERS
        if (type(rows) is not list or len(rows) > S.MAX_CELLS or
                (expected is not None and len(rows) != len(expected))):
            raise S.SupportError('physical column row count does not match its retained support')
        for row in rows:
            if type(row) is not list or len(row) != 4 or type(row[0]) is not str:
                raise S.SupportError('physical column record needs its key and three arrays')
            key, h, u, b = row
            if (any(type(v) is not list for v in (h, u, b)) or
                    not 1 <= len(h) == len(u) == len(b) <= MAX_SUBLAYERS or
                    (expected is not None and expected.get(key) != len(h))):
                raise S.SupportError('physical column layer count does not match its declared profile')
            if any(type(q) is not str for q in (*u, *b)):
                raise S.SupportError('physical column rationals need canonical strings')
        from .resources import select_budget
        size = sum(sum(len(q) for q in (*u, *b))+256*len(h) for _, h, u, b in rows)
        with select_budget(budget).reserve(65536+32*size, category='i05-physical-field-parse'):
            values = {key: (tuple(h), tuple(_rational(q) for q in u), tuple(_rational(q) for q in b))
                      for key, h, u, b in rows}
            if field_record(values) != rows:
                raise S.SupportError('physical column records are duplicated or noncanonical')
            return values
    except (TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        if isinstance(exc, MemoryLimitError):
            raise
        raise S.SupportError('invalid physical column record') from exc


def checked_fields(sphere, records, heat, values, reference, intervals, *, budget=None):
    """Validate actual field/account residuals against their propagated operation bounds."""
    from . import integration_material as M
    patches = S.required(sphere.material).patches
    if set(values) != {p.patch_id for p in patches}:
        raise S.SupportError('physical columns must name exactly the actual material patches')
    residuals, allowances = [], []
    for patch in patches:
        h, u, bound = values[patch.patch_id]
        record_ = records[patch.cohort_id]
        if (not len(h) == len(u) == len(bound) == len(record_.sublayers) or
                any(type(v) is not float or not math.isfinite(v) or v <= 0 for v in h)):
            raise S.SupportError('one finite positive physical height and energy per layer required')
        for q in (*u, *bound):
            rational_text(q)
        if any(b < 0 for b in bound):
            raise S.SupportError('physical heat round-off allowances are nonnegative')
        residual = tuple(q-patch.stock[0]*v for q, v in zip(heat[patch.patch_id], u))
        if any(abs(r) > b for r, b in zip(residual, bound)):
            raise S.SupportError('physical column/account residual exceeds its derived operation allowance')
        temperatures = field_temperature(record_, values[patch.patch_id], reference, budget=budget)
        if any(not math.isfinite(t) or t <= 0 for t in temperatures):
            raise S.SupportError('physical column requires positive finite absolute temperature')
        piece = S.piece_of(patch, sphere.material.phases)
        physical_volumes = M.phase_volume_per_area(record_, h, budget=budget)
        for phase, volume in zip(sphere.material.phases, piece.volume_m3):
            expected = (math.fsum(v for s, v in zip(record_.sublayers, h) if s.phase == phase)*piece.area_m2
                        if record_.volume_convention == 'reference_prism' else
                        physical_volumes.get(phase, Fraction(0))*Fraction(piece.area_m2))
            if abs(expected-volume) > T.RELATIVE_TOLERANCE*max(abs(expected), abs(volume)):
                raise S.SupportError('unsupported deformation: physical heights no longer match material volume')
        M._check_reference_mass(record_, piece, [v/s.thickness_m for s, v in zip(record_.sublayers, h)],
                                sphere.material.phases, intervals, budget=budget)
        residuals.extend(residual); allowances.extend(bound)
    return dict(residual_exact_j=rational_text(sum(residuals, Fraction(0))),
                absolute_residual_exact_j=rational_text(sum(map(abs, residuals), Fraction(0))),
                allowance_exact_j=rational_text(sum(allowances, Fraction(0))),
                layers=len(residuals), rational_codec=RATIONAL_CODEC,
                maximum_integer_bits=max((max(abs(q.numerator).bit_length(), q.denominator.bit_length())
                                          for c in values.values() for q in (*c[1], *c[2])), default=0))


def seed_fields(sphere, records, heat, reference, *, budget=None):
    """Seed only from an explicitly declared profile, never from a saved piece mean."""
    from .integration_material import declared_areal_heat
    out = {}
    for piece in sphere.material.pieces():
        record_ = records[piece.cohort_id]
        patches = S.required(sphere.material).patches_of_piece(piece.face_id, piece.cohort_id)
        areas = [p.stock[0] for p in patches]
        total = sum(areas, Fraction(0))
        heights = tuple(s.thickness_m for s in record_.sublayers)
        energy = declared_areal_heat(record_, reference, budget=budget)
        supplied = [sum((heat[p.patch_id][k] for p in patches), Fraction(0)) for k in range(len(heights))]
        bounds = []
        for q, u in zip(supplied, energy):
            expected = Fraction(float(u*total))
            if q != expected:
                raise S.SupportError('declared physical heat must reproduce the original rounded profile product')
            bounds.append([half_ulp(float(q))*a/total+b for a, b in zip(areas, split_bounds(q, areas))])
        for j, patch in enumerate(patches):
            out[patch.patch_id] = heights, energy, tuple(Fraction(S.upper(b[j])) for b in bounds)
    return out


def route_fields(values, source_heat, routes, target_patches):
    """Rigid routing copies h/u; only known extensive allocation rounding accumulates."""
    grouped = {}
    target = target_patches if isinstance(target_patches, dict) else {p.patch_id: p for p in target_patches}
    for source, receiver, trench, area in routes:
        grouped.setdefault(source, []).append((receiver, area))
    if set(grouped) != set(values):
        raise S.SupportError('physical columns and material routes have different owners')
    # The only post-route area change is the already-booked piece projection:
    # one final binary64 rounding, assigned to the largest retained patch.
    by_piece = {}
    for members in grouped.values():
        for receiver, area in members:
            if receiver is not None:
                patch = target[receiver]
                by_piece.setdefault((patch.face_id, patch.cohort_id), []).append((receiver, area))
    for members in by_piece.values():
        total = sum((a for _, a in members), Fraction(0))
        changes = [(key, target[key].stock[0]-a) for key, a in members]
        if (sum(bool(d) for _, d in changes) > 1 or
                sum((abs(d) for _, d in changes), Fraction(0)) > half_ulp(float(total))):
            raise S.SupportError('physical column route has area change beyond final piece rounding')
    out = {}
    for source, members in grouped.items():
        heights, energy, inherited = values[source]
        areas = [a for _, a in members]; total = sum(areas, Fraction(0))
        bounds = [split_bounds(q, areas) for q in source_heat[source]]
        for j, (receiver, area) in enumerate(members):
            if receiver is None:
                continue
            delta = abs(target[receiver].stock[0]-area)
            allowance = tuple(Fraction(S.upper(b*area/total+rounding[j]+abs(u)*delta))
                              for b, rounding, u in zip(inherited, bounds, energy))
            out[receiver] = heights, energy, allowance
    return out


def birth_fields(record_, patches, amounts, reference, *, budget=None):
    from .integration_material import declared_areal_heat
    heights = tuple(s.thickness_m for s in record_.sublayers)
    energy = declared_areal_heat(record_, reference, budget=budget)
    areas = [p.stock[0] for p in patches]; total = sum(areas, Fraction(0))
    bounds = []
    for q, u in zip(amounts, energy):
        delivered = Fraction(float(u))
        if delivered:
            original_area = q/delivered
            if abs(total-original_area) > half_ulp(float(original_area)):
                raise S.SupportError('birth column area differs beyond its final stock rounding')
        elif q:
            raise S.SupportError('zero declared birth heat cannot supply nonzero heat')
        else:
            original_area = total
        error = abs(u)*abs(total-original_area)+abs(delivered-u)*original_area
        bounds.append([error*a/total+b for a, b in zip(areas, split_bounds(q, areas))])
    return {p.patch_id: (heights, energy, tuple(Fraction(S.upper(b[j])) for b in bounds))
            for j, p in enumerate(patches)}


def add_energy(column, area, energy, *, areal=None, rounding_bound=None):
    """Apply the same physical source and extensive booking, exposing any split rounding."""
    h, u, bound = column
    change = tuple(q/area for q in energy) if areal is None else tuple(areal)
    extra = tuple(abs(q-area*v) for q, v in zip(energy, change))
    allowed = (Fraction(0),)*len(u) if rounding_bound is None else tuple(rounding_bound)
    if len(allowed) != len(u) or any(a < 0 or e > a for e, a in zip(extra, allowed)):
        raise S.SupportError('physical source/account difference exceeds its known rounding operations')
    return h, tuple(a+b for a, b in zip(u, change)), tuple(
        Fraction(S.upper(a+b)) for a, b in zip(bound, allowed))


def seed(sphere, pieces, heat):
    """An explicit homogeneous initial column over each declared piece only."""
    out = {}
    for key, values in zip(pieces, heat):
        patches = S.required(sphere.material).patches_of_piece(*key)
        areas = [p.stock[0] for p in patches]
        total = sum(areas, Fraction(0))
        split = [T._split(Fraction(float(v)), areas, total, T._largest(areas)) for v in values]
        for j, patch in enumerate(patches):
            out[patch.patch_id] = tuple(column[j] for column in split)
    return out


def checked(sphere, records, values):
    patches = S.required(sphere.material).patches
    if set(values) != {p.patch_id for p in patches}:
        raise S.SupportError('patch heat does not name exactly the retained material patches')
    for patch in patches:
        column = values[patch.patch_id]
        if len(column) != len(records[patch.cohort_id].sublayers) or any(type(v) is not Fraction for v in column):
            raise S.SupportError('one exact heat value per patch sublayer is required')
        for value in column:
            if _exact(_exact_text(value), 'patch heat') != value:
                raise S.SupportError('patch heat cannot be stored losslessly')
    return tuple(sorted((key, tuple(column)) for key, column in values.items()))


def project(sphere, values):
    """Rounded reporting projection only; exact residual is not physical heat."""
    support = S.required(sphere.material)
    heat, difference = [], Fraction(0)
    for piece in sphere.material.pieces():
        columns = [values[p.patch_id] for p in support.patches_of_piece(piece.face_id, piece.cohort_id)]
        exact = [sum(column, Fraction(0)) for column in zip(*columns)]
        stored = [float(v) for v in exact]
        difference += sum((Fraction(v)-q for v, q in zip(stored, exact)), Fraction(0))
        heat.append(stored)
    return heat, difference


def record(values):
    return [[key, [_exact_text(v) for v in column]] for key, column in sorted(values.items())]


def restore(rows):
    result = {key: tuple(_exact(v, 'patch heat') for v in column) for key, column in rows}
    if record(result) != rows:
        raise S.SupportError('patch heat rows are duplicated, unsorted or noncanonical')
    return result


def routed(values, routes, book, sinks):
    """Debit each patch once along the exact material route, retaining all child columns."""
    from .integration_material import _consumed
    grouped, result = {}, {}
    for source, target, trench, area in routes:
        grouped.setdefault(source, []).append((target, trench, area))
    if set(grouped) != set(values):
        raise S.SupportError('patch heat and material routes have different source positions')
    for source, members in grouped.items():
        areas = [area for _, _, area in members]
        total = sum(areas, Fraction(0))
        split = [T._split(value, areas, total, T._largest(areas)) for value in values[source]]
        for j, (target, trench, _) in enumerate(members):
            column = tuple(row[j] for row in split)
            if target is None:
                _consumed(trench, column, book, sinks)
            elif target in result:
                raise S.SupportError('two thermal patches would overwrite one position')
            else:
                result[target] = column
    return result


def columns(moving, sphere, patch_ids):
    """Resolve selected local columns with one transient lookup, not one scan per trace."""
    from . import integration_material as M
    from . import integration_thermal as H
    M.bound_moving(moving, sphere)
    if moving._patch_heat is None:
        raise S.SupportError('legacy piece heat has no retained patch columns')
    heat = dict(moving._patch_heat)
    patches = {p.patch_id: p for p in S.required(sphere.material).patches}
    records = {record.cohort_id: record for record in moving.cohorts}
    fields = None if moving._physical_columns is None else dict(moving._physical_columns)
    result = {}
    for patch_id in dict.fromkeys(patch_ids):
        if patch_id not in patches:
            raise S.SupportError('a patch column names no retained position')
        patch = patches[patch_id]
        piece = S.piece_of(patch, sphere.material.phases)
        record_ = records[piece.cohort_id]
        if fields is None:
            # Historical records remain readable as their historical numerical
            # interpretation; no physical field is invented or silently migrated.
            thickness, _ = H.column_of(record_, piece, sphere.material.phases)
            temperatures = H.temperatures(record_, piece, [float(v) for v in heat[patch_id]],
                                          moving.enthalpy_reference_k, sphere.material.phases)
        else:
            field = fields[patch_id]
            thickness = list(field[0])
            temperatures = field_temperature(record_, field, moving.enthalpy_reference_k)
        result[patch_id] = piece, record_, thickness, temperatures
    return result


def column(moving, sphere, patch_id):
    return columns(moving, sphere, (patch_id,))[patch_id]
