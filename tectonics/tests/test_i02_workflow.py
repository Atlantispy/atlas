"""Focused I02.6 checks: the command-level create, advance, inspect, cancel, save, load and continue workflow.

Every command runs the real layered column through the package: the case is prepared by the package alone, advances
commit whole steps through the accepted clock, and continuation after save/load or in a fresh process reaches the
uninterrupted result within the retained parity. Cancellation between steps keeps the accepted prefix; inspection and
status run no physics and read only the root and the requested commit; a changed source or runtime identity refuses
continuation but not inspection; invalid requests change nothing.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np
from threadpoolctl import threadpool_limits

import atlas_tectonics
from atlas_tectonics import integration_clock as K, integration_ledger as L, integration_state as I

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent/'tools'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TOOLS))
import i02_workflow_fixtures as F
import i02_column_workflow as W

SRC = str(Path(atlas_tectonics.__file__).resolve().parents[1])
ENV = dict(os.environ, PYTHONPATH=SRC)
P, Q = '0123456789abcdef0123456789abcdef', 'fedcba9876543210fedcba9876543210'
PARITY = F.POLICY['parity_relative']
STEPS = 16


def near(value, reference, relative=PARITY):
    value, reference = np.asarray(value, dtype=float), np.asarray(reference, dtype=float)
    return float(np.abs(value-reference).max()) <= relative*max(float(np.abs(reference).max()), 1e-300)


def cli(*args, check=True):
    done = subprocess.run([sys.executable, '-B', str(TOOLS/'i02_column_workflow.py'), *map(str, args)],
                          capture_output=True, text=True, env=ENV, timeout=300)
    answer = json.loads(done.stdout.strip().splitlines()[-1])
    if check:
        assert done.returncode == 0 and answer['status'] == 'ok', (answer, done.stderr)
    return answer


class Workflow(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.root = self.folder/'projects'
        self.root.mkdir()

    def final_state(self, project):
        """The accepted head state of a project, reopened in this process through the ledger's restorer."""
        record = json.loads((self.root/project/'project.json').read_text(encoding='utf-8'))
        store = W.store(self.root/project/'ledger'/'ledger.sqlite')
        self.addCleanup(store.close)
        ledger = L.Ledger.open(store, record['ledger_id'], source_id=record['source_id'],
                               runtime_id=record['runtime_id'])
        return ledger, ledger.state(ledger.head())


class LifecycleTests(Workflow):
    def test_create_advance_inspect_save_load_and_continue_the_real_route(self):
        created = cli('create', '--root', self.root, '--project', P)['project']
        self.assertEqual((created['history'], created['head']['sequence'], created['run']), ('initial', 0, None))
        self.assertTrue(created['capabilities']['advance'])
        first = cli('advance', '--root', self.root, '--project', P, '--steps', 5, '--savepoint-steps', 2)['project']
        self.assertEqual((first['run']['state'], first['run']['outcome'], first['run']['accepted_steps']),
                         ('completed', 'COMPLETED', 5))
        self.assertEqual((first['history'], first['head']['accepted_steps'], first['head']['remaining_steps']),
                         ('partial', 5, STEPS-5))
        self.assertEqual(len(first['run']['commits']), 3)                       # savepoints 2, 4 and the end
        head = cli('inspect', '--root', self.root, '--project', P)['commit']
        self.assertEqual((head['key'], head['time_s']), (first['head']['key'], first['head']['time_s']))
        root = cli('inspect', '--root', self.root, '--project', P, '--commit', 'root')['commit']
        self.assertEqual((root['sequence'], root['history']), (0, 'initial'))
        field = cli('inspect', '--root', self.root, '--project', P, '--field', 'temperature_k')['field']
        self.assertEqual((field['units'], field['support'], field['accepted_steps'], len(field['values'])),
                         ('K', 'material point', 5, 32))
        kappa = cli('inspect', '--root', self.root, '--project', P, '--commit', first['run']['commits'][0],
                    '--field', 'kappa')['field']
        self.assertEqual(kappa['accepted_steps'], 2)
        saved = cli('save', '--root', self.root, '--project', P, '--to', self.folder/'saved')['saved']
        self.assertEqual((saved['head'], saved['accepted_steps']), (first['head']['key'], 5))
        loaded = cli('load', '--root', self.root, '--project', Q, '--from', self.folder/'saved')['project']
        self.assertEqual((loaded['head']['key'], loaded['attempt'], loaded['ledger_id']),
                         (saved['head'], 0, first['ledger_id']))
        ends = []
        for project in (Q, P):                                 # the loaded copy and the original both continue
            done = cli('advance', '--root', self.root, '--project', project, '--steps', STEPS-5)['project']
            self.assertEqual((done['run']['state'], done['run']['outcome'], done['history']),
                             ('completed', 'HISTORY_COMPLETE', 'complete'))
            self.assertFalse(done['capabilities']['advance'])
            ends.append(self.final_state(project)[1])
        self.assertEqual(ends[0].state_id, ends[1].state_id)   # the same saved head continues identically
        refused = cli('advance', '--root', self.root, '--project', P, '--steps', 1, check=False)
        self.assertEqual(refused['error']['code'], 'INVALID_REQUEST')           # the cumulative limit holds
        # The real route, not a hand-assembled one: the direct uninterrupted run of the same declared case.
        record = json.loads((self.root/P/'project.json').read_text(encoding='utf-8'))
        with threadpool_limits(limits=1, user_api='blas'):
            spec, inputs = W.case()
            state = W.build_root(spec, inputs, record['source_id'], record['runtime_id'])
            run = I.Continuation(state)
            five = run.advance(state, 5).state
            whole = run.advance(five, STEPS-5).state
        ledger, _ = self.final_state(P)
        self.assertEqual(ledger.root.state_id, state.state_id)
        commit = ledger.head()
        while commit.accepted_steps > 5:
            commit = self._parent(ledger, commit)
        self.assertEqual(ledger.state(commit).column.column_state_id, five.column.column_state_id)   # bitwise
        final = ends[1].column
        for name in ('theta_k', 'kappa'):
            self.assertTrue(near(getattr(final, name), getattr(whole.column, name)), name)
        names = I.STAGE_ACCOUNTS+I.THERMAL_ACCOUNTS
        self.assertTrue(near([final.accounts_j_m[n] for n in names], [whole.column.accounts_j_m[n] for n in names]))
        self.assertEqual(final.counters['stages'], whole.column.counters['stages'])

    @staticmethod
    def _parent(ledger, commit):
        walk = ledger.root
        while True:
            found = ledger.store.metadata(L.successor_key(ledger.ledger_id, walk.key))
            nxt = ledger._checked(found, walk)
            if nxt.key == commit.key:
                return walk
            walk = nxt

    def test_cancellation_between_steps_keeps_the_accepted_prefix(self):
        cli('create', '--root', self.root, '--project', P)
        worker = subprocess.Popen([sys.executable, '-B', str(TOOLS/'i02_column_workflow.py'), 'advance', '--root',
                                   str(self.root), '--project', P, '--steps', str(STEPS), '--savepoint-steps', '1'],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=ENV)
        status, started = self.root/P/'status.json', time.perf_counter()
        while True:
            self.assertLess(time.perf_counter()-started, 120, 'the worker never reported progress')
            try:
                run = json.loads(status.read_text(encoding='utf-8'))['run']
            except (ValueError, OSError):
                run = None
            if run and run['state'] == 'running' and run['accepted_steps'] >= 2:
                break
            time.sleep(.002)
        answer = W.cancel(self.root, P)                        # writes the request, then reports status
        self.assertEqual(answer['cancel'], dict(requested=True, attempt=1))
        out, err = worker.communicate(timeout=120)
        self.assertEqual(worker.returncode, 0, err)
        run = json.loads(out.strip().splitlines()[-1])['project']['run']
        self.assertEqual((run['state'], run['outcome']), ('cancelled', 'CANCELLED'))
        self.assertTrue(2 <= run['accepted_steps'] < STEPS, run)
        self.assertEqual(run['step'], run['accepted_steps'])
        after = cli('status', '--root', self.root, '--project', P)['project']
        self.assertEqual((after['history'], after['head']['accepted_steps']), ('partial', run['step']))
        self.assertTrue(after['capabilities']['advance'] and not after['capabilities']['cancel'])
        done = cli('advance', '--root', self.root, '--project', P, '--steps', STEPS-run['step'])['project']
        self.assertEqual(done['history'], 'complete')


