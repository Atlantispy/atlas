"""Bounded synthetic controls only; no Atlas runtime/store import or real-arm read."""
import copy
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

HERE = Path(__file__).resolve().parent


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(raw):
    return sha256(raw).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


class Bindings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.C = load('dump_r5_compare', HERE.parent/'causal-r20/compare_arms_r20.py')
        cls.B = load('dump_r5_binding', HERE/'array_bindings_r5.py')
        cls.D = load('dump_r5_observer', HERE/'dump_arm_r5.py')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fixture-', dir=HERE)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        (self.folder/'arrays').mkdir()
        (self.folder/'records').mkdir()

    def arrays(self, values):
        rows = []
        for index, (name, value) in enumerate(sorted(values.items())):
            raw = value.tobytes()
            filename = '%04d.bin' % index
            (self.folder/'arrays'/filename).write_bytes(raw)
            descriptor = {'dtype': value.dtype.str, 'shape': list(value.shape), 'chunks': []}
            rows.append(dict(name=name, dtype=value.dtype.str, shape=list(value.shape), sha256=digest(raw),
                             nbytes=len(raw), file=filename, descriptor=descriptor,
                             descriptor_sha256=digest(canonical(descriptor))))
        return rows

    def records(self, values):
        found = {}
        for name, value in values.items():
            raw = canonical(value)
            (self.folder/'records'/(name+'.json')).write_bytes(raw)
            found[name] = {'sha256': digest(raw), 'nbytes': len(raw)}
        return found

    @staticmethod
    def snapshot(metadata, arrays):
        return digest(canonical({'metadata': metadata, 'arrays': {
            n: {'shape': list(v.shape), 'sha256': digest(v.tobytes())} for n, v in arrays.items()}}))

    def root_case(self):
        ex = {'heat': np.array([1., 2.]), 'volume_m3': np.array([3., 4.])}
        mesh = {'schema': 'synthetic-mesh', 'cells': ['s0', 's1']}
        body = {'schema': self.C.SPATIAL_STATE_SCHEMA, 'cells': [{'cell_id': 's0'}, {'cell_id': 's1'}],
                'projection_accounts': {'heat': {}}, 'thermal_mesh_id': digest(canonical(mesh))}
        state = dict(body, state_id=self.snapshot(dict(body, thermal_mesh=mesh), ex))
        collar, heat = {'mass': np.array([1., 2.])}, {'enthalpy': np.array([5.])}
        fd, hd = {'schema': 'collar', 'plan_id': 'grid-id'}, {'schema': 'heat', 'plan_id': 'heat-id'}
        identity = {'fields_id': self.snapshot(fd, collar), 'native_state_id': digest(b'native'),
                    'exterior_heat_id': self.snapshot(hd, heat)}
        partition = np.frombuffer(b'{"partition":1}', dtype='u1')
        values = {**{'exterior-fv:'+n: v for n, v in ex.items()}, **collar,
                  **{'exterior_heat:'+n: v for n, v in heat.items()},
                  'partition-record:partition': partition,
                  'partition-dag:one': np.array([1], dtype='<i4'),
                  'spatial-mesh:one': np.array([2], dtype='<i4')}
        rows = self.arrays(values)
        desc = {r['name']: r['descriptor_sha256'] for r in rows}
        metadata = {'key': 'root-key', 'kind': 'root', 'sequence': 0,
                    'native_state_id': identity['native_state_id'],
                    'state': {'schema': self.C.COLLAR_STATE_SCHEMA, 'fields': fd, 'exterior_heat': hd,
                              'result_id': digest(canonical(identity))},
                    'exterior_state': {'state_id': state['state_id'],
                                       'compact_mesh': {'array_bindings': {'one': desc['spatial-mesh:one']}}},
                    'differential_partition': {'record_blobs': {'partition': {
                        'array': 'partition-record:partition', 'bytes': partition.nbytes,
                        'sha256': digest(partition.tobytes())}}},
                    'compact_partition': {'array_bindings': {'one': desc['partition-dag:one']}}}
        dump = {'schema': self.B.SCHEMA, 'interval': 0, 'arrays': rows,
                'records': self.records({'state': state, 'mesh': mesh}),
                'head': {'key': 'root-key', 'kind': 'root', 'sequence': 0, 'root_metadata': metadata}}
        proofs = {'root': {'files': {'runner_record': {'root': {'kind': 'root', 'root_key': 'root-key',
                         'root_metadata_sha256': digest(canonical(metadata))}}}}}
        return dump, proofs

    def test_root_only_all_native_families_bind_to_independent_root(self):
        dump, proofs = self.root_case()
        status, reviews, layout = self.B.bind_all(self.C, dump, proofs, self.folder)
        self.assertEqual(set(status), {r['name'] for r in dump['arrays']})
        self.assertTrue(all(v[0] == 'bound' for v in status.values()))
        self.assertEqual(layout['exterior-fv:heat']['identity'], ['s0', 's1'])
        self.assertFalse(reviews)
        self.assertEqual(layout['mass']['kind'], 'fixed-domain')
        self.assertEqual(layout['mass']['identity'], ['collar-plan-grid', 'grid-id', 'mass'])

    def test_root_metadata_pin_and_complete_family_faults(self):
        dump, proofs = self.root_case()
        for field in ('kind', 'sequence', 'key', 'native_state_id'):
            bad = copy.deepcopy(dump)
            bad['head']['root_metadata'][field] = 'changed'
            with self.subTest(metadata=field), self.assertRaises(self.C.ProofError):
                self.B.bind_all(self.C, bad, proofs, self.folder)
        for name in [r['name'] for r in dump['arrays']]:
            bad = copy.deepcopy(dump)
            bad['arrays'] = [r for r in bad['arrays'] if r['name'] != name]
            with self.subTest(missing=name), self.assertRaises(self.C.ProofError):
                self.B.bind_all(self.C, bad, proofs, self.folder)

    def test_new_payload_hash_cannot_replace_independent_array_binding(self):
        dump, proofs = self.root_case()
        for name in [r['name'] for r in dump['arrays']]:
            bad = copy.deepcopy(dump)
            row = next(r for r in bad['arrays'] if r['name'] == name)
            if name.startswith(('partition-dag:', 'spatial-mesh:')):
                row['descriptor_sha256'] = digest(b'new descriptor')
            else:
                row['sha256'] = digest(b'new self-declared payload')
            with self.subTest(changed=name), self.assertRaises(self.C.ProofError):
                self.B.bind_all(self.C, bad, proofs, self.folder)

    def test_legacy_root_only_stays_review(self):
        dump, proofs = self.root_case()
        dump['schema'] = self.C.DUMP_SCHEMA_R4
        del dump['head']['root_metadata']
        status, reviews, _ = self.B.bind_all(self.C, dump, proofs, self.folder)
        self.assertEqual(status['mass'][0], 'unbound')
        self.assertTrue(any('metadata' in r for r in reviews))
        self.assertTrue(any('legacy dump' in r for r in reviews))

    def interval_case(self):
        dump, proofs = self.root_case()
        fields = {'force': np.array([7., 8.])}
        force_meta = {'schema': 'force'}
        network = {'vertex_ids': np.frombuffer(b'"v0"\n"v1"', dtype='u1'),
                   'vertex_home': np.array([0, 0], dtype='<i8'),
                   'vertex_reference': np.array([[1., 0., 0.], [0., 1., 0.]]),
                   'view_vertex': np.array([0, 1], dtype='<i8'),
                   'view_plate': np.array([0, 0], dtype='<i8'),
                   'view_reference': np.array([[1., 0., 0.], [0., 1., 0.]]),
                   'faces': np.frombuffer(b'{"face_id":"f0"}', dtype='u1'),
                   'boundaries': np.array([], dtype='u1')}
        desc = {'schema': 'synthetic-network', 'plates': [{'plate_id': 'p0'}],
                'arrays': [{'name': n, 'dtype': a.dtype.str, 'shape': list(a.shape)}
                           for n, a in network.items()]}
        network_hash = sha256(canonical(desc))
        for n, a in network.items():
            network_hash.update(b'\0'+canonical([n, a.dtype.str, list(a.shape)]))
            network_hash.update(a.tobytes())
        desc['network_id'] = network_hash.hexdigest()
        records = {'certification': {'force': force_meta,
                   'solution': {'force_exchange_id': self.snapshot(force_meta, fields)}},
                   'differential': {'endpoint_network': desc},
                   'state': {'cells': [{'cell_id': 's0'}, {'cell_id': 's1'}]},
                   'transport': {'schema': 'atlas.spatial-implicit-transport.v1',
                                 'cell_ids': ['collar0', 's1', 's0']}}
        arrays = {'mass': np.array([1., 2.]), 'exterior_heat:enthalpy': np.array([5.]),
                  'exterior-fv:volume_m3': np.array([3., 4.]),
                  'source-audit:energy': np.array([5., 6.]),
                  'spatial-audit:spatial-transport:stock:mass': np.array([6., 7., 8.]),
                  'spatial-audit:joined-heat:temperature_k': np.array([300., 301.]),
                  **{'certification-force:'+n: a for n, a in fields.items()},
                  **{'differential-network:sphere.'+n: a for n, a in network.items()}}
        dump.update(interval=1, arrays=self.arrays(arrays), records=self.records(records))
        dump['head'].update(key='successor-key', kind='successor', sequence=1)
        table = {group: [] for group in self.C.GROUPS}
        for row in dump['arrays']:
            name = row['name']
            if name.startswith(self.C.COMPOSITE_PREFIXES):
                continue
            group, key = 'full_collar', name
            for prefix, target, strip in self.C.DIRECT_PREFIXES:
                if name.startswith(prefix):
                    group, key = target, name[len(prefix):] if strip else name
                    break
            table[group].append({'name': key, 'dtype': row['dtype'], 'shape': row['shape'],
                                 'sha256': row['sha256']})
        table['collar'] = [copy.deepcopy(table['full_collar'][1])]
        table['native'] = [copy.deepcopy(table['full_collar'][1])]
        proofs['interval'] = {'files': {'producer_receipt': {'completed_endpoint': {
            'root_metadata': dump['head']['root_metadata'], 'array_records': table}}}}
        return dump, proofs

    def test_interval_all_families_and_distinct_transport_cell_layout(self):
        dump, proofs = self.interval_case()
        status, reviews, layout = self.B.bind_all(self.C, dump, proofs, self.folder)
        self.assertTrue(all(v[0] == 'bound' for v in status.values()))
        self.assertEqual(layout['spatial-audit:spatial-transport:stock:mass']['identity'],
                         ['collar0', 's1', 's0'])
        self.assertEqual(layout['exterior-fv:volume_m3']['identity'], ['s0', 's1'])
        self.assertEqual(layout['spatial-audit:joined-heat:temperature_k']['kind'], 'positional-unproved')
        self.assertTrue(reviews)

    def test_omitted_composite_and_direct_families_fail(self):
        dump, proofs = self.interval_case()
        for prefix in ('certification-force:', 'differential-network:', 'source-audit:',
                       'spatial-audit:', 'exterior-fv:', 'exterior_heat:'):
            bad = copy.deepcopy(dump)
            bad['arrays'] = [r for r in bad['arrays'] if not r['name'].startswith(prefix)]
            with self.subTest(removed=prefix), self.assertRaises(self.C.ProofError):
                self.B.bind_all(self.C, bad, proofs, self.folder)

    def test_network_order_and_invented_transport_layout_fail(self):
        dump, proofs = self.interval_case()
        path = self.folder/'records/differential.json'
        record = json.loads(path.read_bytes())
        record['endpoint_network']['arrays'].reverse()
        path.write_bytes(canonical(record))
        with self.assertRaises(self.C.ProofError):
            self.B.bind_all(self.C, dump, proofs, self.folder)
        dump, proofs = self.interval_case()
        path = self.folder/'records/transport.json'
        for ids in (['s0', 's1'], ['s0', 's0', 's1'], [1, 2, 3]):
            record = {'schema': 'atlas.spatial-implicit-transport.v1', 'cell_ids': ids}
            path.write_bytes(canonical(record))
            with self.subTest(ids=ids), self.assertRaises(self.C.ProofError):
                self.B.bind_all(self.C, dump, proofs, self.folder)

    def test_network_domain_preserves_home_frame_meaning(self):
        dump, _ = self.interval_case()
        domain = self.B._network_domain(self.C, dump, self.folder)
        self.assertEqual(domain['homes'], [0, 0])
        path = self.folder/'records/differential.json'
        record = json.loads(path.read_bytes())
        record['endpoint_network']['frames'] = [[1, 0, 0, 0]]
        path.write_bytes(canonical(record))
        changed = self.B._network_domain(self.C, dump, self.folder)
        self.assertNotEqual(domain, changed)
        self.assertEqual(domain['vertices'], changed['vertices'])
        self.assertEqual(domain['views'], changed['views'])

    def observation_case(self):
        dump, _ = self.root_case()
        observer = HERE/'dump_arm_r5.py'
        profile = self.folder/'profile.json'
        profile.write_bytes(b'{}')
        arm = {'profile': profile, 'sha256': digest(b'{}'), 'dumps': self.folder}
        environment = self.D.environment()
        environment['cwd'] = str(self.folder)
        environment['argv'] = [str(observer), '--profile', str(profile), '--profile-sha256', arm['sha256'],
          '--interval', '0', '--out', str(self.folder/'i0'), '--observer-path', str(observer),
          '--observer-sha256', digest(observer.read_bytes())]
        dump.update(pid=99999, observer={'path': str(observer)}, environment=environment,
                    environment_after=copy.deepcopy(environment),
                    loaded_audit={'pinned_modules_checked': 2, 'pinned_source_imports': 2,
                      'exempt': {'path': str(observer), 'sha256': digest(observer.read_bytes())},
                      'data_only_exclusion': True, 'first_resolution': True, 'source_bytes_loader': True},
                    interpreter={'interpreter_seed': {'PYTHONHASHSEED': '0', 'hash_randomization': 0},
                      'instrumentation_at_start': {'trace': False, 'profile': False,
                                                  'monitoring_tools': {}, 'tracemalloc': False},
                      'launch_environment': {'OMP_NUM_THREADS': None, 'OPENBLAS_NUM_THREADS': None,
                        'PYTHONHASHSEED': environment['python_environment'].get('PYTHONHASHSEED'),
                        'PYTHONDONTWRITEBYTECODE': environment['python_environment'].get('PYTHONDONTWRITEBYTECODE')}},
                    store_token_before=[digest(b'catalogue'), [0, 1, 2, 3, 4, 5, 0], None],
                    store_token_after=[digest(b'catalogue'), [0, 1, 2, 3, 4, 5, 0], None],
                    bindings={'catalog': {'path': str(profile), 'sha256': digest(b'{}'), 'nbytes': 2},
                              'reader_receipt': {'path': str(profile), 'sha256': digest(b'{}'), 'nbytes': 2}})
        proof = {'files': {'producer_receipt': {'pid': 100}, 'reader_receipt': {'pid': 101}}}
        return dump, arm, proof, digest(observer.read_bytes())

    def test_closed_observer_evidence_accepts_actual_environment(self):
        self.B.validate_dump_evidence(self.C, *self.observation_case())

    def test_observation_faults_fail(self):
        dump, arm, proof, pin = self.observation_case()
        faults = [
            lambda d: d.update(pid=100),
            lambda d: d['head'].update(unexamined=True),
            lambda d: d['loaded_audit'].update(unexamined=True),
            lambda d: d['interpreter'].update(unexamined=True),
            lambda d: d['interpreter']['instrumentation_at_start'].update(trace=0),
            lambda d: d['environment_after'].update(prefix='changed'),
            lambda d: d['environment_after']['python_environment'].update(PYTHONHASHSEED='1'),
            lambda d: d['bindings']['reader_receipt'].update(nbytes=3),
            lambda d: d.update(store_token_before=[digest(b'catalogue')]),
            lambda d: d['store_token_after'].__setitem__(2, [1, 1]),
            lambda d: d['environment']['argv'].__setitem__(2, 'other-profile.json'),
            lambda d: d['environment']['argv'].__setitem__(1, '--unknown'),
            lambda d: d['environment']['argv'].__setitem__(3, '--profile'),
        ]
        for index, fault in enumerate(faults):
            bad = copy.deepcopy(dump)
            fault(bad)
            with self.subTest(fault=index), self.assertRaises(self.C.ProofError):
                self.B.validate_dump_evidence(self.C, bad, arm, proof, pin)

    def test_historical_catalogue_may_advance_and_missing_plan_stays_review(self):
        dump, arm, proof, pin = self.observation_case()
        dump['bindings']['catalog']['sha256'] = digest(b'previous catalogue')
        self.B.validate_dump_evidence(self.C, dump, arm, proof, pin)
        dump, proofs = self.root_case()
        # The source can legitimately lack a retained layout ID; do not invent one.
        del dump['head']['root_metadata']['state']['fields']['plan_id']
        metadata = dump['head']['root_metadata']
        collar = {'mass': np.array([1., 2.])}
        heat = {'enthalpy': np.array([5.])}
        identity = {'fields_id': self.snapshot(metadata['state']['fields'], collar),
                    'native_state_id': metadata['native_state_id'],
                    'exterior_heat_id': self.snapshot(metadata['state']['exterior_heat'], heat)}
        metadata['state']['result_id'] = digest(canonical(identity))
        proofs['root']['files']['runner_record']['root']['root_metadata_sha256'] = digest(canonical(metadata))
        status, review, layout = self.B.bind_all(self.C, dump, proofs, self.folder)
        self.assertEqual(status['mass'][0], 'bound')
        self.assertEqual(layout['mass']['kind'], 'positional-unproved')
        self.assertTrue(any('correspondence' in message for message in review))

    def test_environment_after_is_after_fence_restore_and_guard_stays_false(self):
        self.assertFalse(self.D.EXTRACTION_READY)
        with self.assertRaises(self.D.DumpRefused):
            self.D.dump(SimpleNamespace(), {})
        entered = []

        class Fence:
            def __init__(self, *args):
                pass

            def __enter__(self):
                entered.append(True)
                return self

            def __exit__(self, *args):
                entered.pop()
                return False

        def environment():
            self.assertFalse(entered)
            return {'restored': True}

        with mock.patch.object(self.D, 'EXTRACTION_READY', True), \
                mock.patch.object(self.D, 'ObserverFence', Fence), \
                mock.patch.object(self.D, '_dump'), \
                mock.patch.object(self.D, 'environment', environment):
            record = {'environment': {'restored': True}}
            self.D.dump(SimpleNamespace(profile='', profile_sha256='', observer_path='', observer_sha256=''), record)
            self.assertEqual(record['environment_after'], record['environment'])
        self.assertFalse(self.D.EXTRACTION_READY)


