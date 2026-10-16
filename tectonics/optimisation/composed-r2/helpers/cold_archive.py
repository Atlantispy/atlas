"""Purposeful cold-bundle finalisation, outside simulation/checkpoint work.

Closed diagnostic/export files are copied, compressed and restored under a
single owned Windows Job before a measured format is selected. Originals are
never retired. Only receipt-authenticated bundles from this writer may restore.
"""
from concurrent.futures import CancelledError
from contextlib import ExitStack
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time

from codec_training import TrainingJob, _executable_lock

TAR = Path('C:/Windows/System32/tar.exe')
TAR_SHA256 = 'a3ac62fd4cdf619a7c53f71ca3fe5fb42f72020975670ff29afe3603f6416a8e'
WORKER = Path(__file__).with_name('cold_archive_worker.py')
JOB_LIMIT = 128 << 20
PARENT_ALLOWANCE = 16 << 20
MAX_JSON = 256 << 10
KINDS = ('completed-diagnostics', 'cold-export')
_SHA = re.compile(r'[0-9a-f]{64}\Z')


class ArchiveRefused(RuntimeError):
    pass


def _require(condition, message):
    if not condition:
        raise ArchiveRefused(message)


def _cancel(token):
    if token is not None and token.is_set():
        raise CancelledError('cold bundle operation cancelled')


def _json_bytes(value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode('utf-8') + b'\n'
    _require(len(raw) <= MAX_JSON, 'bounded bundle metadata exceeded')
    return raw


def _read_json(path, expected=None):
    _require(path.is_file() and not path.is_symlink(), 'missing regular bundle metadata')
    with path.open('rb') as stream:
        raw = stream.read(MAX_JSON + 1)
    _require(len(raw) <= MAX_JSON, 'bundle metadata exceeds fixed limit')
    if expected is not None:
        _require(sha256(raw).hexdigest() == expected, 'bundle metadata identity differs')
    value = json.loads(raw)
    _require(type(value) is dict, 'bundle metadata must be an object')
    return value


def _safe_directory(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        stat = part.lstat()
        _require(part.is_dir() and not part.is_symlink()
                 and not getattr(stat, 'st_file_attributes', 0) & 0x400,
                 'directory contains a link or reparse point')
    return path


def _destination(path):
    path = Path(os.path.abspath(path))
    _safe_directory(path.parent)
    _require(not os.path.lexists(path), 'destination already exists')
    return path


class _MemoryOwner:
    def __init__(self, budget):
        self.reservation = budget.reserve(JOB_LIMIT + PARENT_ALLOWANCE, category='cold-bundle')
        self.reservation.__enter__()

    def close(self):
        value, self.reservation = self.reservation, None
        if value is not None:
            value.__exit__(None, None, None)

    def __del__(self):
        self.close()


def _run(request, destination, *, budget, cancel, timeout_seconds):
    _require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
             and 0 < timeout_seconds <= 30, 'cold bundle timeout must be within 30 seconds')
    _cancel(cancel)
    destination = _destination(destination)
    memory = _MemoryOwner(budget)
    try:
        with tempfile.TemporaryDirectory(prefix='wp10-cold-', dir=destination.parent) as private_name:
            private = _safe_directory(private_name)
            candidate = private / 'candidate'
            request = dict(request, destination=str(candidate), tar_executable=str(TAR),
                           max_seconds=timeout_seconds, ratio_limit=.8)
            (private / 'request.json').write_bytes(_json_bytes(request))
            worker_sha = sha256(WORKER.read_bytes()).hexdigest()
            job = process = None
            started = time.monotonic()
            with ExitStack() as locks:
                locks.enter_context(_executable_lock(TAR, TAR_SHA256))
                locks.enter_context(_executable_lock(WORKER, worker_sha))
                try:
                    _cancel(cancel)
                    job = TrainingJob()
                    limits = job.verify_limits()
                    _require(limits['job_memory_limit_bytes'] == JOB_LIMIT
                             and limits['process_memory_limit_bytes'] == JOB_LIMIT,
                             'cold bundle aggregate Job limits differ')
                    env = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP')
                           if key in os.environ}
                    env['PYTHONDONTWRITEBYTECODE'] = '1'
                    process = job.launch([sys.executable, '-I', '-B', str(WORKER),
                                          str(private / 'request.json'), str(private / 'result.json')],
                                         env, private)
                    while process.poll() is None:
                        _cancel(cancel)
                        remaining = timeout_seconds - (time.monotonic() - started)
                        _require(remaining > 0, 'cold bundle operation exceeded timeout')
                        process.wait(min(.1, remaining))
                    _cancel(cancel)
                    result = _read_json(private / 'result.json')
                    _require(process.poll() == 0 and result.get('status') == 'ok',
                             'cold bundle worker failed: ' + str(result.get('error', 'no detail'))[:2048])
                    # The Windows venv launcher and its interpreter have
                    # separate handles. Reap every still-live owned member,
                    # including interpreter teardown, before releasing memory.
                    # Completed PIDs may linger in accounting; member() verifies
                    # exact membership/liveness and excludes recycled PIDs.
                    join_deadline = min(started + timeout_seconds, time.monotonic() + 2)
                    while True:
                        active = False
                        for pid in job.job.pids():
                            member = job.job.member(pid)
                            if member is not None:
                                active = True
                                try:
                                    _cancel(cancel)
                                    remaining = join_deadline - time.monotonic()
                                    _require(remaining > 0, 'cold bundle descendant did not finish teardown')
                                    member.wait(min(.1, remaining))
                                finally:
                                    member.close()
                        if not active:
                            break
                    metrics = dict(job.metrics(), operation_elapsed_seconds=time.monotonic() - started)
                except BaseException:
                    if job is not None:
                        stopped = job.stop()
                        _require(not stopped.get('remaining') and not stopped.get('action_errors'),
                                 'cold bundle termination did not join the owned process tree')
                    raise
                finally:
                    if process is not None:
                        process.close()
                    if job is not None:
                        job.close()
            _safe_directory(candidate)
            if request['action'] == 'finalise':
                receipt = _read_json(candidate / 'receipt.json')
                _require(receipt.get('schema') == 'atlas.cold-bundle-receipt.v1'
                         and receipt.get('selected_format') in ('tar.zst', 'directory'),
                         'worker receipt schema differs')
                receipt['measurements'] = dict(receipt.get('measurements', {}), **metrics)
                receipt['limits'] = dict(limits, parent_allowance_bytes=PARENT_ALLOWANCE,
                                        timeout_seconds=timeout_seconds)
                receipt['tar_executable_sha256'] = TAR_SHA256
                receipt['worker_sha256'] = worker_sha
                receipt_path = candidate / 'receipt.json'
                # The small fixed point includes the receipt's own decimal size.
                for _ in range(4):
                    encoded = _json_bytes(receipt)
                    _require(len(encoded) <= receipt['policy']['receipt_bytes_allowance_for_ratio'],
                             'final receipt exceeds routing metadata allowance')
                    receipt_path.write_bytes(encoded)
                    size = sum(path.stat().st_size for path in candidate.rglob('*') if path.is_file())
                    if receipt.get('stored_bytes') == size:
                        break
                    receipt['stored_bytes'] = size
                else:
                    raise ArchiveRefused('receipt size did not stabilise')
                result = dict(receipt=receipt, selected_format=receipt['selected_format'],
                              receipt_path=str(destination / 'receipt.json'),
                              receipt_sha256=sha256(receipt_path.read_bytes()).hexdigest(),
                              measurements=receipt['measurements'], deliverable_bytes=size)
            else:
                result['measurements'] = dict(result.get('measurements', {}), **metrics)
            _cancel(cancel)
            _require(not os.path.lexists(destination), 'destination appeared before publication')
            candidate.rename(destination)
        memory.close()
        return result
    except BaseException as error:
        # The traceback may retain request/receipt buffers; keep them funded.
        error._wp10_cold_memory_owner = memory
        raise