class InspectionTests(Workflow):
    def test_status_and_inspection_read_the_root_and_one_commit_without_physics(self):
        cli('create', '--root', self.root, '--project', P)
        cli('advance', '--root', self.root, '--project', P, '--steps', 6, '--savepoint-steps', 2)
        script = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import i02_column_workflow as W
from atlas_tectonics import _integration_heat as H, integration_evolution as E
from atlas_tectonics.storage import ArrayStore
def refuse(*args, **kwargs):
    raise AssertionError('inspection ran physics or rebuilt an operator')
E.stage = H.eigh = H.prepare_propagator = refuse
reads, streams = [], []
get, stream = ArrayStore.get, ArrayStore.iter_chunks
def counted_get(self, key, **kw):
    reads.append(key)
    return get(self, key, **kw)
def counted_stream(self, key, name, **kw):
    streams.append((key, name))
    return stream(self, key, name, **kw)
ArrayStore.get, ArrayStore.iter_chunks = counted_get, counted_stream
root, project = Path(sys.argv[2]), sys.argv[3]
record = json.loads((root/project/'project.json').read_text(encoding='utf-8'))
W.identities = lambda: (record['source_id'], record['runtime_id'])     # no execution-identity capture here
status = W.status(root, project)
field = W.inspect(root, project, field='temperature_k')
print(json.dumps(dict(history=status['project']['history'], reads=reads, streams=streams,
                      units=field['field']['units'], root=status['project']['head']['root_state_id'],
                      head=status['project']['head']['key'])))
