"""Real producer lifetime/parity controls; synthetic science, no IV2 claim."""
import ast
from contextlib import contextmanager
from fractions import Fraction as Q
import gc
from hashlib import sha256
import importlib
import inspect
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from time import perf_counter
import unittest
from unittest.mock import patch

import differential_mesh_patch as DP
import exterior_mesh_patch as EP
import live_mesh_patch as L
import mesh_tables as M

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[4]
BASE = HERE.parents[1]/'runtime-integration-r1'/'runtime-src'/'atlas_tectonics'
TESTS = TASK/'fidelity-integration-20261005'/'source'/'tectonics'/'tests'


def setUpModule():
    global _temporary, _old_path, E, D, WorkBudget, create_retained_scope
    if any(name == 'atlas_tectonics' or name.startswith('atlas_tectonics.') for name in sys.modules):
        raise RuntimeError('fresh process required; no live runtime patching')
    _temporary = tempfile.TemporaryDirectory(prefix='lm-', dir=TASK/'_t')
    package = Path(_temporary.name)/'atlas_tectonics'
    shutil.copytree(BASE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    exterior = package/'integration_exterior_mesh.py'
    exterior.write_text(L.transform_exterior(EP.transform(exterior.read_bytes().decode())), encoding='utf8')
    differential = package/'integration_differential_mesh.py'
    differential.write_text(L.transform_differential(DP.transform(differential.read_text())), encoding='utf8')
    _old_path = list(sys.path)
    sys.path[:0] = [str(Path(_temporary.name)), str(TESTS), str(HERE.parent),
        str(HERE.parents[1]/'runtime-integration-r1'/'ram'), str(HERE.parents[1]/'runtime-integration-r1'/'helpers'),
        str(TASK/'fidelity-integration-20261005'/'heat-repair-20261007')]
    import partition_native_patch as PN
    geometry = package/'integration_differential_geometry.py'
    geometry.write_text(PN.transform(geometry.read_bytes().decode()), encoding='utf8')
    E = importlib.import_module('atlas_tectonics.integration_exterior_mesh')
    D = importlib.import_module('atlas_tectonics.integration_differential_mesh')
    WorkBudget = importlib.import_module('atlas_tectonics.resources').WorkBudget
    create_retained_scope = importlib.import_module('content_cache').create_retained_scope


def tearDownModule():
    sys.path[:] = _old_path
    assert Path(_temporary.name).resolve().parent == (TASK/'_t').resolve()
    _temporary.cleanup()


@contextmanager
def ordinary_fixture():
    from test_integration_collar_geometry import fixture, fund
    from atlas_tectonics import integration_wall_measures as W
    with fixture() as (source, owner, collar, budget):
        funding = fund(source, owner, collar, budget)
        wall = W.measure_walls(funding, source[0], collar, parent_state_id='initial-source',
            start_time_s=source[1].time_s, end_time_s=source[1].time_s+Q(1, 64),
            angular_velocity_rad_s=(0, 0, 0), max_volume_error_m3=Q(1, 10000), max_leaves=64, budget=budget)
        boxes = collar.cell_geometries()
        radius = Q(source[0].network.sphere.radius_m)
        base = boxes[0]
        offset = tuple(sum(base.basis[k][j]*base.origin_m[k] for k in range(3)) for j in range(3))
        lines = tuple(tuple(sorted({-radius-offset[j], -offset[j], radius-offset[j],
            *(v for box in boxes for v in (box.lower_m[j], box.upper_m[j]))})) for j in range(3))
        yield (funding, source[0], wall), dict(grid_lines=lines,
            max_geometry_volume_error_m3=32*radius**3/3, max_leaves=64, budget=budget)


@contextmanager
def differential_fixture():
    import gzip
    from test_integration_differential_mesh_closure import (FIXTURE, FIXTURE_SHA256, Retained,
        PreparedFiniteStocks, stock, NAMES, POSITIVE)
    raw = FIXTURE.read_bytes()
    assert sha256(raw).hexdigest() == FIXTURE_SHA256
    separated = json.loads(gzip.decompress(raw))[1]
    budget = WorkBudget(1 << 30)
    with PreparedFiniteStocks('registry', [stock('supply', 'source', Q(1, 2), 1, 0, 0)],
            field_names=NAMES, nonnegative_fields=POSITIVE, budget=budget) as stocks:
        case = Retained(separated, stocks, budget)
        bounds = case.bounds()
        yield (case.funding, bounds, (case.support,)), dict(endpoint='end',
            max_geometry_volume_error_m3=case.width, max_leaves=64, budget=budget)


def measure(mode, *, route='ordinary', subdivisions=1):
    """One fresh-process construction sample for the root's combined receipt.

    These producers are ephemeral: authoritative disk output is zero. The
    exact logical bytes are streamed to a temporary diagnostic file after the
    construction timing and memory sample, then removed with its test folder.
    """
    import psutil
    assert mode in ('native', 'compact') and route in ('ordinary', 'differential')
    assert type(subdivisions) is int and 1 <= subdivisions <= 4
    process, done = psutil.Process(), threading.Event()
    peak = {'rss': 0, 'private': 0}
    def sample():
        info = process.memory_info()
        peak['rss'] = max(peak['rss'], info.rss)
        peak['private'] = max(peak['private'], getattr(info, 'private', info.rss))
    def monitor():
        while not done.wait(.01):
            sample()
    fixture = ordinary_fixture if route == 'ordinary' else differential_fixture
    scope = None
    with fixture() as (args, kwargs):
        budget = kwargs['budget']
        if route == 'ordinary':
            kwargs['grid_lines'] = tuple(tuple(sorted({a+(b-a)*Q(i, subdivisions)
                for a, b in zip(axis, axis[1:], strict=False) for i in range(subdivisions)} | {axis[-1]}))
                for axis in kwargs['grid_lines'])
            producer = E.build_exterior_mesh
        else:
            kwargs['thermal_subdivisions'] = subdivisions
            producer = D.build_differential_mesh
        if mode == 'compact':
            scope = create_retained_scope(budget, process_epoch='live-mesh-measure')
        before = process.memory_info()
        charged_before = budget.reserved_bytes
        sample()
        worker = threading.Thread(target=monitor, daemon=True)
        worker.start()
        started = perf_counter()
        try:
            mesh = producer(*args, **kwargs, compact_context=None if scope is None else {'scope': scope})
        finally:
            elapsed = perf_counter()-started
            sample(); done.set(); worker.join()
        result = dict(mode=mode, route=route, subdivisions=subdivisions, seconds=elapsed,
            geometry_id=mesh.geometry_id, charged_baseline=charged_before,
            charged_peak=budget.peak_reserved_bytes, charged_after=budget.reserved_bytes,
            rss_baseline=before.rss, private_baseline=getattr(before, 'private', before.rss),
            sampled_rss_peak=peak['rss'], sampled_private_peak=peak['private'],
            process_peak_rss=getattr(process.memory_info(), 'peak_wset', None),
            sample_seconds=.01, authoritative_disk_bytes=0,
            scope_live_bytes=None if scope is None else scope.stats().retained_bytes)
        path = Path(_temporary.name)/'logical-output.json'
        digest, count = sha256(), 0
        with path.open('wb') as handle:
            for block in ((mesh._json,) if scope is None else mesh.iter_legacy_json()):
                handle.write(block); digest.update(block); count += len(block)
        del block
        assert digest.hexdigest() == mesh.geometry_id
        result.update(logical_bytes=count, diagnostic_disk_bytes=path.stat().st_size)
        if scope is None:
            body = mesh.record()
            result.update(cells=len(body['cells']), faces=len(body['faces']))
            del body, mesh
        else:
            result.update(cells=mesh.cell_count, faces=mesh.face_count, compact_column_bytes=mesh._compact.nbytes)
            view = mesh._compact
            del mesh
            view.close(); del view
            scope.close()
        gc.collect()
        result['charged_after_output_release'] = budget.reserved_bytes
        result['source_sha256'] = {name: sha256((HERE/name).read_bytes()).hexdigest() for name in
            ('live_mesh_patch.py', 'mesh_tables.py', 'exterior_mesh_patch.py', 'differential_mesh_patch.py', 'test_live_mesh.py')}
        result['native_source_sha256'] = {name: sha256((BASE/name).read_bytes()).hexdigest() for name in
            ('integration_exterior_mesh.py', 'integration_differential_mesh.py')}
    del args, kwargs, scope
    gc.collect()
    result['final_reserved_bytes'] = budget.reserved_bytes
    return result


class LiveMeshTests(unittest.TestCase):
    def test_source_fence_and_scientific_body(self):
        raw = (BASE/'integration_exterior_mesh.py').read_bytes().decode()
        self.assertEqual(sha256(raw.encode()).hexdigest(), EP.BASE_SOURCE_SHA256)
        with self.assertRaises(EP.CompactExteriorRefused):
            EP.transform(raw+'# changed\n')
        source = EP.transform(raw)
        new = L.transform_exterior(source)
        old_body = ast.parse(L._function(source, 'build_exterior_mesh')).body[0].body
        new_body = ast.parse(L._function(new, '_build_exterior_mesh_record')).body[0].body
        new_body[-1].body = [node for node in new_body[-1].body if not isinstance(node, ast.Delete)]
        self.assertEqual(ast.dump(ast.Module(body=old_body[:-1], type_ignores=[])),
                         ast.dump(ast.Module(body=new_body[:-1], type_ignores=[])))
        self.assertEqual(ast.dump(ast.Module(body=old_body[-1].body[:-4], type_ignores=[])),
                         ast.dump(ast.Module(body=new_body[-1].body[:-2], type_ignores=[])))
        with self.assertRaises(M.MeshTablesRefused):
            L.transform_exterior(new)

    def _parity(self, producer, fixture):
        with fixture() as (args, kwargs):
            budget = kwargs['budget']
            native = producer(*args, **kwargs)
            expected = native._json
            expected_id = native.geometry_id
            del native
            scope = create_retained_scope(budget, process_epoch='live-mesh-test')
            baseline = budget.reserved_bytes
            original_pack = M.pack_mesh
            seen = []
            def checked_pack(record, **options):
                # The actual native builder and geometry arena have returned.
                frames = inspect.stack(context=0)
                self.assertFalse(any(frame.function in ('_build_exterior_mesh_record',
                    '_build_differential_mesh_record') for frame in frames))
                del frames
                self.assertGreater(budget.reserved_bytes, baseline)
                seen.append((len(record['cells']), len(record['faces'])))
                return original_pack(record, **options)
            with patch.object(M, 'pack_mesh', checked_pack):
                mesh = producer(*args, **kwargs, compact_context={'scope': scope})
            self.assertEqual(len(seen), 1)
            self.assertIsNone(mesh._json)
            self.assertIs(mesh._compact.scope, scope)
            self.assertEqual(mesh.geometry_id, expected_id)
            self.assertEqual(b''.join(mesh.iter_legacy_json()), expected)
            row = mesh.cell(0)
            view = mesh._compact
            del mesh
            with self.assertRaises(RuntimeError):
                view.close()
            del row
            view.close()
            del view
            gc.collect()
            self.assertEqual(budget.reserved_bytes, baseline)
            scope.close()

    def test_actual_ordinary_producer_exact_bytes_and_lifetime(self):
        self._parity(E.build_exterior_mesh, ordinary_fixture)

    def test_actual_differential_producer_exact_bytes_and_lifetime(self):
        self._parity(D.build_differential_mesh, differential_fixture)

    def test_actual_differential_producer_from_compact_partition(self):
        from partition_native_patch import _Supports
        from partition_tables import pack_partition_v2
        from test_partition_tables import tiny_partition
        with differential_fixture() as (args, kwargs):
            budget = kwargs['budget']
            native = D.build_differential_mesh(*args, **kwargs)
            expected = native._json
            del native
            scope = create_retained_scope(budget, process_epoch='live-mesh-partition')
            body, unused = tiny_partition(budget, count=1, depth=0)
            del unused
            row = args[2][0].record()
            body['support_ids'] = [args[2][0].support_id]
            body['native_contacts'] = []
            partition = pack_partition_v2(body, iter((row,)), expected_partition_id=M.digest(body), scope=scope)
            sequence = _Supports(partition)
            mesh = D.build_differential_mesh(args[0], args[1], sequence, **kwargs, compact_context={'scope': scope})
            self.assertEqual(b''.join(mesh.iter_legacy_json()), expected)
            with self.assertRaises(RuntimeError):
                partition.close()
            view = mesh._compact
            del mesh
            view.close()
            del view, sequence
            partition.close()
            del partition
            gc.collect()
            scope.close()

    def test_invalid_input_and_retained_failure(self):
        budget = WorkBudget(8 << 20)
        scope = create_retained_scope(budget, process_epoch='live-mesh-failure')
        kwargs = dict(grid_lines=((0, 1),)*3, max_geometry_volume_error_m3=1, max_leaves=1, budget=budget)
        messages = []
        for context in (None, {'scope': scope}):
            try:
                E.build_exterior_mesh(None, None, None, **kwargs, compact_context=context)
            except E.V.VolumeError as error:
                messages.append(str(error))
        self.assertEqual(messages[0], messages[1])
        cause = ValueError('original cause')
        def failed_builder(*args, **kwargs):
            held = own = L.own_record({'cells': ['x'*4096]}, budget)
            assert held is own
            raise RuntimeError('original failure') from cause
        caller_value = 'caller must retain its locals'
        before = budget.reserved_bytes
        try:
            L.build(failed_builder, (), {'budget': budget}, {'scope': scope})
        except RuntimeError as error:
            self.assertEqual(str(error), 'original failure')
            self.assertIs(error.__cause__, cause)
            self.assertEqual(caller_value, 'caller must retain its locals')
            self.assertEqual(budget.reserved_bytes, before)
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_actual_builder_failure_releases_geometry_and_preserves_cause(self):
        with ordinary_fixture() as (args, kwargs):
            budget = kwargs['budget']
            scope = create_retained_scope(budget, process_epoch='live-mesh-late-failure')
            before = budget.reserved_bytes
            cause = ValueError('late geometry cause')
            def fail(*args, **kwargs):
                raise RuntimeError('late geometry failure') from cause
            with patch.object(E, '_assemble', fail):
                try:
                    E.build_exterior_mesh(*args, **kwargs, compact_context={'scope': scope})
                except RuntimeError as error:
                    self.assertEqual(str(error), 'late geometry failure')
                    self.assertIs(error.__cause__, cause)
                    self.assertEqual(budget.reserved_bytes, before)
                else:
                    self.fail('missing geometry failure')
            scope.close()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--measure':
        setUpModule()
        try:
            print(json.dumps(measure(sys.argv[2], subdivisions=int(sys.argv[3]) if len(sys.argv) > 3 else 1,
                route=sys.argv[4] if len(sys.argv) > 4 else 'ordinary'), sort_keys=True))
        finally:
            tearDownModule()
    else:
        unittest.main()
