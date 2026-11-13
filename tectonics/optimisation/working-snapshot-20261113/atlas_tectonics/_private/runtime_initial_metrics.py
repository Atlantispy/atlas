"""Initial metrics through an explicit immutable witness-reporting interface.

Production port from the bound functional fixture; numerical expressions and
return/MemoryLimitError behaviour are preserved. No module rebinding or mocking.
"""
import json
from atlas_tectonics import integration_differential_geometry as G
from atlas_tectonics import integration_differential_mesh as H
from atlas_tectonics import integration_wall_measures as W
from atlas_tectonics.integration_dual_measures import policy_record
from atlas_tectonics.resources import MemoryLimitError

def initial_metrics(case, partition, *, physical_volume_error_m3,
                    thermal_volume_error_m3, max_leaves, thermal_subdivisions=1,
                    max_witness_refinements=0, measure_policy=None,
                    measurement_store=None, measurement_context=None):
    budget = case['budget']
    options = {}
    if measure_policy is not None:
        policy = policy_record(measure_policy)
        options['relative_error'] = W._decode(policy['initial_relative_error'])
    bounds = G.enclose_initial_partition(partition, max_volume_error_m3=physical_volume_error_m3,
        max_leaves=max_leaves, budget=budget, measurement_store=measurement_store,
        measurement_context=measurement_context, **options)
    def report_witness_grid(axis_knots, refinements, peak_accounted_bytes):
        print(json.dumps(dict(stage='certified thermal witness grid',
            axis_knots=list(axis_knots), refinements=refinements,
            peak_accounted_bytes=peak_accounted_bytes)), flush=True)
    try:
        mesh = H.build_differential_mesh(case['funding'], bounds, partition.supports, endpoint='start',
            max_geometry_volume_error_m3=thermal_volume_error_m3, max_leaves=max_leaves,
            thermal_subdivisions=thermal_subdivisions, max_witness_refinements=max_witness_refinements, budget=budget,
            witness_observer=report_witness_grid)
    except MemoryLimitError:
        print(json.dumps(dict(failed_stage='actual initial thermal metrics', budget=budget.statistics())), flush=True)
        raise
    return bounds, mesh
