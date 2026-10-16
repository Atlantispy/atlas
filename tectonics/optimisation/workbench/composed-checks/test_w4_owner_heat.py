"""W4 check 2: genuine owner-call compact heat parity and cold restore on the frozen composed tree.

Plan W4 item 2 (retires X-5/E8/M14 as far as a composed fixture can). Three fresh
``-B`` children (the runner's own interpreter flags, so the two heat functional
workers engage) execute w4_owner_heat_child.py against R/composed-r1 ONLY,
selected through the composed runner's RestartSources and the reviewed restart
profile (native root, composed helpers and ram, H tests). One child runs at a
time, each after a memory gate. Nothing under composed-r1, I, F, H or CR is
written; every store is new under T/_t/w4-owner-heat/<run>. No historical
database is opened.

  A legacy   ordinary owner and root; genuine advance_spatial (legacy parent and mesh)
  B indexed  owner restored over a compact initial mesh (root stored compact), parent
             collar state with retained-owner bytes (as the migration issues it);
             B2 genuine advance_spatial with the legacy end mesh (published),
             B1 the same owner and transport stage heated with ExteriorMesh.from_compact
  C cold     fresh process: CollarWorkflow.open (its _refresh runs COLD), then
             COLD.restore_checkpoint with the legacy head (C1) and with the head
             re-issued over a compact mesh (C2, the M14 seam and compact _context)

The genuine owner call needs actual PreparedSpatialOwner/SpatialOwnerTransport/
ExteriorMesh objects, so the smallest genuine H fixture (private heat native
joined fixture r2: 2x2x2 native, 4x4x4 collar) replaces a synthetic two-cell mesh.
Not owner acceptance, migration, production or scientific acceptance.
"""
import sys
sys.dont_write_bytecode = True

from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import time
import unittest

import psutil

HERE = Path(__file__).resolve().parent              # R/composed-checks
R = HERE.parent
T = R.parents[3]
RC = R/'composed-r1'
PROFILE = RC/'review'/'restart-profile-s2-r1.json'
PROFILE_SHA256 = 'fffa99257a4e946edd9fe32d926a7c96e2319eec180c7d13782dc927f876de84'
MANIFEST_SHA256 = '6a6f493353942ebd27f10c73105fe7d10f5ab1bef1f4d54e72094ac5dcfe4e9b'
EXECUTION_IDENTITY = '86c819bb9c62d591f0c1e529baae717254f6fa21b28537348fe153146c40c906'
RUNNER = RC/'helpers'/'run_prepared_restart.py'
CHILD = HERE/'w4_owner_heat_child.py'
SCRATCH = T/'_t'/'w4-owner-heat'
LAUNCH_ENV = dict(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONHASHSEED='0',
                  PYTHONDONTWRITEBYTECODE='1')       # run_prepared_restart.LAUNCH_ENV
BOOTSTRAP = "import sys; p = sys.argv[1]; exec(compile(open(p, encoding='utf8').read(), p, 'exec'))"
MIN_AVAILABLE = 3 << 29                             # 1.5 GiB before a child starts
RAM_POLLS, RAM_POLL_SECONDS = 40, 30.
CHILD_TIMEOUT = 1800
WORKERS = 2
EXACT_KEYS = ('exact_corrected_enthalpy_j', 'exact_retained_solver_residual_j',
              'exact_stock_projection_residual_j', 'exact_cell_storage_residual_j',
              'exact_paired_face_energy_j', 'exact_source_energy_j', 'exact_outward_boundary_energy_j',
              'geometry_id', 'cell_ids', 'face_ids', 'state_id', 'plan_id', 'call_id')


def file_sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def heavy_peers():
    """Other large Python processes of this environment (another W4 child, for example)."""
    own = {os.getpid()}
    rows = []
    for process in psutil.process_iter(['pid', 'name', 'exe', 'memory_info']):
        try:
            info = process.info
            if (info['pid'] not in own and info['name'] and info['name'].lower().startswith('python')
                    and info['memory_info'] is not None and info['memory_info'].rss > (400 << 20)):
                rows.append(dict(pid=info['pid'], rss_bytes=info['memory_info'].rss))
        except (psutil.Error, OSError):
            continue
    return rows


