"""Actual tiny native/spatial owners; explicitly synthetic archived operands.

No source funding, workflow creation, initial_state, physics stepping, old
reader or real store is used. Geometry/acceptance receipts are NOT proved by
these fixtures. They exercise real current owner construction and validation.
"""
from copy import deepcopy
from fractions import Fraction as Q
import gc
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import numpy as np

import native_transfer as N
import spatial_transfer as S
import test_native_transfer as TN


HERE = Path(__file__).resolve().parent
_temporary = None


def setUpModule():
    global _temporary, F, C, P, Snapshot, WorkBudget, Registry, enc, TectonicsError
    if any(k == 'atlas_tectonics' or k.startswith('atlas_tectonics.') for k in sys.modules):
        raise RuntimeError('clean process required; no loaded runtime replacement')
    _temporary = tempfile.TemporaryDirectory(prefix='spatial-transfer-fixture-', dir=HERE)
    package = Path(_temporary.name)/'atlas_tectonics'
    shutil.copytree(TN.BASE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name, patch in (('regional_execution.py', N.retained_snapshot_source),
                        ('integration_spatial_owner.py', S.spatial_owner_source)):
        path = package/name
        path.write_text(patch(path.read_text(encoding='utf-8')), encoding='utf-8')
    integration = HERE.parent/'runtime-integration-r1'
    sys.path[:0] = [str(Path(_temporary.name)), str(integration/'ram'), str(integration/'helpers'),
                   str(TN.HEAT_TESTS.parents[2]), str(TN.HEAT_TESTS)]
    F = importlib.import_module('test_i04_regional_owner')
    C = importlib.import_module('atlas_tectonics.regional_collar3d')
    P = importlib.import_module('atlas_tectonics.integration_spatial_owner')
    Snapshot = importlib.import_module('atlas_tectonics.regional_execution').RegionalMechanicalSnapshot
    WorkBudget = importlib.import_module('atlas_tectonics.resources').WorkBudget
    Registry = importlib.import_module('atlas_tectonics.integration_regional_inventory').ComponentRegistry
    enc = importlib.import_module('atlas_tectonics.integration_mimetic_heat')._enc
    TectonicsError = importlib.import_module('atlas_tectonics._validation').TectonicsError


def tearDownModule():
    if _temporary is not None:
        assert Path(_temporary.name).resolve().parent == HERE
        _temporary.cleanup()


def build_saved_fixture(collar, native_transfer):
    """Synthetic archived funding/evolved stocks on real prepared geometry.

    Reusable by the workflow tests. No DifferentialPartition is fabricated.
    Caller supplies fixture allowance and keeps the native transfer alive.
    """
    native = collar._native
    transfer = native_transfer.record()
    old = transfer['input']['historical_plan_graph']
    keys = collar._registry.source_keys
    cells = collar.cell_geometries()
    source = collar._map.record()['source']
    components = len(native._composition)
    rho, cp = Q(native._material.density_kg_m3), Q(native._material.heat_capacity_j_kg_k)
    arrays = dict(component_mass_kg=np.zeros((components, *collar.cells)), enthalpy_j=np.zeros(collar.cells),
        **{k: np.zeros(collar.cells) for k in N._REQUIRED_ARRAYS if k.startswith('tracer:')})
    debits = {key: dict.fromkeys(S._STOCKS, Q(0)) for key in keys}
    mass_projection = dict.fromkeys(keys, Q(0))
    cell_accounts = []
    for i, box in enumerate(cells):
        component = i//4
        at = np.unravel_index(i, collar.cells)
        volume, temperature, kappa = box.volume_m3, Q(3, 2), Q(3, 4)
        mass, energy, history = rho*volume, rho*volume*cp*temperature, rho*volume*kappa
        arrays['component_mass_kg'][(component, *at)] = float(mass)
        arrays['enthalpy_j'][at] = float(energy)
        arrays['tracer:source_kappa'][at] = float(history)
        key = keys[component]
        for name, amount in zip(S._STOCKS, (volume, mass, energy, history), strict=True):
            debits[key][name] += amount
        mass_projection[key] += mass-Q(float(arrays['component_mass_kg'][(component, *at)]))
        volumes = [volume if j == component else Q(0) for j in range(components)]
        cell_accounts.append(dict(cell_id=box.cell_id, component_volumes_m3=list(map(enc, volumes)),
            component_bounds_m3=[[enc(v), enc(v)] for v in volumes],
            component_max_deviation_m3=[enc(0) for _ in keys],
            field_error_bounds={k: enc(0) for k in S._STOCKS[1:]},
            exact_minus_projected=dict(mass_kg=enc(mass-Q(float(mass))),
                enthalpy_j=enc(energy-Q(float(energy))), source_kappa_mass_kg=enc(history-Q(float(history))))))
    names = tuple('component_mass_kg:'+str(i) for i in range(components))+('enthalpy_j',)+tuple(sorted(
        k for k in arrays if k.startswith('tracer:')))
    positive = tuple(k for k in names if k != 'enthalpy_j')
    finite_fields = dict.fromkeys(names, Q(0))
    finite_fields.update({'component_mass_kg:0': rho/8, 'enthalpy_j': rho*cp*Q(3, 16), 'tracer:source_kappa': rho*Q(3, 32)})
    finite_initial = dict(stock_id='fixture:retained-reservoir', kind='reservoir',
        lineage=dict(kind='finite-basal-reservoir', source_id='1'*64, source=source, source_key=list(keys[0]),
                     fixture_scope='synthetic archived source receipt, not geometric acceptance'),
        volume_m3=enc(Q(1, 8)), exact={k: enc(v) for k, v in finite_fields.items()})
    basal_debit = dict(volume_m3=Q(1, 8), mass_kg=rho/8,
                       enthalpy_j=rho*cp*Q(3, 16), source_kappa_mass_kg=rho*Q(3, 32))
    source_accounts, remainders = [], []
    for key in keys:
        remainder = dict(volume_m3=Q(1), mass_kg=rho, enthalpy_j=rho*cp*Q(3, 2), source_kappa_mass_kg=rho*Q(3, 4))
        total = {k: debits[key][k]+remainder[k]+(basal_debit[k] if key == keys[0] else 0) for k in S._STOCKS}
        source_accounts.append(dict(patch_id=key[0], sublayer=key[1], source={k: enc(v) for k, v in total.items()},
            debit={k: enc(v) for k, v in debits[key].items()}, component_volume_max_deviation_m3=enc(0),
            component_mass_projection=enc(mass_projection[key])))
        remainders.append(dict(patch_id=key[0], sublayer=key[1],
            stocks={k: enc(v) for k, v in remainder.items()}, geometry='fixture:unchanged physical exclusion',
            radial_layer=F.V.RadialLayer(10., 0., 3., budget=collar._budget).record(),
            geometry_volume_enclosure_m3=[enc(1), enc(1)]))
    funding_meta = dict(schema='atlas.full-cell-collar-funding.v1', source=source,
        owner_id='2'*64, collar_plan_id=old['collar']['plan_id'], volume_map_id=collar._map.volume_map_id,
        native_initial_state_id='3'*64, time_s=0., cells=list(collar.cells), component_keys=[list(k) for k in keys],
        cell_geometries=[c.record() for c in cells], cell_accounts=cell_accounts, source_accounts=source_accounts,
        exterior_remainder=remainders, integration_request=dict(max_cell_volume_width_m3=enc(0),
            max_field_errors={k: enc(0) for k in S._STOCKS[1:]}, max_leaves=1),
        allocation='fixture:original exact partition', projection='fixture:original signed projection',
        inherited_geometry_scope='fixture only; no source acceptance claim', authority='fixture:already booked once',
        component_registry=collar._registry.record(), excluded_static_cells=[],
        basal_inventory=dict(schema='atlas.finite-basal-funding.v1', base_funding_id='1'*64,
            side='fixture', reservoirs=[], stocks=[finite_initial], exact_debits=[dict(
                source_key=list(keys[0]), cell_id='fixture:basal-cell', exact={k: enc(v) for k, v in basal_debit.items()})],
            disjointness='fixture:original certificate retained, not re-proved here',
            pressure_work='fixture:external declared boundary work', compartment_kind='reservoir'))
    funding = Snapshot(funding_meta, arrays)
    funding_record = dict(funding_id=funding.result_id, **funding.descriptor())
    finite_definition = dict(schema='atlas.finite-spatial-stocks.v1', registry_id=collar._registry.registry_id,
        field_names=list(names), nonnegative_fields=list(positive), initial_stocks=[finite_initial])
    finite_definition = dict(owner_id=N._hash(finite_definition), **finite_definition)
    owner = dict(schema='atlas.spatial-exterior-owner.v1', funding_id=funding.result_id,
        collar_plan_id=old['collar']['plan_id'], source=source, grid_id='4'*64, initial_mesh_id='5'*64,
        component_keys=[list(k) for k in keys], native_initial_state_id='3'*64, epoch_s=0.,
        method='implicit-upwind', heat_method=P.HEAT_METHODS['hybrid-mimetic'][0],
        projection_allowances={k: enc(Q(1, 1000)) for k in names},
        conductivity_w_m_k=native._material.conductivity_w_m_k,
        heat_capacity_j_kg_k=native._material.heat_capacity_j_kg_k,
        source_fields='initialise once; retain every spatial field thereafter',
        scope='finite funded common-rigid exterior and actual regional grid, not arbitrary global plate evolution',
        component_registry=collar._registry.record(), finite_stocks=finite_definition)
    owner = dict(owner_id=N._hash(owner), **owner)
    trajectory = dict(segments=[dict(fixture_interval=i) for i in (1, 2, 3)])
    trajectory_id = N._hash(trajectory['segments'])
    rows = []
    for i, key in enumerate(keys):
        exact = dict.fromkeys(names, Q(0))
        exact.update({'component_mass_kg:'+str(i): rho, 'enthalpy_j': rho*cp*Q(3, 2),
            'tracer:source_kappa': rho*Q(3, 4), 'tracer:accumulated_strain_ii': rho*Q(3, 8),
            'tracer:radial_plastic_kappa': rho*Q(1, 8)})
        rows.append(dict(cell_id='fixture:exterior:'+str(i), source_key=list(key), volume_m3=enc(1),
                         exact={k: enc(v) for k, v in exact.items()}))
    mesh = dict(schema='fixture:retained-thermal-mesh', funding_id=funding.result_id, grid_id='4'*64,
        support_id='6'*64, trajectory_id=trajectory_id, time_s=enc(Q(25, 2)),
        cells=[dict(kind='exterior', logical_cell_id=r['cell_id']) for r in rows])
    finite_evolved = deepcopy(finite_initial)
    finite_evolved['volume_m3'] = enc(Q(1, 16))
    finite_evolved['exact'] = {k: enc(v/2) for k, v in finite_fields.items()}
    finite_evolved['exact']['tracer:accumulated_strain_ii'] = enc(Q(1, 32))
    finite_evolved['exact']['tracer:radial_plastic_kappa'] = enc(Q(1, 64))
    finite_state = dict(schema='atlas.finite-spatial-stock-state.v1', owner_id=finite_definition['owner_id'],
        intervals=3, parent_state_id='7'*64, transport_id='8'*64, stocks=[finite_evolved],
        projection_accounts={finite_initial['stock_id']: {k: enc(Q(1, 10000)) for k in names}})
    finite_state = dict(state_id=N._hash(finite_state), **finite_state)
    spatial = dict(schema='atlas.spatial-exterior-state.v1', owner_id=owner['owner_id'], funding_id=funding.result_id,
        time_s=12.5, intervals=3, parent_state_id='9'*64,
        collar_state_id=transfer['input']['historical_collar']['result_id'], support_id='6'*64,
        trajectory_id=trajectory_id, trajectory=trajectory, grid_id='4'*64, thermal_mesh_id=N._hash(mesh),
        thermal_mesh=mesh, cells=rows, projection_accounts={k: enc(Q(1, 1000)) for k in names},
        finite_stock_state=finite_state)
    spatial_arrays = {k: np.array([float(S._q(r['exact'][k])) for r in rows]) for k in names}
    spatial_arrays['volume_m3'] = np.ones(len(rows))
    state = Snapshot(spatial, spatial_arrays)
    return dict(collar=collar, native_transfer=native_transfer,
        funding_record=funding_record, funding_arrays={k: funding.array(k) for k in funding.array_names},
        historical_owner_definition=owner, historical_spatial_record=dict(state_id=state.result_id, **state.descriptor()),
        spatial_arrays={k: state.array(k) for k in state.array_names},
        funding_binding=dict(funding_id=funding.result_id, debit_count=1, ledger_sha256='a'*64),
        origin=transfer['input']['origin'])


class SpatialTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.budget = WorkBudget(256 << 20)
        cls.guard = cls.budget.reserve(2 << 20, category='tiny-spatial-fixture-inputs')
        cls.guard.__enter__()
        cls.source = F.physical_source(cls.budget)
        cls.volume_map = F.physical_map(cls.source, cls.budget)
        cls.native = F.prepare(cls.source[4], cls.budget)
        keys = tuple(sorted(set(cls.source[3])))
        profile = Registry.native_profile(cls.native)
        cls.registry = Registry([dict(lineage=dict(kind='initial-patch-layer',
            source_id=cls.source[1].moving_id, patch_id=k[0], sublayer=k[1]), plate_id='fixture:plate',
            material_id='fixture:material', creep_law_id='fixture:creep', composition_value=float(i), profile=profile)
            for i, k in enumerate(keys)], budget=cls.budget)
        cls.collar = C.PreparedRegionalCollar3D(cls.native, cls.volume_map, ((0, 0),)*3,
            budget=cls.budget, component_registry=cls.registry, mechanics_scope='complete-grid')
        cls.current = N.current_plan_graph(cls.native, cls.collar)
        cls.old = deepcopy(cls.current)
        for name in N._NODES:
            if name != 'collar':
                cls.old[name]['definition']['execution'] = 'a'*64
        TN.rehash_graph(cls.old)

    @classmethod
    def tearDownClass(cls):
        cls.collar.close()
        cls.native.close()
        cls.source = cls.volume_map = cls.registry = None
        cls.guard.__exit__(None, None, None)
        gc.collect()

    def setUp(self):
        gc.collect()
        self.baseline = self.budget.reserved_bytes
        mass = np.full(self.native.cells, self.native._mass)
        arrays = dict(component_mass_kg=np.stack((mass*.75, mass*.25)), enthalpy_j=mass*1.5,
            **{'tracer:damage': mass*0., 'tracer:accumulated_strain_ii': mass*.375,
               'tracer:source_kappa': mass*.75, 'tracer:radial_plastic_kappa': mass*.125})
        meta = dict(schema='atlas.regional-evolution3d-state.v1', plan_id=self.old['native']['plan_id'],
            frame_id=self.native._frame, vertical_datum=self.native._datum, time_s=12.5,
            source='fixture:historical-endpoint', parent_state_id='b'*64,
            inventory='reference mass and sensible enthalpy m*cp*T',
            histories='mass-weighted scalar fields; no elastic tensor or free-surface state')
        native = Snapshot(meta, arrays)
        fields = Snapshot(dict(schema='atlas.regional-collar-fields.v1', plan_id=self.old['collar']['plan_id'],
            source_id='fixture:historical-funding', parent_id='c'*64, time_s=12.5), arrays)
        state = C.RegionalCollarState(fields, native)
        with N.admit_migrated_native_collar(native=self.native, collar=self.collar, historical_graph=self.old,
                historical_native=meta, historical_native_id=native.result_id,
                native_arrays={k: native.array(k) for k in native.array_names}, historical_collar=state.record(),
                collar_arrays=state.arrays(), origin=dict(producer_receipt_sha256='d'*64,
                    store_token_sha256='e'*64, endpoint_lineage_sha256='f'*64)) as lease:
            self.native_owned = lease.adopt()
        self.args = build_saved_fixture(self.collar, self.native_owned)
        self.native_baseline = self.budget.reserved_bytes

    def tearDown(self):
        self.args = self.native_owned = None
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_actual_owner_preserves_funding_evolved_fields_and_finite_history(self):
        original = deepcopy(self.args['historical_spatial_record'])
        with P.PreparedSpatialOwner.from_migrated_checkpoint(**self.args) as lease:
            result = lease.adopt()
        self.assertEqual(type(result.owner), P.PreparedSpatialOwner)
        self.assertEqual(type(result.state), P.SpatialExteriorState)
        self.assertEqual(result.funding.descriptor(), self.args['funding_record'])
        self.assertNotEqual(result.owner.owner_id, self.args['historical_owner_definition']['owner_id'])
        record = result.state.record()
        for key in original.keys()-{'state_id', 'owner_id', 'collar_state_id', 'parent_state_id'}:
            self.assertEqual(record[key], original[key], key)
        self.assertEqual(record['intervals'], 3)
        self.assertEqual(record['parent_state_id'], original['state_id'])
        self.assertEqual(record['collar_state_id'], self.native_owned.state.result_id)
        self.assertEqual(record['finite_stock_state'], original['finite_stock_state'])
        for name, array in self.args['spatial_arrays'].items():
            self.assertEqual(result.state.arrays()[name].tobytes(), array.tobytes())
        provenance = result.record()
        self.assertEqual(provenance['funding_binding']['debit_count'], 1)
        self.assertEqual(provenance['funding_debits_applied'], 0)
        self.assertFalse(provenance['continuation_authorised'])
        self.assertEqual(provenance['schema'], S.TRANSFER_SCHEMA)
        self.assertNotIn('historical_spatial_record', provenance)
        self.assertNotIn('current_spatial_record', provenance)
        self.assertNotIn('original_funding_record', provenance)
        self.assertEqual(provenance['historical_spatial_header'], {k: original[k] for k in S._STATE_HEADER})
        self.assertEqual(provenance['historical_spatial_metadata'],
            S._stream_stats({k: v for k, v in original.items() if k != 'state_id'})[0])
        self.assertTrue(S.snapshot_metadata_matches(result.state._snapshot, provenance['current_spatial_metadata']))
        recovered = dict(record)
        for key in provenance['changed_spatial_fields']:
            recovered[key] = provenance['historical_spatial_header'][key]
        self.assertEqual(recovered, original)
        # Actual ordinary snapshot wire/IDs are unchanged by the transfer-only
        # retained constructor; this is deliberately tiny, never production.
        ordinary = Snapshot({k: v for k, v in record.items() if k != 'state_id'}, result.state.arrays())
        self.assertEqual(ordinary.result_id, result.state.state_id)
        self.assertEqual(ordinary._metadata, result.state._snapshot._metadata)
        self.assertEqual(ordinary._fields, result.state._snapshot._fields)
        del ordinary
        self.assertEqual(self.budget.statistics()['categories'].get('spatial-transfer-scratch', 0), 0)
        result.owner.validate_parent(result.state, self.native_owned.state)
        with self.assertRaisesRegex(TectonicsError, 'no reseeded initial state'):
            result.owner.initial_state
        self.assertEqual(self.native.statistics()['accepted_intervals'], 0)
        result.owner.close()
        del result

    def test_compact_provenance_retains_one_mesh_and_validation_issues_no_copy(self):
        saved = deepcopy(self.args['historical_spatial_record'])
        # A synthetic opaque string tests volume independence, not geometry.
        saved['thermal_mesh']['fixture_volume_probe'] = 'x'*(1 << 20)
        saved['thermal_mesh_id'] = S._stream_hash(saved['thermal_mesh'])
        saved['state_id'] = S._snapshot_id({k: v for k, v in saved.items() if k != 'state_id'},
                                          S._bindings(self.args['spatial_arrays']))
        calls = []
        def observe(frame, event, argument):
            if event == 'call' and frame.f_code is P.PreparedSpatialOwner._issue.__code__:
                calls.append(frame.f_code.co_name)
        previous_profile = sys.getprofile()
        sys.setprofile(observe)
        try:
            with S.admit_migrated_spatial_owner(**dict(self.args, historical_spatial_record=saved)) as lease:
                result = lease.adopt()
        finally:
            sys.setprofile(previous_profile)
        self.assertEqual(calls, [])
        proof = result.record()
        payload = result.state._snapshot.nbytes+result.funding._snapshot.nbytes+len(result._record)
        self.assertLess(len(result._record), 32768)
        self.assertEqual(result.retained_bytes, payload+32768+4*N._width(proof['current_owner_definition'])
                         +1024*(len(self.args['funding_arrays'])+len(self.args['spatial_arrays'])))
        # The remaining allowance is entirely the explicit owner-definition
        # and field headers above; it is independent of the mesh probe size.
        self.assertLess(result.retained_bytes-payload, len(saved['thermal_mesh']['fixture_volume_probe']))
        self.assertEqual(self.budget.statistics()['categories'].get('spatial-transfer-codec-scratch', 0), 0)
        print('compact-v2 fixture: metadata=', len(result.state._snapshot._metadata),
              'provenance=', len(result._record), 'retained=', result.retained_bytes,
              'payload=', payload)
        current = result.state.record()
        full = result.owner.restore(current, result.state.arrays())
        compact = result.owner.restore(current, result.state.arrays(), _validate_only=True)
        self.assertEqual(compact['state_id'], full.state_id)
        self.assertEqual(compact['metadata'], S._stream_stats(full._snapshot.descriptor())[0])
        wrong = dict(result.state.arrays())
        wrong['enthalpy_j'] = wrong['enthalpy_j'].copy()+1
        for compact_only in (False, True):
            with self.assertRaisesRegex(TectonicsError, 'projected arrays disagree'):
                result.owner.restore(current, wrong, _validate_only=compact_only)
        del full, compact, current, wrong
        result.owner.close()
        del result

    def test_old_root_restore_remains_strict(self):
        with S.admit_migrated_spatial_owner(**self.args) as lease:
            result = lease.adopt()
        with self.assertRaisesRegex(TectonicsError, 'source/owner/field'):
            result.owner.restore(self.args['historical_spatial_record'], self.args['spatial_arrays'])
        result.owner.close()
        del result

    def test_escaped_spatial_and_original_funding_buffers_keep_charge(self):
        with S.admit_migrated_spatial_owner(**self.args) as lease:
            result = lease.adopt()
        escaped = result.state.arrays()['enthalpy_j'][:1]
        original_funding_buffer = result.funding.arrays()['component_mass_kg'][:, :1]
        result.owner.close()
        del result
        gc.collect()
        self.assertGreater(self.budget.reserved_bytes, self.native_baseline)
        self.assertEqual(self.budget.statistics()['categories'].get('spatial-transfer-scratch', 0), 0)
        del escaped
        gc.collect()
        self.assertGreater(self.budget.reserved_bytes, self.native_baseline)
        del original_funding_buffer
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.native_baseline)

    def test_identity_count_origin_and_owner_contract_fail_closed(self):
        mutations = []
        for key, value in (('debit_count', 0), ('debit_count', 2), ('funding_id', '0'*64)):
            mutations.append(dict(self.args, funding_binding=dict(self.args['funding_binding'], **{key: value})))
        mutations.append(dict(self.args, origin=dict(self.args['origin'], store_token_sha256='0'*64)))
        changed = deepcopy(self.args['historical_owner_definition'])
        changed['heat_capacity_j_kg_k'] = 7.
        changed['owner_id'] = N._hash({k: v for k, v in changed.items() if k != 'owner_id'})
        mutations.append(dict(self.args, historical_owner_definition=changed))
        fields = dict(self.args['spatial_arrays'])
        fields['enthalpy_j'] = fields['enthalpy_j'].copy()
        fields['enthalpy_j'][0] += 1
        mutations.append(dict(self.args, spatial_arrays=fields))
        for arguments in mutations:
            with self.assertRaises(N.TransferRefused):
                S.admit_migrated_spatial_owner(**arguments)

    def test_actual_spatial_validation_refuses_negative_stock_and_held_error_is_charged(self):
        changed = deepcopy(self.args['historical_spatial_record'])
        changed['cells'][0]['exact']['tracer:radial_plastic_kappa'] = enc(-1)
        fields = {k: a.copy() for k, a in self.args['spatial_arrays'].items()}
        fields['tracer:radial_plastic_kappa'][0] = -1
        changed['state_id'] = N._snapshot_id({k: v for k, v in changed.items() if k != 'state_id'}, S._bindings(fields))
        held = None
        try:
            S.admit_migrated_spatial_owner(**dict(self.args, historical_spatial_record=changed, spatial_arrays=fields))
        except TectonicsError as error:
            held = error
        self.assertIsNotNone(held)
        gc.collect()
        self.assertGreater(self.budget.statistics()['categories'].get('spatial-transfer-scratch', 0), 0)
        held = None
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.native_baseline)

    def test_original_funding_equation_refused_even_after_consistent_rehash(self):
        changed = deepcopy(self.args['funding_record'])
        changed['source_accounts'][0]['source']['mass_kg'] = enc(999)
        changed['funding_id'] = N._snapshot_id({k: v for k, v in changed.items() if k != 'funding_id'}, S._bindings(self.args['funding_arrays']))
        # Direct algebra test avoids making up a new accepted spatial lineage.
        with self.assertRaisesRegex(N.TransferRefused, 'source = debit'):
            S._funding_equations(changed, self.args['funding_arrays'], self.collar,
                                self.native_owned.record()['input']['compatibility'])

    def test_budget_refusal_and_exact_patch_base(self):
        from atlas_tectonics.resources import MemoryLimitError
        with self.budget.reserve(self.budget.available_bytes-1024, category='fixture-pressure'):
            with self.assertRaises(MemoryLimitError):
                S.admit_migrated_spatial_owner(**self.args)
        source = (TN.BASE/'integration_spatial_owner.py').read_text(encoding='utf-8')
        with self.assertRaises(N.TransferRefused):
            S.spatial_owner_source(S.spatial_owner_source(source))

    def test_optional_validation_seams_preserve_ordinary_ast(self):
        import ast
        source = (TN.BASE/'integration_spatial_owner.py').read_text(encoding='utf-8')
        original = ast.parse(source)
        changed = ast.parse(S.spatial_owner_source(source))
        original_owner = next(n for n in original.body if isinstance(n, ast.ClassDef) and n.name == 'PreparedSpatialOwner')

        class RemoveOptionalSeams(ast.NodeTransformer):
            def visit_ClassDef(self, node):
                if node.name == 'PreparedSpatialOwner':
                    node.body = [n for n in node.body if not isinstance(n, ast.FunctionDef)
                                 or n.name != 'from_migrated_checkpoint']
                return self.generic_visit(node)

            def visit_FunctionDef(self, node):
                if node.name == 'initial_state':
                    return next(n for n in original_owner.body if isinstance(n, ast.FunctionDef) and n.name == node.name)
                if node.name in ('restore', 'validate_parent'):
                    node.args.kwonlyargs = []
                    node.args.kw_defaults = []
                return self.generic_visit(node)

            def visit_If(self, node):
                if isinstance(node.test, ast.Name) and node.test.id == '_validate_only':
                    return []
                if isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) and node.test.left.id == '_migrated_record':
                    return ast.parse('r = self._bound(state)').body
                return self.generic_visit(node)

            def visit_Name(self, node):
                if node.id == 'mesh_hash':
                    node.id = '_hash'
                elif node.id == 'time_s' and isinstance(node.ctx, ast.Load):
                    return ast.Attribute(value=ast.Name(id='state', ctx=ast.Load()), attr='time_s', ctx=ast.Load())
                return node

        # Transform only the two changed methods: other unrelated time_s names
        # in the module must remain byte/AST-equivalent as well.
        changed_owner = next(n for n in changed.body if isinstance(n, ast.ClassDef) and n.name == 'PreparedSpatialOwner')
        strip = RemoveOptionalSeams()
        changed_owner.body = [n for n in changed_owner.body if not isinstance(n, ast.FunctionDef)
                              or n.name != 'from_migrated_checkpoint']
        changed_owner.body = [strip.visit(n) if isinstance(n, ast.FunctionDef) and
            n.name in ('initial_state', 'restore', 'validate_parent') else n for n in changed_owner.body]
        self.assertEqual(ast.dump(original, include_attributes=False), ast.dump(changed, include_attributes=False))


if __name__ == '__main__':
    unittest.main(verbosity=2)