def finalise_completed_bundle(source_root, file_names, destination, *, kind, budget,
                              cancel=None, timeout_seconds=30):
    """Automatically select a measured archive for explicit closed export files."""
    _require(kind in KINDS, 'only completed diagnostics or cold exports are eligible')
    _require(type(file_names) in (list, tuple) and 0 < len(file_names) <= 256
             and all(type(name) is str and len(name) <= 100 for name in file_names),
             'bounded explicit file list required')
    source = _safe_directory(source_root)
    return _run(dict(action='finalise', source_root=str(source), files=list(file_names), kind=kind),
                destination, budget=budget, cancel=cancel, timeout_seconds=timeout_seconds)


def restore_completed_bundle(bundle, destination, *, expected_receipt_sha256, budget,
                             cancel=None, timeout_seconds=30):
    """Restore a writer-produced bundle to a new directory; never register it live.

    The expected receipt SHA must come from the saved finalisation result, not
    from the untrusted bundle being opened. Arbitrary external archives are not
    accepted by this API.
    """
    _cancel(cancel)
    _require(type(expected_receipt_sha256) is str and _SHA.fullmatch(expected_receipt_sha256),
             'trusted receipt SHA-256 required')
    source = _safe_directory(bundle)
    receipt = _read_json(source / 'receipt.json', expected_receipt_sha256)
    _require(receipt.get('schema') == 'atlas.cold-bundle-receipt.v1'
             and receipt.get('kind') in KINDS, 'unsupported receipt schema or purpose')
    manifest_sha = receipt.get('manifest_sha256')
    _require(type(manifest_sha) is str and _SHA.fullmatch(manifest_sha), 'missing manifest identity')
    manifest = _read_json(source / 'manifest.json', manifest_sha)
    return _run(dict(action='restore', source_root=str(source), receipt=receipt, manifest=manifest),
                destination, budget=budget, cancel=cancel, timeout_seconds=timeout_seconds)
