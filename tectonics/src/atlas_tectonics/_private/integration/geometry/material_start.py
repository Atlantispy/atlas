"""Diagnostic-only eligibility for exact zero-epoch material plane starts.

This does not alter a mesh: family completeness and 3-D coverage must be proved
separately before using any returned normal. All data come from issued constraints.
"""
from fractions import Fraction as Q


def exact_material_start(constraint, material_omega, D, W, arena):
    """Return an exact oriented (normal, offset) or None; never fit a plane."""
    omega = tuple(material_omega)
    zero = (Q(0), Q(0), Q(0))
    kind = constraint['kind']
    if kind == 'rotated-normal':
        if tuple(map(W._decode, constraint['angular_velocity_rad_s'])) != omega:
            return None
        normal = tuple(map(W._decode, constraint['normal']))
        return (normal, Q(0)) if any(normal) else None
    if kind != 'snapshot-rotated':
        return None
    if (tuple(map(W._decode, constraint['angular_velocity_rad_s'])) != omega or
            W._decode(constraint['snapshot_offset_s']) != 0):
        return None
    normal, error, offset = D._constraint_pose(constraint['constraint'], Q(0), Q(0), 24, arena)
    if error != 0 or offset != 0 or not any(normal):
        return None
    return tuple(normal), offset


def oriented_start_key(normal):
    """Gauge-invariant exact plane identity plus its orientation."""
    first = next((v for v in normal if v), None)
    if first is None:
        raise ValueError('zero plane normal')
    return tuple(v / first for v in normal), (1 if first > 0 else -1)
