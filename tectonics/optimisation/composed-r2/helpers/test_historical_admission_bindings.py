"""Admission bindings: workspace-anchored H, live successor guard pins, successor reader.

Only tiny fixtures are created. Historical evidence JSON is read with its pin
checked; the historical SQLite database is never opened, hashed or copied. The
live fence drills launch only tiny workloads under the composed guard copies.
"""
import ast
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[3]
RUNTIME = HERE.parent/'runtime-integration-r1'
sys.path.insert(0, str(RUNTIME/'runtime-src'))

import historical_admission as A
import resource_guard_patch as P
from test_resource_guard_patch import compose_successor, original_inputs

H = WORKSPACE/'fidelity-integration-20261005/heat-repair-20261007'
DIAGNOSTICS = HERE.parent/'monitored-continuation-r1'/P.DIAGNOSTICS_NAME
REVIEWED = (
    (('private_heat_reader_memory_r3', 'cfec1f1ea62e3bf0fc2e3d1d9d9ca7d7be408fa1949e571baaf443dc4a324155'),
     ('private_heat_recovery_consumer_r4', 'f78b73eb28b172dbb82f357d1373f08434707a6b1bc885d2062d7cfdec219485'),
     ('private_heat_recovery_admission_r1', '8da3151edd7e624b2453d2c170db93371d9694c51e1d65e212d1100aff9fbe36')),
    (('heat-original-connected-20261013-r9.json', 'ca35700a8106d46eb67c876cd15fb5bf86d6abee7480cc94a23acbef68bb4f0d'),
     ('heat-original-connected-20261013-r9.guard.json', 'c60db8c1d74c4ec48bf65d7e65e277aa4c2871f71b1fb2419b8a2b8dd85584eb'),
     ('reader-memory-20261013-r3.json', 'd85b8d4fd5f90326feb6bc393b559b80612ca9420da4ba8bf2649458a7f57904'),
     ('reader-memory-20261013-r3.guard.json', '0aeb93a08365675ded06e542dc5c00dc315725bf1f2abf8bc4828a6ec17d42a3'),
     ('reader-memory-preparation-r3.json', 'a4cfde7c46070b0fd0dd79cf6b2dcf13d7c4ea2a358e9ba7726ff11eaeb2973a')),
    'heat-original-connected-20261013-r9.artifacts/native-joined.sqlite',
    '3f70c26de17535a96b7ddd494aee72900decee272ae0f88edab3a42af1548899')


def file_sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def pinned_evidence(name):
    pin = dict(A._REVIEWED_ORIGINAL.evidence)[name]
    raw = (A.HISTORICAL_ROOT/name).read_bytes()
    assert sha256(raw).hexdigest() == pin, name
    return json.loads(raw)


class RootBinding(unittest.TestCase):
    def test_root_is_original_tree_from_r_and_composed_helpers(self):
        self.assertEqual(A.HISTORICAL_ROOT, H)
        self.assertEqual(A.HISTORICAL_ROOT, HERE.parents[2]/'heat-repair-20261007')
        self.assertTrue((A.HISTORICAL_ROOT/P.GUARD_NAME).is_file())
        with tempfile.TemporaryDirectory(prefix='.hab-', dir=HERE) as temporary:
            helpers = Path(temporary)/'composed-r1/helpers'
            helpers.mkdir(parents=True)
            copy = helpers/'historical_admission.py'
            copy.write_bytes(Path(A.__file__).read_bytes())
            name = 'historical_admission_composed_fixture'
            spec = importlib.util.spec_from_file_location(name, copy)
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            finally:
                sys.modules.pop(name, None)
            self.assertEqual(module.HISTORICAL_ROOT, H)
            self.assertEqual(module._SELF_SHA, A._SELF_SHA)
            # The old depth-relative rule would name a non-existent sibling of R's parents.
            self.assertFalse((helpers.parents[2]/'heat-repair-20261007').exists())

    def test_workspace_anchor_must_be_unique(self):
        base = Path(tempfile.gettempdir()).resolve()
        if base.is_relative_to(WORKSPACE):
            self.skipTest('system temporary directory lies inside the task workspace')
        with tempfile.TemporaryDirectory(prefix='hab-') as temporary:
            outer = Path(temporary)/'outer'
            inner = outer/'nested'
            deep = inner/'a/b/c'
            deep.mkdir(parents=True)
            with self.assertRaisesRegex(A.HistoricalAdmissionRefused, 'unique Atlas task workspace'):
                A._historical_root(deep)
            for root in (outer, inner):
                (root/'.r44-env').mkdir()
                (root/A.HISTORICAL_RELATIVE).mkdir(parents=True)
                if root is outer:
                    self.assertEqual(A._historical_root(deep), outer/A.HISTORICAL_RELATIVE)
            with self.assertRaisesRegex(A.HistoricalAdmissionRefused, 'unique Atlas task workspace'):
                A._historical_root(deep)
            (inner/'.r44-env').rmdir()
            self.assertEqual(A._historical_root(deep), outer/A.HISTORICAL_RELATIVE)


