"""Indexed compact pressure consumer: tiny exact parity, refusals and lifetimes.

Hash-checked transformed geometry/pressure sources are installed in memory in
a fresh process: no package copy, store, original database or scientific run.
Synthetic fixture provenance only, never physical acceptance. The full real
forcing parity is deferred to the composed checks.
"""
import ast
from contextlib import ExitStack
import copy
from copy import deepcopy
from fractions import Fraction as Q
import gc
from hashlib import sha256
import json
from pathlib import Path
import pickle
import sys
import types
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import pressure_indexed_patch as X


HERE = Path(__file__).resolve().parent
RESUME = HERE.parent
RUNTIME = HERE.parents[1]/'runtime-integration-r1'/'runtime-src'
BASE = RUNTIME/'atlas_tectonics'
FROZEN_NAME = 'atlas_tectonics._w1d_frozen_differential_pressure'
IDENTITY = tuple(tuple(Q(int(i == j)) for j in range(3)) for i in range(3))
A, B = (Q(0), Q(0), Q(1)), (Q(1), Q(0), Q(1))
OMEGA = (Q(0), Q(0), Q(1, 10**10))
PROFILE = ((Q(1), Q(5), Q(1), Q(0)),)
FIX = None


def _install(name, text, path):
    module = types.ModuleType(name)
    module.__file__, module.__package__ = str(path), 'atlas_tectonics'
    sys.modules[name] = module
    exec(compile(text, str(path), 'exec'), module.__dict__)
    return module


def setUpModule():
    global np, atlas, G, D, FROZEN, P, V, U, CC, M, PT, PN, SIP, TPT, TMT, WorkBudget, FIX
    if any(n == 'atlas_tectonics' or n.startswith('atlas_tectonics.') for n in sys.modules):
        raise RuntimeError('fresh process required; never patch a loaded production package')
    if str(RUNTIME) not in sys.path:
        sys.path.insert(0, str(RUNTIME))
    if str(RESUME) not in sys.path:
        sys.path.append(str(RESUME))
    import numpy as np
    import atlas_tectonics as atlas
    import partition_native_patch as PN
    path = BASE/'integration_differential_geometry.py'
    G = _install('atlas_tectonics.integration_differential_geometry',
                 PN.transform(path.read_bytes().decode('utf8')), path)
    atlas.integration_differential_geometry = G
    path = BASE/'integration_differential_pressure.py'
    frozen = path.read_bytes().decode('utf8')
    if sha256(frozen.encode()).hexdigest() != X.BASE_SHA256:
        raise RuntimeError('frozen pressure input differs')
    D = _install('atlas_tectonics.integration_differential_pressure', X.transform(frozen), path)
    atlas.integration_differential_pressure = D
    # The unmodified source under a private name: ordinary-route reference only.
    FROZEN = _install(FROZEN_NAME, frozen, path)
    from atlas_tectonics import integration_spatial_pressure as P
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics import integration_support as U
    from atlas_tectonics import integration_pressure_coupling as CC
    from atlas_tectonics.resources import WorkBudget
    import mesh_tables as M
    import partition_tables as PT
    import spatial_indexed_patch as SIP
    import test_partition_tables as TPT
    import test_mesh_tables as TMT
    if TPT.D is not G:
        raise RuntimeError('fixture imported another geometry module')
    FIX = _fixture()


def tearDownModule():
    for name in (FROZEN_NAME,):
        sys.modules.pop(name, None)


