"""CHECK3 metadata at existing boundaries; no worker, observer or sampler.

Integration candidate only. The existing guard owns this recorder's lifetime.
The producer binds its actual forward ledger; the pool verifies object identity.
Journals are append-only, bounded per record, hash-bound at close, not last-N.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import time

FLOOR = 5368709120
SCHEMA = 'atlas.check3.recording.r1'
_active = None


def stamp():
    return dict(monotonic_ns=time.monotonic_ns(), utc=datetime.now(timezone.utc).isoformat())


def source():
    path = Path(__file__).resolve()
    return dict(path=str(path), sha256=sha256(path.read_bytes()).hexdigest())


class Journal:
    def __init__(self, path, binding):
        self.path = Path(path)
        self.stream = self.path.open('xb', buffering=0)
        self.digest, self.count, self.closed = sha256(), 0, False
        self.append(dict(kind='header', schema=SCHEMA, binding=binding,
                         clock='time.monotonic_ns; same-host system monotonic clock', source=source()))

    def append(self, row):
        if self.closed:
            raise RuntimeError('CHECK3 journal already closed')
        raw = (json.dumps(dict(sequence=self.count, **row), sort_keys=True,
                          allow_nan=False, separators=(',', ':'))+'\n').encode('utf8')
        if len(raw) > 1048576:
            raise ValueError('CHECK3 single metadata record exceeds 1 MiB')
        if self.stream.write(raw) != len(raw):
            raise OSError('CHECK3 short journal write')
        self.digest.update(raw)
        self.count += 1

    def finish(self, complete):
        if self.closed:
            raise RuntimeError('CHECK3 journal closed twice')
        try:
            self.append(dict(kind='footer', complete=complete, time=stamp()))
            os.fsync(self.stream.fileno())
        finally:
            self.stream.close()
            self.closed = True
        return dict(path=str(self.path), sha256=self.digest.hexdigest(), records=self.count,
                    complete=complete, schema=SCHEMA)


class Producer:
    def __init__(self, guard):
        self.guard = guard
        self.journal = Journal(guard.output.with_suffix('.check3-producer.jsonl'),
                               dict(nonce=guard.nonce, parent=guard.identity))
        self.calls, self.brackets, self.ledger = 0, 0, None
        self.open_brackets = set()
        self.failed = False
        self.sources = {}

    def bind_source(self, path):
        path = Path(path).resolve()
        pin = sha256(path.read_bytes()).hexdigest()
        old = self.sources.get(str(path))
        if old is not None and old != pin:
            raise RuntimeError('CHECK3 reached source changed during recording')
        if old is None:
            self.sources[str(path)] = pin
            self.journal.append(dict(kind='reached-source', path=str(path), sha256=pin))

    @contextmanager
    def forward(self, ledger, selected_phases, caller_source):
        global _active
        if _active is not None or self.ledger is not None:
            raise RuntimeError('CHECK3 nested/competing forward binding')
        if (not selected_phases or len(set(selected_phases)) != len(selected_phases)
                or any(type(x) is not str or not x for x in selected_phases)):
            raise ValueError('CHECK3 complete selected phase set required')
        self.bind_source(caller_source)
        self.journal.append(dict(kind='forward-begin', time=stamp(), selected_heat_phases=selected_phases,
                                 ledger_type=type(ledger).__module__+'.'+type(ledger).__qualname__))
        self.ledger, _active = ledger, self
        try:
            yield
        except BaseException:
            self.failed = True
            raise
        finally:
            try:
                self.journal.append(dict(kind='forward-end', time=stamp(), calls=self.calls,
                                         complete=not self.failed and not self.open_brackets))
            finally:
                self.ledger, _active = None, None

    def entry(self, budget, meter, faces):
        # METER.active checks the actual Meter type/closed state at the pool.
        # Neither the scratch side ledger nor a supplied numeric alias is accepted.
        if budget is not self.ledger or meter.budget is not self.ledger:
            raise RuntimeError('CHECK3 actual forward-ledger object differs')
        self.guard.check(force=True)
        self.calls += 1
        import psutil
        before = stamp()
        physical = psutil.virtual_memory().available
        physical_time = stamp()
        available = self.ledger.available_bytes
        ledger_time = stamp()
        valid = (type(physical) is int and physical >= 0 and type(available) is int and available >= 0)
        passed = valid and physical >= FLOOR and available >= FLOOR
        self.journal.append(dict(kind='reconstruction-entry', call=self.calls, faces=faces,
            boundary='reconstruct_faces before workers() and before _Pool/worker dispatch',
            before=before, physical=dict(counter='psutil.virtual_memory().available', units='bytes',
                value=physical, time=physical_time),
            forward_ledger=dict(counter='actual forward WorkBudget.available_bytes', units='bytes',
                value=available, time=ledger_time), minimum_bytes=FLOOR, passed=passed))
        # Durable refusal evidence before dispatch, without any budget reservation.
        os.fsync(self.journal.stream.fileno())
        if not passed:
            self.failed = True
            raise RuntimeError('CHECK3 reconstruction entry physical/forward-ledger 5 GiB conjunction refused')

    @contextmanager
    def reread(self):
        self.brackets += 1
        token = self.brackets
        self.open_brackets.add(token)
        self.journal.append(dict(kind='reread-begin', bracket=token, time=stamp(),
                                 operation='producer-re-read-after-publication'))
        completed = False
        try:
            yield
            completed = True
        finally:
            self.journal.append(dict(kind='reread-end', bracket=token, time=stamp(), completed=completed))
            self.open_brackets.remove(token)
            if not completed:
                self.failed = True

    def phase(self, name):
        self.journal.append(dict(kind='phase', name=name, time=stamp()))

    def finish(self):
        if self.ledger is not None or self.open_brackets:
            self.failed = True
        for path in self.sources:
            self.bind_source(path)
        return self.journal.finish(not self.failed)


def reconstruction_entry(budget, meter, faces, caller_source):
    # Other proof/reader routes remain unchanged. Selected IV must bind forward()
    # and its receiver must require nonempty complete entries; absence never passes.
    if _active is not None:
        if meter is None or meter.categories is not None or meter.failed:
            _active.failed = True
            raise RuntimeError('CHECK3 actual live forward meter required at every reconstruction entry')
        _active.bind_source(caller_source)
        _active.entry(budget, meter, faces)


def existing_reread(caller_source):
    from contextlib import nullcontext
    if _active is not None:
        _active.bind_source(caller_source)
    return nullcontext() if _active is None else _active.reread()


class GuardSamples:
    def __init__(self, output, nonce, interval):
        self.journal = Journal(Path(output).with_suffix('.check3-samples.jsonl'),
            dict(nonce=nonce, configured_interval_seconds=interval,
                 membership='same Windows job exact member handles; guardian excluded',
                 metric='RESOURCE_DIAGNOSTICS.sample_job.process_tree_rss_bytes'))

    def observe(self, sample, before, after, phase, sample_number):
        self.journal.append(dict(kind='job-sample', sample=sample_number, before_ns=before,
            after_ns=after, phase=phase, process_tree_rss_bytes=sample['process_tree_rss_bytes'],
            process_count=sample['process_count'], worker_process_count=sample['worker_process_count'],
            members=[dict(pid=x['pid'], created_ticks=x['created_ticks'], rss_bytes=x['rss_bytes'])
                     for x in sample['live_processes']]))

    def finish(self, receipt):
        return self.journal.finish(receipt.get('status') == 'STOPPED'
            and receipt.get('workload_exit_confirmed') is True
            and receipt.get('cleanup') == dict(remaining=[], action_errors=[]))
