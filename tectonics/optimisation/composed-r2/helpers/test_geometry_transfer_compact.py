"""Compact parent geometry transfer on actual tiny native/spatial owners.

Native/collar, funding and spatial owners use their actual constructors. The
parent partition is test_partition_tables' native-schema fixture carrying the
synthetic historical header of test_geometry_transfer_integration: SYNTHETIC
TEST INPUTS, not a historical-reader or scientific acceptance receipt. No
physical solve, workflow or real store is used. The temporary package is
composed from frozen bytes as partition_native_patch -> endpoint seam (staged)
-> geometry_transfer(compact=True), and the coupling as partition_native_patch
-> continuation_transfer. Other modules import install()/CompactParentFixture.
"""
import ast
from concurrent.futures import CancelledError
from copy import deepcopy
from fractions import Fraction as Q
import gc
from hashlib import sha256
import importlib
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import continuation_transfer as X
import geometry_transfer as G
import native_transfer as N
import spatial_transfer as S
import test_geometry_transfer_integration as TG
import test_native_transfer as TN
import test_spatial_transfer as TS


HERE = Path(__file__).resolve().parent
COMPACT = HERE/'compact-geometry-r1'
SEAM = HERE/'endpoint-checkpoints'/'patch_endpoint_seam.py'
# Stage digests (string bytes) of the reviewed chain, recorded in w1a.json.
PARTITION_READER_SHA256 = '29443f86c8dce100af71072426f9848a5cc7ed4f20cbbb323d98a6ec0c725924'
ENDPOINT_READER_SHA256 = '213d1ebb5ef4d072f65ae3c08b99a4537f61985e46fe802e54c58a1b6ac471fd'
GEOMETRY_COMPACT_SHA256 = 'fc9dd85e002fe54db6e409ebe89083996f62611c40d958a5a1e60184f3424253'
GEOMETRY_LEGACY_SHA256 = 'ab635657d381ee59743d7b36bf21d5be6d5f96d6ea6aa361b159676aff56dde5'
HEADER = ('source', 'funding_id', 'collar_plan_id', 'interval_id', 'parent_network_id',
          'endpoint_network_id', 'trajectory_id', 'start_time_s', 'end_time_s')
_temporary = None
_old_path = None
STAGES = {}


def _digest(text):
    return sha256(text.encode('utf8')).hexdigest()


def _seam():
    spec = importlib.util.spec_from_file_location('w1a_patch_endpoint_seam', SEAM)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def staged_seam(geometry_text):
    """Endpoint seam reads package files: stage this text beside frozen batch."""
    with tempfile.TemporaryDirectory(prefix='seam-', dir=Path(_temporary.name)) as staging:
        (Path(staging)/'integration_differential_geometry.py').write_bytes(geometry_text.encode('utf8'))
        shutil.copyfile(TN.BASE/'integration_component_volume_batch.py',
                        Path(staging)/'integration_component_volume_batch.py')
        return _seam().candidate_sources(staging)


def compose(package, PN):
    for name, patch in (('regional_execution.py', N.retained_snapshot_source),
                        ('integration_spatial_owner.py', S.spatial_owner_source)):
        path = package/name
        path.write_bytes(patch(path.read_text(encoding='utf8')).encode('utf8'))
    frozen = (TN.BASE/'integration_differential_geometry.py').read_text(encoding='utf8')
    reader = PN.transform(frozen)
    sources = staged_seam(reader)
    endpoint = sources['integration_differential_geometry.py']
    sources['integration_differential_geometry.py'] = G.transform(endpoint, compact=True)
    for name, text in sources.items():
        (package/name).write_bytes(text.encode('utf8'))
    coupling = PN.transform_coupling((TN.BASE/'integration_differential_coupling.py').read_text(encoding='utf8'))
    composed = X.coupling_source(coupling)
    (package/'integration_differential_coupling.py').write_bytes(composed.encode('utf8'))
    return {'partition_reader': _digest(reader), 'endpoint_reader': _digest(endpoint),
            'geometry_compact': _digest(sources['integration_differential_geometry.py']),
            'coupling_reader': _digest(coupling), 'coupling_compact': _digest(composed)}


