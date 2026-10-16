"""Pose width successor (c) on the exterior mesh: E's deviation sum is stored as a short outward bound.

transform_exterior_mesh(source)   integration_exterior_mesh.py, AFTER width_pose_round (b-quat)

The same rule as width_deviation_bound.py applies to M, now applied to E's two builders
(build_exterior_mesh and _build_exterior_mesh_record). Each builder compares the exact sum
total_error with the declared width and refuses above it. That comparison is unchanged and is still
taken on the exact sum. Only after it passes is the header value that the record stores
(geometry_volume_max_deviation_m3) replaced by

    0                                                                     if total_error == 0
    min(round_up(total_error, 2**(floor_log2(total_error)-64)), width)    otherwise

which is >= total_error (outward), exceeds it by less than 2**-64 relative, and is <= width.
total_error has no other use after the check; the per-cell deviations stay exact.
Exact int and Fraction arithmetic only. The transform checks its input pin (E after (b-quat)),
refuses a second application, and requires the comparison block to occur exactly twice.
Record identity: the stored header deviation changes (part of the pose width identity successor).
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '524622bfa3dc76f797960c321e059ff781f646499222fc688ee027d1b4e79845',
}
MARKER = 'DEVIATION_STORED_BITS'

CHECK_OLD = '''        if total_error > width:
            raise V.VolumeError('declared spatial grid exceeds the predeclared physical geometry volume-error budget')
'''
CHECK_NEW = CHECK_OLD+'''        total_error = _stored_deviation(total_error, width)
'''
HELPER_OLD = '''from .resources import WorkBudget


'''
HELPER_NEW = '''from .resources import WorkBudget

# Pose width (c): the stored deviation sum is an outward bound with a short dyadic
# denominator, at most 2**-DEVIATION_STORED_BITS above the exact sum relative.
DEVIATION_STORED_BITS = 64


def _stored_deviation(total, width):
    """Outward short bound of an exact nonnegative sum already checked against width."""
    if type(total) is not Q or type(width) is not Q or not 0 <= total <= width:
        raise V.VolumeError('checked exact deviation sum required')
    if total == 0:
        return total
    e = total.numerator.bit_length()-total.denominator.bit_length()
    if Q(2)**e > total:
        e -= 1
    quantum = Q(2)**(e-DEVIATION_STORED_BITS)
    return min(-((-total)//quantum)*quantum, width)


'''
EDITS = ((HELPER_OLD, HELPER_NEW, 1), (CHECK_OLD, CHECK_NEW, 2))


def transform_exterior_mesh(source, *, allow_unreviewed_input=False):
    if MARKER in source:
        raise ValueError('exterior deviation bound transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('integration_exterior_mesh.py input is not the reviewed (b-quat) output')
    for old, new, count in EDITS:
        if source.count(old) != count:
            raise ValueError('exterior deviation anchor occurs %d times, expected %d: %s' % (
                source.count(old), count, old.strip()[:60]))
        source = source.replace(old, new)
    return source


TRANSFORMS = {'integration_exterior_mesh.py': transform_exterior_mesh}