def _fixture():
    """Probe-verified tiny partition/mesh: shared DAG constraint nodes."""
    budget = WorkBudget(1 << 30)
    q, ident = TPT.q, TPT.ident
    vec = lambda v: [q(x) for x in v]
    def ray(direction):
        return dict(direction=vec(direction), angular_velocity_rad_s=vec(OMEGA), prior_rotations=[])
    edge = dict(kind='moving-ray-edge', rays=[ray(A), ray(B)])
    fixed = dict(kind='fixed-plane', normal=vec((1, 0, 0)), offset=q(9))
    snap = dict(kind='snapshot-rotated', constraint=edge, snapshot_offset_s=q(Q(1, 2)), angular_velocity_rad_s=vec(OMEGA))
    constraints = {'face': edge, 'other': fixed, 'snap': snap}
    cell = V.CartesianCell((0, -1, 2), (1, 1, 3), budget=budget)
    layer = V.RadialLayer(5, 0, 4, budget=budget).record()
    body, supports = TPT.tiny_partition(budget, count=2, depth=1)
    lids = [ident('pressure-cell-'+str(i)) for i in range(3)]
    def component(lid, literals):
        return dict(logical_cell_id=lid, partition_path=['inherited', 0, [1, -1]],
                    owner_ray_ids=['vertex:a', 'fan:b'], constraints=literals)
    supports[0].update(constraints=deepcopy(constraints), voxel=cell.record(), radial_layer=layer,
        components=[component(lids[0], [['other', -1], ['face', 1]]),
                    component(lids[1], [['snap', 1], ['face', -1], ['other', 1]])])
    supports[1].update(constraints=deepcopy(constraints), voxel=cell.record(), radial_layer=layer,
        plate_id='plate:A', components=[component(lids[2], [['face', 1], ['snap', -1]])])
    sids = [G._record_hash(s) for s in supports]
    body['support_ids'] = sids
    body['native_contacts'][0]['contacts'] = [dict(support_id=sid, logical_cell_id=s['components'][0]['logical_cell_id'],
        voxel_index=s['voxel_index'], axis=0, end=0) for sid, s in zip(sids, supports, strict=True)]
    part_view = TPT.opened(body, supports, budget)[0]
    mesh = TMT.small_mesh_record(budget)
    for row, (sid, lid) in zip(mesh['cells'], ((sids[0], lids[0]), (sids[1], lids[2])), strict=True):
        row.update(kind='exterior', logical_cell_id=lid, source_key=['patch', 0],
                   physical_support={'differential_support_id': sid, 'logical_cell_id': lid})
    mesh['support_tables'] = {'differential_supports': {sid: s for sid, s in zip(sids, supports, strict=True)}}
    odd = deepcopy(mesh)
    odd['cells'][1]['physical_support'] = {'differential_support_id': sids[1], 'logical_cell_id': lids[0]}
    vid, rid, cid = cell.cell_id, ident('layer'), ident('cone')
    plain = TMT.small_mesh_record(budget)
    for row, lid in zip(plain['cells'], (lids[0], lids[2]), strict=True):
        row.update(kind='exterior', logical_cell_id=lid, source_key=['patch', 0],
                   physical_support={'voxel_id': vid, 'radial_layer_id': rid, 'cone_id': cid})
    plain['support_tables'] = {'voxels': {vid: cell.record()}, 'radial_layers': {rid: layer},
                               'cones': {cid: [vec((1, 0, 0)), vec((0, 1, 0)), vec((0, 0, 1))]}}
    native_cell = V.CartesianCell((1, 0, 0), (2, 1, 1), budget=budget)
    return NS(budget=budget, cell=cell, supports=supports, sids=sids, lids=lids, part_view=part_view,
        mesh=mesh, view=TMT.compact_fixture(deepcopy(mesh), budget)[0],
        odd=odd, odd_view=TMT.compact_fixture(deepcopy(odd), budget)[0],
        plain=plain, plain_view=TMT.compact_fixture(deepcopy(plain), budget)[0],
        natives=tuple(G._issue(G.DifferentialSupport, s, budget) for s in supports),
        compact=tuple(PN.materialise_support(part_view, i) for i in range(part_view.support_count)),
        collar=NS(_fields=lambda state: {'component_mass_kg': np.ones((1, 1)), 'enthalpy_j': np.ones(1)},
                  cell_geometries=lambda: (native_cell,), _native=NS(_material=None, _composition=(1,))),
        sphere=NS(material=None, network=NS(faces=())),
        plain_sphere=NS(material=None, network=NS(faces=(NS(face_id='face', plate_id='plate:A'),))),
        funding=NS(descriptor=lambda: {'time_s': 0}))