class PinBindings(unittest.TestCase):
    def test_live_guard_pin_is_the_reviewed_successor(self):
        guard, job, diagnostics = original_inputs()
        self.assertEqual(A.GUARD_PIN, P.SUCCESSOR_PIN)
        self.assertEqual(A.GUARD_PIN, sha256(P.transform(guard)).hexdigest())
        self.assertNotEqual(A.GUARD_PIN, A.HISTORICAL_GUARD_PIN)
        self.assertEqual(A.JOB_PIN, P.JOB_PIN)
        self.assertEqual(A.JOB_PIN, sha256(job).hexdigest())
        self.assertEqual(A.DIAGNOSTICS_PIN, P.DIAGNOSTICS_PIN)
        self.assertEqual(A.DIAGNOSTICS_PIN, sha256(diagnostics).hexdigest())
        self.assertEqual(A.DIAGNOSTICS_PIN, 'c0430517414e7b8aa2bc3a7a9e82143be8351bd0a03f3fd08daa993b64e5ee72')

    def test_historical_guard_receipts_and_review_profile_unchanged(self):
        self.assertEqual((A._REVIEWED_ORIGINAL.metadata_sources, A._REVIEWED_ORIGINAL.evidence,
                          A._REVIEWED_ORIGINAL.database_name, A._REVIEWED_ORIGINAL.database_sha256), REVIEWED)
        self.assertEqual(A.HISTORICAL_GUARD_PIN, P.GUARD_PIN)
        self.assertEqual(A.HISTORICAL_GUARD_PIN, file_sha(A.HISTORICAL_ROOT/P.GUARD_NAME))
        # The historical producer and reader ran under the ORIGINAL r3 guard.
        for name in ('heat-original-connected-20261013-r9.json', 'reader-memory-20261013-r3.json'):
            sources = pinned_evidence(name)['participating_imported_helper_sources']
            self.assertEqual(sources[P.GUARD_NAME], A.HISTORICAL_GUARD_PIN)
            self.assertEqual(sources[P.JOB_NAME], A.JOB_PIN)
        for name in ('heat-original-connected-20261013-r9.guard.json', 'reader-memory-20261013-r3.guard.json'):
            self.assertEqual(pinned_evidence(name)['schema'], 'atlas.private.continuation-guard.r3')

    def test_fence_order_and_public_issuer_use_the_shared_fence(self):
        tree = ast.parse(Path(A.__file__).read_text(encoding='utf8'))
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        fences = [ast.unparse(call) for call in ast.walk(functions['guardian_fence'])
                  if isinstance(call, ast.Call) and ast.unparse(call.func) == '_loaded_source_fence']
        self.assertEqual(fences, ['_loaded_source_fence(module, GUARD_PIN, check)',
            '_loaded_source_fence(job, JOB_PIN, check)', '_loaded_source_fence(diagnostics, DIAGNOSTICS_PIN, check)'])
        body = [ast.unparse(statement) for statement in functions['admit_historical_endpoint'].body]
        fence = body.index('guardian_fence(guard, budget=budget, check=check)')
        self.assertLess(fence, next(i for i, line in enumerate(body) if '_admit(store' in line))
        self.assertNotIn('HISTORICAL_GUARD_PIN', ast.unparse(functions['guardian_fence']))