"""
        done = subprocess.run([sys.executable, '-B', '-c', script, str(TOOLS), str(self.root), P], capture_output=True,
                              text=True, env=ENV, timeout=300)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout.strip().splitlines()[-1])
        record = json.loads((self.root/P/'project.json').read_text(encoding='utf-8'))
        self.assertEqual((out['history'], out['units']), ('partial', 'K'))
        # Only the root (rebuilt when the ledger opens) and the inspected commit (restored and validated) are read.
        self.assertEqual(set(out['reads']), {record['root_key'], out['head']})
        self.assertEqual(out['streams'], [])

    def test_a_changed_identity_refuses_continuation_but_not_inspection(self):
        cli('create', '--root', self.root, '--project', P)
        cli('advance', '--root', self.root, '--project', P, '--steps', 2)
        cli('save', '--root', self.root, '--project', P, '--to', self.folder/'saved')
        changed = ('0'*64, '1'*64)
        with mock.patch.object(W, 'identities', return_value=changed):
            with self.assertRaises(W.JobError) as caught:
                W.advance(self.root, P, steps=1)
            self.assertEqual(caught.exception.code, 'SOURCE_MISMATCH')
            with self.assertRaises(W.JobError) as caught:
                W.load(self.root, Q, self.folder/'saved')
            self.assertEqual(caught.exception.code, 'SOURCE_MISMATCH')
            status = W.status(self.root, P)['project']
            self.assertFalse(status['identity_matches_current'] or status['capabilities']['advance'])
            self.assertEqual(W.inspect(self.root, P)['commit']['accepted_steps'], 2)
        self.assertFalse((self.root/Q).exists())

    def test_invalid_requests_change_nothing(self):
        cli('create', '--root', self.root, '--project', P)
        cli('advance', '--root', self.root, '--project', P, '--steps', 2)
        before = (self.root/P/'status.json').read_bytes()
        head = cli('inspect', '--root', self.root, '--project', P)['commit']
        half = head['time_s']+.5*head['schedule']['step_s']
        cases = {
            'fractional end time': (('advance', '--until-s', half), 'INVALID_REQUEST'),
            'zero steps': (('advance', '--steps', 0), 'INVALID_REQUEST'),
            'beyond the schedule': (('advance', '--steps', STEPS), 'INVALID_REQUEST'),
            'non-finite end time': (('advance', '--until-s', 'nan'), 'INVALID_REQUEST'),
            'infinite end time': (('advance', '--until-s', 'inf'), 'INVALID_REQUEST'),
            'fractional steps': (('advance', '--steps', '1.5'), 'INVALID_REQUEST'),
            'unknown field': (('inspect', '--field', 'elevation_m'), 'REFUSED'),
            'commit off the chain': (('inspect', '--commit', '4'*64), 'NO_RESULT'),
            'save over an existing path': (('save', '--to', self.root/P), 'REQUEST_CONFLICT'),
            'second create': (('create',), 'REQUEST_CONFLICT'),
        }
        for name, (args, code) in cases.items():
            with self.subTest(name):
                answer = cli(args[0], '--root', self.root, '--project', P, *args[1:], check=False)
                self.assertEqual((answer['status'], answer['error']['code']), ('error', code))
        self.assertEqual((self.root/P/'status.json').read_bytes(), before)
        answer = cli('advance', '--root', self.root, '--project', 'NOT-AN-ID', '--steps', 1, check=False)
        self.assertEqual(answer['error']['code'], 'INVALID_REQUEST')
        cli('save', '--root', self.root, '--project', P, '--to', self.folder/'saved')
        record = json.loads((self.folder/'saved'/'project.json').read_text(encoding='utf-8'))
        record['saved_head'] = '5'*64
        (self.folder/'saved'/'project.json').write_text(json.dumps(record), encoding='utf-8')
        answer = cli('load', '--root', self.root, '--project', Q, '--from', self.folder/'saved', check=False)
        self.assertEqual(answer['error']['code'], 'INVALID_STATE')
        self.assertFalse((self.root/Q).exists())

    def test_status_inspection_cancel_and_load_never_write_what_they_read(self):
        cli('create', '--root', self.root, '--project', P)
        cli('advance', '--root', self.root, '--project', P, '--steps', 3)
        cli('save', '--root', self.root, '--project', P, '--to', self.folder/'saved')
        (self.root/P/'worker.lock').unlink()                   # a lock file is never created by a reader

        def files(folder):
            return {p.relative_to(folder).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in sorted(folder.rglob('*')) if p.is_file()}
        project, saved = files(self.root/P), files(self.folder/'saved')
        W.status(self.root, P)
        W.inspect(self.root, P)
        W.inspect(self.root, P, commit='root', field='theta_k')
        W.cancel(self.root, P)
        W.load(self.root, Q, self.folder/'saved')
        self.assertEqual((files(self.root/P), files(self.folder/'saved')), (project, saved))
        ledger = self.root/P/'ledger'/'ledger.sqlite'
        ledger.rename(ledger.with_name('moved.sqlite'))
        for call in (lambda: W.status(self.root, P), lambda: W.inspect(self.root, P)):
            with self.assertRaises(FileNotFoundError):
                call()                                         # a missing store is reported, never created
        self.assertFalse(ledger.exists())

    def test_status_rolls_back_a_commit_whose_writer_was_killed(self):
        W.create(self.root, P)
        W.advance(self.root, P, steps=2)
        before = W.status(self.root, P)['project']['head']['key']
        ledger = self.root/P/'ledger'/'ledger.sqlite'
        size = ledger.stat().st_size
        script = r"""
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import i02_column_workflow as W
from atlas_tectonics import integration_clock as K, integration_ledger as L
from atlas_tectonics.storage import ArrayStore, StoreLimits, storage_profile
directory = Path(sys.argv[2])/sys.argv[3]
record = W._project(directory)
profile = storage_profile('balanced')
s = ArrayStore(W._ledger_path(directory), StoreLimits(chunk_bytes=profile.chunk_bytes, max_array_bytes=64 << 20,
                                                      max_store_bytes=512 << 20, decoded_cache_bytes=4 << 20,
                                                      sqlite_cache_bytes=1024), profile.compression)
