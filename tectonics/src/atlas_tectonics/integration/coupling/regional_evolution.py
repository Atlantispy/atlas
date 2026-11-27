"""Source-bound, independently retained Cartesian regional material owner.

This deliberately narrow port does not return a sheared 3-D field as a rigid
spherical column. Selected source columns are dormant while this owner exists.
The caller must enforce the reservation at its global evolution/return boundary.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
from typing import Any

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.integration import bridges as B
from atlas_tectonics.integration import material as M
from atlas_tectonics.integration import support as U
from atlas_tectonics.integration.geometry import volume as V
from atlas_tectonics.integration.coupling.strength import CreepLaw
from atlas_tectonics.regional.execution import RegionalMechanicalSnapshot
from atlas_tectonics.regional.execution3d import SIDES, PreparedRegionalStokes3D
from atlas_tectonics.regional.execution3d import _digest_array
from atlas_tectonics.mechanics.stokes_execution import _factored_scale
from atlas_tectonics.integration.resources import canonical_json
from atlas_tectonics.integration.resources import json_sha256
from atlas_tectonics.integration.reuse import content_record


class RegionalOwnerRefused(TectonicsError):
    """Unsupported material, map, reservation or checkpoint; never homogenise."""


def _exact(q):
    return [str(q.numerator), str(q.denominator)]


def _text(value, label):
    if type(value) is not str or not value or len(value) > 256 or not value.isascii():
        raise RegionalOwnerRefused(label+' requires a bounded explicit ASCII identity')
    return value


@dataclass(frozen=True)
class CellAllocation:
    """One pure source patch/sublayer in one cell; shares are exact volume shares.

    There is exactly one row per Cartesian cell in x,y,z (z-fastest) order.
    Shares of a selected patch/layer must sum to exactly one. These are supplied
    geometric-volume allocations, not positions reconstructed from face means.
    """
    patch_id: str
    sublayer: int
    share: Fraction

    def __post_init__(self):
        _text(self.patch_id, 'patch')
        if type(self.sublayer) is not int or self.sublayer < 0:
            raise RegionalOwnerRefused('nonnegative sublayer index required')

    def record(self):
        return [self.patch_id, self.sublayer, _exact(self.share)]


def _source_binding(sphere, moving):
    return dict(sphere_state_id=sphere.state_id, network_id=sphere.network.network_id,
                material_id=sphere.material.material_id, moving_id=moving.moving_id)


def _native_contract(native, basal_side=None):
    definition = native.descriptor()
    if basal_side is None:
        for i, side in enumerate(SIDES):
            if definition['boundary_types'][side][i//2] != 'velocity':
                raise RegionalOwnerRefused('material owner requires prescribed normal velocity on all six walls')
    else:
        for i, side in enumerate(SIDES):
            boundary = definition['boundary_types'][side]
            if side == basal_side:
                if boundary[i//2] != 'traction':
                    raise RegionalOwnerRefused('declared basal side requires natural normal traction')
            elif tuple(boundary) != ('velocity',)*3:
                raise RegionalOwnerRefused('natural-base owner requires prescribed velocity on the other five walls')
    return definition


def _creep_contract(native, definition, creep_match):
    _text(creep_match['creep_law_id'], 'creep_law_id')
    law = CreepLaw.from_record(creep_match['law'])
    if definition['rheology']['family'] == 'radial-3d-creep-plastic':
        if definition['rheology']['creep_law'] != law.record():
            raise RegionalOwnerRefused('native radial creep differs from the actual source creep law')
        return
    if definition['rheology']['family'] == 'constant':
        pass
    elif definition['rheology']['law'] != law.record():
        raise RegionalOwnerRefused('native temperature-dependent law is not the actual declared source creep law')


class RegionalVolumeMap:
    """Source-bound pure Cartesian cells inside explicitly radial material.

    This is an exact containment certificate for the retained cone geometry,
    not exact spherical area measurement. The immutable record keeps the
    existing area enclosure separately from booked inventories. No clipped
    mixed cell, fitted map, arbitrary share or historical conversion is used.
    """

    __slots__ = ('_record', 'volume_map_id')

    def __setattr__(self, name, value):
        raise RegionalOwnerRefused('regional volume maps are immutable')

    def __init__(self, sphere, moving, footprint, *, cells, lengths_m,
                 origin_local_m, cell_sources, map_source, budget):
        if (type(cells) is not tuple or len(cells) != 3 or
                any(type(n) is not int or not 2 <= n <= 24 for n in cells)):
            raise RegionalOwnerRefused('three bounded native cell counts are required')
        lengths, origin = tuple(float(v) for v in lengths_m), tuple(float(v) for v in origin_local_m)
        count = math.prod(cells)
        if (type(cell_sources) is not tuple or len(cell_sources) != count or
                any(type(row) is not tuple or len(row) != 2 or type(row[1]) is not int or row[1] < 0
                    for row in cell_sources)):
            raise RegionalOwnerRefused('one explicit patch/sublayer source per native cell required')
        for patch_id, _ in cell_sources:
            _text(patch_id, 'cell source patch')
        _text(map_source, 'volume map source')
        if len(set(cell_sources)) > 16:
            raise RegionalOwnerRefused('at most sixteen source patch/layer components')
        support = U.required(sphere.material)
        amount = 65536+32768*count+4*support.workspace_bytes()
        with budget.reserve(amount, category='regional-volume-map'), U.geometry_workspace(budget):
            frame, projection, _, _, _ = B._charted(sphere.network, footprint)
            basis = tuple(tuple(Fraction(float(v)) for v in row) for row in frame.basis)
            if (any(v not in (-1, 0, 1) for row in basis for v in row) or
                    any(sum(abs(v) for v in row) != 1 for row in basis) or
                    any(sum(abs(basis[i][j]) for i in range(3)) != 1 for j in range(3))):
                raise RegionalOwnerRefused('this exact contained-box route requires an actual signed-permutation frame')
            frame_origin = tuple(Fraction(float(v)) for v in frame.origin_m)
            global_origin = tuple(frame_origin[i]+sum((basis[i][j]*Fraction(origin[j]) for j in range(3)), Fraction(0))
                                  for i in range(3))
            spacing = tuple(Fraction(v)/n for v, n in zip(lengths, cells))
            patches = {p.patch_id: p for p in support.patches if p.face_id in footprint.face_ids}
            field = dict(moving._physical_columns)
            layers, area, rows, used = {}, {}, [], {}
            V.RadialLayer(sphere.network.sphere.radius_m,
                                     footprint.depth_top_m, footprint.depth_bottom_m, budget=budget)
            containment_cones = {}
            for flat, (patch_id, layer_index) in enumerate(cell_sources):
                patch = patches[patch_id]
                record = moving.cohort(patch.cohort_id)
                if patch_id not in layers:
                    layers[patch_id] = M.layer_geometry(record, field[patch_id][0], budget=budget)
                    # Internal triangulation is not a material contact. Admit a
                    # combined cone only after exact coverage proof, never a
                    # hull or mere membership of the box's corners in a union.
                    try:
                        containment_cones[patch_id] = (V.convex_cone_union(patch.cells, budget=budget),)
                    except V.VolumeError:
                        # A genuinely nonconvex/disconnected patch may still
                        # contain a pure cell wholly in an original convex part.
                        containment_cones[patch_id] = patch.cells
                    lo, hi = U.area_interval_sr(patch.cells)
                    radius2 = Fraction(sphere.network.sphere.radius_m)**2
                    area[patch_id] = lo*radius2, hi*radius2
                index = np.unravel_index(flat, cells)
                lower = tuple(int(i)*h for i, h in zip(index, spacing))
                upper = tuple((int(i)+1)*h for i, h in zip(index, spacing))
                cell = V.CartesianCell(lower, upper, origin_m=global_origin, basis=basis, budget=budget)
                layer = layers[patch_id][layer_index]
                cones = containment_cones[patch_id]
                if not any(V.contains_cartesian_cell(layer, cone, cell, budget=budget) for cone in cones):
                    raise RegionalOwnerRefused('native cell crosses its actual source radial layer or material contact')
                used[(patch_id, layer_index)] = used.get((patch_id, layer_index), Fraction(0))+cell.volume_m3
                rows.append(dict(cell=cell.record(), patch_id=patch_id, sublayer=layer_index,
                    face_id=patch.face_id, cohort_id=patch.cohort_id,
                    plate_id=sphere.network.face_plate(patch.face_id)))
            source_rows = []
            for patch_id in sorted(layers):
                patch, record = patches[patch_id], moving.cohort(patches[patch_id].cohort_id)
                lower_area, upper_area = area[patch_id]
                for j, layer in enumerate(layers[patch_id]):
                    debit = used.get((patch_id, j), Fraction(0))
                    bounds = tuple(a*layer.volume_per_area_m for a in area[patch_id])
                    if debit > bounds[0]:
                        raise RegionalOwnerRefused('contained cell debit is not certified below the source volume lower enclosure')
                    source_rows.append(dict(patch_id=patch_id, sublayer=j, radial_layer=layer.record(),
                        retained_area_enclosure_m2=[_exact(lower_area), _exact(upper_area)],
                        booked_area_m2=_exact(patch.stock[0]),
                        booked_area_allowance_m2=patch.area_allowance_m2,
                        geometry_volume_enclosure_m3=[_exact(v) for v in bounds],
                        ideal_box_volume_m3=_exact(debit),
                        remainder_geometry=dict(operation='source radial cone layer minus disjoint native cells',
                            source_patch_id=patch_id, source_layer_id=layer.layer_id,
                            excluded_cell_indices=[i for i, key in enumerate(cell_sources) if key == (patch_id, j)]),
                        remainder_volume_enclosure_m3=[_exact(v-debit) for v in bounds]))
            request = dict(footprint=footprint.record(), cells=list(cells), lengths_m=list(lengths),
                origin_local_m=list(origin), cell_sources=[list(row) for row in cell_sources], map_source=map_source)
            embedding = dict(sphere=sphere.network.sphere.descriptor(), frame=frame.descriptor(),
                basis=[[_exact(v) for v in row] for row in basis],
                frame_origin_m=[_exact(v) for v in frame_origin], origin_local_m=list(origin),
                origin_global_m=[_exact(v) for v in global_origin], cells=list(cells), lengths_m=list(lengths),
                spacing_m=[_exact(v) for v in spacing])
            described = dict(schema='atlas.regional-volume-map.v1', source=_source_binding(sphere, moving),
                request=request, embedding=embedding, cell_sources=rows, source_layers=source_rows,
                source_volume_convention=V.PHYSICAL_RADIAL_SHELL,
                geometry='exact signed-permutation affine boxes; exact containment in retained cones or proved '
                         'convex unions, and radial layers',
                area_scope='existing directed area enclosure and atan premise; booked area is not exact geometric area',
                disjointness='regular native grid cells have disjoint interiors by construction',
                projection=B._plain(projection))
            encoded = canonical_json(described)
            object.__setattr__(self, '_record', encoded)
            object.__setattr__(self, 'volume_map_id', hashlib.sha256(encoded).hexdigest())

    def record(self):
        return dict(volume_map_id=self.volume_map_id, **json.loads(self._record))

    @classmethod
    def restore(cls, record, sphere, moving, *, budget):
        """Rebuild against actual current sources and repeat every proof."""
        try:
            request = record['request']
            rebuilt = cls(sphere, moving, B.Footprint(**request['footprint']),
                cells=tuple(request['cells']), lengths_m=tuple(request['lengths_m']),
                origin_local_m=tuple(request['origin_local_m']),
                cell_sources=tuple(tuple(row) for row in request['cell_sources']),
                map_source=request['map_source'], budget=budget)
            if rebuilt.record() != record:
                raise RegionalOwnerRefused('physical volume map, source, geometry or proof was changed')
            return rebuilt
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            if isinstance(exc, RegionalOwnerRefused):
                raise
            raise RegionalOwnerRefused('invalid physical volume-map record') from exc

    def native_binding(self, native):
        """Require the actual scaled Q2 node path to reproduce this exact box."""
        return self._bind_native(native)

    def _bind_native(self, native, mapped=None):
        cells = native._cells if type(native) is PreparedRegionalStokes3D else native.cells
        count = math.prod(2*n+1 for n in cells)
        with native._resource.reserve(65536+4*len(self._record)+512*count, category='regional-physical-node-binding'):
            data = self.record() if mapped is None else mapped
            embedding = data['embedding']
            definition = native.descriptor()
            return self._native_binding(native, definition, data, embedding)

    def _native_binding(self, native, definition, data, embedding):
        mechanical = type(native) is PreparedRegionalStokes3D
        scale = native._scales.length_m if mechanical else native._ms.length_m
        dimensions = _factored_scale(np.asarray(embedding['lengths_m']), (), (scale,), 'scaled box')
        axes = []
        for j, n in enumerate(embedding['cells']):
            axis = _factored_scale(np.arange(2*n+1)*(dimensions[j]/n/2),
                                  (scale,), (), 'coordinates')
            axes.append(axis)
        points = np.stack(np.meshgrid(*axes, indexing='ij'), axis=-1).reshape(-1, 3)
        if mechanical and not np.array_equal(points, native.coordinates('velocity')):
            raise RegionalOwnerRefused('actual mechanical velocity nodes differ from the contained native grid')
        basis = np.asarray([[float(Fraction(*map(int, q))) for q in row] for row in embedding['basis']])
        origin = np.asarray(embedding['origin_local_m'])
        frame_origin = np.asarray([float(Fraction(*map(int, q))) for q in embedding['frame_origin_m']])
        actual = (points+origin)@basis.T+frame_origin
        # A signed permutation is separable: these 3*(2*n+1) exact checks prove
        # the entire Cartesian product without O(nodes) rational construction.
        for i in range(3):
            j = next(j for j in range(3) if basis[i, j] != 0)
        return dict(schema='atlas.regional-owner-physical-binding.v1', volume_map_id=self.volume_map_id,
            source=data['source'], source_volume_convention=V.PHYSICAL_RADIAL_SHELL,
            embedding=embedding, native_plan_id=definition['material_source'] if mechanical else native.plan_id,
            physical_points_sha256=_digest_array(actual),
            cell_sources=[{k: row[k] for k in ('patch_id', 'sublayer', 'face_id', 'cohort_id', 'plate_id')}
                          for row in data['cell_sources']])


class RegionalOwnerState:
    """Detached native depth fields plus their immutable ownership/checkpoint record."""
    __slots__ = ('native_state', 'exchange', 'inventory', '_metadata', 'owner_state_id')

    def __init__(self, native_state, exchange, metadata, inventory=None):
        encoded = canonical_json(metadata)
        object.__setattr__(self, 'native_state', native_state)
        object.__setattr__(self, 'exchange', exchange)
        object.__setattr__(self, 'inventory', inventory)
        object.__setattr__(self, '_metadata', encoded)
        identity = dict(metadata=metadata,
            native_state_id=native_state.result_id,
            exchange_id=None if exchange is None else exchange.result_id)
        if inventory is not None:
            identity['inventory_id'] = inventory.result_id
        object.__setattr__(self, 'owner_state_id', json_sha256(content_record(identity)))

    def __setattr__(self, name, value):
        raise RegionalOwnerRefused('regional owner states are immutable')

    def descriptor(self):
        result = dict(metadata=json.loads(self._metadata), native=self.native_state.descriptor(),
            exchange=None if self.exchange is None else self.exchange.descriptor(),
            native_state_id=self.native_state.result_id,
            exchange_id=None if self.exchange is None else self.exchange.result_id,
            owner_state_id=self.owner_state_id)
        if self.inventory is not None:
            result.update(inventory=self.inventory.descriptor(), inventory_id=self.inventory.result_id)
        return result

    def arrays(self):
        result = {'regional.native.'+key: self.native_state.array(key)
                  for key in self.native_state.array_names}
        if self.exchange is not None:
            result.update({'regional.exchange.'+key: self.exchange.array(key)
                           for key in self.exchange.array_names})
        if self.inventory is not None:
            result.update({'regional.inventory.'+key: self.inventory.array(key)
                           for key in self.inventory.array_names})
        return result


@dataclass(frozen=True)
class RegionalOwnerAdvance:
    state: RegionalOwnerState
    native_advance: object
    exchange: RegionalMechanicalSnapshot


class PreparedRegionalOwner:
    """Own one admitted regional inventory, with no accumulated snapshot cache.

    Native plan lifetime belongs to the caller. The wrapper reserves its retained
    definition/initial state and transient record work against the SAME budget.
    Returned states are caller-owned immutable snapshots, not an unbounded cache.
    Supported source-bound constitutive declarations and pure initial cells are
    required. Material walls are impermeable unless explicit physical finite
    reservoirs fund this owner. Declared boundary heat conduction is allowed.
    """

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __init__(self, native_plan, sphere, moving, footprint, allocations=None, *,
                 plate_ids, creep_match, map_source=None, budget, volume_map=None, boundary_reservoirs=(),
                 component_registry=None, basal_side=None, material_quadrature=False):
        self._guard = None
        self._funding = None
        self._closed = False
        self._material_quadrature = material_quadrature
        self._basal_side = basal_side
        if component_registry is not None:
            component_registry.validate_native(native_plan, source_id=moving.moving_id)
        self._registry = component_registry
        # Charge geometry serialisation before making decimal strings/copies.
        # Whole source-support accounting is conservative; immutable source arrays
        # remain the caller's, not copied into an unbounded regional cache.
        amount = 65536+16384*math.prod(native_plan.cells)+3*U.required(sphere.material).workspace_bytes()
        # Additional source labels retain distinct masses; they are not merged
        # into an old slot. Four array-construction copies scale with the actual
        # admitted workload while the caller's WorkBudget remains unchanged.
        amount += 32*max(0, len(native_plan._composition)-16)*math.prod(native_plan.cells)
        if volume_map is not None:
            amount += 4*len(volume_map._record)
        self._guard = budget.reserve(amount, category='regional-owner-retained')
        self._guard.__enter__()
        try:
            self._physical = self._remainder = None
            if volume_map is None:
                self._prepare(native_plan, sphere, moving, footprint, allocations, plate_ids=plate_ids,
                              creep_match=creep_match, map_source=map_source, budget=budget)
            else:
                self._prepare_radial(native_plan, sphere, moving, footprint, volume_map, plate_ids=plate_ids,
                                     creep_match=creep_match, map_source=map_source, budget=budget)
                if boundary_reservoirs:
                    self._activate_funding(volume_map, sphere, moving, boundary_reservoirs)
        except BaseException:
            self.close()
            raise

    def _prepare(self, native_plan, sphere, moving, footprint, allocations, *,
                 plate_ids, creep_match, map_source, budget):
        self._native, self._budget = native_plan, budget
        definition = _native_contract(native_plan)
        _creep_contract(native_plan, definition, creep_match)
        _text(map_source, 'spatial transfer source')
        extracted = B.extract(sphere, footprint)
        patches = {p.patch_id: p for p in extracted.material_support.patches}
        keys = tuple(sorted({(row.patch_id, row.sublayer) for row in allocations}))
        if len(keys) > 16 or len(keys) != len(definition['composition_values']):
            raise RegionalOwnerRefused('one native composition component per source patch/layer, at most sixteen')
        source_patches = tuple(sorted({p for p, _ in keys}))
        # Retain the original I05 guard on its original reporting-piece support
        # and arithmetic. The native reference field is a separate physical
        # representation, not a demand that rounded stocks have an exact ratio.
        selected_pieces = {(patches[p].face_id, patches[p].cohort_id) for p in source_patches}
        intervals = sphere.network.step-moving.declared_step
        for piece in sphere.material.pieces():
            if (piece.face_id, piece.cohort_id) in selected_pieces:
                record = moving.cohort(piece.cohort_id)
        physical_columns = M._patch_columns(moving, sphere, source_patches)
        heat = dict(moving._patch_heat)
        components, stocks, temperatures = [], [], []
        mat = native_plan._material
        for patch_id, layer_index in keys:
            patch = patches[patch_id]
            record = moving.cohort(patch.cohort_id)
            if layer_index >= len(record.sublayers):
                raise RegionalOwnerRefused('unknown source sublayer')
            layer = record.sublayers[layer_index]
            phase = sphere.material.phases.index(layer.phase)
            _, _, heights, temperature = physical_columns[patch_id]
            share = Fraction(heights[layer_index])/sum((Fraction(h) for s, h in zip(record.sublayers, heights)
                                                       if s.phase == layer.phase), Fraction(0))
            mass = patch.stock[1+phase]*share
            volume = patch.stock[1+len(sphere.material.phases)+phase]*share
            q = heat[patch_id][layer_index]
            absolute = q+mass*Fraction(mat.heat_capacity_j_kg_k)*Fraction(moving.enthalpy_reference_k)
            components.append(dict(patch_id=patch_id, sublayer=layer_index,
                plate_id=sphere.network.face_plate(patch.face_id)))
            stocks.append((volume, mass, q, absolute, Fraction(record.kappa[layer_index])))
            temperatures.append(temperature[layer_index])
        # Selected patches transfer whole columns: a reservation must not leave
        # an unowned layer beneath a globally dormant horizontal footprint.
        for patch_id in source_patches:
            record = moving.cohort(patches[patch_id].cohort_id)
        transfer = dict(source=map_source, allocations=[a.record() for a in allocations],
                        source_patches=[patches[p].record() for p in source_patches])
        layout = dict(schema='atlas.regional-owner-layout.v1', region_id=footprint.region_id,
            cells=list(native_plan.cells), lengths_m=list(native_plan.lengths_m), plate_ids=list(plate_ids),
            components=components, native_plan_id=native_plan.plan_id, transfer_id=json_sha256(transfer))
        binding = dict(sphere_state_id=sphere.state_id, network_id=sphere.network.network_id,
                       material_id=sphere.material.material_id, moving_id=moving.moving_id)
        reservation = dict(schema='atlas.regional-source-reservation.v1', source=binding,
            patch_ids=list(source_patches), region_id=footprint.region_id,
            status='owned-by-region; spherical source records dormant; no return implemented')
        base = dict(schema='atlas.regional-owner-plan.v2', layout=layout, transfer=transfer,
            extract=extracted.record(), creep_match=creep_match, reservation=reservation,
            native_plan=definition, source_enthalpy_reference_k=moving.enthalpy_reference_k,
            sampling='one source patch/layer per initial cell; later native cell mixture',
            physical_column_source='retained physical h/areal heat; never reconstructed from reporting stocks',
            inventory_guard=dict(method='I05 original piece reference-mass guard', intervals_since_declaration=intervals),
            admission_projection='source minus native retained separately; not physical mass, heating or plasticity; closed owner only',
            geometric_scope='declared conservative flat-box volume map, not an isometric spherical deformation')
        if self._material_quadrature:
            base['material_quadrature'] = True
        try:
            shape = native_plan.cells
            masses = np.zeros((len(keys), *shape))
            enthalpy = np.zeros(shape)
            kappa = np.zeros(shape)
            residuals = [[Fraction(0) for _ in range(4)] for _ in keys]
            for flat, allocation in enumerate(allocations):
                component = keys.index((allocation.patch_id, allocation.sublayer))
                cell = np.unravel_index(flat, shape)
                volume, mass, relative, absolute, memory = stocks[component]
                exact = (volume*allocation.share, mass*allocation.share,
                         absolute*allocation.share, mass*memory*allocation.share)
                # Match native initial_state's reference-field arithmetic using
                # the actual retained physical temperature and passive kappa.
                # Exact booked stocks remain in the separate signed account.
                stored = (native_plan._volume, native_plan._mass,
                          temperatures[component]*(native_plan._mass*mat.heat_capacity_j_kg_k),
                          float(memory)*native_plan._mass)
                for j, (value, q) in enumerate(zip(stored, exact)):
                    if not math.isfinite(value) or (q != 0 and value == 0):
                        raise RegionalOwnerRefused('source projection overflows or erases a positive inventory')
                    residuals[component][j] += Fraction(value)-q
                masses[(component, *cell)] = stored[1]
                enthalpy[cell], kappa[cell] = stored[2], stored[3]
            base['admission_accounts'] = [dict(component=i,
                exact_volume_m3=_exact(stock[0]), exact_mass_kg=_exact(stock[1]),
                exact_relative_heat_j=_exact(stock[2]), exact_absolute_heat_j=_exact(stock[3]),
                exact_source_kappa_mass_kg=_exact(stock[1]*stock[4]),
                physical_temperature_k=temperatures[i],
                projection_rounding=[_exact(v) for v in residuals[i]]) for i, stock in enumerate(stocks)]
            projection = [dict(component=i, **{name: _exact(-value) for name, value in zip(
                ('volume_m3', 'mass_kg', 'absolute_heat_j', 'source_kappa_mass_kg'), residuals[i])})
                for i in range(len(keys))]
            base['source_minus_native_projection'] = projection
            self._projection = canonical_json(projection)
            self._definition = canonical_json(base)
            self.owner_id = json_sha256(content_record(base))
            self._layout, self._reservation = canonical_json(layout), canonical_json(reservation)
            fields = dict(component_mass_kg=masses, enthalpy_j=enthalpy,
                **{'tracer:damage': np.zeros(shape), 'tracer:accumulated_strain_ii': np.zeros(shape),
                   'tracer:source_kappa': kappa})
            if self._material_quadrature:
                fields['material_quadrature_m3'] = np.sum(masses, axis=0)/mat.density_kg_m3
            native = native_plan._state(fields, moving.time_s, self.owner_id, None)
            native_plan._fields(native)
            self.initial_state = self._issued(native, None, None, 0)
        except BaseException:
            self.close()
            raise

    def _prepare_radial(self, native, sphere, moving, footprint, volume_map, *,
                        plate_ids, creep_match, map_source, budget):
        self._native, self._budget = native, budget
        definition = _native_contract(native, self._basal_side)
        _creep_contract(native, definition, creep_match)
        mapped = volume_map.record()
        if (mapped['source'] != _source_binding(sphere, moving) or
                mapped['request']['footprint'] != footprint.record() or
                (map_source is not None and map_source != mapped['request']['map_source'])):
            raise RegionalOwnerRefused('physical map is not bound to this source/footprint/declaration')
        radial = definition['rheology']['family'] == 'radial-3d-creep-plastic'
        if radial:
            pass
        binding = volume_map._bind_native(native, mapped)
        rows = mapped['cell_sources']
        mapped_keys = tuple(sorted({(row['patch_id'], row['sublayer']) for row in rows}))
        keys = mapped_keys if self._registry is None else self._registry.source_keys
        source_plates = (() if self._registry is None else self._registry.initial_source_plate_ids)
        patch_ids = tuple(sorted({p for p, _ in keys}))
        patches = {p.patch_id: p for p in U.required(sphere.material).patches if p.patch_id in patch_ids}
        field, heat = dict(moving._physical_columns), dict(moving._patch_heat)
        mat, reference = native._material, Fraction(moving.enthalpy_reference_k)
        rho, cp = Fraction(mat.density_kg_m3), Fraction(mat.heat_capacity_j_kg_k)
        target = (mat.density_kg_m3, mat.heat_capacity_j_kg_k, mat.conductivity_w_m_k,
                  mat.expansion_per_k, mat.internal_heating_w_m3)
        source, geometry, temperature, memory = {}, {}, {}, {}
        source_geometry = {(row['patch_id'], row['sublayer']): row for row in mapped['source_layers']}
        additional_geometry = []
        component_index = {key: i for i, key in enumerate(keys)}
        for patch_id in patch_ids:
            patch, record = patches[patch_id], moving.cohort(patches[patch_id].cohort_id)
            heights, areal, _ = field[patch_id]
            if (record.volume_convention != V.PHYSICAL_RADIAL_SHELL or
                    record.reference_radius_m != sphere.network.sphere.radius_m):
                raise RegionalOwnerRefused('physical shell ownership cannot reinterpret a prism history')
            layers = M.layer_geometry(record, heights, budget=budget)
            if patch_id not in {p for p, _ in source_geometry}:
                # These actual source patches contain no native cell. Their
                # entire retained cone/layer is reserved, not assigned invented
                # box intersections. The material support already owns each
                # actual patch; measured area uncertainty remains explicit.
                with U.geometry_workspace(budget):
                    area = tuple(q*Fraction(sphere.network.sphere.radius_m)**2
                                 for q in U.area_interval_sr(patch.cells))
                for j, shell in enumerate(layers):
                    bounds = tuple(q*shell.volume_per_area_m for q in area)
                    item = dict(patch_id=patch_id, sublayer=j, radial_layer=shell.record(),
                        retained_area_enclosure_m2=[_exact(q) for q in area],
                        booked_area_m2=_exact(patch.stock[0]), booked_area_allowance_m2=patch.area_allowance_m2,
                        geometry_volume_enclosure_m3=[_exact(q) for q in bounds],
                        ideal_box_volume_m3=_exact(Fraction(0)),
                        remainder_geometry=dict(operation='source radial cone layer minus disjoint native cells',
                            source_patch_id=patch_id, source_layer_id=shell.layer_id, excluded_cell_indices=[]),
                        remainder_volume_enclosure_m3=[_exact(q) for q in bounds])
                    source_geometry[patch_id, j] = item
                    additional_geometry.append(item)
            phase_weights = M.phase_volume_per_area(record, heights, budget=budget)
            for j, (layer, shell) in enumerate(zip(record.sublayers, layers)):
                values = (layer.reference_density_kg_m3, layer.heat_capacity_j_kg_k, layer.conductivity_w_m_k,
                          layer.alpha_per_k, layer.radiogenic_w_m3)
                if values != target or layer.creep_law_id != creep_match['creep_law_id']:
                    raise RegionalOwnerRefused('source remainder and cells require the same actual admitted material/creep law')
                key = patch_id, j
                if self._registry is not None and key in keys:
                    pass
                phase = sphere.material.phases.index(layer.phase)
                factor = shell.volume_per_area_m
                share = factor/phase_weights[layer.phase]
                mass = patch.stock[1+phase]*share
                volume = patch.stock[1+len(sphere.material.phases)+phase]*share
                relative = heat[patch_id][j]
                source[key] = (volume, mass, relative, relative+mass*cp*reference,
                               mass*Fraction(record.kappa[j]))
                geometry[key] = shell
                # The retained state is an explicit layer FV-constant caloric
                # field. No original unresolved linear radial profile is used
                # as a scalar box average.
                temperature[key] = reference+areal[j]/(rho*cp*factor)
                memory[key] = Fraction(record.kappa[j])
        shape = native.cells
        masses = np.zeros((len(native._composition), *shape)); enthalpy = np.zeros(shape); kappa = np.zeros(shape)
        ideal = {key: [Fraction(0)]*5 for key in source}
        projected = {key: [Fraction(0)]*5 for key in source}
        spacing = [Fraction(*map(int, q)) for q in mapped['embedding']['spacing_m']]
        cell_volume = math.prod(spacing)
        for flat, row in enumerate(rows):
            key = row['patch_id'], row['sublayer']; component = component_index[key]
            cell = np.unravel_index(flat, shape)
            exact_mass = rho*cell_volume
            exact_relative = exact_mass*cp*(temperature[key]-reference)
            exact = (cell_volume, exact_mass, exact_relative,
                     exact_relative+exact_mass*cp*reference, exact_mass*memory[key])
            stored_mass = native._mass
            stored_heat = float(temperature[key])*(native._mass*mat.heat_capacity_j_kg_k)
            stored_kappa = float(memory[key])*native._mass
            if (not all(math.isfinite(v) for v in (stored_mass, stored_heat, stored_kappa)) or
                    stored_mass <= 0 or stored_heat <= 0 or (memory[key] != 0 and stored_kappa == 0)):
                raise RegionalOwnerRefused('native field projection overflows or erases a physical inventory')
            represented = (Fraction(native._volume), Fraction(stored_mass),
                Fraction(stored_heat)-Fraction(stored_mass)*cp*reference,
                Fraction(stored_heat), Fraction(stored_kappa))
            for j in range(5):
                ideal[key][j] += exact[j]
                projected[key][j] += represented[j]
            masses[(component, *cell)] = stored_mass
            enthalpy[cell], kappa[cell] = stored_heat, stored_kappa
        names = ('volume_m3', 'mass_kg', 'relative_heat_j', 'absolute_heat_j', 'source_kappa_mass_kg')
        residuals, remainders, accounts = [], [], []
        for key in sorted(source):
            outside = [a-b for a, b in zip(source[key], ideal[key])]
            if any(outside[j] < 0 for j in (0, 1, 3, 4)):
                raise RegionalOwnerRefused('actual source inventory cannot fund the ideal contained cells and positive remainder')
            component = component_index.get(key)
            residual = [a-b for a, b in zip(ideal[key], projected[key])]
            common = dict(patch_id=key[0], sublayer=key[1], component=component)
            remainders.append(dict(**common, geometry=source_geometry[key]['remainder_geometry'],
                geometry_volume_enclosure_m3=source_geometry[key]['remainder_volume_enclosure_m3'],
                stocks={name: _exact(q) for name, q in zip(names, outside)},
                physical_temperature_k=_exact(temperature[key]), source_kappa=_exact(memory[key])))
            residuals.append(dict(**common, **{name: _exact(q) for name, q in zip(names, residual)}))
            accounts.append(dict(**common, source={name: _exact(q) for name, q in zip(names, source[key])},
                ideal_debit={name: _exact(q) for name, q in zip(names, ideal[key])},
                native_projection={name: _exact(q) for name, q in zip(names, projected[key])}))
        layout = dict(schema='atlas.regional-owner-layout.v1', region_id=footprint.region_id,
            cells=list(native.cells), lengths_m=list(native.lengths_m), plate_ids=list(plate_ids),
            components=[dict(patch_id=p, sublayer=j, plate_id=sphere.network.face_plate(patches[p].face_id)) for p, j in keys],
            native_plan_id=native.plan_id, transfer_id=volume_map.volume_map_id)
        if self._registry is not None:
            layout.update(schema='atlas.regional-owner-layout.v2',
                          components=self._registry.layout_components(), component_registry=self._registry.record())
            if source_plates:
                layout['initial_source_plate_ids'] = list(source_plates)
        reservation = dict(schema='atlas.regional-source-reservation.v2', source=_source_binding(sphere, moving),
            patch_ids=list(patch_ids), region_id=footprint.region_id,
            status='native cells and explicit outside-box shell remainder owned here; full source columns dormant')
        base: dict[str, Any] = dict(schema='atlas.regional-owner-plan.v3', layout=layout,
            transfer=dict(source=mapped['request']['map_source'], volume_map_id=volume_map.volume_map_id),
            volume_map=mapped, physical_geometry_binding=binding,
            extract=B.extract(sphere, footprint).record(), creep_match=creep_match, reservation=reservation,
            native_plan=definition, source_enthalpy_reference_k=moving.enthalpy_reference_k,
            admission_accounts=accounts, source_minus_native_projection=residuals, physical_remainder=remainders,
            accounting='source = native + physical shell-minus-box remainder + ideal-minus-native projection',
            projection_scope='numerical signed account, never rock or heating',
            geometric_scope='certified pure contained Cartesian cells; measured source area retains its declared enclosure',
            remainder_scope='dormant source fields, not an evolved or resampled exterior reservoir',
            boundary_scope='closed material walls; finite open-boundary funding and shared global clock not yet implemented')
        if self._material_quadrature:
            base['material_quadrature'] = True
        if self._registry is not None:
            base['component_registry'] = self._registry.record()
        if additional_geometry:
            base['additional_source_layers'] = additional_geometry
        if source_plates:
            reservation['initial_source_plate_ids'] = list(source_plates)
        if self._basal_side is not None:
            base['basal_side'] = self._basal_side
            base['boundary_scope'] = ('natural normal basal traction; admission only; complete-grid mechanics '
                                      'and actual carved finite basal inventories required for continuation')
        self._definition = canonical_json(base)
        object.__setattr__(self, 'owner_id', json_sha256(content_record(base)))
        self._layout, self._reservation = canonical_json(layout), canonical_json(reservation)
        self._projection, self._physical, self._remainder = canonical_json(residuals), canonical_json(binding), canonical_json(remainders)
        fields = dict(component_mass_kg=masses, enthalpy_j=enthalpy,
            **{'tracer:damage': np.zeros(shape), 'tracer:accumulated_strain_ii': np.zeros(shape),
               'tracer:source_kappa': kappa})
        if self._material_quadrature:
            fields['material_quadrature_m3'] = np.sum(masses, axis=0)/mat.density_kg_m3
        if radial:
            fields['tracer:radial_plastic_kappa'] = np.zeros(shape)
        state = native._state(fields, moving.time_s, self.owner_id, None)
        native._fields(state)
        self.initial_state = self._issued(state, None, None, 0)

    def _verify(self):
        self._native.descriptor()

    def _activate_funding(self, volume_map, sphere, moving, reservoirs):
        from atlas_tectonics.integration.coupling.regional_inventory import RegionalBoundaryFunding
        self._funding = RegionalBoundaryFunding(volume_map, sphere, moving, self._native,
            self.layout(), self.physical_remainder(), reservoirs, budget=self._budget)
        funding = self._funding.descriptor()
        base = json.loads(self._definition)
        base.update(schema='atlas.regional-owner-plan.v4', boundary_inventory=funding,
            physical_remainder=funding['physical_remainder'],
            accounting='source = native + finite halo reservoirs + physical remainder + separately booked projection',
            boundary_scope='finite initially homogeneous physical halo reservoirs; no refill or global reinsertion')
        self._definition = canonical_json(base)
        object.__setattr__(self, 'owner_id', json_sha256(content_record(base)))
        self._remainder = canonical_json(funding['physical_remainder'])
        previous = self.initial_state.native_state
        native = self._native._state({k: previous.array(k) for k in previous.array_names},
            previous.descriptor()['time_s'], self.owner_id, None)
        object.__setattr__(self, 'initial_state', self._issued(native, None, None, 0, self._funding.initial_state))

    def descriptor(self):
        self._verify()
        return dict(owner_id=self.owner_id, **json.loads(self._definition))

    def reservation(self):
        return json.loads(self._reservation)

    def layout(self):
        return json.loads(self._layout)

    def admission_projection(self):
        """Exact signed source-minus-native representation account; never a source term."""
        return json.loads(self._projection)

    def physical_geometry_binding(self):
        """None for the incompatible legacy flat map; exact physical join otherwise."""
        return None if self._physical is None else json.loads(self._physical)

    def physical_remainder(self):
        """Dormant shell-minus-box fields/accounts, not a recyclable inlet supply."""
        return None if self._remainder is None else json.loads(self._remainder)

    def require_dormant_source(self, sphere, moving):
        self._verify()

    def assert_global_available(self, patch_ids):
        self._verify()

    def _issued(self, native, exchange, parent, intervals, inventory=None):
        metadata = dict(schema='atlas.regional-owner-state.v2',
            owner_id=self.owner_id, reservation=self.reservation(), layout=self.layout(),
            source_minus_native_projection=self.admission_projection(),
            parent_owner_state_id=parent, intervals=intervals)
        if self._physical is not None:
            metadata.update(schema='atlas.regional-owner-state.v3',
                physical_geometry_binding=self.physical_geometry_binding(), physical_remainder=self.physical_remainder())
        if self._funding is not None:
            metadata.update(schema='atlas.regional-owner-state.v4', boundary_funding_id=self._funding.funding_id)
        return RegionalOwnerState(native, exchange, metadata, inventory)

    def _bound(self, state):
        metadata = state.descriptor()['metadata']
        required = {'schema', 'owner_id', 'reservation', 'layout', 'parent_owner_state_id', 'intervals',
                    'source_minus_native_projection'}
        schema = 'atlas.regional-owner-state.v2'
        if self._physical is not None:
            required |= {'physical_geometry_binding', 'physical_remainder'}
            schema = 'atlas.regional-owner-state.v3'
        if self._funding is not None:
            required.add('boundary_funding_id'); schema = 'atlas.regional-owner-state.v4'
            from atlas_tectonics.integration.coupling.regional_inventory import RegionalBoundaryFunding

            if type(self) is PreparedRegionalOwner and type(self._funding) is RegionalBoundaryFunding:
                inventory = self._funding._bound_owner_fields(state.inventory)
            else:
                self._funding._bound(state.inventory)
                inventory = None
            if inventory is None:
                inventory = state.inventory.descriptor()
        elif state.inventory is not None:
            raise RegionalOwnerRefused('closed owner cannot contain an unowned boundary inventory')
        if (set(metadata) != required or metadata.get('schema') != schema or
                metadata.get('owner_id') != self.owner_id or metadata['reservation'] != self.reservation() or
                metadata['layout'] != (layout := self.layout()) or
                metadata['source_minus_native_projection'] != self.admission_projection()):
            raise RegionalOwnerRefused('regional state belongs to a different source/layout/native plan')
        count = metadata['intervals']
        native = state.native_state.descriptor()
        if count == 0:
            if (metadata['parent_owner_state_id'] is not None or state.exchange is not None or
                    state.owner_state_id != self.initial_state.owner_state_id):
                raise RegionalOwnerRefused('initial owner state must reproduce its exact source admission')
        else:
            _text(metadata['parent_owner_state_id'], 'parent owner state')
            exchange = state.exchange.descriptor()
            if (exchange.get('schema') != 'atlas.regional-owner-exchange.v1' or
                    exchange.get('layout') != (layout if type(self) is PreparedRegionalOwner else self.layout()) or
                    exchange.get('layout_id') != json_sha256(
                        layout if type(self) is PreparedRegionalOwner else self.layout()) or
                    exchange.get('state_id') != state.native_state.result_id or
                    exchange.get('parent_state_id') != native.get('parent_state_id') or
                    native.get('time_s') != exchange.get('start_time_s', math.nan)+exchange.get('duration_s', math.nan) or
                    not np.array_equal(state.native_state.array('component_mass_kg'),
                                       state.exchange.array('component_mass_after_interval_kg'))):
                raise RegionalOwnerRefused('retained exchange, parent, time or material fields do not bind the actual successor')
        self._native._fields(state.native_state)

    def _closed_driving(self, velocity, coupling):
        shape = tuple(2*n+1 for n in self._native.cells)
        nv = math.prod(shape)
        a = np.asarray(velocity, dtype=float)
        if a.ndim == 0:
            a = np.full((nv, 3), float(a))
        fields = [a]
        if coupling is not None:
            modes = np.asarray(coupling.get('boundary_modes_m'), dtype=float)
            fields.extend(modes)
        for field in fields:
            field = field.reshape(*shape, 3)
            for axis in range(3):
                if any(np.any(np.take(field[..., axis], i, axis=axis) != 0) for i in (0, -1)):
                    raise RegionalOwnerRefused('closed owner refuses normal boundary flow/modes; explicit finite source/export funding is required')

    def advance(self, state, duration_s, *, sphere, moving, **driving):
        """Advance retained fields; source records are checked but NEVER resampled.

        Driving keys are native advance keys except boundary_stocks: this owner
        supplies empty closed-wall stocks or its retained finite inventory. Return includes native
        mechanics/transport/conduction and the same-solve exchange, not a second
        heat deposit for the global column route.
        """
        self.require_dormant_source(sphere, moving)
        self._bound(state)
        if self._funding is None:
            self._closed_driving(driving.get('velocity_m_s'), driving.get('coupling'))
        count = state.descriptor()['metadata']['intervals']
        from atlas_tectonics.integration.coupling.regional_exchange import regional_exchange
        with self._budget.reserve(65536+8192*math.prod(self._native.cells), category='regional-owner-advance'):
            # Empty means zero inventory, not an incomplete transported schema.
            # Radial plasticity carries its new history separately from original
            # source kappa; preserve every validated extra tracer even at rest.
            extra_tracers = tuple(name.removeprefix('tracer:') for name in state.native_state.array_names
                if name.startswith('tracer:') and name not in
                ('tracer:damage', 'tracer:accumulated_strain_ii'))
            funding = self._funding
            stocks = (self._native.empty_boundary_stocks(extra_tracers) if funding is None else
                      funding.stocks(state.inventory))
            result = self._native.advance(state.native_state, duration_s,
                boundary_stocks=stocks, **driving)
            exchange = regional_exchange(result, layout=self.layout(), parent_state=state.native_state,
                                         budget=self._budget)
            inventory = None
            current_funding = self._funding
            if current_funding is not None:
                if current_funding is funding:
                    current_funding._bound(state.inventory)
                    inventory = current_funding._advance_with_stocks(state.inventory, result, state.native_state, stocks)
                else:
                    inventory = current_funding.advance(state.inventory, result, state.native_state)
            next_state = self._issued(result.state, exchange, state.owner_state_id, count+1, inventory)
            return RegionalOwnerAdvance(next_state, result, exchange)

    def restore(self, record, arrays, *, sphere, moving):
        """Lossless existing-workflow descriptor/array checkpoint seam, not a file store."""
        self.require_dormant_source(sphere, moving)
        with self._budget.reserve(65536+16384*math.prod(self._native.cells), category='regional-owner-restore'):
            try:
                native_arrays = {k.removeprefix('regional.native.'): v for k, v in arrays.items()
                                 if k.startswith('regional.native.')}
                expected_shapes = {k: v.shape for k, v in self.initial_state.arrays().items()
                                   if k.startswith('regional.native.')}
                if (set(native_arrays) != {k.removeprefix('regional.native.') for k in expected_shapes} or
                        any(np.shape(v) != expected_shapes['regional.native.'+k] or
                            np.asarray(v).dtype != np.dtype('float64') for k, v in native_arrays.items())):
                    raise RegionalOwnerRefused('native checkpoint fields, shape or dtype differ from this bounded owner')
                native = RegionalMechanicalSnapshot(record['native'], native_arrays)
                exchange_arrays = {k.removeprefix('regional.exchange.'): v for k, v in arrays.items()
                                   if k.startswith('regional.exchange.')}
                if record['exchange'] is None:
                    if exchange_arrays or record['exchange_id'] is not None:
                        raise RegionalOwnerRefused('unexpected exchange arrays')
                    exchange = None
                else:
                    from atlas_tectonics.integration.coupling.regional_exchange import restore_exchange
                    exchange = restore_exchange(record['exchange'], exchange_arrays, layout=self.layout(),
                                                expected_result_id=record['exchange_id'], budget=self._budget)
                inventory = None
                if self._funding is not None:
                    inventory_arrays = {k.removeprefix('regional.inventory.'): v for k, v in arrays.items()
                                        if k.startswith('regional.inventory.')}
                    inventory = self._funding.restore(record['inventory'], inventory_arrays, record['inventory_id'])
                state = RegionalOwnerState(native, exchange, record['metadata'], inventory)
                if (state.descriptor() != record or set(state.arrays()) != set(arrays) or
                        any(np.asarray(arrays[k]).dtype != np.dtype('float64') for k in arrays)):
                    raise RegionalOwnerRefused('regional checkpoint identity, fields or binary64 dtype was altered')
                self._bound(state)
                if state.descriptor()['metadata']['intervals'] == 0 and state.owner_state_id != self.initial_state.owner_state_id:
                    raise RegionalOwnerRefused('initial checkpoint does not reproduce source admission')
                return state
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                if isinstance(exc, RegionalOwnerRefused):
                    raise
                raise RegionalOwnerRefused('malformed or stale regional checkpoint: '+str(exc)) from exc

    def close(self):
        if self._funding is not None:
            self._funding.close()
            self._funding = None
        if self._guard is not None:
            self._guard.__exit__(None, None, None)
            self._guard = None
        self._closed = True

    def __enter__(self):
        self._verify()
        return self

    def __exit__(self, *_):
        self.close()
