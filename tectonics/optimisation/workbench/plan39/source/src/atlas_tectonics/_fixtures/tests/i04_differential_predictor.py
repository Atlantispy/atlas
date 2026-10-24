"""Next same-parent force driver from one candidate interval's component masks.

The first proposal of an accepted clock uses the current geometry: its Q2 trace
is constrained by every component mask AS IT IS at the start. Where the two
plate fields are discontinuous on a prescribed native wall, that trace cannot
equal either rigid field pointwise, and material first exposed during the
interval has no start mask at all. ``PreparedDifferentialIteration`` therefore
admits a later driver built from the PRECEDING proposal's time-integrated
masks. This factory builds exactly that driver with the same accepted-start
pressure, authored force, exterior balance and angular subspace; nothing is
fitted to a result and no FE error enters a volume or stream bound.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import contextmanager
from fractions import Fraction as Q

from atlas_tectonics import integration_differential_trace as T
from atlas_tectonics import integration_regional_driving as R
from atlas_tectonics import integration_volume as V


def interval_predictor(case, *, network, current, prototype, forcing, exterior, prepared, pressure,
                       plates, boundary, basis, global_basis, force_control):
    """Return ``build(interval, partition, stream_width)``, a driver context.

    Moment width, leaf ceiling, FE error/work bounds and map/constraint sources
    are those of the current-geometry driver. ``stream_width`` is the candidate
    interval's own predeclared stream allowance, as for the final trace.
    """
    budget = case['budget']

    def predictor_trace(interval, partition, stream_width):
        """The predictor's trace; its inputs are retained first and a refusal keeps its query."""
        from i04_differential_continuation_control import _retain_trace_failure, _retain_trace_inputs
        _retain_trace_inputs(None, partition,
            case['volume_map'], dict(plate_ids=list(plates), endpoint=None, open_side='z0',
            max_moment_width=V._encoded(Q(1, 10**24)), max_volume_width=V._encoded(Q(stream_width)), max_leaves=64,
            interval_predictor=True), budget, name='predictor-trace-inputs',
            scope='inputs of a same-parent interval-predictor trace over one candidate interval')
        try:
            return T.PreparedDifferentialTrace(prototype, case['volume_map'], interval,
                V.RadialLayer(10, 0, 3, budget=budget), network=network, plate_ids=plates,
                endpoint=None, open_side='z0', max_moment_width=Q(1, 10**24),
                max_volume_width=stream_width, max_leaves=64, component_partition=partition,
                interval_predictor=True, force_geometry=current, budget=budget)
        except Exception as error:
            _retain_trace_failure(error, 'predictor-component-moment-failure')
            raise

    @contextmanager
    def build(interval, partition, stream_width):
        with predictor_trace(interval, partition, stream_width) as trace, \
             T.DifferentialPlateBoundaryLift(network, prototype, case['volume_map'], trace,
                boundary.boundary_id, angular_rate_basis=basis,
                map_source='actual complete material component masks',
                constraint_source=force_control.constraint_source,
                max_l2_error_squared=10000, max_work_error=10000, budget=budget) as lift, \
             R.PreparedRegionalDriving(network, forcing, exterior, prepared, lift, budget=budget,
                differential_pressure=pressure, pressure_native=prototype,
                global_angular_rate_basis=global_basis,
                global_constraint_source=force_control.constraint_source) as driver:
            yield driver
    return build