def install(prefix):
    """Compose and import the temporary package once, in a clean process."""
    global _temporary, _old_path, D, PN, PT, M, T, RES, CR, WorkBudget, MemoryLimitError, VolumeError
    if any(k == 'atlas_tectonics' or k.startswith('atlas_tectonics.') for k in sys.modules):
        raise RuntimeError('clean process required; no loaded runtime replacement')
    _old_path = list(sys.path)
    sys.path.insert(0, str(COMPACT))
    PN = importlib.import_module('partition_native_patch')
    _temporary = tempfile.TemporaryDirectory(prefix=prefix, dir=HERE)
    root = Path(_temporary.name)
    package = root/'atlas_tectonics'
    shutil.copytree(TN.BASE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    STAGES.update(compose(package, PN))
    integration = HERE.parent/'runtime-integration-r1'
    sys.path[:0] = [str(root), str(integration/'ram'), str(integration/'helpers'),
                   str(TN.HEAT_TESTS.parents[2]), str(TN.HEAT_TESTS)]
    D = importlib.import_module('atlas_tectonics.integration_differential_geometry')
    CR = importlib.import_module('atlas_tectonics.regional_collar3d')
    RES = importlib.import_module('atlas_tectonics.integration_spatial_reservoir')
    resources = importlib.import_module('atlas_tectonics.resources')
    WorkBudget, MemoryLimitError = resources.WorkBudget, resources.MemoryLimitError
    VolumeError = importlib.import_module('atlas_tectonics.integration_volume').VolumeError
    # Existing fixture builders only; these populate test-helper globals.
    TS.F = importlib.import_module('test_i04_regional_owner')
    TS.C = CR
    TS.P = importlib.import_module('atlas_tectonics.integration_spatial_owner')
    TS.Snapshot = importlib.import_module('atlas_tectonics.regional_execution').RegionalMechanicalSnapshot
    TS.WorkBudget = WorkBudget
    TS.Registry = importlib.import_module('atlas_tectonics.integration_regional_inventory').ComponentRegistry
    TS.enc = importlib.import_module('atlas_tectonics.integration_mimetic_heat')._enc
    TS.TectonicsError = importlib.import_module('atlas_tectonics._validation').TectonicsError
    TG.D = D
    # After the composed package is loaded: its atlas_tectonics is reused.
    T = importlib.import_module('test_partition_tables')
    PT = importlib.import_module('partition_tables')
    M = importlib.import_module('mesh_tables')


def uninstall():
    global _temporary
    if _old_path is not None:
        sys.path[:] = _old_path
    if _temporary is not None:
        assert Path(_temporary.name).resolve().parent == HERE
        _temporary.cleanup()
        _temporary = None


def setUpModule():
    install('gtc-')


def tearDownModule():
    uninstall()


def rehash_supports(body, supports):
    body['support_ids'] = [D._record_hash(row) for row in supports]
    for contact, ident in zip(body['native_contacts'][0]['contacts'], body['support_ids'], strict=True):
        contact['support_id'] = ident
    return body


def historical_parent(budget, legacy):
    """Native-schema body with the synthetic historical header; carried charts only."""
    body, supports = T.tiny_partition(budget)
    for support in supports:
        # A fixed exclusion cannot be advected into a carried material chart.
        support['components'][0]['constraints'] = [['carried:edge', 1], ['normal', -1]]
    for name in HEADER:
        body[name] = deepcopy(legacy[name])
    return rehash_supports(body, supports), supports


def foreign_parent(body, supports):
    """Identical header fields; one support changed, so the body is rehashed."""
    supports = deepcopy(supports)
    supports[0]['work_units'] += 1
    return rehash_supports(deepcopy(body), supports), supports


def compact(body, supports, budget, *, check=lambda: None):
    identity = D._record_hash(body)
    metadata, arrays = PT.pack_partition(body, iter(supports), expected_partition_id=identity, budget=budget)
    return PT.CompactPartition(metadata, arrays, expected_partition_id=identity, budget=budget, check=check)


def descriptor(body, supports):
    return dict(partition_id=D._record_hash(body), **deepcopy(body), supports=deepcopy(supports))


class CompactParentFixture:
    """Actual tiny native transfer, collar, funding and evolved interval."""
    @classmethod
    def setUpClass(cls):
        TS.SpatialTransferTests.setUpClass()
        cls.budget = TS.SpatialTransferTests.budget

    @classmethod
    def tearDownClass(cls):
        TS.SpatialTransferTests.tearDownClass()
        TS.SpatialTransferTests.collar = TS.SpatialTransferTests.native = None
        TS.SpatialTransferTests.old = TS.SpatialTransferTests.current = None
        gc.collect()
        if cls.budget.reserved_bytes:
            raise AssertionError(cls.budget.statistics())

    def setUp(self):
        self.fixture = TS.SpatialTransferTests('test_old_root_restore_remains_strict')
        self.fixture.setUp()
        self.collar = self.fixture.collar
        with S.admit_migrated_spatial_owner(**self.fixture.args) as lease:
            self.spatial = lease.adopt()
        self.funding = self.spatial.funding
        self.geometry, legacy = TG.synthetic_geometry_and_partition(spatial=self.spatial,
            collar=self.collar, native_transfer=self.fixture.native_owned, budget=self.budget)
        self.body, self.supports = historical_parent(self.budget, legacy)
        del legacy
        gc.collect()
        self.baseline = self.budget.reserved_bytes

    def tearDown(self):
        self.spatial.owner.close()
        self.spatial = self.funding = self.geometry = self.collar = None
        self.body = self.supports = None
        gc.collect()
        self.fixture.tearDown()
        self.fixture = None

    def operands(self, **changes):
        return dict(dict(funding=self.funding, collar=self.collar, budget=self.budget), **changes)

    def bind(self, view, **changes):
        return G.bind_parent_geometry_compact(**dict(dict(native_transfer=self.fixture.native_owned,
            compact_partition=view, geometry=self.geometry, funding=self.funding,
            collar=self.collar, budget=self.budget), **changes))

    def bind_dict(self, body=None, supports=None, **changes):
        record = descriptor(self.body if body is None else body, self.supports if supports is None else supports)
        return G.bind_parent_geometry(**dict(dict(native_transfer=self.fixture.native_owned,
            partition_descriptor=record, geometry=self.geometry, funding=self.funding,
            collar=self.collar, budget=self.budget), **changes))

    def admit(self, view, transfer=None, **changes):
        operands = dict(dict(funding=self.funding, collar=self.collar, geometry=self.geometry,
                             budget=self.budget), **changes)
        return D.DifferentialPartition.from_compact(view, operands['funding'], operands['collar'],
            operands['geometry'], budget=operands['budget'], _runtime_transfer=transfer)

    def restore(self, transfer=None, body=None, supports=None):
        record = descriptor(self.body if body is None else body, self.supports if supports is None else supports)
        return D.DifferentialPartition.restore(record, self.funding, self.collar, self.geometry,
                                               budget=self.budget, _runtime_transfer=transfer)

    def prepare(self, parent, transfer):
        """Actual, unpatched prepare_interval_partition up to chart assembly.

        The real collar's verify() refuses monkeypatched runtime callables, so
        nothing is intercepted. The tiny parent's chart is not a physical grid:
        _assemble_partition refuses it, and its frame's received arguments are
        returned with the error. None means assembly was never reached.
        """
        finite = RES.PreparedFiniteStocks(T.ident('registry'), [dict(stock_id='sink', kind='sink',
            lineage={'fixture': 'finite restore control'}, volume_m3=T.q(1), exact={'mass': T.q(1)})],
            field_names=('mass',), nonnegative_fields=('mass',), budget=self.budget)
        try:
            step = dict(parent_network_id=self.body['endpoint_network_id'],
                prior_trajectory_id=self.body['trajectory_id'], start_time_s=self.body['end_time_s'],
                end_time_s=TS.enc(13), duration_s=TS.enc(Q(1, 2)),
                plate_angular_velocity_rad_s={'plate:A': [T.q(0)]*3}, boundary_paths=[])
            interval = D._issue(D.DifferentialInterval, step, self.budget)
            try:
                D.prepare_interval_partition(parent, interval, self.funding, object(), self.collar,
                    finite_stock_state=finite.initial(), max_components=1000, budget=self.budget,
                    _runtime_transfer=transfer)
            except Exception as error:
                return assembly_arguments(error)
            raise AssertionError('synthetic tiny chart unexpectedly assembled')
        finally:
            finite.close()


def assembly_arguments(error):
    """Copy the arguments _assemble_partition received; drop the traceback."""
    tb, arguments = error.__traceback__, None
    while tb is not None:
        if tb.tb_frame.f_code is D._assemble_partition.__code__:
            local = tb.tb_frame.f_locals
            arguments = (D._encoded(local['regions']), local['grid_lines'], local['max_components'],
                         local['parent_partition'].partition_id)
            del local
        tb = tb.tb_next
    return arguments, type(error), str(error)


class CompactTransformSourceTests(unittest.TestCase):
    def test_compact_transform_composition_and_exact_change_set(self):
        frozen = (TN.BASE/'integration_differential_geometry.py').read_text(encoding='utf8')
        reader = PN.transform(frozen)
        endpoint = staged_seam(reader)['integration_differential_geometry.py']
        composed = G.transform(endpoint, compact=True)
        compile(composed, 'compact-geometry-transfer', 'exec')
        self.assertEqual((_digest(reader), _digest(endpoint), _digest(composed)),
                         (PARTITION_READER_SHA256, ENDPOINT_READER_SHA256, GEOMETRY_COMPACT_SHA256))
        self.assertEqual(STAGES['geometry_compact'], GEOMETRY_COMPACT_SHA256)
        # The endpoint seam and the compact transfer edit disjoint text.
        self.assertEqual(staged_seam(G.transform(reader, compact=True))['integration_differential_geometry.py'],
                         composed)
        # Ordinary transform bytes are unchanged; wrong order/input refuses.
        self.assertEqual(_digest(G.transform(frozen)), GEOMETRY_LEGACY_SHA256)
        for source, flag in ((frozen, True), (reader, False), (endpoint, False), (composed, True)):
            with self.subTest(source=_digest(source)[:12], compact=flag):
                with self.assertRaises(G.GeometryTransferRefused):
                    G.transform(source, compact=flag)
        with self.assertRaises(ValueError):
            PN.transform(staged_seam(frozen)['integration_differential_geometry.py'])
        self.assertEqual(composed.count(G.PARTITION_READER_MARKER), 1)
        tree = ast.parse(composed)
        helpers = [tree.body.pop(), tree.body.pop()]
        self.assertEqual([h.name for h in helpers], ['_transferred_partition_binding', '_transferred_collar_binding'])
        names, calls = [], []
        for node in ast.walk(tree):
            # from_compact already carries _runtime_transfer from the reader seam.
            if isinstance(node, ast.FunctionDef) and node.name in ('restore', 'prepare_interval_partition'):
                for at, argument in enumerate(node.args.kwonlyargs):
                    if argument.arg == '_runtime_transfer':
                        self.assertIsNone(node.args.kw_defaults[at].value)
                        del node.args.kwonlyargs[at]
                        del node.args.kw_defaults[at]
                        names.append(node.name)
                        break
            if isinstance(node, ast.BoolOp):
                for at, value in enumerate(node.values):
                    if not (isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not)
                            and isinstance(value.operand, ast.Call)):
                        continue
                    name = ast.unparse(value.operand.func)
                    arguments = [ast.unparse(x) for x in value.operand.args]
                    if name == '_transferred_collar_binding':
                        self.assertEqual(arguments, ['body', 'funding', 'collar', 'budget', '_runtime_transfer'])
                        original = "body.get('collar_plan_id') != collar.plan_id"
                    elif name == '_transferred_partition_binding':
                        self.assertEqual(arguments, ['parent_partition', 'old', 'funding', 'collar', 'budget',
                                                     '_runtime_transfer'])
                        original = "old['collar_plan_id'] != collar.plan_id"
                    else:
                        continue
                    calls.append(name)
                    node.values[at] = ast.parse(original, mode='eval').body
        self.assertEqual(sorted(names), ['prepare_interval_partition', 'restore'])
        self.assertEqual(sorted(calls), ['_transferred_collar_binding', '_transferred_partition_binding'])
        self.assertEqual(ast.dump(ast.parse(endpoint)), ast.dump(tree))


