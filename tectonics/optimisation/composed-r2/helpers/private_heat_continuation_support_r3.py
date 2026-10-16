"""Source-fenced, job-guarded first/second interval and cold-reader lifecycle.
Derived from pinned support r2; all previous input/store/ledger checks
remain. First producer has no old checkpoint input; every reader or
continuation copies its separately hash-bound predecessor.
"""
from contextlib import contextmanager
from hashlib import sha256
import importlib.machinery
import json
import os
from pathlib import Path
import shutil
import sys
from time import monotonic, sleep
import traceback

HERE = Path(__file__).resolve().parent
MANIFEST = 'continuation-preparation-r3.json'
SAVE_RETRIES, SAVE_RETRY_SECONDS = 100, 0.1          # ten seconds for a receipt someone is reading


def file_hash(path):
    digest = sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def atomic_save(path, record):
    path = Path(path)
    temporary = path.with_name(path.name+'.writing')
    created = False
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            created = True
            json.dump(record, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        # Whatever reads the receipt (a monitor, an editor, a scanner) can deny its replacement while it
        # holds the file; a large receipt read line by line can be held for more than a second.
        for attempt in range(SAVE_RETRIES):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == SAVE_RETRIES-1:
                    raise
                sleep(SAVE_RETRY_SECONDS)
    finally:
        if created and temporary.exists():
            temporary.unlink()


def error_record(record, error, stage):
    """Preserve the original failure, including when cleanup or capture also fails."""
    item = dict(stage=stage, type=type(error).__name__, message=str(error),
                traceback=''.join(traceback.format_exception(error)))
    record.setdefault('errors', []).append(item)
    if 'failure' not in record:
        record.update(failure=str(error), failure_type=type(error).__name__, failure_stage=stage)
    record['status'] = 'INTERRUPTED' if isinstance(error, KeyboardInterrupt) else 'FAILED'


def attempt(record, stage, operation):
    try:
        return operation()
    except BaseException as error:
        error_record(record, error, stage)
        return None


def store_limits(previous):
    """Larger per-run envelope, preserving codec/chunks/cache/total store policy."""
    result = dict(previous)
    if result.get('chunk_bytes') != 65536 or result.get('max_store_bytes') != 4 << 30:
        raise ValueError('Expected the accepted 64KiB chunks and 4GiB store envelope')
    result.update(max_array_bytes=1 << 30, max_manifest_bytes=2 << 20,
                  max_staging_bytes=2 << 30)
    return result


def disk_preflight(folder, limits):
    # Conservative additional free space for copied/growing DB, rollback journal,
    # and disk staging. None of these ceilings allocates memory or disk here.
    required = 2*limits['max_store_bytes'] + limits['max_staging_bytes']
    free = shutil.disk_usage(folder).free
    if free < required:
        raise OSError('Insufficient free disk for database, rollback journal and staging envelopes')
    return dict(required_free_bytes=required, available_free_bytes=free)


def metered_re_reads(workflow, budget, meter, log):
    """Explicit resource-admission adapter; no token precheck or skipped read.

    The unchanged native refresh owns stale-token, parent/root and publication
    checks. The meter, not this adapter, decides healthy/failed/nested scope use.
    """
    original = workflow._refresh

    def refresh():
        started = monotonic()
        row = dict(status='STARTED', name='workflow-refresh-%d' % (len(log)+1))
        log.append(row)
        try:
            with meter.read_scope(budget, row['name']):
                value = original()
            row['status'] = 'RETURNED'
            return value
        except BaseException as error:
            row.update(status='FAILED', failure_type=type(error).__name__)
            raise
        finally:
            row['seconds'] = monotonic()-started
    workflow._refresh = refresh
    return original


class ContinuationSources:
    """Validate common bindings and refuse unlisted local imports before execution."""
    def __init__(self, root, receipt, manifest):
        self.root = Path(root).resolve()
        self.pins = dict(receipt['participating_imported_helper_sources'])
        for name, digest in receipt['native_source']['clone_source_hashes'].items():
            self._add('native-composed-r7/tectonics/src/'+name, digest)
        for name, digest in manifest['files'].items():
            self._add(name, digest)

    def _add(self, name, digest):
        if name in self.pins and self.pins[name] != digest:
            raise ValueError('New harness cannot replace a producer source: '+name)
        self.pins[name] = digest

    def path(self, name):
        path = (self.root/name).resolve()
        if not path.is_relative_to(self.root) or Path(name).is_absolute():
            raise ValueError('Source outside private candidate')
        return path

    def validate_before_imports(self):
        for name, digest in self.pins.items():
            if file_hash(self.path(name)) != digest:
                raise ValueError('Bound source changed: '+name)

    def check_imported(self):
        found = {}
        for module in tuple(sys.modules.values()):
            name = getattr(module, '__file__', None)
            if not name:
                continue
            path = Path(name).resolve()
            if path.is_relative_to(self.root) and path.suffix == '.py':
                relative = path.relative_to(self.root).as_posix()
                if relative not in self.pins or file_hash(path) != self.pins[relative]:
                    raise ValueError('Unbound/changed participating source: '+relative)
                found[relative] = self.pins[relative]
        return found

    @contextmanager
    def imports(self):
        outer = self

        class Loader(importlib.machinery.SourceFileLoader):
            def get_code(self, fullname):
                path = Path(self.path).resolve()
                name = path.relative_to(outer.root).as_posix()
                raw = path.read_bytes()
                if name not in outer.pins or sha256(raw).hexdigest() != outer.pins[name]:
                    raise ImportError('Unbound/changed private import: '+name)
                return compile(raw, str(path), 'exec', dont_inherit=True)

        class Finder:
            def find_spec(self, fullname, path=None, target=None):
                spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
                if spec and spec.origin and spec.origin.endswith('.py'):
                    location = Path(spec.origin).resolve()
                    if location.is_relative_to(outer.root):
                        spec.loader = Loader(fullname, str(location))
                        return spec
                return None

        finder = Finder()
        sys.meta_path.insert(0, finder)
        try:
            self.check_imported()
            yield
        finally:
            sys.meta_path.remove(finder)


def execute_cli(worker, driver_file, *, schema, success, kind):
    """Terminal evidence on every admitted attempt, including finalisation errors."""
    if kind not in ('first', 'continue', 'first-read', 'reopen'):
        raise ValueError('Unknown lifecycle kind')
    import argparse
    parser = argparse.ArgumentParser()
    for name in (() if kind == 'first' else ('receipt', 'database')):
        parser.add_argument('--'+name, type=Path, required=True)
        parser.add_argument('--'+name+'-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-manifest-sha256', required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.parent != HERE or output.suffix != '.json':
        raise ValueError('New output directly in private candidate required')
    record = dict(schema=schema, status='STARTED', production_acceptance=False,
                  pid=os.getpid(), phases=[], errors=[], operation=kind)
    # Exclusive admission precedes imports and source/input checks. No old output
    # or old checkpoint can be replaced by this lifecycle.
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(record, stream)
        stream.write('\n')
    save = lambda: atomic_save(output, record)
    guard = budget = sources = None
    completed = False
    inputs = {}
    copied = None
    began = monotonic()
    manifest_path = HERE/MANIFEST
    try:
        if not sys.dont_write_bytecode:
            raise RuntimeError('Run with -B to preserve frozen source')
        if file_hash(manifest_path) != args.source_manifest_sha256.lower():
            raise ValueError('Explicit preparation manifest hash differs')
        manifest = json.loads(manifest_path.read_bytes())
        for name in (Path(__file__).name, Path(driver_file).name,
                     'private_heat_continuation_guard_r3.py'):
            if file_hash(HERE/name) != manifest['files'][name]:
                raise ValueError('Bootstrap helper differs from explicit manifest: '+name)
        from private_heat_continuation_guard_r3 import ContinuationGuard, RSS_LIMIT, FREE_FLOOR
        guard = ContinuationGuard(output, record, save)
        record['guard_limits'] = dict(rss_bytes=RSS_LIMIT, free_floor_bytes=FREE_FLOOR,
                                      start_available_bytes=RSS_LIMIT+FREE_FLOOR)
        record['preparation_manifest_sha256'] = args.source_manifest_sha256.lower()
        if kind == 'first':
            receipt = dict(participating_imported_helper_sources={},
                native_source=dict(clone_source_hashes={}))
        else:
            for name in ('receipt', 'database'):
                path = getattr(args, name).resolve()
                if not path.is_relative_to(HERE):
                    raise ValueError('Private candidate input required')
                expected_hash = getattr(args, name+'_sha256').lower()
                if file_hash(path) != expected_hash:
                    raise ValueError('Explicit producer input hash differs: '+name)
                inputs[str(path)] = expected_hash
                setattr(args, name, path)
            record['inputs'] = inputs
            if args.receipt.stat().st_size > 16 << 20:
                raise ValueError('Receipt exceeds 16MiB')
            receipt = json.loads(args.receipt.read_bytes())
            if receipt.get('database_sha256') != inputs[str(args.database)]:
                raise ValueError('Database is not the one bound by the producer receipt')
            if any(Path(str(args.database)+s).exists() for s in ('-wal', '-journal')):
                raise ValueError('Producer database must be closed, without WAL/journal')
        sources = ContinuationSources(HERE, receipt, manifest)
        sources.validate_before_imports()
        with sources.imports():
            if kind == 'first':
                expected = None
                limits = dict(chunk_bytes=65536, max_array_bytes=512 << 20,
                    max_store_bytes=4 << 30, max_staging_bytes=1 << 30)
            else:
                if kind in ('continue', 'first-read'):
                    import probe_heat_original_reopen_r4 as reader
                else:
                    import probe_heat_original_continue_reopen_r3 as reader
                expected = reader._expected(receipt, os.getpid())
                record['producer'] = dict(pid=expected['producer_pid'], status=receipt['status'],
                    schema=receipt['schema'], head_key=expected['head_key'], workflow_id=expected['workflow_id'])
                record['producer_pid'] = expected['producer_pid']
                limits = store_limits(expected['store_limits']) if kind == 'continue' else expected['store_limits']
            record['store_limits'] = limits
            record['disk_preflight'] = disk_preflight(HERE, limits)
            import psutil
            # Room for the guardian's ceiling above its floor. r1 asked for 5.25 GiB, which admits a run
            # that the floor then stops at its first cold read, minutes or an hour in.
            start_floor = RSS_LIMIT+FREE_FLOOR
            available = psutil.virtual_memory().available
            record['memory_at_start'] = dict(available_bytes=available, required_bytes=start_floor)
            if available < start_floor:
                raise MemoryError('At least %.2fGiB free physical RAM required at start' % (start_floor/(1 << 30)))
            artifacts = output.with_suffix('.artifacts')
            artifacts.mkdir(exist_ok=False)
            record['artifacts'] = str(artifacts)
            copied = artifacts/'native-joined.sqlite'
            if kind != 'first':
                guard.phase('copy-closed-producer-checkpoint')
                with copied.open('xb') as destination, args.database.open('rb') as original:
                    for block in iter(lambda: original.read(1 << 20), b''):
                        guard.check()
                        destination.write(block)
                if file_hash(copied) != inputs[str(args.database)]:
                    raise ValueError('Checkpoint copy differs')
                record['advanced_database' if kind == 'continue' else 'consumer_database'] = str(copied)
            os.environ['ATLAS_FOCUSED_ARTIFACT_DIR'] = str(artifacts)
            # Capture is a participating helper before use, including failure paths.
            import private_heat_native_failure_capture_r6 as capture
            try:
                if kind == 'first':
                    budget = worker(record, artifacts, guard, save)
                elif kind == 'continue':
                    budget = worker(record, artifacts, guard, save, receipt, copied, sources)
                else:
                    budget = worker(receipt, copied, guard.phase, record, sources=sources, guard=guard)
                completed = True
                record['status'] = 'VERIFYING'
            except BaseException as error:
                error_record(record, error, 'workload')
                # The traceback, and what the ledger and the meter held, are made durable before anything
                # slower: after a guard trigger this process has five seconds. Named "at failure": taken
                # before the frames are retired, they are not the final figures.
                attempt(record, 'early-failure-save', save)
                def early_accounting():
                    held = getattr(guard, 'budget', None)
                    meter = sys.modules.get('private_heat_process_meter_r1')
                    if held is not None:
                        record['logical_budget_at_failure'] = held.statistics()
                        if meter is not None:
                            record['heat_read_memory_at_failure'] = meter.record(held)
                attempt(record, 'early-failure-accounting', early_accounting)
                attempt(record, 'early-failure-save', save)
                attempt(record, 'failure-capture', lambda: record.update(
                    failure_capture=capture.capture(sys.exc_info(), artifacts/'failure')))
            record['participating_imported_helper_sources'] = sources.check_imported()
    except BaseException as error:
        error_record(record, error, 'preflight-or-source-finalisation')
    finally:
        import gc
        attempt(record, 'frame-retirement', gc.collect)
        budget = budget if budget is not None else getattr(guard, 'budget', None)
        def accounting():
            meter = sys.modules.get('private_heat_process_meter_r1')
            if meter is not None and budget is not None:
                record['carried_after_last_read_bytes'] = meter.settle_carried(budget)
                record['heat_read_memory'] = meter.record(budget)
            if budget is not None:
                record['final_logical_budget'] = budget.statistics()
                record['final_reserved_bytes'] = budget.reserved_bytes
                if budget.reserved_bytes:
                    raise RuntimeError('Reservations remain after frame retirement')
        attempt(record, 'accounting', accounting)
        def bindings():
            if any(file_hash(path) != digest for path, digest in inputs.items()):
                raise ValueError('Producer input changed')
            if file_hash(manifest_path) != args.source_manifest_sha256.lower():
                raise ValueError('Preparation manifest changed')
            if sources is not None:
                sources.validate_before_imports()
                record['participating_imported_helper_sources'] = sources.check_imported()
            record['input_hashes_unchanged'] = True
            record['participating_sources_unchanged'] = True
        attempt(record, 'final-bindings', bindings)
        def consumer_copy():
            # The copy the reader opened, byte for byte, once its store has closed: the store's own token
            # speaks for one connection only. Its own attempt, so that it hides no other binding.
            if kind in ('first-read', 'reopen') and completed:
                if (file_hash(copied) != inputs[str(args.database)]
                        or any(Path(str(copied)+s).exists() for s in ('-wal', '-journal'))):
                    raise ValueError('The reader changed its copy of the saved database')
                record['consumer_database_unchanged'] = True
        attempt(record, 'consumer-copy-unchanged', consumer_copy)
        try:
            # For the record only: what the operating system kept for this process. The guardian's
            # figure is a sample of the whole tree every quarter second; this is the parent's own peak.
            import psutil
            memory = psutil.Process().memory_info()
            record['parent_os_peak'] = {name: getattr(memory, name) for name in
                ('rss', 'peak_wset', 'private', 'peak_pagefile') if hasattr(memory, name)}
        except Exception as error:
            record['parent_os_peak_unavailable'] = repr(error)
        if guard is not None:
            attempt(record, 'final-guard-check', lambda: guard.check(force=True))
        record['elapsed_seconds'] = monotonic()-began
        if record['status'] == 'STARTED':
            error_record(record, RuntimeError('No completed workload result'), 'finalisation')
        # Persist before close as well: on escalation the guardian owns the final
        # terminal override after confirmed death of this process.
        try:
            save()
        finally:
            if guard is not None:
                attempt(record, 'guardian-shutdown', guard.close)
            if completed and not record['errors'] and record['status'] == 'VERIFYING':
                record['status'] = success
            save()
    print(json.dumps({k: record.get(k) for k in ('status', 'elapsed_seconds', 'failure')}), flush=True)
    return 0 if record['status'] == success else 1