ledger = L.Ledger.open(s, record['ledger_id'], source_id=record['source_id'], runtime_id=record['runtime_id'])
real = s.metadata
def dying(key):
    if s._db.in_transaction:            # the commit's rows are written and COMMIT is not reached; spill, then die
        s._db.execute('INSERT INTO chunks VALUES(?,?,?,?,?)', ('f'*64, b'{}', 'raw', '0'*64, bytes(4 << 20)))
        print(W._ledger_path(directory).stat().st_size, flush=True)
        os._exit(9)
    return real(key)
s.metadata = dying
K.Clock(ledger).advance(steps=1)
"""
        done = subprocess.run([sys.executable, '-B', '-c', script, str(TOOLS), str(self.root), P], capture_output=True,
                              text=True, env=ENV, timeout=300)
        self.assertEqual(done.returncode, 9, done.stderr)
        journal = Path(str(ledger)+'-journal')
        self.assertTrue(journal.exists())                       # a hot journal was left behind
        self.assertGreater(int(done.stdout.split()[-1]), size)  # uncommitted pages had reached the database file
        status = W.status(self.root, P)['project']              # recovered through the native store, then read
        self.assertEqual((status['head']['key'], status['head']['accepted_steps']), (before, 2))
        self.assertFalse(journal.exists())
        self.assertEqual(ledger.stat().st_size, size)
        with closing(sqlite3.connect(ledger)) as raw:
            self.assertEqual(raw.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(W.advance(self.root, P, steps=1)['project']['head']['accepted_steps'], 3)

    def test_load_verifies_every_commit_and_accepts_only_the_exact_record(self):
        cli('create', '--root', self.root, '--project', P)
        cli('advance', '--root', self.root, '--project', P, '--steps', 4, '--savepoint-steps', 1)
        saved = self.folder/'saved'
        cli('save', '--root', self.root, '--project', P, '--to', saved)
        record = json.loads((saved/'project.json').read_text(encoding='utf-8'))
        edits = {'injected key': lambda r: r.update(note='copied along'),
                 'another case': lambda r: r.update(case='cases/i01_weakening_v1.json'),
                 'missing case': lambda r: r.pop('case'), 'another case id': lambda r: r.update(case_id='other'),
                 'another root key': lambda r: r.update(root_key='6'*64),
                 'foreign status': lambda r: r.update(status='CANON')}
        for name, edit in edits.items():
            with self.subTest(name):
                copy = self.folder/name.replace(' ', '-')
                shutil.copytree(saved, copy)
                changed = dict(record)
                edit(changed)
                (copy/'project.json').write_text(json.dumps(changed), encoding='utf-8')
                with self.assertRaises(W.JobError) as caught:
                    W.load(self.root, Q, copy)
                self.assertEqual(caught.exception.code, 'INVALID_STATE')
                self.assertFalse((self.root/Q).exists())
        # One payload byte of an earlier commit's own chunk: the head is untouched, so only a full check finds it.
        second = L.successor_key(record['ledger_id'], L.successor_key(record['ledger_id'], record['root_key']))
        raw = sqlite3.connect(saved/'ledger.sqlite')
        body = json.loads(raw.execute('SELECT body FROM snapshots WHERE id=?', (second,)).fetchone()[0])
        chunk = body['arrays']['column.theta_k']['chunks'][0]
        payload = bytearray(raw.execute('SELECT payload FROM chunks WHERE id=?', (chunk,)).fetchone()[0])
        payload[len(payload)//2] ^= 1
        raw.execute('UPDATE chunks SET payload=? WHERE id=?', (bytes(payload), chunk))
        raw.commit()
        raw.close()
        answer = cli('load', '--root', self.root, '--project', Q, '--from', saved, check=False)
        self.assertEqual((answer['status'], answer['error']['code']), ('error', 'STORE_REFUSED'))
        self.assertFalse((self.root/Q).exists())
        self.assertEqual(cli('inspect', '--root', self.root, '--project', P)['commit']['accepted_steps'], 4)

    def test_the_attempt_limit_refuses_without_committing_and_status_stays_readable(self):
        cli('create', '--root', self.root, '--project', P)
        path = self.root/P/'status.json'
        state = json.loads(path.read_text(encoding='utf-8'))
        state['attempt'] = W.MAX_ATTEMPTS
        path.write_text(json.dumps(state), encoding='utf-8')
        before = path.read_bytes()
        answer = cli('advance', '--root', self.root, '--project', P, '--steps', 1, check=False)
        self.assertEqual(answer['error']['code'], 'ATTEMPT_LIMIT')
        self.assertEqual(path.read_bytes(), before)
        after = cli('status', '--root', self.root, '--project', P)['project']
        self.assertEqual((after['attempt'], after['head']['accepted_steps']), (W.MAX_ATTEMPTS, 0))

    def test_an_interrupted_run_is_reported_from_the_committed_head(self):
        W.create(self.root, P)
        W.advance(self.root, P, steps=3, savepoint_steps=1)
        path = self.root/P/'status.json'
        state = json.loads(path.read_text(encoding='utf-8'))
        state['attempt'] += 1                                  # a worker that died after its first progress report
        state['run'] = dict(state='running', attempt=state['attempt'], start_step=1, accepted_steps=1,
                            head=state['head'])
        path.write_text(json.dumps(state), encoding='utf-8')
        project = W.status(self.root, P)['project']
        run = project['run']
        self.assertEqual((run['state'], run['step'], run['accepted_steps'], run['head']),
                         ('interrupted', 3, 2, project['head']['key']))


class RobustnessTests(Workflow):
    """Review round 5: read-only projects, path limits, held status files, occupied request paths, truthful
    capabilities, replaced ledgers, foreign saved records, malformed files and interrupted runs."""

    def poll_hook(self, action):
        """Run ``action(directory, attempt)`` once, at the running advance's first poll between steps."""
        original, done = W._Watch.__call__, []

        def poll(watch):
            if not done:
                done.append(1)
                state = json.loads((self.root/P/'status.json').read_text(encoding='utf-8'))
                action(self.root/P, state['attempt'])
            return original(watch)
        return mock.patch.object(W._Watch, '__call__', poll)

    def test_status_and_inspection_work_on_a_read_only_project(self):
        W.create(self.root, P)
        W.advance(self.root, P, steps=2)
        files = [p for p in (self.root/P).rglob('*') if p.is_file()]
        for path in files:
            os.chmod(path, stat.S_IREAD)
        self.addCleanup(lambda: [os.chmod(path, stat.S_IREAD | stat.S_IWRITE) for path in files])
        project = W.status(self.root, P)['project']
        self.assertEqual((project['head']['accepted_steps'], project['worker_active']), (2, False))
        self.assertEqual(W.inspect(self.root, P, field='kappa')['field']['accepted_steps'], 2)

    @unittest.skipUnless(os.name == 'nt', "Windows' classic 260-character path limit")
    def test_paths_too_long_for_what_the_workflow_writes_are_refused_up_front(self):
        def deep(length):                      # a new directory whose path is at least ``length`` characters
            path = self.folder/('deep-%d' % length)
            while len(str(path)) < length:
                path = path/('d'*max(1, min(40, length-len(str(path))-1)))
            path.mkdir(parents=True)
            return path
        long_root = deep(260-1-32-W.LONGEST_IN_PROJECT)
        with self.assertRaises(W.JobError) as caught:
            W.create(long_root, P)
        self.assertEqual(caught.exception.code, 'INVALID_PATH')
        self.assertEqual(list(long_root.iterdir()), [])
        W.create(self.root, P)
        parent = deep(260-W.LONGEST_IN_SAVE+5)
        with self.assertRaises(W.JobError) as caught:
            W.save(self.root, P, parent/'saved')
        self.assertEqual(caught.exception.code, 'INVALID_PATH')
        self.assertEqual(list(parent.iterdir()), [])
        short = deep(len(str(self.folder))+12)         # a short parent, but a destination name too long to hold a store
        name = 'n'*(260-W.LONGEST_IN_SAVED-len(str(short)))
        for call in (lambda: W.save(self.root, P, short/name), lambda: W.load(self.root, Q, short/name)):
            with self.assertRaises(W.JobError) as caught:
                call()
            self.assertEqual(caught.exception.code, 'INVALID_PATH')
        self.assertEqual(list(short.iterdir()), [])

    @unittest.skipUnless(sys.platform == 'win32', 'a reader blocking a replacement is a Windows behaviour')
    def test_a_reader_holding_the_status_file_never_stalls_the_run_or_loses_its_outcome(self):
        W.create(self.root, P)
        path, holding, release = self.root/P/'status.json', threading.Event(), threading.Event()

        def hold():
            with path.open('rb'):
                holding.set()
                release.wait(30)

        def start_holding(directory, attempt):
            threading.Thread(target=hold, daemon=True).start()
            self.assertTrue(holding.wait(10))
            threading.Timer(2., release.set).start()
        started = time.perf_counter()
        with self.poll_hook(start_holding):
            run = W.advance(self.root, P, steps=8, savepoint_steps=1)['project']['run']
        elapsed = time.perf_counter()-started
        self.assertEqual((run['state'], run['accepted_steps']), ('completed', 8))
        self.assertLess(elapsed, 7.)                 # progress while held was skipped at once, not waited for
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['run']['state'], 'completed')

    def test_an_occupied_cancellation_path_is_replaced_or_reported(self):
        W.create(self.root, P)
        answers = []

        def oversized(directory, attempt):
            W._cancel_path(directory, attempt).write_bytes(b' '*(W.MAX_REQUEST+1))
            answers.append(W.cancel(self.root, P)['cancel'])
        with self.poll_hook(oversized):
            run = W.advance(self.root, P, steps=4, savepoint_steps=1)['project']['run']
        self.assertEqual(answers, [dict(requested=True, attempt=1)])
        self.assertEqual(run['state'], 'cancelled')

        def occupied(directory, attempt):
            W._cancel_path(directory, attempt).mkdir()
            with self.assertRaises(W.JobError) as caught:
                W.cancel(self.root, P)
            answers.append(caught.exception.code)
        with self.poll_hook(occupied):
            run = W.advance(self.root, P, steps=2)['project']['run']
        self.assertEqual((answers[-1], run['state']), ('INVALID_STATE', 'completed'))

    def test_capabilities_reflect_the_attempt_limit_and_an_occupied_request_path(self):
        W.create(self.root, P)
        path = self.root/P/'status.json'
        state = json.loads(path.read_text(encoding='utf-8'))
        self.assertTrue(W.status(self.root, P)['project']['capabilities']['advance'])
        path.write_text(json.dumps(dict(state, attempt=W.MAX_ATTEMPTS)), encoding='utf-8')
        self.assertFalse(W.status(self.root, P)['project']['capabilities']['advance'])
        path.write_text(json.dumps(state), encoding='utf-8')
        W._cancel_path(self.root/P, 1).mkdir()
        self.assertFalse(W.status(self.root, P)['project']['capabilities']['advance'])
        W._cancel_path(self.root/P, 1).rmdir()
        self.assertTrue(W.status(self.root, P)['project']['capabilities']['advance'])

    def test_a_replaced_ledger_is_reported_and_not_continued(self):
        W.create(self.root, P)
        W.advance(self.root, P, steps=2)
        ledger = self.root/P/'ledger'/'ledger.sqlite'
        shutil.copyfile(ledger, self.folder/'older.sqlite')
        W.advance(self.root, P, steps=2)
        shutil.copyfile(self.folder/'older.sqlite', ledger)       # an older copy put back behind the status file
        project = W.status(self.root, P)['project']
        self.assertEqual((project['recorded_head_on_ledger'], project['capabilities']['advance'],
                          project['head']['accepted_steps']), (False, False, 2))
        before = ledger.read_bytes()
        with self.assertRaises(W.JobError) as caught:
            W.advance(self.root, P, steps=1)
        self.assertEqual(caught.exception.code, 'INVALID_STATE')
        self.assertEqual(ledger.read_bytes(), before)

    def test_a_ledger_swapped_in_from_another_project_of_the_same_case_is_refused(self):
        W.create(self.root, P)
        W.create(self.root, Q)
        W.advance(self.root, P, steps=2)                         # one commit, at step 2
        W.advance(self.root, Q, steps=3, savepoint_steps=1)      # commits at steps 1, 2 and 3: the same keys
        shutil.copyfile(self.root/Q/'ledger'/'ledger.sqlite', self.root/P/'ledger'/'ledger.sqlite')
        project = W.status(self.root, P)['project']
        self.assertEqual((project['recorded_head_on_ledger'], project['capabilities']['advance']), (False, False))
        with self.assertRaises(W.JobError) as caught:
            W.advance(self.root, P, steps=1)
        self.assertEqual(caught.exception.code, 'INVALID_STATE')

    def test_load_refuses_a_saved_store_holding_foreign_records(self):
        W.create(self.root, P)
        W.advance(self.root, P, steps=2)
        W.save(self.root, P, self.folder/'saved')
        s = W.store(self.folder/'saved'/'ledger.sqlite')
        try:
            s.put('9'*64, {'padding': np.zeros(8)}, {'note': 'not a commit of this ledger'})
        finally:
            s.close()
        with self.assertRaises(W.JobError) as caught:
            W.load(self.root, Q, self.folder/'saved')
        self.assertEqual(caught.exception.code, 'INVALID_STATE')
        self.assertFalse((self.root/Q).exists())

    def test_malformed_project_files_are_invalid_state(self):
        W.create(self.root, P)
        state = json.loads((self.root/P/'status.json').read_text(encoding='utf-8'))
        without_head = {key: value for key, value in state.items() if key != 'head'}
        for name, text in (('status.json', '['*2000+']'*2000), ('project.json', '{not json'),
                           ('status.json', json.dumps(state)[:-1]+', "huge": '+'9'*5000+'}'),
                           ('status.json', json.dumps(without_head)), ('status.json', json.dumps(dict(state, head=None)))):
            with self.subTest(name=name, text=text[:40]):
                path = self.root/P/name
                original = path.read_bytes()
                path.write_text(text, encoding='utf-8')
                for call in (lambda: W.status(self.root, P), lambda: W.advance(self.root, P, steps=1)):
                    with self.assertRaises(W.JobError) as caught:
                        call()
                    self.assertEqual(caught.exception.code, 'INVALID_STATE')
                path.write_bytes(original)

    def test_only_a_hot_journal_opens_the_live_store_for_a_snapshot(self):
        W.create(self.root, P)
        source, copy_ = W._ledger_path(self.root/P), self.folder/'copy.sqlite'
        for code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_READONLY, sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_IOERR,
                     sqlite3.SQLITE_READONLY_ROLLBACK):
            error = sqlite3.OperationalError('injected')
            error.sqlite_errorcode = code
            with self.subTest(code=code), mock.patch.object(W.sqlite3, 'connect', side_effect=error), \
                    mock.patch.object(W, 'store') as opened, self.assertRaises(sqlite3.OperationalError):
                W._backup(source, copy_, recover=True)
            self.assertEqual(opened.call_count, code == sqlite3.SQLITE_READONLY_ROLLBACK)
            self.assertFalse(copy_.exists())

    def test_an_interrupted_run_records_the_interruption_at_the_committed_head(self):
        W.create(self.root, P)
        original, polls = W._Watch.__call__, []

        def poll(watch):
            polls.append(1)
            if len(polls) == 3:
                raise KeyboardInterrupt
            return original(watch)
        with mock.patch.object(W._Watch, '__call__', poll), self.assertRaises(KeyboardInterrupt):
            W.advance(self.root, P, steps=6)
        run = json.loads((self.root/P/'status.json').read_text(encoding='utf-8'))['run']
        head = W.status(self.root, P)['project']['head']
        self.assertEqual((run['state'], run['error']['code'], run['head'], run['step']),
                         ('interrupted', 'INTERRUPTED', head['key'], head['accepted_steps']))
        self.assertEqual(head['accepted_steps'], 2)                 # the steps accepted before it are kept