def small(time, *, intervals=1, rows=None, key=0):
    rows = (0, 2) if rows is None else rows
    return dict(cells=[dict(cell_id=FIX.lids[i], source_key=['patch', key],
                            exact={'enthalpy_j': TPT.q(1), 'component_mass_kg:0': TPT.q(1)}) for i in rows],
                time_s=time, intervals=intervals)


def legacy_state(time, mesh=None, **kwargs):
    mesh = FIX.mesh if mesh is None else mesh
    return NS(record=lambda: dict(deepcopy(small(time, **kwargs)), thermal_mesh=deepcopy(mesh)))


def compact_state(time, view=None, budget=None, **kwargs):
    view, budget = FIX.view if view is None else view, FIX.budget if budget is None else budget
    body = json.dumps(small(time, **kwargs), sort_keys=True, separators=(',', ':')).encode()
    snapshot = SIP.IndexedSpatialSnapshot(body, (), '0'*64, view, ('0'*64, 0), float(time), budget)
    return NS(_snapshot=snapshot, _budget=budget, state_id='1'*64)


def regions(state, supports, endpoint, *, module=None, budget=None, sphere=None):
    module, budget = D if module is None else module, FIX.budget if budget is None else budget
    return module._current_regions(FIX.sphere if sphere is None else sphere, FIX.funding, FIX.collar, None,
                                   state, supports, endpoint, Q(5), Q(1), budget)


def summary(result):
    found, densities, cells = result
    rows = [dict(keys=list(r), cell=r['cell'].record(), cone=r['cone'], world=r.get('world_planes'),
                 physical=tuple(r.get('_physical_planes', ())), radial=r['radial'], density=r['density'],
                 plate=r['plate_id']) for r in found]
    return rows, densities, [c.record() for c in cells]


def stubs(material=None):
    stack = ExitStack()
    stack.enter_context(patch.object(U, 'required', return_value=NS(patches=()) if material is None else material))
    stack.enter_context(patch.object(P, '_density', return_value=(Q(2), Q(300))))
    return stack


def no_whole_exports():
    original = PT.CompactPartition.legacy_record
    def selected(instance, ref=None):
        if ref is None:
            raise AssertionError('whole partition export')
        return original(instance, ref)
    stack = ExitStack()
    stack.enter_context(patch.object(M.CompactMesh, 'legacy_record', side_effect=AssertionError('whole mesh export')))
    stack.enter_context(patch.object(PT.CompactPartition, 'legacy_record', selected))
    return stack


def outcome(call):
    try:
        call()
        return 'accepted'
    except Exception as error:
        return type(error).__name__+': '+str(error)


def deep(value, seen):
    if id(value) in seen or isinstance(value, (type, types.ModuleType)):
        return 0
    seen.add(id(value))
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        size += sum(deep(k, seen)+deep(v, seen) for k, v in value.items())
    elif isinstance(value, (list, tuple, set)):
        size += sum(deep(v, seen) for v in value)
    elif isinstance(value, Q):
        size += deep(value.numerator, seen)+deep(value.denominator, seen)
    return size


def _inverse_indexed(module):
    seen = dict(dispatch=0, record=0, header=0, imports=0)
    for fn in ast.walk(module):
        if not isinstance(fn, ast.FunctionDef):
            continue
        body = []
        for stmt in fn.body:
            if isinstance(stmt, ast.ImportFrom) and stmt.module == 'pressure_indexed_patch':
                seen['imports'] += 1
                continue
            if isinstance(stmt, ast.If) and ast.unparse(stmt.test) == '_pressure_indexed(spatial_state)':
                seen['dispatch'] += 1
                continue
            if isinstance(stmt, ast.Assign) and ast.unparse(stmt.value) == "_pressure_mesh_header(c['thermal_mesh'], budget)":
                seen['header'] += 1
                stmt = ast.parse("mesh = c['thermal_mesh']").body[0]
            body.append(stmt)
        fn.body = body
    for node in ast.walk(module):
        if isinstance(node, ast.Tuple):
            for i, element in enumerate(node.elts):
                if ast.unparse(element) == '_pressure_state_record(spatial_state)':
                    node.elts[i] = ast.parse('spatial_state.record()', mode='eval').body
                    seen['record'] += 1
    return module, seen


