"""One bounded D4 native domain with retained channel physics and exact ancestry.

Only the private routing/trial resource envelopes change. Native classes,
R14 erosion, the 8192-bit exact-number bound and all source/physical guards
remain. The 8192-layer ceiling is below the native column engine's 16384.
This is a working non-canon common-domain adapter, not a new producer.
"""
from dataclasses import dataclass, field, replace
from fractions import Fraction as F
import hashlib
from pathlib import Path
from types import SimpleNamespace

from work.geology_r1 import native as g1
from work.generator_upgrade_r28.preflight import clone
from work.terrain_model_r7.hillslope_kernel import Grid
from work.topography_r1 import kernels

MAX_CELLS, MAX_CONNECTORS, MAX_LAYERS, MAX_BITS = 256, 2048, 8192, 8192
DEFAULT_EVIDENCE = 'native-terrain-r1 common-domain channel trial'


def _verify_source():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != globals().get('_R12_EXECUTED_SHA256'):
        raise ValueError('executed native domain source differs; no repin')


def _prepared():
    native, geometry, original, _ = kernels._scope(True)
    if native.MAX_BITS != MAX_BITS or native.MAX_LAYERS != 2048:
        raise ValueError('retained native arithmetic/layer envelope differs')
    scope = dict(original, MAX_CELLS=MAX_CELLS, MAX_CONNECTORS=MAX_CONNECTORS, MAX_LAYERS=MAX_LAYERS)
    route = clone(kernels._route_kernel, **scope)
    private = SimpleNamespace(**dict(vars(native), MAX_CELLS=MAX_CELLS,
                                     MAX_CONNECTORS=MAX_CONNECTORS, MAX_LAYERS=MAX_LAYERS, route_water=route))
    return private, geometry, scope, route


@dataclass(frozen=True)
class Domain:
    grid: Grid
    cell_ids: tuple
    connectors: tuple
    _native: object = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        _verify_source()
        if type(self.grid) is not Grid or not 0 < self.grid.size <= MAX_CELLS:
            raise ValueError('one explicit native grid of at most 256 cells required')
        if (type(self.cell_ids) not in (list, tuple) or len(self.cell_ids) != self.grid.size
                or any(type(key) is not str or not key.strip() or len(key) > 1024 for key in self.cell_ids)
                or len(set(self.cell_ids)) != len(self.cell_ids)):
            raise ValueError('one unique explicit row-major identity per grid cell required')
        if type(self.connectors) not in (tuple, list) or len(self.connectors) > MAX_CONNECTORS:
            raise ValueError('bounded explicit immutable native connectors required')
        tt = g1.ground_gate.backend()[1]
        object.__setattr__(self, '_native', tt)
        object.__setattr__(self, 'cell_ids', tuple(self.cell_ids))
        object.__setattr__(self, 'connectors', tuple(self.connectors))
        positions = {key: divmod(i, self.grid.cols) for i, key in enumerate(self.cell_ids)}
        expected = {}
        for key, (row, col) in positions.items():
            for dr, dc in ((-1, 0), (0, -1), (0, 1), (1, 0)):
                rr, cc = row + dr, col + dc
                if 0 <= rr < self.grid.rows and 0 <= cc < self.grid.cols:
                    other = self.cell_ids[rr * self.grid.cols + cc]
                    expected[key, other] = F(self.grid.dy_m if dr else self.grid.dx_m)
        found, identities, pairs = {}, set(), set()
        for edge in self.connectors:
            if type(edge) is not tt.Connector:
                raise ValueError('same actual G1 native Connector class required')
            if edge.connector_id in identities:
                raise ValueError('duplicate connector identity')
            identities.add(edge.connector_id)
            pair = (edge.source_id, edge.receiver_id, edge.outlet_elevation_m)
            if pair in pairs:
                raise ValueError('duplicate physical connector')
            pairs.add(pair)
            if edge.source_id not in positions:
                raise ValueError('connector source is outside the whole native domain')
            if edge.receiver_id is None:
                row, col = positions[edge.source_id]
                if row not in (0, self.grid.rows - 1) and col not in (0, self.grid.cols - 1):
                    raise ValueError('explicit external connector must start at the perimeter')
            else:
                key = edge.source_id, edge.receiver_id
                if key not in expected or edge.length_m != expected[key]:
                    raise ValueError('internal connector must match exact D4 support geometry')
                found[key] = edge.length_m
        if found != expected:
            raise ValueError('complete directed D4 internal connector inventory required')

    def _state(self, state):
        if (type(state) is not self._native.LandscapeState
                or len(state.columns) != len(self.cell_ids)
                or set(state.column_map) != set(self.cell_ids)):
            raise ValueError('one whole native state must match every declared grid support')
        if sum(len(c.layers) for _, c in state.columns) > MAX_LAYERS:
            raise ValueError('bounded 8192 total native layer envelope exceeded')
        area = F(self.grid.dx_m) * F(self.grid.dy_m)
        if any(c.area_m2 != area for _, c in state.columns):
            raise ValueError('native support area differs from the exact grid cell area')

    def route(self, state, runoff, duration):
        _verify_source()
        self._state(state)
        expected = kernels.p.sources()
        _, _, _, route = _prepared()
        result = route(state, runoff, self.connectors, duration_years=duration)
        kernels.p.verify_sources(expected)
        _verify_source()
        return result

    def trial(self, state, runoff, duration, laws, sediment_laws, controls, *,
              evidence_id=DEFAULT_EVIDENCE):
        _verify_source()
        self._state(state)
        result = kernels._trial(state, runoff, self.connectors, laws, sediment_laws,
            duration_years=duration, controls=controls, evidence_id=evidence_id,
            prepared=_prepared())
        self._state(result.state)
        _verify_source()
        return result