class RequestFileTests(Workflow):
    """Cancellation files and concurrent creation: nothing left over, malformed or foreign stops or blocks a run."""

    def test_a_leftover_request_never_cancels_a_new_attempt(self):
        cli('create', '--root', self.root, '--project', P)
        leftover = W._cancel_path(self.root/P, 1)
        leftover.write_text(json.dumps(dict(project_id=P, attempt=1)), encoding='utf-8')
        run = cli('advance', '--root', self.root, '--project', P, '--steps', 2)['project']['run']
        self.assertEqual((run['state'], run['accepted_steps']), ('completed', 2))
        self.assertFalse(leftover.exists())
        W._cancel_path(self.root/P, 2).mkdir()                 # not a file: refused, and the attempt is not used
        before = (self.root/P/'status.json').read_bytes()
        answer = cli('advance', '--root', self.root, '--project', P, '--steps', 1, check=False)
        self.assertEqual(answer['error']['code'], 'INVALID_STATE')
        self.assertEqual((self.root/P/'status.json').read_bytes(), before)

    def test_malformed_foreign_and_non_regular_requests_never_stop_a_run(self):
        W.create(self.root, P)
        directory = self.root/P
        writers = {
            'malformed': lambda path, attempt: path.write_bytes(b'{not json'),
            'deeply nested': lambda path, attempt: path.write_bytes(b'['*2000+b']'*2000),
            'foreign project': lambda path, attempt: path.write_text(json.dumps(dict(project_id=Q, attempt=attempt))),
            'next attempt': lambda path, attempt: _cancel_next(path, attempt),
            'directory': lambda path, attempt: path.mkdir(),
        }
        original = W._Watch.__call__
        for name, write in writers.items():
            with self.subTest(name):
                written = []

                def poll(watch):
                    if not written:
                        attempt = json.loads((directory/'status.json').read_text(encoding='utf-8'))['attempt']
                        write(W._cancel_path(directory, attempt), attempt)
                        written.append(attempt)
                    return original(watch)
                with mock.patch.object(W._Watch, '__call__', poll):
                    run = W.advance(self.root, P, steps=2)['project']['run']
                self.assertEqual((run['state'], run['outcome'], run['accepted_steps']), ('completed', 'COMPLETED', 2))
                self.assertTrue(written)

    def test_two_projects_can_be_created_at_once(self):
        workers = [subprocess.Popen([sys.executable, '-B', str(TOOLS/'i02_column_workflow.py'), 'create', '--root',
                                     str(self.root), '--project', project], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, env=ENV) for project in (P, Q)]
        answers = [json.loads(w.communicate(timeout=300)[0].strip().splitlines()[-1]) for w in workers]
        self.assertEqual([a['status'] for a in answers], ['ok', 'ok'], answers)
        self.assertEqual(sorted(p.name for p in self.root.iterdir() if not p.name.endswith('.lock')), sorted((P, Q)))