def _inverse_funding(module):
    # The same inverse as R/test_funding_transfer.py's pressure seam check.
    if module.body[-1].name != '_transferred_funding_binding':
        raise AssertionError('funding helper absent')
    module.body.pop()
    names, guards = [], 0
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef):
            for index, arg in enumerate(node.args.kwonlyargs):
                if arg.arg == '_runtime_funding_transfer':
                    del node.args.kwonlyargs[index], node.args.kw_defaults[index]
                    names.append(node.name)
                    break
        if isinstance(node, ast.BoolOp):
            for index, value in enumerate(node.values):
                if (isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not) and
                        isinstance(value.operand, ast.Call) and
                        ast.unparse(value.operand.func) == '_transferred_funding_binding'):
                    node.values[index] = ast.parse("f['collar_plan_id'] != collar.plan_id", mode='eval').body
                    guards += 1
    return module, sorted(names), guards


def _pressure_source():
    # Read the bytes and execute only the transform; never import its runtime.
    tree = ast.parse((RESUME/'funding_transfer.py').read_text(encoding='utf8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'pressure_source')
    namespace = {'FundingTransferRefused': type('FundingTransferRefused', (ValueError,), {})}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'funding_transfer.pressure_source', 'exec'), namespace)
    return namespace['pressure_source'], namespace['FundingTransferRefused']