FENCE_WORKLOAD = '''"""Tiny live-fence fixture under a launched guard. No scientific imports."""
import json
import os
from pathlib import Path
import sys
import types

import private_heat_continuation_guard_r3 as G


class Budget:
    """Identity-only stand-in; the guard records its statistics at each sync."""
    def statistics(self):
        return dict(fixture=True)


def main():
    output, source = Path(sys.argv[1]), sys.argv[2]
    sys.path.append(source)
    import historical_admission as A
    record = dict(status='STARTED', pid=os.getpid(), phases=[], errors=[], cases={})
    with output.open('x', encoding='utf-8') as stream:
        json.dump(record, stream)
    save = lambda: G._write(output, record)
    guard = G.ContinuationGuard(output, record, save)
    guard.phase('fence')
    budget = Budget()
    guard.budget = budget
    check = lambda: guard.check(force=True)
    def attempt(name, **changes):
        try:
            A.guardian_fence(guard, budget=changes.get('budget', budget), check=check)
            record['cases'][name] = 'ACCEPTED'
        except A.HistoricalAdmissionRefused as error:
            record['cases'][name] = 'REFUSED: '+str(error)
        except Exception as error:
            record['cases'][name] = 'ERROR: '+repr(error)
    attempt('successor')
    if hasattr(G, 'RESOURCE_DIAGNOSTICS'):
        D = sys.modules['private_heat_resource_diagnostics_r1']
        attempt('foreign-budget', budget=Budget())
        pin = A.GUARD_PIN
        A.GUARD_PIN = A.HISTORICAL_GUARD_PIN
        attempt('historical-pin')
        A.GUARD_PIN = pin
        pin = A.DIAGNOSTICS_PIN
        A.DIAGNOSTICS_PIN = '0'*64
        attempt('diagnostics-pin')
        A.DIAGNOSTICS_PIN = pin
        function = D.sample_job
        D.sample_job = lambda *args: None
        attempt('diagnostics-code-replaced')
        D.sample_job = function
        G.RESOURCE_DIAGNOSTICS = types.ModuleType('private_heat_resource_diagnostics_r1')
        attempt('diagnostics-binding-replaced')
        G.RESOURCE_DIAGNOSTICS = D
        del sys.modules['private_heat_resource_diagnostics_r1']
        attempt('diagnostics-unloaded')
        sys.modules['private_heat_resource_diagnostics_r1'] = D
        limits = guard._control['limits']
        guard._control['limits'] = dict(limits, rss_bytes=13 << 30)
        attempt('raised-ceiling')
        guard._control['limits'] = dict(limits, rss_bytes=11 << 30)
        attempt('receipt-limits-differ')
        guard._control['limits'] = limits
        attempt('restored')
    guard.close()
    record['status'] = 'PASS_SYNTHETIC_FENCE'
    save()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
'''