def memory_gate(label, log):
    """Wait (bounded) for 1.5 GiB available; prefer no other heavy Python process."""
    for poll in range(RAM_POLLS):
        available, peers = psutil.virtual_memory().available, heavy_peers()
        if available >= MIN_AVAILABLE and (not peers or poll >= RAM_POLLS//2):
            log.append(dict(child=label, polls=poll, available_bytes=available, heavy_peers=peers))
            return
        time.sleep(RAM_POLL_SECONDS)
    log.append(dict(child=label, polls=RAM_POLLS, available_bytes=psutil.virtual_memory().available,
                    heavy_peers=heavy_peers(), refused=True))
    raise unittest.SkipTest('less than 1.5 GiB available after %d polls; not started' % RAM_POLLS)


def kill_tree(process):
    try:
        parent = psutil.Process(process.pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
    except psutil.Error:
        pass


def run_child(mode, run, log, **extra):
    workdir = run/mode
    workdir.mkdir()
    out = workdir/'result.json'
    arguments = dict(mode=mode, runner=str(RUNNER), profile=str(PROFILE), profile_sha=PROFILE_SHA256,
                     workdir=str(workdir), out=str(out), workers=WORKERS, **extra)
    environment = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
    environment.update(LAUNCH_ENV, TMP=str(workdir/'tmp'), TEMP=str(workdir/'tmp'))
    (workdir/'tmp').mkdir()
    memory_gate(mode, log)
    # The real runner starts `python -B run_prepared_restart.py`; heat workers start
    # `python -B <helper> worker` and refuse a caller with other interpreter flags
    # (-I would force the serial fallback). PYTHONPATH/PYTHONHOME are removed and
    # the working directory holds no source, so '' on sys.path imports nothing.
    command = [sys.executable, '-B', '-c', BOOTSTRAP, str(CHILD), json.dumps(arguments)]
    started = time.monotonic()
    with open(workdir/'stdout.txt', 'wb') as stdout, open(workdir/'stderr.txt', 'wb') as stderr:
        process = subprocess.Popen(command, cwd=workdir, env=environment, stdout=stdout, stderr=stderr)
        try:
            code = process.wait(timeout=CHILD_TIMEOUT)
        except subprocess.TimeoutExpired:
            kill_tree(process)
            process.wait()
            code = 'timeout'
    seconds = round(time.monotonic()-started, 3)
    result = json.loads(out.read_text(encoding='utf8')) if out.is_file() else None
    log.append(dict(child=mode, returncode=code, wall_seconds=seconds,
                    command=['<T>/.r44-env/Scripts/python.exe', '-B', '-c', '<bootstrap>',
                             str(CHILD.relative_to(T)), '<arguments>'],
                    status=None if result is None else result.get('status')))
    return result


class OwnerHeatComposed(unittest.TestCase):
    run_dir = None
    results = {}
    log = []

    @classmethod
    def setUpClass(cls):
        if file_sha(PROFILE) != PROFILE_SHA256:
            raise AssertionError('frozen restart profile changed')
        profile = json.loads(PROFILE.read_bytes())
        if (profile['source_manifest']['sha256'] != MANIFEST_SHA256 or
                file_sha(T/profile['source_manifest']['path']) != MANIFEST_SHA256):
            raise AssertionError('frozen composed manifest changed')
        SCRATCH.mkdir(parents=True, exist_ok=True)
        cls.run_dir = SCRATCH/datetime.now().strftime('run-%Y%m%d-%H%M%S')
        cls.run_dir.mkdir()                                       # never reuse or overwrite a run
        cls.results['legacy'] = run_child('legacy', cls.run_dir, cls.log)
        cls.results['indexed'] = run_child('indexed', cls.run_dir, cls.log)
        indexed = cls.results['indexed']
        if indexed is not None and indexed.get('status') == 'PASS_CHILD_COMPLETED':
            cls.results['cold'] = run_child('cold', cls.run_dir, cls.log,
                                            b_result=str(cls.run_dir/'indexed'/'result.json'))
        (cls.run_dir/'harness-log.json').write_text(json.dumps(cls.log, indent=2, sort_keys=True), encoding='utf8')

    def child(self, mode):
        result = self.results.get(mode)
        self.assertIsNotNone(result, mode+' child wrote no result')
        self.assertEqual(result['status'], 'PASS_CHILD_COMPLETED',
                         mode+': '+str(result.get('error'))+'\n'+str(result.get('traceback', ''))[-4000:])
        return result

    def heats(self):
        legacy, indexed = self.child('legacy'), self.child('indexed')
        return dict(A=legacy['heat'], B2=indexed['advance_heat'], B1=indexed['compact_heat'])

    def test_1_children_selected_only_the_frozen_composed_tree(self):
        for mode in ('legacy', 'indexed', 'cold'):
            result = self.child(mode)
            with self.subTest(mode=mode):
                self.assertEqual(result['proof'], result['proof_after'])
                self.assertEqual(result['proof']['source_manifest_sha256'], MANIFEST_SHA256)
                self.assertEqual(result['execution_provenance'],
                                 dict(execution_identity=EXECUTION_IDENTITY, execution_mode='strict'))
                self.assertEqual(result['imports']['atlas_outside_native_root'], [])
                self.assertEqual(result['imports']['outside_selected_roots'], [])
                self.assertEqual(result['launch_environment'], LAUNCH_ENV)
                self.assertIsNone(result['memory_guard_stop'])
                self.assertEqual([Path(p).resolve() for p in result['sys_path_head']],
                                 [RC/'runtime-src', RC/'helpers', RC/'ram',
                                  T/'fidelity-integration-20261005'/'heat-repair-20261007'/'source'/'tectonics'/'tests'])

    def test_1b_heat_functional_workers_engaged(self):
        for mode, expected in (('legacy', 1), ('indexed', 3)):      # B2, B1, B3
            report = self.child(mode)['workers']
            with self.subTest(mode=mode):
                self.assertEqual(report['workers'], WORKERS)
                self.assertEqual(len(report['calls']), expected)
                self.assertEqual(report['fallbacks'], [])
                for call in report['calls']:
                    self.assertEqual((call['workers'], call['fallback']), (WORKERS, None))
                    self.assertGreater(call['collected'], 0)

    def test_2_genuine_owner_calls_not_fixtures(self):
        for label, heat in self.heats().items():
            with self.subTest(heat=label):
                self.assertTrue(heat['live_joined_heat'])
                self.assertIs(heat['call_fixture'], False)
                self.assertIs(heat['header']['genuine_forward_origin'], True)
                self.assertEqual(heat['header']['origin_binding_status'], 'FORWARD_ACTUAL_OWNER_SNAPSHOT')
                self.assertIs(heat['header']['production_acceptance'], False)
                self.assertTrue(heat['consumer_sources_match_ram_pins'])
                self.assertEqual((heat['origin']['owner'], heat['origin']['step'], heat['mesh']['type']),
                                 ('PreparedSpatialOwner', 'SpatialOwnerTransport', 'ExteriorMesh'))
                self.assertTrue(heat['origin']['snapshot_is_result'])
        heats = self.heats()
        self.assertEqual([heats[k]['mesh']['is_compact'] for k in ('A', 'B2', 'B1')], [False, False, True])
        self.assertEqual([heats[k]['geometry']['encoded_is_none'] for k in ('A', 'B2', 'B1')], [False, False, True])
        self.assertTrue(heats['B1']['geometry']['indexed'])
        self.assertTrue(heats['B1']['same_step_object_as_B2'])
        self.assertTrue(heats['B1']['same_owner_object_as_B2'])
        self.assertTrue(heats['B1']['whole_export_refusals']['compact_mesh_record'].startswith('VolumeError'))
        self.assertNotEqual(heats['B1']['whole_export_refusals']['indexed_metric_record'], 'ACCEPTED')

    def test_3_post_migration_types_reach_the_live_owner_call(self):
        heats, indexed = self.heats(), self.child('indexed')
        self.assertEqual(heats['A']['origin']['parent'], dict(snapshot='RegionalMechanicalSnapshot', metadata='bytes'))
        self.assertFalse(self.child('legacy')['root']['compact_root'])
        self.assertTrue(indexed['root']['compact_root'])
        self.assertEqual(indexed['root']['initial'], dict(snapshot='IndexedSpatialSnapshot', metadata='_RecordBytes'))
        for label in ('B2', 'B1'):
            origin = heats[label]['origin']
            self.assertEqual(origin['parent'], dict(snapshot='IndexedSpatialSnapshot', metadata='_RecordBytes'))
            for name in ('source_parent_native', 'source_parent_fields'):
                self.assertEqual(origin[name], dict(snapshot='RegionalMechanicalSnapshot',
                                                    metadata='_RetainedSnapshotBytes'), label+' '+name)
            for name in ('result', 'source_inventory', 'native_source_inventory'):
                self.assertEqual(origin[name]['metadata'], 'bytes', label+' '+name)
        self.assertEqual(indexed['retained_parent']['result_id'], indexed['retained_parent']['plain_result_id'])

    def test_4_public_arrays_byte_identical(self):
        heats = self.heats()
        reference = heats['A']
        self.assertGreater(len(reference['arrays']), 0)
        for label in ('B2', 'B1'):
            with self.subTest(heat=label):
                self.assertEqual(sorted(heats[label]['arrays']), sorted(reference['arrays']))
                for name, value in reference['arrays'].items():
                    self.assertEqual(heats[label]['arrays'][name], value, name)
                self.assertEqual(heats[label]['call_arrays'], reference['call_arrays'])

    def test_5_exact_accounts_plan_and_call_identical(self):
        heats = self.heats()
        reference = heats['A']
        for label in ('B2', 'B1'):
            with self.subTest(heat=label):
                for key in EXACT_KEYS:
                    self.assertEqual(heats[label]['descriptor'][key], reference['descriptor'][key], key)
                self.assertEqual(heats[label]['plan'], reference['plan'])
                self.assertEqual(heats[label]['call_meta'], reference['call_meta'])
                differing = sorted(k for k in set(reference['descriptor']) | set(heats[label]['descriptor'])
                                   if heats[label]['descriptor'].get(k) != reference['descriptor'].get(k))
                self.assertEqual(differing, [])
                self.assertEqual(heats[label]['result_id'], reference['result_id'])

    def test_6a_frozen_independent_reopen_of_composed_successor(self):
        """The reader's route on the unmodified frozen tree: open -> _refresh -> COLD -> validate_exchange."""
        frozen = self.child('cold')['frozen_open']
        self.assertEqual(frozen['status'], 'OPENED', json.dumps(frozen, indent=1))

    def test_6b_cold_restore_through_composed_indexed_route(self):
        """COLD.restore_checkpoint itself (no validate_saved_exchange gate) on the frozen tree;
        the reopen and validate_exchange use the in-memory diagnostic only if 6a refused."""
        indexed, cold = self.child('indexed'), self.child('cold')
        published, heat = indexed['published'], indexed['advance_heat']
        self.assertEqual(cold['opened']['head_key'], published['head_key'])
        self.assertEqual(cold['opened']['exterior_state_id'], published['exterior_state_id'])
        self.assertEqual(cold['opened']['collar_result_id'], published['collar_result_id'])
        self.assertEqual(cold['opened']['intervals'], 1)
        self.assertTrue(cold['opened']['parent_compact'])
        self.assertTrue(cold['indexed_head_logical_bytes_equal'])
        for name, value in cold['stored_audit_arrays'].items():
            self.assertEqual(value, heat['arrays'][name], name)
        rows = cold['cold']
        self.assertEqual(len(rows), 2)
        for label, row in rows.items():
            with self.subTest(route=label):
                self.assertEqual(row['binding_type'], 'RestoredHeatBinding')
                self.assertIs(row['fixture_only'], False)
                self.assertEqual(row['result_id'], published['joined_heat_id'])
                for key in EXACT_KEYS:
                    self.assertEqual(row['descriptor'][key], heat['descriptor'][key], key)
                self.assertEqual(row['descriptor'], heat['descriptor'])
                self.assertEqual(row['arrays'], {k: heat['arrays'][k] for k in row['arrays']})
                self.assertEqual(sorted(row['arrays']), sorted(cold['stored_audit_arrays']))
                self.assertEqual(row['parent'], dict(snapshot='IndexedSpatialSnapshot', metadata='_RecordBytes'))
                self.assertEqual(row['reserved_after'], row['reserved_before'])
        c1, c2 = (rows[k] for k in sorted(rows))
        self.assertEqual((c1['head']['snapshot'], c1['mesh_is_compact'], c1['geometry']['encoded_is_none']),
                         ('RegionalMechanicalSnapshot', False, False))
        self.assertEqual((c2['head']['snapshot'], c2['mesh_is_compact'], c2['geometry']['encoded_is_none']),
                         ('IndexedSpatialSnapshot', True, True))
        # The real route (indexed parent, legacy head) must pass the whole seam. C2's
        # validate_exchange outcome is reported, not asserted: no composed successor
        # head can be indexed (advance_spatial and heat_from_spatial need mesh.record()).
        self.assertEqual(c1['validate_exchange']['status'], 'PASSED', c1['validate_exchange'])
        self.assertEqual(c2['streams']['metric_identity'] > 0, True)

    def test_7a_frozen_same_process_reopen_after_publication(self):
        """The runner's own post-publication _refresh on the unmodified frozen tree."""
        same = self.child('indexed')['same_process_cold']
        self.assertEqual(same['status'], 'PASSED', json.dumps(same, indent=1))

    def test_7b_retained_snapshot_bytes_concern(self):
        indexed = self.child('indexed')
        mechanism = indexed['decoder_mechanism']
        self.assertEqual(mechanism['retained_metadata_type'], '_RetainedSnapshotBytes')
        for label in ('issuer_snapshot_identity', 'ram_context_snapshot'):
            self.assertTrue(mechanism[label+':retained'].startswith('refused: ValueError: Owned ensure_ascii'),
                            mechanism)
            self.assertEqual(mechanism[label+':plain'], 'accepted')
        # The live owner call and publication ran with the retained parent (test 3);
        # the reopen re-restores the parent collar from the store as plain bytes.
        same = indexed.get('same_process_cold_diagnostic', indexed['same_process_cold'])
        self.assertEqual(same['intervals'], 1)
        self.assertFalse(same['restored_collar_parent_is_retained'])
        self.assertEqual(same['head_collar']['metadata'], 'bytes')
        legacy_heat = indexed['legacy_mesh_owner_heat']
        self.assertEqual(legacy_heat['result_id'], indexed['advance_heat']['result_id'])
        self.assertTrue(legacy_heat['arrays_equal_B2'])

    def test_8_metric_identity_measured(self):
        indexed = self.child('indexed')
        for key in ('metric_identity_legacy', 'metric_identity_indexed'):
            self.assertTrue(indexed[key]['matches'], key)
        self.assertTrue(indexed['metric_identity_indexed']['indexed'])
        self.assertEqual(indexed['metric_identity_indexed']['logical_json_bytes'],
                         indexed['metric_identity_legacy']['logical_json_bytes'])
        self.assertGreater(indexed['compact_heat']['streams_during_owner_call']['metric_identity'], 0)
        self.assertTrue(indexed['indexed_parent_identity']['matches'])
        self.assertGreater(indexed['legacy_mesh_owner_heat']['streams']['indexed_snapshot_identity'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