class PressureIndexedTests(unittest.TestCase):
    def test_v2_partition_supports_regions_exact_parity_and_owned_planes(self):
        from content_cache import create_retained_scope
        from record_views import RecordRef
        scope = create_retained_scope(FIX.budget, process_epoch='wp4-pressure-v2')
        body_owner = FIX.part_view.legacy_record()
        body = body_owner.value
        view = PT.pack_partition_v2(body, iter(FIX.supports),
            expected_partition_id=G._record_hash(body), scope=scope)
        del body, body_owner
        supports = tuple(PN.materialise_support(view, i) for i in range(view.support_count))
        root_index, original = view.record._root, RecordRef.export
        def selected(ref, **kwargs):
            self.assertNotEqual(ref.index, root_index, 'whole descriptor export forbidden')
            return original(ref, **kwargs)
        with stubs(), no_whole_exports(), patch.object(RecordRef, 'export', selected):
            expected = regions(legacy_state(1), FIX.natives, 'end')
            actual = regions(compact_state(1), supports, 'end')
        self.assertEqual(summary(actual), summary(expected))
        owners = [r['_physical_planes']._owner for r in actual[0] if r.get('_physical_planes')]
        self.assertTrue(owners)
        self.assertTrue(all(o.stats['shared_hits'] > 0 for o in owners))
        self.assertTrue(all(o.reserved >= o.stats['charged'] for o in owners))
        escaped = actual[0][-1]['_physical_planes']
        del actual, expected, owners, supports
        gc.collect(); view.close()
        self.assertTrue(escaped._owner.reserved)
        del escaped
        gc.collect(); scope.close()

    def setUp(self):
        gc.collect()
        self.base = FIX.budget.reserved_bytes

    def tearDown(self):
        gc.collect()
        self.assertEqual(FIX.budget.reserved_bytes, self.base)

    def test_transform_exact_seams_single_application_and_ordinary_ast(self):
        frozen = (BASE/'integration_differential_pressure.py').read_bytes().decode('utf8')
        self.assertEqual(frozen.count('\r'), 0)
        for old, _ in X._SEAMS:
            self.assertEqual(frozen.count(old), 1)
        candidate = X.transform(frozen)
        self.assertEqual(sha256(candidate.encode()).hexdigest(), X.TRANSFORMED_SHA256)
        for bad in (candidate, frozen+'\n', frozen.replace('\n', '\r\n'), frozen.encode(), None):
            with self.assertRaises(X.PressureIndexedRefused):
                X.transform(bad)
        module, seen = _inverse_indexed(ast.parse(candidate))
        self.assertEqual(seen, dict(dispatch=1, record=1, header=1, imports=3))
        self.assertEqual(ast.dump(module), ast.dump(ast.parse(frozen)))
        pressure_source, refused = _pressure_source()
        composed = pressure_source(candidate)
        compile(composed, 'composed-pressure', 'exec')
        self.assertEqual(sha256(composed.encode()).hexdigest(), X.COMPOSED_SHA256)
        with self.assertRaises(X.PressureIndexedRefused):
            X.transform(pressure_source(frozen))
        with self.assertRaises(refused):
            pressure_source(composed)
        module, names, guards = _inverse_funding(ast.parse(composed))
        self.assertEqual((names, guards), (['differential_pressure_forcing', 'prescribe_reservoir_pressure'], 2))
        module, seen = _inverse_indexed(module)
        self.assertEqual(ast.dump(module), ast.dump(ast.parse(frozen)))
        # Line-anchored exact-once: a deeper indented copy or a repeat refuses.
        with self.assertRaises(X.PressureIndexedRefused):
            X._once('def f():\n        x = 1\n', '    x = 1\n', '')
        with self.assertRaises(X.PressureIndexedRefused):
            X._once('x = 1\nx = 1\n', 'x = 1\n', '')
        self.assertEqual(X._once('a\nx = 1\n', 'x = 1\n', 'y\n'), 'a\ny\n')

    def test_regions_parity_legacy_compact_and_mixed(self):
        with stubs():
            for endpoint, now in (('end', 1), ('start', 0)):
                legacy = regions(legacy_state(now), FIX.natives, endpoint)
                with no_whole_exports():
                    compact = regions(compact_state(now), FIX.compact, endpoint)
                    mixed = regions(compact_state(now), FIX.natives, endpoint)
                self.assertEqual(summary(compact), summary(legacy))
                self.assertEqual(summary(mixed), summary(legacy))
                self.assertEqual(len(legacy[0]), 3)
                times = {t for r in legacy[0][1:] for _, t in r['_physical_planes']}
                self.assertEqual(times, {Q(now)})
                for result in (compact, mixed):
                    exterior = result[0][1:]
                    self.assertEqual([list(r) for r in exterior], [list(r) for r in legacy[0][1:]])
                    self.assertTrue(all(type(r['_physical_planes']) is X._OwnedPlanes for r in exterior))
                    self.assertEqual(len({id(r['_physical_planes']._owner) for r in exterior}), 1)
                    self.assertNotIn('_physical_planes', result[0][0])
                self.assertTrue(all(type(r['_physical_planes']) is tuple for r in legacy[0][1:]))
                # One decoded record per shared DAG node, even across supports.
                self.assertIs(compact[0][1]['_physical_planes'][1][0], compact[0][2]['_physical_planes'][0][0])
                owner = compact[0][1]['_physical_planes']._owner
                self.assertEqual(owner.stats['decoded'], 3)
                self.assertGreater(owner.stats['shared_hits'], 0)
                if endpoint == 'end':
                    self._wall_parity(legacy, compact)
                del legacy, compact, mixed, owner

    def _wall_parity(self, legacy, compact):
        budget = FIX.budget
        pose = D._KernelPose(IDENTITY, Q(1, 10**8), history=((OMEGA, Q(1)),))
        records = [c for r in compact[0][1:] for c, _ in r['_physical_planes']]
        before = [M.canonical(c) for c in records]
        kinds = []
        for width, leaves in ((Q(1), 256), (Q(64), 4096)):
            outputs = []
            for result in (legacy, compact):
                selected = [dict(r, side=0) for r in result[0][1:]]
                try:
                    outputs.append(('ok', P.moving_wall_integrals(A, B, (PROFILE, PROFILE), selected, FIX.cell, pose,
                        gravity=1, support_radius=1, radius=5, width=width, max_leaves=leaves, budget=budget)))
                except CC.PressureCouplingRefused as error:
                    outputs.append(('refused', str(error), tuple(getattr(error, '__notes__', ()))))
            self.assertEqual(outputs[0], outputs[1])
            kinds.append(outputs[0][0])
        self.assertEqual(kinds, ['refused', 'ok'])
        proofs = [[P._face_on_wall(c, t, A, B, pose, budget) for c, t in result[0][1]['_physical_planes']]
                  for result in (legacy, compact)]
        self.assertEqual(proofs, [[False, True]]*2)
        self.assertEqual([M.canonical(c) for c in records], before)

    def test_non_differential_initial_branch_parity(self):
        material = NS(patches=(NS(patch_id='patch', face_id='face'),))
        with stubs(material):
            legacy = regions(legacy_state(0, FIX.plain, intervals=0), (), 'start', sphere=FIX.plain_sphere)
            with no_whole_exports():
                compact = regions(compact_state(0, FIX.plain_view, intervals=0), (), 'start', sphere=FIX.plain_sphere)
            self.assertEqual(summary(compact), summary(legacy))
            self.assertEqual([r['plate_id'] for r in compact[0][1:]], ['plate:A']*2)
            self.assertTrue(all(r['_physical_planes'] == () and not r['_physical_planes'] for r in compact[0][1:]))
            del legacy, compact
            a = outcome(lambda: regions(legacy_state(0, FIX.plain, intervals=1), (), 'start', sphere=FIX.plain_sphere))
            b = outcome(lambda: regions(compact_state(0, FIX.plain_view, intervals=1), (), 'start', sphere=FIX.plain_sphere))
            self.assertEqual(a, b)
            self.assertIn('old source cones cannot locate an advanced differential field', a)

    def test_refusal_parity_and_order(self):
        other = WorkBudget(1 << 26)
        with stubs():
            self._refusals(other)
        self.assertGreater(other.peak_reserved_bytes, 0)
        # Every foreign-budget object died with the helper frame.
        gc.collect()
        self.assertEqual(other.reserved_bytes, 0)

    def _refusals(self, other):
        foreign = (G._issue(G.DifferentialSupport, FIX.supports[0], other),)
        cases = {
            'duplicate': (dict(), lambda s: s+s[:1], 'end', 'duplicate physical support'),
            'missing support': (dict(), lambda s: s[:1], 'end', 'force supplied a different physical component geometry'),
            'wrong budget': (dict(), lambda s: foreign, 'end', 'issued current physical component supports required'),
            'not a support': (dict(), lambda s: ('support',), 'end', 'issued current physical component supports required'),
            'clock': (dict(), lambda s: s, 'start', 'component force geometry has another clock'),
            'coverage': (dict(rows=(0,)), lambda s: s, 'end', 'carried fields and physical support have different cell coverage'),
            'lineage': (dict(key=1), lambda s: s, 'end', 'carried cell lineage differs from its physical support'),
        }
        for name, (shape, chosen, endpoint, message) in cases.items():
            gc.collect()
            before = FIX.budget.reserved_bytes
            a = outcome(lambda: regions(legacy_state(1, **shape), chosen(FIX.natives), endpoint))
            b = outcome(lambda: regions(compact_state(1, **shape), chosen(FIX.compact), endpoint))
            self.assertEqual(a, b, name)
            self.assertIn(message, a, name)
            gc.collect()
            self.assertEqual(FIX.budget.reserved_bytes, before, name)
        # Component lookup precedes the supplied-support comparison.
        for chosen in (lambda s: s[:1], lambda s: s):
            a = outcome(lambda: regions(legacy_state(1, FIX.odd), chosen(FIX.natives), 'end'))
            b = outcome(lambda: regions(compact_state(1, FIX.odd_view), chosen(FIX.compact), 'end'))
            self.assertEqual(a, b)
            self.assertEqual(a, 'VolumeError: thermal physical support reference has no matching component')
        # Compact-only: an indexed mesh on another budget is refused.
        mesh = TMT.compact_fixture(deepcopy(FIX.mesh), other)[0]
        refused = outcome(lambda: regions(compact_state(1, mesh, other), FIX.compact, 'end'))
        self.assertEqual(refused, 'PressureCouplingRefused: compact pressure mesh belongs to another budget')
        self.assertGreater(other.reserved_bytes, 0)

    def test_held_error_keeps_constraint_owner_charged(self):
        budget = FIX.budget
        pose = D._KernelPose(IDENTITY, Q(1, 10**8), history=((OMEGA, Q(1)),))
        def failing():
            found = regions(compact_state(1), FIX.compact, 'end')[0]
            raise RuntimeError('held', len(found))
        with stubs():
            try:
                failing()
            except RuntimeError:
                held = sys.exc_info()
            gc.collect()
            self.assertGreater(budget.statistics()['categories'].get(X.RETAINED, 0), 0)
            found = held[2].tb_next.tb_frame.f_locals['found']
            self.assertEqual([P._face_on_wall(c, t, A, B, pose, budget) for c, t in found[1]['_physical_planes']],
                             [False, True])
            copies = [dict(r, side=0) for r in found[1:]]
            del found, held
            gc.collect()
            # Region copies alone keep every borrowed record funded.
            self.assertGreater(budget.statistics()['categories'].get(X.RETAINED, 0), 0)
            self.assertEqual([P._face_on_wall(c, t, A, B, pose, budget) for c, t in copies[0]['_physical_planes']],
                             [False, True])
            for action in (pickle.dumps, copy.copy, copy.deepcopy):
                with self.assertRaises(TypeError):
                    action(copies[0]['_physical_planes'])
            with self.assertRaises(AttributeError):
                copies[0]['_physical_planes']._owner = None
            del copies
            gc.collect()
            self.assertEqual(budget.reserved_bytes, self.base)
            self.assertEqual(budget.statistics()['categories'].get(X.RETAINED, 0), 0)
            # A first-pass refusal keeps posed entries and scratch charged while held.
            try:
                regions(compact_state(1), FIX.compact+FIX.compact[:1], 'end')
            except CC.PressureCouplingRefused:
                held = sys.exc_info()
            gc.collect()
            categories = budget.statistics()['categories']
            self.assertGreater(categories.get(X.ENTRIES, 0), 0)
            self.assertGreater(categories.get(X.SCRATCH, 0), 0)
            del held
        gc.collect()
        categories = budget.statistics()['categories']
        self.assertEqual([categories.get(k, 0) for k in (X.RETAINED, X.ENTRIES, X.SCRATCH)], [0, 0, 0])

    def test_accounting_real_vs_booked(self):
        budget = FIX.budget
        with stubs():
            found = regions(compact_state(1), FIX.compact, 'end')[0][1:]
        owner = found[0]['_physical_planes']._owner
        records = deep(list(owner._records.values()), set())
        shapes = [deep({k: v for k, v in r.items() if k not in ('_physical_planes', 'cell')}, set()) for r in found]
        self.assertTrue(records <= owner.stats['record_bytes'] <= 4*records, (records, owner.stats))
        self.assertTrue(all(size <= X.REGION_CHARGE <= 4*size for size in shapes), shapes)
        self.assertEqual(owner.stats['charged'], owner.stats['record_bytes']+X.REGION_CHARGE*len(found))
        self.assertTrue(owner.stats['charged'] <= owner.reserved == budget.statistics()['categories'][X.RETAINED])
        # One slim posed entry against its booking.
        measure = G.posed_support(FIX.compact[0], endpoint='end', budget=budget)
        view = measure.record()
        entry = X._posed_entry(FIX.compact[0], view, 'end', budget)
        del measure, view
        retained = deep([entry.support_id, entry.time_s, entry.duration, entry.plate_id, entry.radial_layer,
                         entry.voxel, entry.constraints, entry.pairs, entry.nodes], set())
        self.assertTrue(retained <= entry.lease.size <= 4*retained, (retained, entry.lease.size))
        # Thermal row index: booked coefficient against a same-shape replica.
        thermal, lease = X._exterior_index(FIX.view, budget)
        self.assertTrue(deep(thermal, set()) <= lease.size)
        replica = {sha256(str(i).encode()).hexdigest(): 1000+i for i in range(4096)}
        per_entry = deep(replica, set())/len(replica)
        self.assertTrue(per_entry <= X.INDEX_ENTRY <= 4*per_entry, per_entry)
        print('\npressure accounting:', json.dumps(dict(
            record_measured=records, record_booked=owner.stats['record_bytes'],
            region_measured=shapes, region_booked=X.REGION_CHARGE, arena_charged=owner.stats['charged'],
            arena_reserved=owner.reserved, entry_measured=retained, entry_booked=entry.lease.size,
            index_measured=deep(thermal, set()), index_booked=lease.size,
            index_entry_measured=round(per_entry, 1), index_entry_booked=X.INDEX_ENTRY,
            handle_owner=getattr(getattr(entry.handle, '_owner', None), 'size', None), stats=owner.stats)))
        del found, owner, entry, thermal, lease, replica

    def test_record_and_header_seams(self):
        budget = FIX.budget
        record = {'thermal_mesh': {}}
        ordinary = NS(record=lambda: record)
        self.assertIs(X.state_record(ordinary), record)
        self.assertFalse(X.is_indexed(ordinary))
        mesh = deepcopy(FIX.mesh)
        value, owner = X.mesh_header(mesh, budget)
        self.assertIs(value, mesh)
        self.assertIsNone(owner)
        stub = object()
        self.assertEqual(X.mesh_header(stub, budget), (stub, None))
        with patch.dict(sys.modules):
            sys.modules.pop('spatial_indexed_patch')
            self.assertFalse(X.is_indexed(ordinary))
            self.assertIs(X.state_record(ordinary), record)
            self.assertNotIn('spatial_indexed_patch', sys.modules)
        state = compact_state(1)
        self.assertTrue(X.is_indexed(state))
        logical = X.state_record(state)
        self.assertIs(type(logical), SIP._LogicalRecord)
        self.assertIs(logical['thermal_mesh'], FIX.view)
        self.assertIsNotNone(logical._allocation)
        value, owner = X.mesh_header(logical['thermal_mesh'], budget)
        self.assertEqual(value, {k: v for k, v in FIX.mesh.items() if k not in M.SPECIAL})
        self.assertIs(type(owner), M.OwnedRow)
        with self.assertRaises(SIP.IndexedSpatialRefused):
            X.mesh_header(FIX.view, WorkBudget(1 << 20))
        del logical, value, owner, state

    def test_ordinary_route_matches_frozen_source_and_accounting(self):
        results = []
        for module in (FROZEN, D):
            budget = WorkBudget(1 << 30)
            natives = tuple(G._issue(G.DifferentialSupport, s, budget) for s in FIX.supports)
            with stubs():
                found = regions(legacy_state(1), natives, 'end', module=module, budget=budget)
            results.append((summary(found), budget.statistics()))
            del found, natives
        self.assertEqual(results[0], results[1])
        self.assertFalse({X.RETAINED, X.ENTRIES, X.SCRATCH} & set(results[1][1]['categories']))


if __name__ == '__main__':
    unittest.main()
