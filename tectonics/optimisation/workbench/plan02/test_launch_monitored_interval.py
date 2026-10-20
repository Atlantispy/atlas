"""Launcher preflight/postcheck controls plus trivial guarded seed/hooks children.

The fixture runner mirrors only the runner interface the launcher uses
(RestartProfile.read, command(), RestartSources.verify); its workload imports
nothing scientific. A tiny fixture file stands in for the original database,
and the explicitly booked gate is met by an injected probe in the test harness only; the
launcher's CLI has no limit option. Synthetic receipts are never a restart PASS.
"""
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import launch_monitored_interval as L
import route2_gate as RG
import start_gate as SG
import resource_guard_patch as P
from test_resource_guard_patch import compose_successor

HERE = Path(__file__).resolve().parent
ORIGINAL_BYTES = b'fixture stand-in for the original database; not a database\n'
HARNESS = '''import sys
sys.path.insert(0, sys.argv[1])
import launch_monitored_interval as L
L._available_bytes = lambda: 16 << 30
L._pending_reboot = lambda: []
L.ORIGINAL_DATABASE = (sys.argv[2], sys.argv[3])
raise SystemExit(L.main(sys.argv[4:]))
'''

FIXTURE_RUNNER = '''"""Launcher test runner: the runner interface shape around a trivial workload."""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import route2_gate as RG
import start_gate as SG

HERE = Path(__file__).resolve().parent


class RestartRefused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise RestartRefused(message)


@dataclass(frozen=True)
class RestartProfile:
    path: Path
    sha256: str
    _record: bytes

    @classmethod
    def read(cls, path, pin):
        path = Path(path).resolve()
        raw = path.read_bytes()
        require(sha256(raw).hexdigest() == pin, 'pinned configuration changed')
        return cls(path, pin, raw)

    def record(self):
        return json.loads(self._record)


class RestartSources:
    def __init__(self, profile):
        self.profile = profile

    def verify(self):
        row = self.profile.record()
        workspace = Path(row['workspace'])
        raw = (workspace/row['source_manifest']['path']).read_bytes()
        require(sha256(raw).hexdigest() == row['source_manifest']['sha256'], 'pinned manifest changed')
        for name, pin in json.loads(raw)['files'].items():
            require(sha256((workspace/name).read_bytes()).hexdigest() == pin, 'participating source changed: '+name)
        return dict(source_manifest_sha256=row['source_manifest']['sha256'], native_source_digest='fixture-only')


def gate_key(profile, python, *, stop_before_advance=False, dev_timing=False):
    return RG.command_key(profile, python, entry=HERE/'fixture_workload.py', step='producer',
                          stop_before_advance=stop_before_advance, dev_timing=dev_timing)


def command(profile, python, *, stop_before_advance=False, start_gate=None):
    RestartSources(profile).verify()
    row = profile.record()
    output = Path(row['output_directory'])
    require(output.parent.is_dir() and not output.exists(), 'exclusive new output directory required')
    guard = Path(row['workspace'])/row['modules']['private_heat_continuation_guard_r3']
    return [str(python), '-B', str(guard), '--launch', '--output', str(output/'run.json'), '--',
            str(python), '-B', str(HERE/'fixture_workload.py'), '--workload',
            '--profile', str(profile.path), '--profile-sha256', profile.sha256,
            *(['--stop-before-advance'] if stop_before_advance else []),
            *([SG.ARGUMENT, SG.encode(start_gate)] if start_gate is not None else [])]
'''

FIXTURE_WORKLOAD = '''"""Trivial guarded seed/hooks child for launcher tests. No scientific imports."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import private_heat_continuation_guard_r3 as G

PROBE = 'import json,os,sys; print(json.dumps([os.environ.get("PYTHONHASHSEED"), sys.flags.hash_randomization]))'


def main():
    args = sys.argv[1:]
    row = json.loads(Path(args[args.index('--profile')+1]).read_bytes())
    output = Path(row['output_directory'])/'run.json'
    record = dict(schema='atlas.prepared-restart-result.v1', status='STARTED', pid=os.getpid(),
        profile_sha256=args[args.index('--profile-sha256')+1], errors=[], production_acceptance=False,
        fixture='launcher seed/hooks fixture only; not a restart')
    with output.open('x', encoding='utf-8') as stream:
        json.dump(record, stream)
    save = lambda: G._write(output, record)
    guard = G.ContinuationGuard(output, record, save)
    guard.phase('fixture-start')
    child = subprocess.run([sys.executable, '-B', '-c', PROBE], capture_output=True, text=True, timeout=30,
                           stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    record['interpreter'] = dict(PYTHONHASHSEED=os.environ.get('PYTHONHASHSEED'),
        hash_randomization=sys.flags.hash_randomization, gettrace=repr(sys.gettrace()),
        getprofile=repr(sys.getprofile()), monitoring=[sys.monitoring.get_tool(i) for i in range(6)],
        OPENBLAS_NUM_THREADS=os.environ.get('OPENBLAS_NUM_THREADS'), OMP_NUM_THREADS=os.environ.get('OMP_NUM_THREADS'),
        PYTHONDONTWRITEBYTECODE=os.environ.get('PYTHONDONTWRITEBYTECODE'), dont_write_bytecode=sys.dont_write_bytecode,
        child=json.loads(child.stdout))
    if row['fixture_kind'] == 'wait':
        guard.phase('waiting')
        deadline = time.monotonic()+30
        try:
            while time.monotonic() < deadline:
                guard.check(force=True)
                time.sleep(.05)
        except G.GuardAborted as error:
            record.update(status='INTERRUPTED', failure=str(error))
            save()
            return 1
        record['status'] = 'FIXTURE_WAIT_TIMED_OUT'
    guard.phase('fixture-close')
    guard.close()
    record['status'] = 'FIXTURE_SEED_HOOKS_ONLY' if record['status'] == 'STARTED' else record['status']
    save()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
'''


def sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


class Fixture:
    def __init__(self, root, kind='seed'):
        self.root = Path(root).resolve()
        helpers = self.root/'helpers'
        helpers.mkdir()
        compose_successor(helpers)
        (helpers/'fixture_runner.py').write_text(FIXTURE_RUNNER, encoding='utf8')
        (helpers/'fixture_workload.py').write_text(FIXTURE_WORKLOAD, encoding='utf8')
        self.runner, self.workload = helpers/'fixture_runner.py', helpers/'fixture_workload.py'
        (self.root/'original.bin').write_bytes(ORIGINAL_BYTES)
        (self.root/'runs').mkdir()
        (self.root/'queries').mkdir()
        self.write_manifest(sorted(helpers.glob('*.py')))
        self.row = dict(schema='atlas.prepared-restart-launch.v1', workspace=str(self.root),
            source_manifest=dict(path='manifest.json', sha256=sha(self.root/'manifest.json')),
            modules={'private_heat_continuation_guard_r3': 'helpers/'+P.GUARD_NAME},
            output_directory=str(self.root/'runs'/'s2'), completed_query_directory='queries/completed',
            store_limits=dict(max_store_bytes=1 << 20, max_staging_bytes=1 << 20), fixture_kind=kind)
        self.write_profile()

    def write_manifest(self, files):
        manifest = dict(files={p.relative_to(self.root).as_posix(): sha(p) for p in files})
        (self.root/'manifest.json').write_bytes(json.dumps(manifest, sort_keys=True).encode())

    def write_profile(self):
        path = self.root/'profile.json'
        path.write_bytes(json.dumps(self.row, sort_keys=True).encode())
        self.profile, self.pin = path, sha(path)

    @property
    def out(self):
        return Path(self.row['output_directory'])

    def listing(self):
        return sorted(p.name for p in (self.root/'runs').iterdir())

    def preflight(self, **changes):
        options = dict(booking_bytes=5 << 30, booking_basis='synthetic fixture booking')
        options.update(changes)
        return L.preflight(self.profile, self.pin, runner=self.runner, **options)


def probes(available=16 << 30, reboot=(), free=None, matches=()):
    patches = [patch.object(L, '_available_bytes', return_value=available),
               patch.object(L, '_pending_reboot', return_value=list(reboot)),
               patch.object(L, '_matching_processes', return_value=list(matches))]
    if free is not None:
        patches.append(patch.object(L, '_disk_free', return_value=free))
    class Stack:
        def __enter__(self):
            for item in patches:
                item.start()
        def __exit__(self, *_):
            for item in reversed(patches):
                item.stop()
    return Stack()


CLEAN_ENV = {k: v for k, v in os.environ.items()
             if k not in L.HOOK_ENV and k not in ('PYTHONHASHSEED', 'ATLAS_DEV_STAGE_TIMING')}