@unittest.skipUnless(os.name == 'nt', 'Windows job-object integration')
class LiveGuardFence(unittest.TestCase):
    def launch(self, *, successor):
        temporary = tempfile.TemporaryDirectory(prefix='hgf-')
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        if successor:
            pins = compose_successor(folder)
            self.assertEqual(pins[P.GUARD_NAME], A.GUARD_PIN)
        else:
            guard, job, _ = original_inputs()
            (folder/P.GUARD_NAME).write_bytes(guard)
            (folder/P.JOB_NAME).write_bytes(job)
        (folder/'fence_workload.py').write_text(FENCE_WORKLOAD, encoding='utf8')
        output = folder/'run.json'
        result = subprocess.run([sys.executable, '-B', str(folder/P.GUARD_NAME), '--launch', '--output', str(output),
            '--', sys.executable, '-B', str(folder/'fence_workload.py'), str(output), str(HERE)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW)
        receipt = json.loads(output.with_suffix('.guard.json').read_bytes())
        record = json.loads(output.read_bytes())
        self.assertEqual(result.returncode, 0, result.stderr + repr(receipt))
        self.assertEqual((receipt['status'], receipt['workload_exit_code']), ('STOPPED', 0))
        self.assertEqual(receipt['cleanup'], dict(remaining=[], action_errors=[]))
        self.assertEqual(record['status'], 'PASS_SYNTHETIC_FENCE')
        return record['cases']

    def test_successor_guard_and_diagnostics_fences(self):
        cases = self.launch(successor=True)
        self.assertEqual(cases.pop('successor'), 'ACCEPTED')
        self.assertEqual(cases.pop('restored'), 'ACCEPTED')
        expected = {'foreign-budget': 'live shared-budget guardian', 'historical-pin': 'loaded guard source bytes differ',
            'diagnostics-pin': 'loaded guard source bytes differ', 'diagnostics-code-replaced': 'loaded guarded function',
            'diagnostics-binding-replaced': 'diagnostics binding replaced', 'diagnostics-unloaded': 'diagnostics binding replaced',
            'raised-ceiling': '12 GiB ceiling', 'receipt-limits-differ': 'exact limits'}
        self.assertEqual(set(cases), set(expected))
        for name, message in expected.items():
            self.assertTrue(cases[name].startswith('REFUSED: ') and message in cases[name], (name, cases[name]))

    def test_original_r3_guard_bytes_are_refused_by_the_live_fence(self):
        cases = self.launch(successor=False)
        self.assertEqual(set(cases), {'successor'})
        self.assertIn('REFUSED: loaded guard source bytes differ', cases['successor'])


class SuccessorReadonly(unittest.TestCase):
    def setUp(self):
        from atlas_tectonics.resources import WorkBudget
        from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression
        import numpy as np
        self.temporary = tempfile.TemporaryDirectory(prefix='hsr-')
        self.folder = Path(self.temporary.name)
        self.budget = WorkBudget(64 << 20)
        self.limits = StoreLimits(chunk_bytes=128, max_array_bytes=1 << 20, max_store_bytes=8 << 20,
            max_manifest_bytes=65536, verified_cache_entries=32, sqlite_cache_bytes=65536, codec_workspace_bytes=65536)
        self.compression = Compression()
        self.path = self.folder/'successor.sqlite'
        with ArrayStore(self.path, self.limits, budget=self.budget) as store:
            store.put('a'*64, {'field': np.arange(40, dtype=np.float64)}, {'fixture': 'successor copy'},
                      budget=self.budget)
        self.sha = file_sha(self.path)
        self.stat = self.path.stat()

    def tearDown(self):
        import gc
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.temporary.cleanup()

    def open(self, **changes):
        args = dict(expected_sha256=self.sha, limits=self.limits, compression=self.compression, budget=self.budget)
        args.update(changes)
        return A.open_successor_readonly(self.path, **args)

    def assert_unchanged(self):
        self.assertEqual(file_sha(self.path), self.sha)
        self.assertEqual((self.path.stat().st_size, self.path.stat().st_mtime_ns),
                         (self.stat.st_size, self.stat.st_mtime_ns))
        self.assertFalse(any(Path(str(self.path)+s).exists() for s in ('-wal', '-journal', '-shm')))

    def test_hash_checked_readonly_view_never_writes_or_admits(self):
        calls = []
        with self.open(check=lambda: calls.append(1)) as store:
            self.assertGreater(len(calls), 0)
            self.assertEqual(store.metadata('a'*64), {'fixture': 'successor copy'})
            self.assertIs(store._historical_readonly, A._SUCCESSOR_READONLY)
            self.assertEqual(store._db.execute('PRAGMA query_only').fetchone(), (1,))
            with self.assertRaises(sqlite3.OperationalError):
                store._db.execute('DELETE FROM chunks')
            review = A._Review((), (), self.path.name, self.sha)
            with self.assertRaisesRegex(A.HistoricalAdmissionRefused, 'ORIGINAL readonly store'):
                A._admit(store, root=self.folder, review=review, budget=self.budget, check=lambda: None)
        self.assert_unchanged()

    def test_refusals_before_any_open_or_reservation(self):
        from atlas_tectonics.resources import WorkBudget
        fresh = WorkBudget(64 << 20)
        cases = (dict(expected_sha256='0'*64), dict(expected_sha256=self.sha.upper()),
                 dict(limits={'chunk_bytes': 128}), dict(budget=object()))
        for changes in cases:
            with self.subTest(changes=sorted(changes)), self.assertRaises(A.HistoricalAdmissionRefused):
                self.open(**dict(dict(budget=fresh), **changes))
        journal = Path(str(self.path)+'-journal')
        journal.write_bytes(b'')
        with self.assertRaisesRegex(A.HistoricalAdmissionRefused, 'sidecars'):
            self.open(budget=fresh)
        journal.unlink()
        with self.assertRaisesRegex(A.HistoricalAdmissionRefused, 'historical tree'):
            A.open_successor_readonly(A.HISTORICAL_ROOT/P.GUARD_NAME, expected_sha256=A.HISTORICAL_GUARD_PIN,
                limits=self.limits, compression=self.compression, budget=fresh)
        from concurrent.futures import CancelledError
        def cancelled():
            raise CancelledError('fixture cancellation')
        with self.assertRaises(CancelledError):
            self.open(check=cancelled, budget=fresh)
        self.assertEqual((fresh.reserved_bytes, fresh.peak_reserved_bytes), (0, 0))
        self.assert_unchanged()

    def test_file_replaced_between_hash_and_open_refuses_and_releases(self):
        original = A._open_readonly
        def replaced(path, *args, **kwargs):
            # A same-content rewrite still changes the identity the hash vouched for.
            os.utime(path, ns=(self.stat.st_atime_ns, self.stat.st_mtime_ns+10**9))
            return original(path, *args, **kwargs)
        with patch.object(A, '_open_readonly', side_effect=replaced), \
                self.assertRaisesRegex(A.HistoricalAdmissionRefused, 'changed while opening'):
            self.open()
        import gc
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