class CompactGeometryTransferTests(CompactParentFixture, unittest.TestCase):
    def test_compact_binding_record_equals_dict_binding_record(self):
        view = compact(self.body, self.supports, self.budget)
        legacy = self.bind_dict()
        binding = self.bind(view)
        self.assertIs(type(binding), G.ParentGeometryTransfer)
        self.assertEqual(binding.record(), legacy.record())
        self.assertEqual(bytes(binding._record), bytes(legacy._record))
        record = binding.record()
        self.assertEqual(record['historical_partition_id'], view.partition_id)
        self.assertEqual(record['historical_partition_id'], D._record_hash(self.body))
        self.assertNotEqual(record['historical_collar_plan_id'], self.collar.plan_id)
        self.assertEqual(record['current_collar_plan_id'], self.collar.plan_id)
        self.assertEqual(record['native_transfer_id'], self.fixture.native_owned.transfer_id)
        self.assertFalse(record['scientific_acceptance'])
        self.assertEqual(self.collar._native.statistics()['accepted_intervals'], 0)
        categories = self.budget.statistics()['categories']
        for name in ('binding', 'compact-parent', 'contract', 'fields'):
            self.assertEqual(categories.get('geometry-transfer-'+name+'-scratch', 0), 0, name)
        del view, legacy, binding
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_bind_compact_refuses_rehashed_fields_and_wrong_types(self):
        for name, value in (('source', dict(self.body['source'], fixture='another-source')),
                            ('funding_id', '0'*64), ('collar_plan_id', '1'*64),
                            ('end_time_s', TS.enc(13)), ('interval_id', '2'*64),
                            ('trajectory_id', '3'*64), ('endpoint_network_id', '4'*64),
                            ('scope', 'initial-current')):
            view = compact(dict(deepcopy(self.body), **{name: value}), self.supports, self.budget)
            with self.subTest(field=name):
                with self.assertRaises(G.GeometryTransferRefused):
                    self.bind(view)
            del view
        view = compact(self.body, self.supports, self.budget)
        unsealed = object.__new__(PT.CompactPartition)
        other = WorkBudget(1 << 20)
        for case, changes in (('unsealed', dict(compact_partition=unsealed)),
                              ('legacy dict', dict(compact_partition=descriptor(self.body, self.supports))),
                              ('another budget', dict(budget=other)),
                              ('not a native transfer', dict(native_transfer=object()))):
            with self.subTest(case=case):
                with self.assertRaises(G.GeometryTransferRefused):
                    self.bind(view, **changes)
        self.assertEqual(other.reserved_bytes, 0)
        # Deliberately inconsistent provenance in a NEGATIVE fixture only.
        bad = self.fixture.native_owned.record()
        bad['current_collar']['fields']['time_s'] = 99.
        bad_transfer = N.OwnedMigratedNativeCollar(self.fixture.native_owned.state, N._json(bad))
        with self.assertRaises(G.GeometryTransferRefused):
            self.bind(view, native_transfer=bad_transfer)
        del bad_transfer
        # Rehash BOTH geometry and parent at another time: the migrated native
        # clock is still 12.5 and binds independently of the parent header.
        moved = D._issue(D.DifferentialInterval, dict(self.geometry.record(), end_time_s=TS.enc(13)), self.budget)
        shifted = compact(dict(deepcopy(self.body), interval_id=moved.interval_id, end_time_s=TS.enc(13)),
                          self.supports, self.budget)
        with self.assertRaises(G.GeometryTransferRefused):
            self.bind(shifted, geometry=moved)
        del moved, shifted, view, unsealed
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_foreign_parent_with_identical_header_refused(self):
        view = compact(self.body, self.supports, self.budget)
        body_b, supports_b = foreign_parent(self.body, self.supports)
        foreign = compact(body_b, supports_b, self.budget)
        self.assertNotEqual(foreign.partition_id, view.partition_id)
        fields = G.PARENT_COMPACT_FIELDS
        self.assertEqual(PN._view_fields(view, view.root(), fields).value,
                         PN._view_fields(foreign, foreign.root(), fields).value)
        binding = self.bind(view)
        self.assertFalse(binding.matches_compact(foreign, **self.operands()))
        self.assertFalse(G.collar_binding_matches_compact(foreign, self.funding, self.collar, self.budget, binding))
        with self.assertRaises(VolumeError):
            self.admit(foreign, binding)
        self.assertTrue(binding.matches_compact(view, **self.operands()))
        # Matching is by content, not representation: each binding admits the
        # same parent through the other route, never the foreign one.
        legacy = self.bind_dict()
        self.assertTrue(legacy.matches_compact(view, **self.operands()))
        self.assertFalse(legacy.matches_compact(foreign, **self.operands()))
        for token in (binding, legacy):
            part = self.admit(view, token)
            self.assertEqual(part.partition_id, view.partition_id)
            restored = self.restore(token)
            self.assertEqual(restored.partition_id, view.partition_id)
            del part, restored
        with self.assertRaises(VolumeError):
            self.restore(binding, body=body_b, supports=supports_b)
        del view, foreign, binding, legacy, token
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_mismatched_funding_collar_budget_refused_without_foreign_charge(self):
        view = compact(self.body, self.supports, self.budget)
        binding = self.bind(view)
        with S.admit_migrated_spatial_owner(**self.fixture.args) as lease:
            separate = lease.adopt()
        self.assertEqual(separate.funding.funding_id, self.funding.funding_id)
        # A genuinely prepared different plan, not a mutated executing plan.
        other_collar = CR.PreparedRegionalCollar3D(self.collar._native, self.collar._map, ((0, 0),)*3,
            budget=self.budget, mechanics_scope='complete-grid')
        self.assertNotEqual(other_collar.plan_id, self.collar.plan_id)
        other = WorkBudget(1 << 20)
        foreign_view = compact(self.body, self.supports, other)
        held = other.reserved_bytes
        try:
            mismatches = (dict(funding=separate.funding), dict(collar=other_collar), dict(budget=other))
            refusal = AssertionError('allocation before owner identity refusal')
            with mock.patch.object(N, '_Allocation', side_effect=refusal), \
                    mock.patch.object(M, '_Allocation', side_effect=refusal):
                for changes in mismatches:
                    with self.subTest(owner=sorted(changes)):
                        self.assertFalse(binding.matches_compact(view, **self.operands(**changes)))
                self.assertFalse(binding.matches_compact(foreign_view, **self.operands()))
                self.assertFalse(binding.matches_compact(foreign_view, **self.operands(budget=other)))
                self.assertFalse(G.collar_binding_matches_compact(view, self.funding, self.collar, other, binding))
                self.assertFalse(G.collar_binding_matches_compact(foreign_view, self.funding, self.collar,
                                                                  self.budget, binding))
            for changes in mismatches:
                with self.subTest(admission=sorted(changes)):
                    with self.assertRaises(VolumeError):
                        self.admit(view, binding, **changes)
            for changes in (dict(collar=other_collar), dict(budget=other), dict(compact_partition=foreign_view)):
                with self.subTest(bind=sorted(changes)):
                    with self.assertRaises(G.GeometryTransferRefused):
                        self.bind(view, **changes)
            self.assertEqual(other.reserved_bytes, held)
        finally:
            other_collar.close()
            separate.owner.close()
        del foreign_view, changes, mismatches
        gc.collect()
        self.assertEqual(other.reserved_bytes, 0)
        del separate, other_collar, view, binding
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_compact_paths_never_export_whole_body(self):
        view = compact(self.body, self.supports, self.budget)
        root, regions = view.root().index, view.root().field('source_regions').index
        export = PT.CompactPartition.legacy_record
        def selected_only(instance, ref=None):
            if ref is None or ref.index in (root, regions):
                raise AssertionError('whole partition/source-region export forbidden')
            return export(instance, ref)
        # Runtime callables stay unpatched (collar verify() refuses that); the
        # composed compact record()/descriptor() raise VolumeError if reached.
        with mock.patch.object(PT.CompactPartition, 'legacy_record', selected_only):
            binding = self.bind(view)
            self.assertTrue(binding.matches_compact(view, **self.operands()))
            part = self.admit(view, binding)
            arguments, kind, message = self.prepare(part, binding)
        self.assertIsNotNone(arguments, (kind, message))
        self.assertEqual(arguments[3], view.partition_id)
        with self.assertRaises(VolumeError):
            part.record()
        del view, binding, part, arguments
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_budget_pressure_refuses_before_decode(self):
        view = compact(self.body, self.supports, self.budget)
        native = self.fixture.native_owned
        required = G._binding_scratch_bytes(native, self.collar)
        with self.budget.reserve(self.budget.available_bytes-required+1, category='fixture-pressure'):
            with mock.patch.object(N.OwnedMigratedNativeCollar, 'record',
                                   side_effect=AssertionError('unadmitted native JSON decode')) as decode:
                with self.assertRaises(MemoryLimitError):
                    self.bind(view)
                decode.assert_not_called()
        binding = self.bind(view)
        required = G._matches_compact_scratch_bytes(binding, self.collar)
        self.assertLess(required, G._matches_scratch_bytes(binding, self.body, self.collar))
        with self.budget.reserve(self.budget.available_bytes-required+1, category='fixture-pressure'):
            with mock.patch.object(N.OwnedMigratedNativeCollar, 'record',
                                   side_effect=AssertionError('unadmitted matching decode')) as decode, \
                    mock.patch.object(G.ParentGeometryTransfer, 'record',
                                      side_effect=AssertionError('unadmitted binding decode')) as own:
                with self.assertRaises(MemoryLimitError):
                    binding.matches_compact(view, **self.operands())
                decode.assert_not_called()
                own.assert_not_called()
        self.assertTrue(binding.matches_compact(view, **self.operands()))
        stats = self.budget.statistics()
        for category in ('binding', 'match', 'contract', 'fields', 'compact-parent'):
            name = 'geometry-transfer-'+category+'-scratch'
            self.assertGreater(stats['category_peaks'][name], 0, name)
            self.assertEqual(stats['categories'].get(name, 0), 0, name)
        del view, binding
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_held_refusal_retains_scratch_then_zero(self):
        view = compact(dict(deepcopy(self.body), funding_id='0'*64), self.supports, self.budget)
        held = None
        try:
            self.bind(view)
        except G.GeometryTransferRefused as error:
            held = error
        self.assertIsNotNone(held)
        gc.collect()
        categories = self.budget.statistics()['categories']
        self.assertGreater(categories.get('geometry-transfer-binding-scratch', 0), 0)
        self.assertGreaterEqual(categories.get('geometry-transfer-compact-parent-scratch', 0),
            G._json_decode_bytes(self.funding._snapshot._metadata)+G._json_decode_bytes(self.geometry._json))
        held = None
        gc.collect()
        categories = self.budget.statistics()['categories']
        for name in ('binding', 'compact-parent'):
            self.assertEqual(categories.get('geometry-transfer-'+name+'-scratch', 0), 0, name)
        del view
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_lifetime_and_zero_final_reservations(self):
        retained = 'geometry-transfer-binding-retained'
        self.assertEqual(self.budget.statistics()['categories'].get(retained, 0), 0)
        view = compact(self.body, self.supports, self.budget)
        binding = self.bind(view)
        part = self.admit(view, binding)
        self.assertIs(part.compact_view(), view)
        expected = len(binding._record)+4096
        self.assertEqual(self.budget.statistics()['categories'][retained], expected)
        with self.assertRaises(G.GeometryTransferRefused):
            binding._funding = None
        escaped = binding._record
        del part, binding
        gc.collect()
        self.assertEqual(self.budget.statistics()['categories'].get('compact-partition-native-wrapper', 0), 0)
        self.assertEqual(self.budget.statistics()['categories'][retained], expected)
        del escaped
        gc.collect()
        self.assertEqual(self.budget.statistics()['categories'].get(retained, 0), 0)
        del view
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_cancellation_during_streamed_identity(self):
        calls = [0, None]
        def check():
            calls[0] += 1
            if calls[1] is not None and calls[0] >= calls[1]:
                raise CancelledError('fixture cancellation inside identity stream')
        view = compact(self.body, self.supports, self.budget, check=check)
        entries, stream = [], G._streamed_body_id
        def spy(value):
            entries.append(calls[0])
            return stream(value)
        with mock.patch.object(G, '_streamed_body_id', spy):
            calls[0] = 0
            binding = self.bind(view)
            # Re-run the same bind, cancelling at the first streamed body node.
            calls[0], calls[1] = 0, entries[0]+1
            held = None
            try:
                self.bind(view)
            except CancelledError as error:
                held = error
        self.assertIsNotNone(held)
        self.assertEqual(entries, [entries[0], entries[0]])
        self.assertEqual(calls[0], entries[0]+1)
        # Bounded admission performs no streamed work, so it never polls.
        before = calls[0]
        self.assertTrue(binding.matches_compact(view, **self.operands()))
        self.assertEqual(calls[0], before)
        self.assertGreater(self.budget.statistics()['categories'].get('geometry-transfer-binding-scratch', 0), 0)
        held = None
        gc.collect()
        self.assertEqual(self.budget.statistics()['categories'].get('geometry-transfer-binding-scratch', 0), 0)
        del view, binding
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_matches_compact_is_bounded(self):
        view = compact(self.body, self.supports, self.budget)
        counts = dict(support=0, body=0)
        digest, stream = PT.CompactPartition._hash, PT.CompactPartition.iter_legacy_json
        def counted_hash(instance, node):
            counts['support'] += 1
            return digest(instance, node)
        def counted_stream(instance, ref=None):
            counts['body'] += ref is None
            yield from stream(instance, ref)
        with mock.patch.object(PT.CompactPartition, '_hash', counted_hash), \
                mock.patch.object(PT.CompactPartition, 'iter_legacy_json', counted_stream):
            binding = self.bind(view)
        # The restart boundary re-streams the body and every ordered support once.
        self.assertEqual(counts, dict(support=view.support_count, body=1))
        reopened = compact(self.body, self.supports, self.budget)
        def forbidden(*args, **kwargs):
            raise AssertionError('matches_compact must not stream or export the parent')
        with mock.patch.object(PT.CompactPartition, '_hash', forbidden), \
                mock.patch.object(PT.CompactPartition, 'iter_legacy_json', forbidden), \
                mock.patch.object(PT.CompactPartition, 'legacy_record', forbidden):
            for candidate in (view, reopened):
                self.assertTrue(binding.matches_compact(candidate, **self.operands()))
                self.assertTrue(G.collar_binding_matches_compact(candidate, self.funding, self.collar,
                                                                 self.budget, binding))
        del view, reopened, binding, candidate
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)


if __name__ == '__main__':
    unittest.main(verbosity=2)