def channel_layer_sources(before, trial):
    """Return exact fractions of INPUT source mass for every output layer.

    Native deposit/export fractions use eroded mass as their denominator. They
    are converted here to the same full-input-layer basis as hillside transfers.
    This validates immediate ancestry; the caller composes persistent origins.
    """
    _verify_source()
    tt = g1.ground_gate.backend()[1]
    if type(before) is not tt.LandscapeState or type(trial) is not tt.TerrainTrial:
        raise ValueError('same actual native state and TerrainTrial classes required')
    states = (before, trial.erosion_state, trial.state)
    if any(type(s) is not tt.LandscapeState or not 0 < len(s.columns) <= MAX_CELLS
           or sum(len(c.layers) for _, c in s.columns) > MAX_LAYERS for s in states):
        raise ValueError('bounded native channel states required')
    initial, stripped, final = (s.column_map for s in states)
    if set(initial) != set(stripped) or set(initial) != set(final):
        raise ValueError('channel state support inventory changed')
    for key, column in initial.items():
        for output in (stripped[key], final[key]):
            if (column.area_m2, column.basal_elevation_m) != (output.area_m2, output.basal_elevation_m):
                raise ValueError('channel transfer changed fixed physical supports')
    layers = {(key, i): layer for key, c in initial.items() for i, layer in enumerate(c.layers)}

    def source(row):
        identity = row['source_cell'], row['source_layer_index']
        if type(identity[1]) is not int or identity not in layers:
            raise ValueError('channel event has no exact input source layer')
        return identity, layers[identity]

    removed = {}
    for event in trial.erosion_events:
        identity, layer = source(event)
        amount = tt._q(event['eroded_mass_kg'], 'channel removed source mass', True)
        if (identity in removed or amount > layer.mass_kg
                or event['source_initial_mass_kg'] != layer.mass_kg
                or event['remaining_mass_kg'] != layer.mass_kg - amount
                or event['source_layer'] != tt._layer_record(layer)):
            raise ValueError('channel erosion source identity or finite split differs')
        removed[identity] = amount
    result, expected_layers = {}, {}
    closure = {identity: F() for identity in layers}
    for key, column in initial.items():
        result[key], expected_layers[key] = [], []
        for i, layer in enumerate(column.layers):
            identity = key, i
            mass = layer.mass_kg - removed.get(identity, F())
            if mass:
                expected_layers[key].append(replace(layer, mass_kg=mass))
                fraction = tt._q(mass / layer.mass_kg, 'retained source fraction')
                result[key].append([dict(source_cell=key, source_layer_index=i,
                                         fraction_of_source_mass=fraction)])
                closure[identity] += fraction
        if tuple(expected_layers[key]) != stripped[key].layers:
            raise ValueError('channel erosion state differs from its finite source events')

    for event in trial.deposit_events:
        key, index, layer = event['destination_cell'], event['destination_layer_index'], event['layer']
        if (key not in result or type(index) is not int or index != len(result[key])
                or type(layer) is not tt.Layer or layer.phase != 'mobile_sediment'
                or event['material_id'] != layer.material_id or event['mass_kg'] != layer.mass_kg):
            raise ValueError('channel deposit destination layer identity/order differs')
        sources, amount, seen = [], F(), set()
        for row in event['sources']:
            identity, original = source(row)
            mass = tt._q(row['mass_kg'], 'channel deposited source mass', True)
            if (identity in seen or identity not in removed
                    or row['fraction_of_eroded_mass'] != mass / removed[identity]
                    or original.material_id != layer.material_id
                    or original.grain_density_kg_m3 != layer.grain_density_kg_m3):
                raise ValueError('channel deposit source material/fraction differs')
            seen.add(identity)
            fraction = tt._q(mass / original.mass_kg, 'deposited input-source fraction')
            sources.append(dict(source_cell=identity[0], source_layer_index=identity[1],
                                fraction_of_source_mass=fraction))
            closure[identity] += fraction
            amount += mass
        if amount != layer.mass_kg:
            raise ValueError('channel deposit ancestry does not reconstruct its mass')
        result[key].append(sources)
        expected_layers[key].append(layer)
    if any(tuple(expected_layers[key]) != column.layers for key, column in final.items()):
        raise ValueError('channel final layers differ from retained/deposited ancestry')
    for row in trial.exports:
        identity, original = source(row)
        mass = tt._q(row['mass_kg'], 'channel exported source mass')
        if (identity not in removed or row['material_id'] != original.material_id
                or row['solid_volume_m3'] != mass / original.grain_density_kg_m3
                or row['fraction_of_eroded_mass'] != mass / removed[identity]):
            raise ValueError('channel export source identity/fraction differs')
        closure[identity] += tt._q(mass / original.mass_kg, 'exported input-source fraction')
    if any(fraction != 1 for fraction in closure.values()):
        raise ValueError('channel source retention/deposition/export does not close exactly')
    _verify_source()
    return result
