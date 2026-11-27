from fractions import Fraction as Q

from hashlib import sha256

from atlas_tectonics._private import private_heat_original_coverage_r3 as physical_control

TARGET = '4.9171027966256209779674411407088268288935981282609672659484679021446505633744583E-40'

POLICY = dict(initial_relative_error=Q(1, 1000), max_initial_width_m3=Q(32000),
    max_relative_material_error=Q(1, 100), max_l1_material_error_m3=Q(32),
    max_relative_rebase=Q(1, 1000), max_l1_rebase_m3=Q(1))

ADVANCE_OPTIONS = dict(orientation_max_leaves=2**19, native_directed_max_leaves=2**19,
    native_mask_max_leaves=2**19, ale_max_leaves=2**19, final_trace_max_leaves=2**19,
    thermal_max_leaves=2**19, thermal_witness_refinements=32)

def snapshots(snapshot):
    return [dict(name=name, shape=list(shape), dtype='float64', sha256=sha256(raw).hexdigest())
            for name, shape, raw in snapshot._fields]

def arrays(values):
    return [dict(name=name, shape=list(value.shape), dtype=value.dtype.str,
                 sha256=sha256(value.tobytes(order='C')).hexdigest()) for name, value in values.items()]

class _Cancel:
    # The guard as the workflow's cancel value, in both forms native stages ask for:
    # called, or asked is_set(). Either way it runs the guard's own check.
    __slots__ = ('_check',)

    def __init__(self, check):
        self._check = check

    def __call__(self):
        return self._check()

    def is_set(self):
        return bool(self._check())
