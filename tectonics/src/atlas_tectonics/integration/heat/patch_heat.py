"""Exact I05 heat attached to retained I03 material positions, not sampling means.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction
import math

from atlas_tectonics.integration import support as S
from atlas_tectonics.integration import transfer as T
from atlas_tectonics.integration.ledger import _exact, _exact_text
from atlas_tectonics.integration.resources import MemoryLimitError


RATIONAL_CODEC = 'signed-hex-over-positive-hex-v1'


def restore_workspace(patch_count, encoded_bytes):
    """JSON decoding envelope from actual bytes; do not assume 32 layers/patch.

    Each encoded numeric character is charged 32 bytes for decoded scalar/list
    overhead and transient copies, plus 1024 bytes per row. Subsequent rational
    parsing and issuing have separate, nested actual-width/actual-layer charges.
    """
    return 65536+1024*patch_count+32*encoded_bytes


# Measured: with the integer term, books 1.1x to 2x the traced declaration peak (DeclarationBooking).
LAYER_WORKSPACE = 512


def field_workspace(values):
    """Accounted copies, rational operations and serialisation, including growing integers."""
    layers = sum(len(c[0]) for c in values.values())
    integer_bytes = sum((abs(q.numerator).bit_length()+q.denominator.bit_length()+7)//8
                        for _, u, b in values.values() for q in (*u, *b))
    return 65536+LAYER_WORKSPACE*layers+64*integer_bytes


def rational_text(value):
    """Canonical general rational, with no decimal conversion or arbitrary bit ceiling."""
    try:
        pass
    except OverflowError:
        pass
    return '%s/%s' % (hex(value.numerator), hex(value.denominator))


def _rational(text):
    n, d = text.split('/')
    value = Fraction(int(n, 16), int(d, 16))
    return value


def half_ulp(value):
    return Fraction(math.ulp(float(value)))/2


def split_bounds(shares, largest):
    """The exact forward bound of T._split: one rounding except the remainder."""
    bounds = [Fraction(0) if k == largest else half_ulp(share)
              for k, share in enumerate(shares)]
    bounds[largest] = sum(bounds, Fraction(0))
    return bounds


def capacity_area(record_, heights, *, budget=None):
    from atlas_tectonics.integration.material import volume_per_area
    return tuple(Fraction(s.reference_density_kg_m3)*Fraction(s.heat_capacity_j_kg_k)*weight
                 for s, weight in zip(record_.sublayers, volume_per_area(record_, heights, budget=budget)))


def field_temperature(record_, column, reference, *, budget=None):
    heights, energy, _ = column
    return [float(Fraction(reference)+u/c) for u, c in zip(energy, capacity_area(record_, heights, budget=budget))]


def field_record(values):
    return [[key, list(h), [rational_text(q) for q in u], [rational_text(q) for q in bound]]
            for key, (h, u, bound) in sorted(values.items())]


def field_restore(rows, *, expected=None, budget=None):
    return _restore_fields(rows, expected, budget, _field_roundtrip)


def _field_restore_stored(rows, *, expected=None, budget=None):
    """Receive the detached JSON rows from the stored moving-state loader."""
    return _restore_fields(rows, expected, budget, _stored_field_order)


def _field_roundtrip(values, rows):
    return field_record(values) == rows


def _stored_field_order(values, rows):
    if len(values) != len(rows):
        return False
    previous = None
    for key in values:
        if previous is not None and key <= previous:
            return False
        previous = key
    return True


def _restore_fields(rows, expected, budget, admits_order):
    try:
        from atlas_tectonics.integration.material import MAX_SUBLAYERS
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
        from atlas_tectonics.integration.resources import select_budget
        size = sum(sum(len(q) for q in (*u, *b))+256*len(h) for _, h, u, b in rows)
        with select_budget(budget).reserve(65536+32*size, category='i05-physical-field-parse'):
            values = {key: (tuple(h), tuple(_rational(q) for q in u), tuple(_rational(q) for q in b))
                      for key, h, u, b in rows}
            if not admits_order(values, rows):
                raise S.SupportError('physical column records are duplicated or noncanonical')
            return values
    except (TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        if isinstance(exc, MemoryLimitError):
            raise
        raise S.SupportError('invalid physical column record') from exc


def checked_fields(sphere, records, heat, values, reference, intervals, *, budget=None):
    """Validate actual field/account residuals against their propagated operation bounds."""
    from atlas_tectonics.integration import material as M
    patches = S.required(sphere.material).patches
    residuals, allowances = [], []
    for patch in patches:
        h, u, bound = values[patch.patch_id]
        record_ = records[patch.cohort_id]
        for q in (*u, *bound):
            rational_text(q)
        residual = tuple(q-patch.stock[0]*v for q, v in zip(heat[patch.patch_id], u))
        if any(abs(r) > b for r, b in zip(residual, bound)):
            raise S.SupportError('physical column/account residual exceeds its derived operation allowance')
        field_temperature(record_, values[patch.patch_id], reference, budget=budget)
        piece = S.piece_of(patch, sphere.material.phases)
        physical_volumes = M.phase_volume_per_area(record_, h, budget=budget)
        for phase, volume in zip(sphere.material.phases, piece.volume_m3):
            (math.fsum(v for s, v in zip(record_.sublayers, h) if s.phase == phase)*piece.area_m2
                        if record_.volume_convention == 'reference_prism' else
                        physical_volumes.get(phase, Fraction(0))*Fraction(piece.area_m2))
        M._check_reference_mass(record_, piece, [v/s.thickness_m for s, v in zip(record_.sublayers, h)],
                                sphere.material.phases, intervals, budget=budget)
        residuals.extend(residual); allowances.extend(bound)
    return dict(residual_exact_j=rational_text(sum(residuals, Fraction(0))),
                absolute_residual_exact_j=rational_text(sum(map(abs, residuals), Fraction(0))),
                allowance_exact_j=rational_text(sum(allowances, Fraction(0))),
                layers=len(residuals), rational_codec=RATIONAL_CODEC,
                maximum_integer_bits=max((max(abs(q.numerator).bit_length(), q.denominator.bit_length())
                                          for c in values.values() for q in (*c[1], *c[2])), default=0))


def seed_fields(sphere, records, heat, reference, winners, *, budget=None):
    """Seed only from an explicitly declared profile, never from a saved piece mean."""
    from atlas_tectonics.integration.material import declared_areal_heat
    out = {}
    for piece in sphere.material.pieces():
        record_ = records[piece.cohort_id]
        patches = S.required(sphere.material).patches_of_piece(piece.face_id, piece.cohort_id)
        areas = [p.stock[0] for p in patches]
        total, largest = winners[piece.face_id, piece.cohort_id]
        heights = tuple(s.thickness_m for s in record_.sublayers)
        energy = declared_areal_heat(record_, reference, budget=budget)
        supplied = [sum((heat[p.patch_id][k] for p in patches), Fraction(0)) for k in range(len(heights))]
        bounds = []
        for layer, (q, u) in enumerate(zip(supplied, energy)):
            bounds.append([half_ulp(float(q))*a/total+b for a, b in
                           zip(areas, split_bounds([heat[p.patch_id][layer] for p in patches], largest))])
        for j, patch in enumerate(patches):
            out[patch.patch_id] = heights, energy, tuple(Fraction(S.upper(b[j])) for b in bounds)
    return out


def route_fields(values, allocated, groups, target_patches):
    """Rigid routing copies h/u; only known extensive allocation rounding accumulates."""
    target = target_patches if isinstance(target_patches, dict) else {p.patch_id: p for p in target_patches}
    # The only post-route area change is the already-booked piece projection:
    # one final binary64 rounding, assigned to the largest retained patch.
    by_piece = {}
    for members, _, _ in groups.values():
        for receiver, _, area in members:
            if receiver is not None:
                patch = target[receiver]
                by_piece.setdefault((patch.face_id, patch.cohort_id), []).append((receiver, area))
    for members in by_piece.values():
        total = sum((a for _, a in members), Fraction(0))
    out = {}
    for source, (members, total, largest) in groups.items():
        heights, energy, inherited = values[source]
        bounds = [split_bounds(shares, largest) for shares in allocated[source]]
        for j, (receiver, _, area) in enumerate(members):
            if receiver is None:
                continue
            delta = abs(target[receiver].stock[0]-area)
            allowance = tuple(Fraction(S.upper(b*area/total+rounding[j]+abs(u)*delta))
                              for b, rounding, u in zip(inherited, bounds, energy))
            out[receiver] = heights, energy, allowance
    return out


def birth_fields(record_, patches, amounts, reference, total, largest, allocated, *, budget=None):
    from atlas_tectonics.integration.material import declared_areal_heat
    heights = tuple(s.thickness_m for s in record_.sublayers)
    energy = declared_areal_heat(record_, reference, budget=budget)
    areas = [p.stock[0] for p in patches]
    bounds = []
    for layer, (q, u) in enumerate(zip(amounts, energy)):
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
        bounds.append([error*a/total+b for a, b in zip(areas, split_bounds(allocated[layer], largest))])
    return {p.patch_id: (heights, energy, tuple(Fraction(S.upper(b[j])) for b in bounds))
            for j, p in enumerate(patches)}


def add_energy(column, area, energy, *, areal=None, rounding_bound=None):
    """Apply the same physical source and extensive booking, exposing any split rounding."""
    h, u, bound = column
    change = tuple(q/area for q in energy) if areal is None else tuple(areal)
    allowed = (Fraction(0),)*len(u) if rounding_bound is None else tuple(rounding_bound)
    return h, tuple(a+b for a, b in zip(u, change)), tuple(
        Fraction(S.upper(a+b)) for a, b in zip(bound, allowed))


def seed(sphere, pieces, heat, *, winners=None):
    """An explicit homogeneous initial column over each declared piece only."""
    out = {}
    for key, values in zip(pieces, heat):
        patches = S.required(sphere.material).patches_of_piece(*key)
        areas = [p.stock[0] for p in patches]
        total = sum(areas, Fraction(0))
        largest = T._largest(areas, lambda k: tuple(sorted(patches[k].cells)))
        if winners is not None:
            winners[key] = total, largest
        split = [T._split(Fraction(float(v)), areas, total, largest) for v in values]
        for j, patch in enumerate(patches):
            out[patch.patch_id] = tuple(column[j] for column in split)
    return out


def checked(sphere, records, values):
    patches = S.required(sphere.material).patches
    for patch in patches:
        pass
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


def route_groups(routes):
    """Use the stage's physical winner; share the emitted area total."""
    grouped, winners = {}, {}
    for source, target, trench, area, largest in routes:
        grouped.setdefault(source, []).append((target, trench, area))
        winners[source] = largest
    return {source: (tuple(members), sum((area for _, _, area in members), Fraction(0)), winners[source])
            for source, members in grouped.items()}


def routed(values, groups, book, sinks, *, allocated=None):
    """Debit each patch once along the exact material route, retaining all child columns."""
    from atlas_tectonics.integration.material import _consumed
    result = {}
    for source, (members, total, largest) in groups.items():
        areas = [area for _, _, area in members]
        split = [T._split(value, areas, total, largest) for value in values[source]]
        if allocated is not None:
            allocated[source] = split
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
    from atlas_tectonics.integration import material as M
    from . import thermal as H
    M.bound_moving(moving, sphere)
    heat = dict(moving._patch_heat)
    patches = {p.patch_id: p for p in S.required(sphere.material).patches}
    records = {record.cohort_id: record for record in moving.cohorts}
    fields = None if moving._physical_columns is None else dict(moving._physical_columns)
    result = {}
    for patch_id in dict.fromkeys(patch_ids):
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
