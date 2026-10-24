"""Shared actual initial spatial owner; caller declares geometric accuracy.

No force or future interval is invented to initialise source material. This
helper makes no joined scientific-acceptance claim. Volume and thermal metric
budgets are mandatory and independent of later signed swept-volume bounds.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import contextmanager
from fractions import Fraction as Q
import json
from unittest.mock import patch

from atlas_tectonics import integration_differential_geometry as G
from atlas_tectonics import integration_differential_mesh as H
from atlas_tectonics import integration_volume as V, integration_wall_measures as W
from atlas_tectonics.integration_dual_measures import B_NAME, policy_record
from atlas_tectonics.integration_spatial_owner import PreparedSpatialOwner
from atlas_tectonics.integration_spatial_reservoir import PreparedFiniteStocks
from atlas_tectonics.resources import MemoryLimitError


def initial_partition(case, *, max_components):
    sphere, budget = case['source'][0], case['budget']
    current = G.prepare_current_geometry(sphere.network, budget=budget)
    cells = case['collar'].cell_geometries()
    excluded = tuple(V.CartesianCell.from_record(r, budget=budget)
                     for r in case['funding'].descriptor()['excluded_static_cells'])
    base = cells[0]; radius = Q(sphere.network.sphere.radius_m)
    offset = tuple(sum(base.basis[k][j]*base.origin_m[k] for k in range(3)) for j in range(3))
    # Include the actual sphere origin for the piecewise-affine squared-radius
    # thermal metric. This is grid choice, never a change of physical support.
    lines = tuple(tuple(sorted({-radius-offset[j], -offset[j], radius-offset[j],
        *(q for c in (*cells, *excluded) for q in (c.lower_m[j], c.upper_m[j]))})) for j in range(3))
    partition = G.prepare_differential_partition(case['funding'], sphere, current, case['collar'],
        grid_lines=lines, max_components=max_components, budget=budget)
    return current, partition


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
    witness_grid = H._witness_grid
    def report_witness_grid(*args, **kwargs):
        result = witness_grid(*args, **kwargs)
        print(json.dumps(dict(stage='certified thermal witness grid',
            axis_knots=list(map(len, result[0])), refinements=result[2],
            peak_accounted_bytes=budget.peak_reserved_bytes)), flush=True)
        return result
    try:
        with patch.object(H, '_witness_grid', report_witness_grid):
            mesh = H.build_differential_mesh(case['funding'], bounds, partition.supports, endpoint='start',
                max_geometry_volume_error_m3=thermal_volume_error_m3, max_leaves=max_leaves,
                thermal_subdivisions=thermal_subdivisions, max_witness_refinements=max_witness_refinements, budget=budget)
    except MemoryLimitError:
        print(json.dumps(dict(failed_stage='actual initial thermal metrics', budget=budget.statistics())), flush=True)
        raise
    return bounds, mesh


def projection_allowances(totals, created_tracers=()):
    """Transport projection bound of every field from its pre-solve inventory.

    Same pre-solve extensive numerical projection contract as the retained
    common-rigid workflow. Not a physical-geometry or motion tolerance. Each
    bound is 1e-10 of the field's pre-solve inventory, hence zero for a field
    with none, which an all-zero field meets exactly.

    The one exception is a tracer the caller names in ``created_tracers`` and
    whose pre-solve inventory is zero. A history tracer is carried as tracer
    times mass, so its reference is the inventory of a unit tracer on the
    same material, the total mass: declared before any solve, never from a
    residual. The two force-selected joined controls (actuated and transform)
    name accumulated strain, the tracer their source stage creates; damage
    and plastic strain keep the exact zero they meet. This is a declared
    change of ONE numerical acceptance limit of those two controls, and of
    their owner identity, which hashes the allowances. The mass reference is
    loose against the inventory actually transported, so the joined helper
    also holds each named tracer to 1e-10 of its transported input after
    every accepted advance; it reads the names from the case.
    """
    created = tuple(created_tracers)
    if len(set(created)) != len(created) or any(k not in totals or not k.startswith('tracer:') for k in created):
        raise ValueError('created tracers must be distinct history tracers of this owner')
    mass = sum((q for k, q in totals.items() if k.startswith('component_mass_kg:')), Q(0))
    return {k: (mass if k in created and not q else q)/Q(10**10) for k, q in totals.items()}


@contextmanager
def initial_spatial_owner(case, partition, bounds, mesh, *, created_tracers=(), measure_policy=None):
    budget, funding = case['budget'], case['funding']
    dual = measure_policy is not None
    if dual:
        policy_record(measure_policy)  # All six limits exist before owner preparation.
    if dual != (B_NAME in case['state'].fields.array_names):
        raise ValueError('native material quadrature and explicit spatial measure policy must agree')
    arrays = funding.arrays()
    count = len(case['registry'].rows)
    names = tuple('component_mass_kg:'+str(i) for i in range(count))
    names += ('enthalpy_j',)+tuple(sorted(k for k in arrays if k.startswith('tracer:')))
    if dual:
        names += (B_NAME,)
    positive = tuple(k for k in names if k != 'enthalpy_j')
    totals = {k: Q(0) for k in names}
    for i in range(count):
        totals['component_mass_kg:'+str(i)] = sum((abs(Q(float(v))) for v in arrays['component_mass_kg'][i].flat), Q(0))
    for name in names:
        if not name.startswith('component_mass_kg:') and name != B_NAME:
            totals[name] += sum((abs(Q(float(v))) for v in arrays[name].flat), Q(0))
    if dual:
        totals[B_NAME] = sum((abs(Q(float(v))) for v in case['state'].fields.array(B_NAME).flat), Q(0))
    keys = tuple(map(tuple, funding.descriptor()['component_keys']))
    for row in funding.exterior_remainder():
        at = keys.index((row['patch_id'], row['sublayer'])); stock = row['stocks']
        totals['component_mass_kg:'+str(at)] += abs(W._decode(stock['mass_kg']))
        totals['enthalpy_j'] += abs(W._decode(stock['enthalpy_j']))
        totals['tracer:source_kappa'] += abs(W._decode(stock['source_kappa_mass_kg']))
        if dual:
            totals[B_NAME] += abs(W._decode(stock['volume_m3']))
    for row in case['finite_rows']:
        for name in names:
            totals[name] += abs(W._decode(row['exact'][name]))
    errors = projection_allowances(totals, created_tracers)
    case['created_tracers'] = tuple(created_tracers)
    with PreparedFiniteStocks(case['registry'].registry_id, case['finite_rows'],
            field_names=names, nonnegative_fields=positive, budget=budget) as finite, \
         PreparedSpatialOwner(funding, case['collar'], bounds, mesh, method='implicit-upwind',
            max_projection_errors=errors, finite_stocks=finite, budget=budget,
            measure_policy=measure_policy) as owner:
        yield owner