class Preflight(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lmi-')
        self.fixture = Fixture(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_compact_headroom_uses_fixed_interval_limits(self):
        import run_prepared_restart as runner
        f = self.fixture
        with f.runner.open('a', encoding='utf8') as stream:
            stream.write('\nCOMPACT_STORE_LIMITS = '+repr(runner.COMPACT_STORE_LIMITS)+'\n')
        f.write_manifest(sorted((f.root/'helpers').glob('*.py')))
        f.row.update(storage_format='interval-catalog-v1')
        f.row['source_manifest']['sha256'] = sha(f.root/'manifest.json')
        f.write_profile()
        required = (2*runner.COMPACT_STORE_LIMITS['max_store_bytes']+
                    runner.COMPACT_STORE_LIMITS['max_staging_bytes']+L.DEFAULT_QUERY_STORE_BYTES)
        with probes(free=required-1):
            with self.assertRaisesRegex(ValueError, 'disk headroom'):
                f.preflight(environ=CLEAN_ENV)
        with probes(free=required):
            plan = f.preflight(environ=CLEAN_ENV)
        self.assertEqual(plan['record']['disk']['required_bytes'], required)
        self.assertEqual(f.listing(), [])

    def test_plan_env_argv_and_record_without_writes(self):
        with probes(available=16 << 30):
            plan = self.fixture.preflight(environ=CLEAN_ENV)
        self.assertEqual({k: plan['env'][k] for k in L.LAUNCH_ENV}, dict(PYTHONHASHSEED='0',
            OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1'))
        argv, record = plan['argv'], plan['record']
        self.assertEqual(argv[2], str(self.fixture.root/'helpers'/P.GUARD_NAME))
        self.assertEqual(record['guard']['sha256'], P.SUCCESSOR_PIN)
        self.assertEqual(record['runner'], dict(path=str(self.fixture.runner), sha256=sha(self.fixture.runner)))
        self.assertEqual(record['memory'], dict(available_bytes=16 << 30, hard_gate_bytes=8 << 30))
        self.assertEqual(argv[-2:], [SG.ARGUMENT, SG.encode(plan['gate'])])
        self.assertEqual(record['disk']['query_quota_source'], 'endpoint-checkpoint default')
        self.assertEqual(record['completed_queries']['exists'], False)
        self.assertEqual(self.fixture.listing(), [])
        self.assertIs(record['stop_before_advance'], False)
        with probes(available=12 << 30):
            self.assertEqual(self.fixture.preflight(environ=dict(CLEAN_ENV, PYTHONHASHSEED='0'))['record']['memory'],
                             dict(available_bytes=12 << 30, hard_gate_bytes=8 << 30))
            staged = self.fixture.preflight(environ=CLEAN_ENV, stop_before_advance=True)
        self.assertEqual(staged['argv'][-3], '--stop-before-advance')
        self.assertEqual(staged['argv'][-2], SG.ARGUMENT)
        self.assertIs(staged['record']['stop_before_advance'], True)
        self.assertEqual(self.fixture.listing(), [])
        self.assertEqual((L.RSS_BYTES, L.FREE_BYTES, L.LOGICAL_BYTES), (12 << 30, 1 << 30, 16 << 30))

    def _enable_dev_runner(self):
        source = self.fixture.runner.read_text(encoding='utf8')
        source = source.replace('stop_before_advance=False, start_gate=None):',
                                'stop_before_advance=False, dev_timing=False, start_gate=None):', 1)
        source = source.replace("*(['--stop-before-advance'] if stop_before_advance else []),",
                                "*(['--stop-before-advance'] if stop_before_advance else []),"
                                 "*(['--dev-timing'] if dev_timing else []),", 1)
        self.fixture.runner.write_text(source, encoding='utf8')
        self.fixture.write_manifest(sorted((self.fixture.root/'helpers').glob('*.py')))
        self.fixture.row['source_manifest']['sha256'] = sha(self.fixture.root/'manifest.json')
        self.fixture.write_profile()

    def test_dev_timing_explicit_and_environment_forwarding(self):
        self._enable_dev_runner()
        with probes():
            baseline = self.fixture.preflight(environ=CLEAN_ENV)['argv']
            off = self.fixture.preflight(environ=dict(CLEAN_ENV, ATLAS_DEV_STAGE_TIMING='0'))
            self.assertEqual(off['argv'], baseline)
            self.assertFalse(off['record']['dev_timing'])
            for flags in (dict(dev_timing=True, environ=CLEAN_ENV),
                          dict(environ=dict(CLEAN_ENV, ATLAS_DEV_STAGE_TIMING='1'))):
                with self.subTest(flags=flags):
                    plan = self.fixture.preflight(**flags)
                    self.assertEqual(plan['argv'][:-2], baseline[:-2]+['--dev-timing'])
                    self.assertEqual(plan['argv'][-2:], [SG.ARGUMENT, SG.encode(plan['gate'])])
                    self.assertTrue(plan['record']['dev_timing'])
            staged = self.fixture.preflight(environ=CLEAN_ENV, dev_timing=True, stop_before_advance=True)
            self.assertEqual(staged['argv'][:-2], baseline[:-2]+['--stop-before-advance', '--dev-timing'])
            self.assertEqual(staged['argv'][-2:], [SG.ARGUMENT, SG.encode(staged['gate'])])
        self.assertEqual(self.fixture.listing(), [])

    def test_dev_timing_requires_new_runner_only_when_enabled(self):
        with probes():
            self.assertNotIn('--dev-timing', self.fixture.preflight(environ=CLEAN_ENV)['argv'])
            for flags in (dict(dev_timing=True, environ=CLEAN_ENV),
                          dict(environ=dict(CLEAN_ENV, ATLAS_DEV_STAGE_TIMING='1'))):
                with self.subTest(flags=flags), self.assertRaisesRegex(ValueError, 'no dev-timing mode'):
                    self.fixture.preflight(**flags)
        self.assertEqual(self.fixture.listing(), [])

    def test_dev_timing_malformed_values_refuse_before_runner_load(self):
        for value in ('yes', 'true', '2', ' 1', None):
            with self.subTest(value=value), patch.object(L, 'load_runner') as load:
                with self.assertRaisesRegex(ValueError, 'unset, 0 or 1'):
                    self.fixture.preflight(environ=dict(CLEAN_ENV, ATLAS_DEV_STAGE_TIMING=value))
                load.assert_not_called()
        with patch.object(L, 'load_runner') as load:
            with self.assertRaisesRegex(ValueError, 'dev timing flag'):
                self.fixture.preflight(environ=CLEAN_ENV, dev_timing='1')
            load.assert_not_called()
        self.assertEqual(self.fixture.listing(), [])

    def test_dev_timing_cli_forwards_only_launch_option(self):
        args = ['--launch', '--profile', str(self.fixture.profile), '--profile-sha256', self.fixture.pin,
                '--dev-timing', '--booking-bytes', str(5 << 30), '--booking-basis', 'fixture']
        with patch.object(L, 'launch', return_value=0) as launch:
            self.assertEqual(L.main(args), 0)
            self.assertIs(launch.call_args.kwargs['dev_timing'], True)
        with self.assertRaises(SystemExit):
            L.main(['--status', '--profile', str(self.fixture.profile), '--profile-sha256',
                    self.fixture.pin, '--dev-timing'])

    def test_refusals_create_nothing(self):
        f = self.fixture
        cases = [
            ('available', dict(available=(8 << 30)-1), {}, 'start gate refused'),
            ('reboot', dict(reboot=['RebootPending']), {}, 'pending Windows restart'),
            ('disk', dict(free=0), {}, 'disk headroom'),
            ('live process', dict(matches=[dict(pid=1, cmdline=[])]), {}, 'live process'),
            ('seed', {}, dict(environ=dict(CLEAN_ENV, PYTHONHASHSEED='1')), 'PYTHONHASHSEED'),
            ('coverage', {}, dict(environ=dict(CLEAN_ENV, COVERAGE_PROCESS_START='x')), 'instrumentation'),
            ('path', {}, dict(environ=dict(CLEAN_ENV, PYTHONPATH='x')), 'import-path'),
            ('profile pin', {}, dict(), 'pinned restart profile changed')]
        for name, probe, changes, message in cases:
            with self.subTest(name), probes(**probe), self.assertRaisesRegex(ValueError, message):
                if name == 'profile pin':
                    L.preflight(f.profile, '0'*64, runner=f.runner, environ=CLEAN_ENV)
                else:
                    f.preflight(**dict(dict(environ=CLEAN_ENV), **changes))
            self.assertEqual(f.listing(), [])

    def test_source_runner_output_and_lock_refusals(self):
        f = self.fixture
        with probes():
            (f.root/'runs'/'s2.launch.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'sibling'):
                f.preflight(environ=CLEAN_ENV)
            (f.root/'runs'/'s2.launch.json').unlink()
            f.out.mkdir()
            with self.assertRaisesRegex(ValueError, 'exclusive new output'):
                f.preflight(environ=CLEAN_ENV)
            f.out.rmdir()
            original = f.workload.read_bytes()
            f.workload.write_bytes(original+b'# changed\n')
            with self.assertRaisesRegex(ValueError, 'participating source changed'):
                f.preflight(environ=CLEAN_ENV)
            f.workload.write_bytes(original)
            f.write_manifest(sorted(p for p in (f.root/'helpers').glob('*.py') if p != f.runner))
            f.row['source_manifest']['sha256'] = sha(f.root/'manifest.json')
            f.write_profile()
            with self.assertRaisesRegex(ValueError, 'runner bytes are not the profile manifest pin'):
                f.preflight(environ=CLEAN_ENV)
            f.write_manifest(sorted((f.root/'helpers').glob('*.py')))
            f.row['source_manifest']['sha256'] = sha(f.root/'manifest.json')
            f.row['output_directory'] = str(f.root/'RUNS'/'s2')
            f.write_profile()
            with self.assertRaisesRegex(ValueError, 'canonical absolute output'):
                f.preflight(environ=CLEAN_ENV)
            f.row['output_directory'] = str(f.root/'runs'/'s2')
            f.write_profile()
            queries = f.root/'queries'/'completed'
            queries.mkdir()
            (queries/('a'*64+'.query')).write_bytes(b'q')
            (queries/('b'*64+'.partial-'+'c'*32)).write_bytes(b'pp')
            if os.name == 'nt':
                import msvcrt
                with open(queries/'owner.lock', 'a+b', buffering=0) as lock:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    with self.assertRaisesRegex(ValueError, 'owner lock is held'):
                        f.preflight(environ=CLEAN_ENV)
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            state = f.preflight(environ=CLEAN_ENV)['record']['completed_queries']
            self.assertEqual((state['queries'], state['query_bytes'], state['partials'], state['partial_bytes'],
                              state['lock_held']), (1, 1, 1, 2, False))
        self.assertEqual(f.listing(), [])

    def test_missing_or_half_booking_and_seed_refuse_before_any_output(self):
        for options in (dict(booking_bytes=None, booking_basis=None), dict(booking_bytes=None), dict(booking_basis=None)):
            with self.subTest(options=options), probes(), self.assertRaises(ValueError):
                self.fixture.preflight(environ=CLEAN_ENV, **options)
            self.assertEqual(self.fixture.listing(), [])
        flags = type('Flags', (), {name: getattr(sys.flags, name) for name in dir(sys.flags)
                                 if not name.startswith('_')})()
        flags.hash_randomization = 1
        with probes(), patch.object(SG.sys, 'flags', flags):
            with self.assertRaisesRegex(ValueError, 'production requires seed 0'):
                self.fixture.preflight(environ=CLEAN_ENV)
        self.assertEqual(self.fixture.listing(), [])

    def test_unpinned_runner_is_refused_before_any_execution(self):
        f = self.fixture
        marker = f.root/'executed.txt'
        foreign = f.root/'helpers'/'foreign_runner.py'
        foreign.write_text('from pathlib import Path\nPath(%r).write_text("ran")\n' % str(marker), encoding='utf8')
        for operation in (lambda: L.load_runner(f.profile, f.pin, foreign),
                          lambda: L.preflight(f.profile, f.pin, runner=foreign, environ=CLEAN_ENV)):
            with probes(), self.assertRaisesRegex(ValueError, 'runner bytes are not the profile manifest pin'):
                operation()
        with self.assertRaisesRegex(ValueError, 'pinned restart profile changed'):
            L.load_runner(f.profile, '0'*64, f.runner)
        self.assertFalse(marker.exists())

    def test_exclusive_records_and_real_runner_interface(self):
        path = Path(self.temporary.name)/'record.json'
        L._write_exclusive(path, dict(a=1))
        with self.assertRaises(FileExistsError):
            L._write_exclusive(path, dict(a=2))
        runner = HERE/'run_prepared_restart.py'
        raw = runner.read_bytes()
        module = L._exec_runner(runner, raw, sha256(raw).hexdigest())
        parameters = list(inspect.signature(module.command).parameters.values())
        self.assertEqual([item.name for item in parameters[:2]], ['profile', 'python'])
        # Anything else must be keyword-only with a default (e.g. stop_before_advance).
        self.assertTrue(all(item.kind is item.KEYWORD_ONLY and item.default is not item.empty
                            for item in parameters[2:]))
        self.assertEqual(list(inspect.signature(module.RestartProfile.read).parameters), ['path', 'pin'])
        self.assertTrue(callable(module.RestartSources.verify))
        if os.name == 'nt':
            # Read-only HKLM key presence probe; the value depends on the host.
            self.assertTrue(set(L._pending_reboot()) <= set(L.REBOOT_KEYS))
        import historical_admission as A
        review = A._REVIEWED_ORIGINAL
        self.assertEqual(L.ORIGINAL_DATABASE, (A.HISTORICAL_RELATIVE+'/'+review.database_name, review.database_sha256))
        self.assertEqual(L.ORIGINAL_DATABASE[1], '3f70c26de17535a96b7ddd494aee72900decee272ae0f88edab3a42af1548899')


class Postcheck(unittest.TestCase):
    """Synthetic receipts: the exact clean case passes; each deviation refuses."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lmp-')
        f = self.fixture = Fixture(self.temporary.name)
        with probes():
            plan = f.preflight(environ=CLEAN_ENV)
        self.p = plan['paths']
        L._write_exclusive(self.p['launch'], plan['record'])
        f.out.mkdir()
        self.p['checkpoint'].write_bytes(b'synthetic checkpoint bytes')
        parent, guardian = dict(pid=2_000_000_004, created_ticks=134_000_000_000_000_000), 2_000_000_008
        limits = dict(rss_bytes=12 << 30, free_floor_bytes=1 << 30)
        self.guard = dict(schema=L.GUARD_SCHEMA, status='STOPPED', reason=None, workload_exit_confirmed=True,
            workload_exit_code=0, cleanup=dict(remaining=[], action_errors=[]), limits=limits, sample_interval=.25,
            grace_seconds=5., parent=parent, nonce='n', guardian=dict(pid=guardian), launch_cohort=[],
            resource_summary=dict(schema=L.SUMMARY_SCHEMA), samples=3,
            sampled_peak_bytes=dict(process_tree_rss=5 << 30))
        self.control = dict(parent=parent, nonce='n', close_requested=True, limits=limits)
        self.tracking = dict(output=str(f.out), guardian=dict(pid=guardian, create_time=1., cmdline=[]), parent=parent)
        self.run = dict(schema=L.RUN_SCHEMA, status=L.PASS_STATUS, pid=parent['pid'], profile_sha256=f.pin,
            stop_before_advance=False,
            errors=[], production_acceptance=False, final_reserved_bytes=0, original_database_unchanged=True,
            same_process_cold_reopen=False, same_process_cold_reopen_reason=L.COLD_REOPEN_DROPPED,
            independent_process_reopen=False,
            previous_endpoint=dict(head='h1', intervals=1, time_s=12.5, funding_id='f'),
            advanced_endpoint=dict(head='h2', intervals=2, time_s=25., funding_id='f'),
            guard_limits=SG.guard_limits(plan['record']['start_gate']), start_gate=plan['record']['start_gate'],
            resources=dict(sampled_peak_bytes=dict(process_tree_rss=4 << 30)),
            interpreter_seed=dict(PYTHONHASHSEED='0', hash_randomization=0),
            completed_queries=dict(hits=0, misses=3, written=3, incomplete=0),
            checkpoint=str(self.p['checkpoint']), checkpoint_sha256=sha(self.p['checkpoint']),
            source_proof=dict(source_manifest_sha256=f.row['source_manifest']['sha256'], native_source_digest='fixture-only'),
            supervisor=dict(pid=guardian, status='STOPPED'))
        self.original = patch.object(L, 'ORIGINAL_DATABASE', ('original.bin', sha256(ORIGINAL_BYTES).hexdigest()))
        self.original.start()

    def tearDown(self):
        self.original.stop()
        self.temporary.cleanup()

    def write(self, **records):
        for name in ('guard', 'control', 'tracking', 'run'):
            value = records.get(name, getattr(self, name))
            self.p[name].write_bytes(json.dumps(value).encode())

    def check(self, **records):
        self.write(**records)
        with patch.object(L, '_matching_processes', return_value=[]):
            return L.postcheck(self.fixture.profile, self.fixture.pin, runner=self.fixture.runner, write=False)

    def refresh_admission(self, *, staged=False, run=None):
        """Rebuild the fixture's actual launch contract after an intentional profile/mode change."""
        f = self.fixture
        module, _, _ = L.load_runner(f.profile, f.pin, f.runner)
        profile = module.RestartProfile.read(f.profile, f.pin)
        key = module.gate_key(profile, sys.executable, stop_before_advance=staged)
        gate = SG.decide(key, booking=(5 << 30, 'synthetic fixture booking'))
        admitted = dict(gate, available_bytes=16 << 30, hash_randomization=0)
        launch = json.loads(self.p['launch'].read_bytes())
        launch.update(profile=dict(path=str(f.profile), sha256=f.pin), source_manifest=f.row['source_manifest'],
                      stop_before_advance=staged, start_gate=admitted)
        argv = launch['argv'][:11]+['--profile', str(f.profile), '--profile-sha256', f.pin]
        launch['argv'] = argv+(['--stop-before-advance'] if staged else [])+[SG.ARGUMENT, SG.encode(gate)]
        self.p['launch'].write_bytes(json.dumps(launch).encode())
        target = self.run if run is None else run
        target.update(start_gate=admitted, guard_limits=SG.guard_limits(admitted))

    def test_compact_catalog_pin_members_and_retained_release(self):
        import reopen_prepared_restart as reader
        f = self.fixture
        helper = f.root/'helpers'/'reopen_prepared_restart.py'
        helper.write_bytes(Path(reader.__file__).read_bytes())
        f.row.update(storage_format='interval-catalog-v1')
        f.row['modules']['reopen_prepared_restart'] = helper.relative_to(f.root).as_posix()
        f.write_manifest(sorted((f.root/'helpers').glob('*.py')))
        f.row['source_manifest']['sha256'] = sha(f.root/'manifest.json')
        f.write_profile()
        launch = json.loads(self.p['launch'].read_bytes())
        launch['profile']['sha256'] = f.pin
        launch['source_manifest']['sha256'] = f.row['source_manifest']['sha256']
        self.p['launch'].write_bytes(json.dumps(launch).encode())
        self.run['profile_sha256'] = f.pin
        self.run['source_proof']['source_manifest_sha256'] = f.row['source_manifest']['sha256']
        self.refresh_admission()
        directory = f.out/'compact-checkpoint'
        directory.mkdir()
        member = directory/'interval-0000.sqlite'
        member.write_bytes(b'synthetic sealed interval; not scientific acceptance')
        catalog = directory/'interval-catalog.json'
        catalog.write_bytes(json.dumps(dict(schema='atlas.interval-catalog.v1', workflow_id='f'*64,
            generation=1, entries=[dict(interval=0, filename=member.name,
                                        file_sha256=sha(member))])).encode())
        storage = reader.storage_inventory(catalog)
        self.run.update(compact_storage=storage, checkpoint=str(catalog),
                        checkpoint_sha256=sha(catalog), compact_retained_after_close=dict(retained_bytes=0))
        with patch.object(reader, '__file__', str(helper)):
            result = self.check()
            self.assertEqual(result['failures'], [], result)
            for change in (dict(checkpoint_sha256='0'*64),
                           dict(compact_retained_after_close=dict(retained_bytes=1))):
                with self.subTest(change=change):
                    self.assertEqual(self.check(run=dict(self.run, **change))['failures'], ['checkpoint'])
            member.write_bytes(b'changed interval')
            self.assertEqual(self.check()['failures'], ['checkpoint'])

    def test_missing_or_foreign_admission_fails_postcheck(self):
        foreign = json.loads(json.dumps(self.run['start_gate']))
        foreign['key']['python']['sha256'] = '0'*64
        cases = ({k: v for k, v in self.run.items() if k != 'start_gate'},
                 dict(self.run, start_gate=foreign))
        for run in cases:
            with self.subTest(has_admission='start_gate' in run):
                result = self.check(run=run)
                self.assertEqual(result['status'], 'FAILED')
                self.assertIn('run_start_gate', result['failures'])
                self.assertNotIn('gate_evidence', result)

    def test_changed_validated_snapshot_cannot_publish_evidence(self):
        original = RG.evidence
        def change_after_checks(key, snapshots):
            self.p['guard'].write_bytes(self.p['guard'].read_bytes()+b'\n')
            return original(key, snapshots)
        with patch.object(RG, 'evidence', side_effect=change_after_checks):
            result = self.check()
        self.assertEqual(result['failures'], ['gate_evidence'])
        self.assertNotIn('gate_evidence', result)

    def test_exact_success_then_each_single_deviation_refuses(self):
        result = self.check()
        self.assertEqual((result['status'], result['failures']), ('PASS', []), result)
        changed = lambda record, **values: dict(getattr(self, record), **values)
        import psutil
        own = psutil.Process()
        live = dict(pid=own.pid, created_ticks=round(own.create_time()*1e7)+L.EPOCH_TICKS)
        cases = {
            'guard_stopped': dict(guard=changed('guard', status='HARD_STOPPED')),
            'guard_exit': dict(guard=changed('guard', workload_exit_code=1)),
            'guard_cleanup': dict(guard=changed('guard', cleanup=dict(remaining=[dict(pid=5)], action_errors=[]))),
            'guard_limits': dict(guard=changed('guard', limits=dict(rss_bytes=13 << 30, free_floor_bytes=1 << 30)),
                                 control=changed('control', limits=dict(rss_bytes=13 << 30, free_floor_bytes=1 << 30))),
            'guard_parent': dict(run=changed('run', pid=12)),
            'guard_control': dict(control=changed('control', close_requested=False)),
            'guard_supervisor': dict(run=changed('run', supervisor=dict(pid=3, status='STOPPED'))),
            'resource_summary': dict(guard={k: v for k, v in self.guard.items() if k != 'resource_summary'}),
            'tracking': dict(tracking=changed('tracking', guardian=dict(pid=2_000_000_012, create_time=1., cmdline=[]))),
            'no_live_workers': dict(guard=changed('guard', parent=live), control=changed('control', parent=live),
                                    tracking=changed('tracking', parent=live), run=changed('run', pid=live['pid'])),
            'run_status': dict(run=changed('run', status='FAILED')),
            'run_errors': dict(run=changed('run', errors=[dict(type='X')])),
            'zero_reservations': dict(run=changed('run', final_reserved_bytes=4096)),
            'not_production_acceptance': dict(run=changed('run', production_acceptance=True)),
            'original_unchanged_recorded': dict(run=changed('run', original_database_unchanged=False)),
            'reopen_scope': dict(run=changed('run', independent_process_reopen=True)),
            'one_interval': dict(run=changed('run', advanced_endpoint=dict(head='h2', intervals=3, time_s=25., funding_id='f'))),
            'run_guard_limits': dict(run=changed('run', guard_limits=dict(self.run['guard_limits'], start_available_bytes=9 << 30))),
            'profile_pin': dict(run=changed('run', profile_sha256='0'*64)),
            'interpreter_seed': dict(run=changed('run', interpreter_seed=dict(PYTHONHASHSEED=None, hash_randomization=1))),
            'completed_queries': dict(run=changed('run', completed_queries=dict(hits=-1, misses=0, written=0, incomplete=0))),
            'checkpoint': dict(run=changed('run', checkpoint_sha256='0'*64)),
            'sources': dict(run=changed('run', source_proof=dict(source_manifest_sha256='0'*64, native_source_digest='x')))}
        for name, records in cases.items():
            with self.subTest(name):
                self.assertEqual(self.check(**records)['failures'], [name])
        # Owner decision 14 Oct 2026: an interval receipt must record the dropped
        # same-process successor reopen with exactly the runner's reason.
        self.assertEqual(L.COLD_REOPEN_DROPPED, 'dropped by owner decision 14 Oct 2026; '
                         'the mandatory independent fresh-process reader performs the cold reopen')
        no_reason = {k: v for k, v in self.run.items() if k != 'same_process_cold_reopen_reason'}
        reopen_cases = {'old same-process successor reopen': changed('run', same_process_cold_reopen=True),
                        'missing reason': no_reason,
                        'other reason': changed('run', same_process_cold_reopen_reason='skipped'),
                        'textual flag': changed('run', same_process_cold_reopen='False')}
        for name, run in reopen_cases.items():
            with self.subTest(name):
                self.assertEqual(self.check(run=run)['failures'], ['reopen_scope'])
        files = {'guard_no_abort': self.p['cancel'], 'checkpoint': Path(str(self.p['checkpoint'])+'-journal')}
        for name, path in files.items():
            with self.subTest(name):
                path.write_bytes(b'')
                self.assertEqual(self.check()['failures'], [name])
                path.unlink()
        with self.subTest('original_database'):
            (self.fixture.root/'original.bin').write_bytes(ORIGINAL_BYTES+b'x')
            self.assertEqual(self.check()['failures'], ['original_database'])
            (self.fixture.root/'original.bin').write_bytes(ORIGINAL_BYTES)
        with self.subTest('launch sources'):
            self.fixture.workload.write_bytes(self.fixture.workload.read_bytes()+b'#\n')
            self.assertEqual(set(self.check()['failures']), {'launch_sources_unchanged', 'sources', 'run_start_gate'})
            self.fixture.workload.write_text(FIXTURE_WORKLOAD, encoding='utf8')
        self.write()
        with patch.object(L, '_matching_processes', return_value=[]):
            self.assertEqual(L.postcheck(self.fixture.profile, self.fixture.pin, runner=self.fixture.runner)['status'], 'PASS')
            with self.assertRaisesRegex(ValueError, 'exclusive postcheck'):
                L.postcheck(self.fixture.profile, self.fixture.pin, runner=self.fixture.runner)
        self.assertEqual(json.loads(self.p['postcheck'].read_bytes())['independent_process_reopen_required'], True)

    def test_unresponsive_guardian_termination_needs_flag_and_exact_identity(self):
        self.write(guard=dict(self.guard, status='RUNNING'),
                   tracking=dict(self.tracking, guardian=dict(pid=4242, create_time=5., cmdline=['python', 'guard'])))
        terminated = []
        class Fake:
            def __init__(self, pid, created=5., cmdline=('python', 'guard')):
                self.pid, self.created, self.line = pid, created, list(cmdline)
            def create_time(self):
                return self.created
            def cmdline(self):
                return self.line
            def terminate(self):
                terminated.append(self.pid)
            def wait(self, timeout):
                return 0
        import psutil
        args = (self.fixture.profile, self.fixture.pin)
        with patch.object(L, 'CANCEL_SECONDS', .3):
            result = L.cancel(*args, runner=self.fixture.runner)
            self.assertEqual((result['status'], result['created_cancel'], terminated),
                             ('CANCEL_REQUESTED_UNCONFIRMED', True, []))
            with patch.object(psutil, 'Process', lambda pid: Fake(pid, created=6.)), \
                    self.assertRaisesRegex(ValueError, 'identity differs; nothing terminated'):
                L.cancel(*args, runner=self.fixture.runner, terminate_unresponsive_guardian=True)
            self.assertEqual(terminated, [])
            with patch.object(psutil, 'Process', lambda pid: Fake(pid)):
                result = L.cancel(*args, runner=self.fixture.runner, terminate_unresponsive_guardian=True)
        self.assertEqual((result['status'], result['created_cancel'], terminated), ('GUARDIAN_TERMINATED', False, [4242]))
        self.assertTrue(self.p['cancel'].is_file())

    def test_staged_mode_comes_from_the_launch_record_and_is_never_an_interval(self):
        launch = json.loads(self.p['launch'].read_bytes())
        self.p['launch'].unlink()
        L._write_exclusive(self.p['launch'], dict(launch, stop_before_advance=True))
        staged = {k: v for k, v in self.run.items() if k not in
                  ('advanced_endpoint', 'completed_queries', 'same_process_cold_reopen_reason')}
        # A staged run cold-reopens only its published root, in the runner's process.
        staged.update(status=L.STOPPED_STATUS, stop_before_advance=True, same_process_cold_reopen=True)
        self.refresh_admission(staged=True, run=staged)
        result = self.check(run=staged)
        self.assertEqual((result['status'], result['failures'], result['stop_before_advance']), ('PASS', [], True))
        for deviation in (dict(same_process_cold_reopen=False),
                          dict(same_process_cold_reopen_reason=L.COLD_REOPEN_DROPPED)):
            with self.subTest(staged_deviation=sorted(deviation)):
                self.assertEqual(self.check(run=dict(staged, **deviation))['failures'], ['reopen_scope'])
        self.assertNotIn('one_interval', [row['name'] for row in result['checks']])
        self.assertEqual(self.check(run=dict(staged, status=L.PASS_STATUS))['failures'], ['run_status'])
        self.assertEqual(self.check(run=dict(staged, advanced_endpoint=self.run['advanced_endpoint']))['failures'],
                         ['root_only'])
        # An interval receipt under a staged launch record (or the reverse) refuses.
        self.assertIn('run_status', self.check()['failures'])


@unittest.skipUnless(os.name == 'nt', 'Windows job-object integration')
class RealLaunch(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lml-')

    def tearDown(self):
        self.temporary.cleanup()

    def fixture(self, kind):
        root = Path(self.temporary.name)/'w'
        root.mkdir()
        return Fixture(root, kind=kind)

    def harness(self, fixture, mode):
        return [sys.executable, '-B', '-c', HARNESS, str(HERE), 'original.bin', sha256(ORIGINAL_BYTES).hexdigest(),
                mode, '--profile', str(fixture.profile), '--profile-sha256', fixture.pin, '--runner', str(fixture.runner),
                *(['--booking-bytes', str(5 << 30), '--booking-basis', 'synthetic fixture booking'] if mode == '--launch' else [])]

    def run_cli(self, fixture, mode):
        result = subprocess.run(self.harness(fixture, mode), env=dict(CLEAN_ENV, PYTHONHASHSEED='0'), capture_output=True, text=True,
                                timeout=90, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        return result, [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]

    def test_launcher_seed_and_hooks_real(self):
        f = self.fixture('seed')
        result, lines = self.run_cli(f, '--launch')
        self.assertEqual(result.returncode, 1, result.stdout+result.stderr)
        self.assertEqual([line['status'] for line in lines], ['PREFLIGHT_PASSED', 'RUNNING', 'FAILED'])
        p = L.paths(f.out)
        guard = json.loads(p['guard'].read_bytes())
        run = json.loads(p['run'].read_bytes())
        self.assertEqual(lines[1]['guardian'], guard['guardian']['pid'])
        self.assertEqual(lines[1]['parent'], guard['parent'])
        self.assertEqual((guard['status'], guard['workload_exit_code'], guard['cleanup']),
                         ('STOPPED', 0, dict(remaining=[], action_errors=[])))
        self.assertEqual(run['status'], 'FIXTURE_SEED_HOOKS_ONLY')
        self.assertEqual(run['interpreter'], dict(PYTHONHASHSEED='0', hash_randomization=0, gettrace='None',
            getprofile='None', monitoring=[None]*6, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
            PYTHONDONTWRITEBYTECODE='1', dont_write_bytecode=True, child=['0', 0]))
        launch = json.loads(p['launch'].read_bytes())
        self.assertEqual(launch['env'], L.LAUNCH_ENV)
        self.assertEqual(launch['guard']['sha256'], P.SUCCESSOR_PIN)
        tracking = json.loads(p['tracking'].read_bytes())
        self.assertEqual(tracking['guardian']['pid'], guard['guardian']['pid'])
        post = json.loads(p['postcheck'].read_bytes())
        ok = {row['name']: row['ok'] for row in post['checks']}
        for name in ('guard_schema', 'guard_stopped', 'guard_exit', 'guard_cleanup', 'guard_limits', 'guard_parent',
                     'guard_control', 'guard_supervisor', 'guard_no_abort', 'resource_summary', 'tracking',
                     'launch_record', 'launch_sources_unchanged', 'no_live_workers', 'not_production_acceptance',
                     'original_database'):
            self.assertTrue(ok[name], (name, post))
        # A fixture never becomes a restart PASS.
        self.assertFalse(ok['run_status'])
        self.assertEqual(post['status'], 'FAILED')
        self.assertTrue(p['log'].is_file())

    def test_status_cancel_and_postcheck_real(self):
        f = self.fixture('wait')
        root, p = f.root, L.paths(f.out)
        launcher = subprocess.Popen(self.harness(f, '--launch'), env=dict(CLEAN_ENV, PYTHONHASHSEED='0'), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline, waiting = time.monotonic()+60, False
            while not waiting and time.monotonic() < deadline and launcher.poll() is None:
                waiting = ((L._peek(p['run']) or {}).get('stage') == 'waiting' and
                           bool((L._peek(p['tracking']) or {}).get('guardian')))
                time.sleep(.1)
            self.assertTrue(waiting, 'fixture never reached its waiting phase')
            # The real process scan sees the live guardian by its output path.
            self.assertGreaterEqual(len(L._matching_processes([str(f.out)+os.sep])), 1)
            before = (sorted(x.name for x in (root/'runs').iterdir()), p['launch'].read_bytes())
            result, lines = self.run_cli(f, '--status')
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            state = lines[-1]
            self.assertEqual((state['guard']['status'], state['run']['stage'], state['guardian_alive']),
                             ('RUNNING', 'waiting', True))
            self.assertEqual(state['completed_queries']['lock_held'], None)
            self.assertEqual((sorted(x.name for x in (root/'runs').iterdir()), p['launch'].read_bytes()), before)
            result, lines = self.run_cli(f, '--cancel')
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual(lines[-1]['status'], 'CANCELLED')
            self.assertIn(lines[-1]['guard_status'], ('PARENT_EXITED', 'HARD_STOPPED'))
            self.assertEqual(lines[-1]['reason'], 'user_cancel')
            self.assertEqual(lines[-1]['cleanup'], dict(remaining=[], action_errors=[]))
            stdout, stderr = launcher.communicate(timeout=60)
        finally:
            if launcher.poll() is None:
                launcher.kill()
        self.assertEqual(launcher.returncode, 1, stdout+stderr)
        self.assertEqual(json.loads(p['run'].read_bytes())['status'], 'INTERRUPTED')
        post = json.loads(p['postcheck'].read_bytes())
        self.assertEqual(post['status'], 'FAILED')
        self.assertTrue({'guard_stopped', 'guard_no_abort'} <= set(post['failures']))
        self.assertTrue({row['name']: row['ok'] for row in post['checks']}['no_live_workers'])
        result, lines = self.run_cli(f, '--cancel')
        self.assertEqual(lines[-1]['status'], 'ALREADY_TERMINAL')
        result, lines = self.run_cli(f, '--postcheck')
        self.assertEqual((result.returncode, lines[-1]['status']), (2, 'REFUSED'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