def _cancel_next(path, attempt):
    """A valid request for the next attempt, written while this one runs: it must not touch either attempt."""
    W._cancel_path(path.parent, attempt+1).write_text(json.dumps(dict(project_id=P, attempt=attempt+1)),
                                                      encoding='utf-8')


class OutcomeTests(Workflow):
    """Correction round A5/A6/D: every run outcome answers on the command line with its JSON line and a truthful exit
    code, and an advance answers for its own attempt even when another starts as soon as its lock is released."""

    SCRIPT = r"""
import json, sys, types
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import i02_column_workflow as W
from atlas_tectonics import integration_state as I
record = json.loads((Path(sys.argv[3])/sys.argv[4]/'project.json').read_text(encoding='utf-8'))
W.identities = lambda: (record['source_id'], record['runtime_id'])   # an injected ending is not a source change
mode, real, calls = sys.argv[2], I.Continuation.advance, []
def patched(self, state, steps, **kwargs):        # two real whole steps, then the requested ending
    calls.append(1)
    if len(calls) <= 2:
        return real(self, state, steps, **kwargs)
    if mode == 'refused':
        return types.SimpleNamespace(accepted_steps=0, status='REFUSED_TEMPERATURE_STEP', reason='patched refusal')
    if mode == 'failed':
        raise RuntimeError('patched failure inside the run')
    raise KeyboardInterrupt
I.Continuation.advance = patched
sys.argv = ['i02_column_workflow.py', 'advance', '--root', sys.argv[3], '--project', sys.argv[4], '--steps', '6']
raise SystemExit(W.main())
"""

    def ended(self, mode):
        done = subprocess.run([sys.executable, '-B', '-c', self.SCRIPT, str(TOOLS), mode, str(self.root), P],
                              capture_output=True, text=True, env=ENV, timeout=300)
        return done.returncode, json.loads(done.stdout.strip().splitlines()[-1]), done.stderr

    def test_each_run_outcome_answers_with_its_line_and_exit_code(self):
        cli('create', '--root', self.root, '--project', P)
        partial = cli('advance', '--root', self.root, '--project', P, '--steps', 4, '--max-seconds', 1e-6)['project']
        self.assertEqual((partial['run']['state'], partial['run']['outcome'], partial['run']['accepted_steps']),
                         ('partial', 'REFUSED_DEADLINE', 0))                     # the budget ended before a step
        self.assertTrue(partial['capabilities']['advance'])
        code, answer, err = self.ended('refused')
        run = answer['project']['run']
        self.assertEqual((code, answer['status'], run['state'], run['outcome'], run['accepted_steps']),
                         (0, 'ok', 'refused', 'REFUSED_TEMPERATURE_STEP', 2), err)
        code, answer, err = self.ended('failed')
        run = answer['project']['run']
        self.assertEqual((code, answer['status'], answer['error']['code'], run['state'], run['accepted_steps']),
                         (2, 'error', 'WORKER_FAILED', 'failed', 2), err)       # never exit 0 with "ok"
        code, answer, err = self.ended('interrupted')
        self.assertEqual((code, answer['status'], answer['error']['code']), (2, 'error', 'INTERRUPTED'), err)
        after = cli('status', '--root', self.root, '--project', P)['project']
        self.assertEqual((after['run']['state'], after['attempt'], after['head']['accepted_steps']),
                         ('interrupted', 4, 6))                                  # 2+2+2 committed steps are kept

    def test_a_ledger_advanced_outside_the_worker_lock_fails_the_run(self):
        W.create(self.root, P)
        record = json.loads((self.root/P/'project.json').read_text(encoding='utf-8'))
        original, polls = W._Watch.__call__, []

        def poll(watch):
            polls.append(1)
            if len(polls) == 2:                       # another writer, bypassing the lock, commits one step
                s = W.store(W._ledger_path(self.root/P))
                try:
                    outside = L.Ledger.open(s, record['ledger_id'], source_id=record['source_id'],
                                            runtime_id=record['runtime_id'])
                    K.Clock(outside).advance(steps=1)
                finally:
                    s.close()
            return original(watch)
        with mock.patch.object(W._Watch, '__call__', poll):
            answer = W.advance(self.root, P, steps=3)
        run = answer['project']['run']
        self.assertEqual((answer['status'], answer['error']['code'], run['state'], run['outcome'],
                          run['accepted_steps']), ('error', 'INVALID_STATE', 'failed', 'REFUSED_STALE_PARENT', 0))
        self.assertEqual(answer['project']['head']['accepted_steps'], 1)

    def test_an_advance_answers_for_its_own_attempt_while_another_waits_or_is_refused(self):
        W.create(self.root, P)
        path = self.root/P/'status.json'
        watch, lock, patient, status = W._Watch.__call__, W.jobs._lock, W._lock_patiently, W.status
        for queued in (False, True):
            with self.subTest(queued=queued):
                attempt = json.loads(path.read_text(encoding='utf-8'))['attempt']
                start = W.status(self.root, P)['project']['head']['accepted_steps']
                running, waiting, refused, first, answers = (threading.Event(), threading.Event(), threading.Event(),
                                                             [], {})

                def poll(poller):
                    if not first:                # the first run holds its lock until the second advance waits
                        first.append(1)
                        running.set()
                        assert waiting.wait(60)
                        assert queued or refused.wait(60)     # ... or until that advance has given up
                    return watch(poller)

                @contextmanager
                def observed(lock_path):
                    held = lock(lock_path)
                    try:
                        held.__enter__()
                    except W.JobError:
                        if threading.current_thread().name == 'second':
                            waiting.set()
                        raise
                    try:
                        yield
                    finally:
                        held.__exit__(None, None, None)

                def patiently(lock_path, seconds=2.):
                    return patient(lock_path, 60. if queued else seconds)

                def late(root, project_id):      # an answer read after the lock is released would see attempt+2
                    if threading.current_thread().name == 'first':
                        until = time.perf_counter()+10
                        while time.perf_counter() < until and json.loads(path.read_text(
                                encoding='utf-8'))['attempt'] < attempt+2:
                            time.sleep(.01)
                    return status(root, project_id)

                def run(steps):
                    name = threading.current_thread().name
                    try:
                        answers[name] = W.advance(self.root, P, steps=steps)
                    except W.JobError as exc:
                        answers[name] = exc.code
                        refused.set()
                with mock.patch.object(W._Watch, '__call__', poll), mock.patch.object(W.jobs, '_lock', observed), \
                        mock.patch.object(W, '_lock_patiently', patiently), mock.patch.object(W, 'status', late):
                    one = threading.Thread(target=run, args=(2,), name='first')
                    one.start()
                    self.assertTrue(running.wait(120))
                    two = threading.Thread(target=run, args=(1,), name='second')
                    two.start()
                    one.join(120)
                    two.join(120)
                mine = answers['first']['project']
                self.assertEqual((mine['run']['attempt'], mine['run']['state'], mine['head']['accepted_steps'],
                                  mine['worker_active']), (attempt+1, 'completed', start+2, False))
                if queued:
                    theirs = answers['second']['project']
                    self.assertEqual((theirs['run']['attempt'], theirs['run']['state'],
                                      theirs['head']['accepted_steps']), (attempt+2, 'completed', start+3))
                else:
                    self.assertEqual(answers['second'], 'RUN_BUSY')


class CaseTests(Workflow):
    def test_the_workflow_case_is_the_checked_fixture_column(self):
        with threadpool_limits(limits=1, user_api='blas'):
            spec, inputs = W.case()
            case = W.build_root(spec, inputs, F.SOURCE_ID, F.RUNTIME_ID)
            fixture = F.root(STEPS)
        self.assertEqual((case.reference.reference_id, case.settings.settings_id, case.column.column_state_id,
                          case.materials.state_id),
                         (fixture.reference.reference_id, fixture.settings.settings_id, fixture.column.column_state_id,
                          fixture.materials.state_id))
        self.assertEqual((case.settings.steps, case.settings.step_s, case.reservoirs), (STEPS, 6.25e12, None))
        self.assertTrue(np.any(case.column.theta_k < 0) and np.any(case.column.initial_kappa > 0))


if __name__ == '__main__':
    unittest.main()