def main():
    if len(sys.argv) != 2:
        raise SystemExit('one new output stem required')
    stem = Path(sys.argv[1])
    if any(stem.with_suffix(ext).exists() for ext in ('.json', '.log')):
        raise SystemExit('preserve existing evidence')
    pins = json.loads((HERE/'SOURCE-PINS.json').read_bytes())['files']
    def changed():
        return [p for p, h in pins.items() if digest(Path(p).read_bytes()) != h]
    if changed():
        raise SystemExit('source pins changed before controls')
    log = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Bindings)
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    changes = changed()
    payload = {'schema': 'plan04-dump-r5-synthetic-controls.v1',
               'status': 'PASS' if result.wasSuccessful() and not changes else 'FAIL',
               'tests': result.testsRun, 'failures': result.failures, 'errors': result.errors,
               'changed_pins': changes, 'source_pins': pins, 'real_arm': False, 'scientific_run': False,
               'readiness': False, 'scope': 'new r5 proof/family/layout boundaries only'}
    payload['failures'] = [(str(t), detail) for t, detail in result.failures]
    payload['errors'] = [(str(t), detail) for t, detail in result.errors]
    stem.with_suffix('.log').write_text(log.getvalue(), encoding='utf8')
    payload['log_sha256'] = digest(stem.with_suffix('.log').read_bytes())
    stem.with_suffix('.json').write_text(json.dumps(payload, indent=2)+'\n', encoding='utf8')
    print(log.getvalue())
    print(json.dumps({k: payload[k] for k in ('status', 'tests', 'changed_pins')}))
    return 0 if payload['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
