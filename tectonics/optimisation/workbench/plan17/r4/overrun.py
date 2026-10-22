"""One nonterminal overrun event; delivery never runs on the resource-guard thread."""
import argparse
import ctypes
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

LAUNCHER = Path('C:/Users/LOCAL_USER/Documents/Codex/atlas-run-events/launch_notify.py')
LAUNCHER_SHA = 'e278d24176363c216be1610254934d257d334f0293d29f88329ef411c917ddad'
DELIVERY_SECONDS = 30
WORKER_SECONDS = 100


def write_json(path, value):
    pending = path.with_suffix('.pending')
    with pending.open('x', encoding='utf8') as stream:
        json.dump(value, stream, indent=2)
    pending.replace(path)


def load_delivery():
    if sha256(LAUNCHER.read_bytes()).hexdigest() != LAUNCHER_SHA:
        raise ValueError('qualified completion helper changed')
    spec = importlib.util.spec_from_file_location('plan17_qualified_delivery', LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_contained


def deliver(config, directory, runner=None):
    """Persist before each send; a failed/ambiguous attempt is never retried."""
    directory = Path(directory)
    path = directory / 'overrun.json'
    record = dict(schema='plan17-overrun.r1', event_id=config['event_id'], nonterminal=True,
                  status='attempting', notifications={})
    with path.open('x', encoding='utf8') as stream:
        json.dump(record, stream, indent=2)
    recipients = list(dict.fromkeys(str(uuid.UUID(config[key])) for key in ('owner', 'coordinator')))
    runner = load_delivery() if runner is None else runner
    message = (f"Plan17 actionable overrun event {config['event_id']}. NONTERMINAL: "
               f"{config['phase']} exceeded 1.5x its {config['projected_minutes']}-minute booking "
               f"at {config['elapsed_seconds']:.3f}s. Request SHA256 {config['manifest_sha256']}; "
               f"request {config['manifest_path']}; proof record {config['result_directory']}; "
               f"delivery record {path}. The fixed surface-query proof has exceeded its projected duration; "
               "a query-level cause is not established by this guard. Owner and coordinator: "
               "recommendation is to continue under "
               "the unchanged memory guards and child timeouts while the owner checks current "
               "progress and decides whether an owned cancellation is justified. No new kill deadline, "
               "retry, next-run clearance or scientific acceptance. Deduplicate by event ID; "
               "queued delivery is submission, not confirmation that a recipient read it.")
    for recipient in recipients:
        target = directory / recipient
        target.mkdir()
        entry = dict(status='attempting', directory=str(target))
        record['notifications'][recipient] = entry
        write_json(path, record)
        try:
            result = runner(dict(argv=[config['codex'], 'queue', '--thread', recipient,
                                       '--message', message], cwd=config['cwd']),
                            target, timeout=DELIVERY_SECONDS)
            entry['process'] = result
            entry['status'] = ('queued' if result.get('outcome') == 'succeeded'
                               and result.get('exit_code') == 0 and result.get('tree_final') is True
                               else 'failed_or_unconfirmed')
        except Exception as failure:
            entry.update(status='failed_or_unconfirmed', error=type(failure).__name__ + ': ' + str(failure))
        write_json(path, record)
    record['status'] = ('queued' if all(item['status'] == 'queued'
                                      for item in record['notifications'].values())
                        else 'failed_or_unconfirmed')
    write_json(path, record)
    return record


class GuardedEvent:
    """Aggregate retained proof/notice jobs; close neither until final drain."""
    def __init__(self, proof, owned, config, env, *, clock=time.monotonic, job_factory=None):
        self.proof, self.owned, self.config, self.env = proof, owned, config, env
        self.clock = clock
        self.notice = (owned.backend() if job_factory is None else job_factory)()
        self.directory = Path(config['result_directory']) / 'overrun'
        self.thread = None
        self.started = clock()
        self.triggered_at = None
        self.cancelled = threading.Event()
        self.launch_done = threading.Event()
        self.launch_error = None
        self.worker_timeout = False

    def trigger(self):
        if self.thread is not None:
            return
        self.triggered_at = self.clock()
        self.thread = threading.Thread(target=self._launch, name='plan17-overrun-launch', daemon=True)
        try:
            self.thread.start()
        except Exception as failure:
            self.launch_error = type(failure).__name__ + ': ' + str(failure)
            self.launch_done.set()

    def _launch(self):
        try:
            self.directory.mkdir()
            config = dict(self.config, elapsed_seconds=self.triggered_at - self.started)
            write_json(self.directory / 'config.json', config)
            with (self.directory / 'stdout.log').open('xb') as stdout, (self.directory / 'stderr.log').open('xb') as stderr:
                if not self.cancelled.is_set():
                    self.notice.start([sys.executable, '-B', '-I', str(Path(__file__).resolve()),
                                       '--deliver', str(self.directory / 'config.json')],
                                      str(Path(__file__).resolve().parent), self.env, stdout, stderr)
        except BaseException as failure:
            self.launch_error = type(failure).__name__ + ': ' + str(failure)
        finally:
            self.launch_done.set()

    def sleep(self, seconds):
        if self.thread is None and self.clock() - self.started > self.config['projected_minutes'] * 90:
            self.trigger()
        time.sleep(seconds)

    def snapshot(self):
        proof = self.proof.snapshot()
        notice = self.notice.accounting()
        if (self.thread is not None and (notice['active'] or not self.launch_done.is_set())
                and self.clock() - self.triggered_at > WORKER_SECONDS):
            self.worker_timeout = True
            self.cancelled.set()
        if self.cancelled.is_set() and notice['active']:
            self.notice.terminate_owned()
            notice = self.notice.accounting()
        launching = self.thread is not None and not self.launch_done.is_set()
        return dict(exit_code=proof['exit_code'],
                    job=dict(active=proof['job']['active'] + notice['active'] + int(launching)),
                    proof=proof, notification=notice, notification_launch_pending=launching)

    def sample(self, unused):
        pids = {os.getpid()}
        for job in (self.proof, self.notice):
            members = self.owned.JobPids()
            if not job.k.QueryInformationJobObject(job.job, 3, ctypes.byref(members), ctypes.sizeof(members), None):
                raise OSError(ctypes.get_last_error(), 'owned combined membership unavailable')
            if members.assigned != members.listed or members.listed > 256:
                raise ValueError('incomplete combined job membership sample')
            pids.update(int(members.ids[index]) for index in range(members.listed))
        rss = 0
        for pid in pids:
            try:
                rss += self.owned.psutil.Process(pid).memory_info().rss
            except self.owned.psutil.NoSuchProcess:
                continue
        return rss, self.owned.psutil.virtual_memory().available

    def terminate_owned(self):
        self.cancelled.set()
        return dict(proof=self.proof.terminate_owned(), notification=self.notice.terminate_owned())

    def outcome(self):
        record = dict(triggered=self.thread is not None, worker_timeout=self.worker_timeout,
                      launch_error=self.launch_error, ownership=dict(self.notice.identity))
        if self.thread is not None:
            record['worker_exit_code'] = self.notice.exit_code()
            record['worker_finality'] = self.notice.accounting()
            try:
                record['delivery'] = json.loads((self.directory / 'overrun.json').read_bytes())
            except Exception as failure:
                record['delivery'] = dict(status='failed_or_unconfirmed',
                                         error=type(failure).__name__ + ': ' + str(failure))
            if (self.launch_error or self.worker_timeout or record['worker_exit_code'] != 0
                    or record['worker_finality']['active'] or record['delivery'].get('status') != 'queued'):
                record['delivery']['status'] = 'failed_or_unconfirmed'
        return record

    def close(self):
        if self.thread is not None and not self.launch_done.is_set():
            raise RuntimeError('notification launch unresolved; retain ownership')
        self.notice.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deliver', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.deliver.read_bytes())
    result = deliver(config, args.deliver.parent)
    return 0 if result['status'] == 'queued' else 1


if __name__ == '__main__':
    raise SystemExit(main())
