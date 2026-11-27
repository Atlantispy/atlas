"""Fresh source-bound funding of a full-cell homogeneous FV collar.

This issues a proposed ONE-TIME allocation, not authority to spend a previously
reserved source. A transaction owner must reserve it atomically. Evolved native
or collar state must be continued, never refreshed through this constructor.
Spatial integration, inherited area uncertainty and binary64 projection remain
distinct accounts. No exterior time evolution is inferred here.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass, field
from fractions import Fraction as Q
import math
import weakref

import numpy as np

from atlas_tectonics.integration import material as M
from atlas_tectonics.integration import support as U
from . import volume as V
from . import volume_bounds as B
from . import volume_overlap as O
from atlas_tectonics.regional.execution import RegionalMechanicalSnapshot


FIELDS = ('mass_kg', 'enthalpy_j', 'source_kappa_mass_kg')


def _encode(q):
    return V._encoded(Q(q))


def _partition(bounds, total):
    """Label/order-invariant feasible quadrature closure of a PROVED partition.

    Midpoints plus the common signed fraction of each uncertainty width give
    sum(v)=total. Since total lies in [sum(lo),sum(hi)], that fraction is in
    [-1/2,1/2]. Every value remains in its own proved interval. This is not a
    normalisation of missing coverage, masses, or an unproved geometry union.
    """
    low, high = sum((a for a, _ in bounds), Q(0)), sum((b for _, b in bounds), Q(0))
    if high == low:
        return tuple(a for a, _ in bounds)
    shift = (total-(low+high)/2)/(high-low)
    values = tuple((a+b)/2+shift*(b-a) for a, b in bounds)
    return values


def _cone_planes(cone):
    return tuple(O._plane(tuple(-v for v in O._cross(a, b)), 0)
                 for a, b in zip(cone, cone[1:]+cone[:1]))


def _candidate_and_coverage(cell, groups, budget):
    """Whole-cell radial coverage plus exact angular complement exhaustion."""
    candidates, planes = set(), []
    minimum, maximum = cell.radial_bounds_squared_m2
    with B._Arena(budget) as arena:
        original = B._box(cell)
        for patch_id, (cones, envelope) in groups.items():
            intersects = False
            for cone in cones:
                boundaries = _cone_planes(cone)
                part = original
                for plane in boundaries:
                    part = B._clip(part, plane, arena)
                    if not part:
                        break
                if part and B._volume(part, arena) > 0:
                    intersects = True
                    planes.append(boundaries)
            if intersects:
                if minimum < envelope.bottom_radius_m**2 or maximum > envelope.top_radius_m**2:
                    raise V.VolumeError('full cell is not covered radially by every intersected selected patch interval')
                candidates.add(patch_id)
        # Coverage follows from the actual union, never from a sum of measured
        # areas or corner membership in different cones.
        uncovered = B._outside_holes(original, planes, arena)
        if any(B._volume(part, arena) > 0 for part in uncovered):
            raise V.VolumeError('selected actual source cones leave an uncovered full-cell region')
    return candidates


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class FullCellFunding:
    _snapshot: RegionalMechanicalSnapshot = field(repr=False)
    _resource: object = field(repr=False, compare=False)
    _source_volume_proven: bool = field(repr=False, compare=False, init=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('FullCellFunding is issued by fund_full_cells()')

    @property
    def funding_id(self):
        return self._snapshot.result_id

    def descriptor(self):
        return dict(funding_id=self.funding_id, **self._snapshot.descriptor())

    def arrays(self):
        return {name: self._snapshot.array(name) for name in self._snapshot.array_names}

    def exterior_remainder(self):
        return self._snapshot.descriptor()['exterior_remainder']

    @classmethod
    def restore(cls, record, arrays, sphere, moving, collar, owner, *, budget):
        """Reissue only initial admission, never reconstruct an evolved state."""
        request = record.get('integration_request')
        encoded = [request['max_cell_volume_width_m3'], *request['max_field_errors'].values()]
        # Guard encoded sizes BEFORE allocating integers or their Fractions.
        with budget.reserve(65536+1024*sum(len(v) for pair in encoded for v in pair),
                            category='collar-funding-restore'):
            def decode(pair):
                try:
                    value = Q(int(pair[0], 16), int(pair[1], 16))
                except (ValueError, ZeroDivisionError) as exc:
                    raise V.VolumeError('invalid rational funding request') from exc
                return value
            rebuilt = fund_full_cells(sphere, moving, collar, owner,
                max_cell_volume_width_m3=decode(request['max_cell_volume_width_m3']),
                max_field_errors={k: decode(v) for k, v in request['max_field_errors'].items()},
                max_leaves=request['max_leaves'], budget=budget)
            if 'basal_inventory' in record:
                from atlas_tectonics.integration.coupling.basal_inventory import carve_basal_inventory
                from atlas_tectonics.integration.coupling.regional_inventory import HaloReservoir
                basal = record['basal_inventory']
                rebuilt = carve_basal_inventory(rebuilt, sphere, moving, collar,
                    tuple(HaloReservoir.from_record(row, budget=budget) for row in basal['reservoirs']), budget=budget,
                    compartment_kind=basal.get('compartment_kind', 'source'))
            return rebuilt


def fund_full_cells(sphere, moving, collar, owner, *, max_cell_volume_width_m3,
                    max_field_errors, max_leaves, budget):
    """Propose a fresh whole-grid allocation from actual radial patch fields.

    Existing fresh inner fields are copied bit-for-bit. Only native-increment
    histories start at zero; actual source raw kappa remains a carried tracer.
    Selected components must supply a complete geometric partition of every
    full cell and share the native density/Cp/k. Unsupported material is refused,
    never supplied as a zero-filled corner or an averaged constitutive law.
    """
    owner.require_dormant_source(sphere, moving)
    owner._bound(owner.initial_state)
    definition, layout = collar.descriptor(), owner.layout()
    registry = owner._registry
    keys = (tuple((row['patch_id'], row['sublayer']) for row in layout['components']) if registry is None
            else registry.source_keys)
    if ((None if registry is None else registry.record()) != definition.get('component_registry') or
            keys != tuple(sorted(set(keys))) or
            (registry is None and len(keys) != len(collar._native._composition))):
        raise V.VolumeError('actual ordered source component layout does not match native fields')
    support = U.required(sphere.material)
    count, components = math.prod(collar.cells), len(collar._native._composition)
    with budget.reserve(262144+256*count*(components+8)+4*support.workspace_bytes(),
                        category='collar-source-funding'), U.geometry_workspace(budget):
        cells = collar.cell_geometries()
        patch_ids = {k[0] for k in keys}
        patches = {p.patch_id: p for p in support.patches if p.patch_id in patch_ids}
        del patch_ids
        physical, heat = dict(moving._physical_columns), dict(moving._patch_heat)
        reference = Q(moving.enthalpy_reference_k)
        source, geometry, densities, groups, measures = {}, {}, {}, {}, {}
        for patch_id, patch in patches.items():
            record = moving.cohort(patch.cohort_id)
            heights, areal, _ = physical[patch_id]
            layers = M.layer_geometry(record, heights, budget=budget)
            phase_factor = M.phase_volume_per_area(record, heights, budget=budget)
            try:
                cones = (V.convex_cone_union(patch.cells, budget=budget),)
            except V.VolumeError:
                cones = patch.cells
            chosen_layers = sorted(j for p, j in keys if p == patch_id)
            if chosen_layers != list(range(chosen_layers[0], chosen_layers[-1]+1)) or chosen_layers[-1] >= len(layers):
                raise V.VolumeError('selected source patch layers must be a valid contiguous radial interval')
            groups[patch_id] = (cones, V.RadialLayer(record.reference_radius_m,
                layers[chosen_layers[0]].top_depth_m, layers[chosen_layers[-1]].bottom_depth_m, budget=budget))
            area = U.area_interval_sr(patch.cells)
            area = tuple(q*Q(sphere.network.sphere.radius_m)**2 for q in area)
            for j, (layer, shell) in enumerate(zip(record.sublayers, layers)):
                key = patch_id, j
                rho, cp = Q(layer.reference_density_kg_m3), Q(layer.heat_capacity_j_kg_k)
                factor = shell.volume_per_area_m
                phase = sphere.material.phases.index(layer.phase)
                share = factor/phase_factor[layer.phase]
                mass = patch.stock[1+phase]*share
                volume = patch.stock[1+len(sphere.material.phases)+phase]*share
                source[key] = (volume, mass, heat[patch_id][j]+mass*cp*reference, mass*Q(record.kappa[j]))
                geometry[key] = shell
                measures[key] = tuple(a*factor for a in area)
                if key in keys:
                    absolute = areal[j]/factor+rho*cp*reference
                    densities[key] = (rho, absolute, rho*Q(record.kappa[j]))
        ncharts = sum(len(groups[p][0]) for p, _ in keys)
        chart_width = Q(max_cell_volume_width_m3)/ncharts
        mass = np.zeros((components, *collar.cells))
        energy = np.zeros(collar.cells)
        tracers = {name.removeprefix('tracer:'): np.zeros(collar.cells)
                   for name in owner.initial_state.native_state.array_names if name.startswith('tracer:')}
        debit = {key: [Q(0)]*4 for key in source}
        projections = {key: [Q(0)]*3 for key in source}
        source_uncertainty = {key: Q(0) for key in source}
        cell_rows = []
        for flat, cell in enumerate(cells):
            at = np.unravel_index(flat, collar.cells)
            candidates = _candidate_and_coverage(cell, groups, budget)
            bounds = []
            for key in keys:
                lo = hi = Q(0)
                if key[0] in candidates:
                    for cone in groups[key[0]][0]:
                        enclosed = B.enclose_shell_cell(geometry[key], cone, cell,
                            max_width_m3=chart_width, max_leaves=max_leaves, budget=budget)
                        if not enclosed.meets_budget:
                            raise V.VolumeError('source-cell curved integration did not meet the declared width budget')
                        lo += enclosed.lower_m3; hi += enclosed.upper_m3
                bounds.append((lo, hi))
            volumes = _partition(bounds, cell.volume_m3)
            errors = tuple(max(v-a, b-v) for v, (a, b) in zip(volumes, bounds))
            # Exact partition closure removes a common scalar density. This
            # gives zero total mass error for common rho, without claiming that
            # the individual component interfaces were integrated exactly.
            field_errors = []
            for j, name in enumerate(FIELDS):
                qs = [densities[key][j] for key in keys]
                centre = (min(qs)+max(qs))/2
                bound = sum((abs(q-centre)*e for q, e in zip(qs, errors)), Q(0))
                if bound > max_field_errors[name]:
                    raise V.VolumeError('source-cell allocation exceeds declared '+name+' integration budget')
                field_errors.append(bound)
            exact_columns = [tuple(v*q for q in densities[key]) for key, v in zip(keys, volumes)]
            for i, (key, volume, exact, error) in enumerate(zip(keys, volumes, exact_columns, errors)):
                debit[key] = [a+b for a, b in zip(debit[key], (volume, *exact))]
                source_uncertainty[key] += error
                mass[(i, *at)] = float(exact[0])
            energy[at] = float(sum((row[1] for row in exact_columns), Q(0)))
            tracers['source_kappa'][at] = float(sum((row[2] for row in exact_columns), Q(0)))
            # Full-grid arrays preserve the actual old inner arrays, not a
            # differently rounded reconstruction of the same fresh source.
            inner = all(s.start <= int(i) < s.stop for s, i in zip(collar._inner, at))
            if inner:
                local = tuple(int(i)-s.start for s, i in zip(collar._inner, at))
                for i in range(components):
                    mass[(i, *at)] = owner.initial_state.native_state.array('component_mass_kg')[(i, *local)]
                energy[at] = owner.initial_state.native_state.array('enthalpy_j')[local]
                for name in tracers:
                    tracers[name][at] = owner.initial_state.native_state.array('tracer:'+name)[local]
            projected = (tuple(Q(float(mass[(i, *at)])) for i in range(components)),
                         Q(float(energy[at])), Q(float(tracers['source_kappa'][at])))
            # Component mass has a unique projection. Mixed-cell heat/history
            # has no unique per-source float split; retain its projection once
            # at the cell, never invent a proportional per-source reassignment.
            projection = [sum((row[0] for row in exact_columns), Q(0))-sum(projected[0], Q(0)),
                          sum((row[1] for row in exact_columns), Q(0))-projected[1],
                          sum((row[2] for row in exact_columns), Q(0))-projected[2]]
            for i, key in enumerate(keys):
                projections[key][0] += exact_columns[i][0]-projected[0][i]
            cell_rows.append(dict(cell_id=cell.cell_id, component_volumes_m3=list(map(_encode, volumes)),
                component_bounds_m3=[list(map(_encode, pair)) for pair in bounds],
                component_max_deviation_m3=list(map(_encode, errors)),
                field_error_bounds={k: _encode(q) for k, q in zip(FIELDS, field_errors)},
                exact_minus_projected={k: _encode(q) for k, q in zip(FIELDS, projection)}))
        remainder, accounts = [], []
        for key in sorted(source):
            remaining = tuple(a-b for a, b in zip(source[key], debit[key]))
            if any(q < 0 for q in remaining):
                raise V.VolumeError('actual source stock cannot fund the proposed full cells and nonnegative remainder')
            error = source_uncertainty[key]
            common = dict(patch_id=key[0], sublayer=key[1])
            remainder.append(dict(**common, radial_layer=geometry[key].record(),
                geometry='actual source cone/shell minus shared full-cell exclusion union',
                geometry_volume_enclosure_m3=[_encode(max(Q(0), measures[key][0]-debit[key][0]-error)),
                                               _encode(measures[key][1]-debit[key][0]+error)],
                stocks={k: _encode(q) for k, q in zip(('volume_m3', *FIELDS), remaining)}))
            accounts.append(dict(**common,
                source={k: _encode(q) for k, q in zip(('volume_m3', *FIELDS), source[key])},
                debit={k: _encode(q) for k, q in zip(('volume_m3', *FIELDS), debit[key])},
                component_volume_max_deviation_m3=_encode(error),
                component_mass_projection=_encode(projections[key][0])))
        arrays = dict(component_mass_kg=mass, enthalpy_j=energy,
                      **{'tracer:'+name: value for name, value in tracers.items()})
        metadata = dict(schema='atlas.full-cell-collar-funding.v1',
            source=dict(sphere_state_id=sphere.state_id, network_id=sphere.network.network_id,
                        material_id=sphere.material.material_id, moving_id=moving.moving_id),
            owner_id=owner.owner_id, collar_plan_id=collar.plan_id, volume_map_id=definition['volume_map_id'],
            native_initial_state_id=owner.initial_state.native_state.result_id,
            time_s=moving.time_s, cells=list(collar.cells), component_keys=[list(k) for k in keys],
            cell_geometries=[cell.record() for cell in cells], cell_accounts=cell_rows,
            source_accounts=accounts, exterior_remainder=remainder,
            integration_request=dict(max_cell_volume_width_m3=_encode(max_cell_volume_width_m3),
                max_field_errors={k: _encode(q) for k, q in max_field_errors.items()}, max_leaves=max_leaves),
            allocation='proved full partition; interval-midpoint plus width-weighted feasible closure, label invariant',
            projection='exact proposed debit = native floating inventory + separately signed cell projection',
            inherited_geometry_scope='retained rays and existing spherical-area enclosure premise; no historical positional bound inferred',
            authority='one-time fresh funding proposal; transaction must reserve source; no clock advance or future resampling')
        if registry is not None:
            metadata['component_registry'] = registry.record()
            if registry.initial_source_plate_ids:
                metadata['initial_source_plate_ids'] = list(registry.initial_source_plate_ids)
        snapshot = RegionalMechanicalSnapshot(metadata, arrays)
        result = object.__new__(FullCellFunding)
        object.__setattr__(result, '_snapshot', snapshot)
        object.__setattr__(result, '_resource', budget)
        object.__setattr__(result, '_source_volume_proven', True)
        lease = budget.reserve(8192+2*snapshot.nbytes, category='collar-funding-retained')
        lease.__enter__()
        try:
            weakref.finalize(result, lease.__exit__, None, None, None)
        except BaseException:
            lease.__exit__(None, None, None)
            raise
        return result
