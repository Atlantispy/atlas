"""Step 8 native storage admission and bounded live publication boundary.

Applied to reviewed sources at composition time. No frozen source is edited,
no scientific issuer is replaced, and cold readers retain full validation.
"""
import json
from contextlib import contextmanager
from pathlib import Path
import sys

# WP16, capture-digest generation 2026-10-16: the three pre-advance operands are
# written as atlas.diagnostic-capture.v1 files (exact bytes, zstd level 3) instead
# of gzip level 1. raw_bytes/raw_sha256 remain the codec-independent logical
# identity (for the mesh, the view's geometry_id); container_sha256 only
# authenticates one file against its own receipt and is never compared across runs.
CAPTURE_FORMAT = 'atlas.diagnostic-capture.v1'
CAPTURE_KINDS = {'mesh': 'mesh', 'closed_graph': 'closed-graph', 'bounds': 'bounds'}
CAPTURE_CHUNK = 65536
# The existing pinned WP10 Zstandard library in its permanent folder; there is no
# raw or gzip fallback: a missing or changed library refuses. It is named by its
# task-relative key (the runtime manifest's data_only key) and found under the one
# ancestor of this module that holds it, so no machine path is written here.
CAPTURE_LIBRARY_KEY = ('fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/'
                       'resumability-r1/compact-geometry-r1/native/wp10_zstd.dll')
CAPTURE_LIBRARY_SHA256 = 'a40c24ad328da37a42c7f69e434c576254f11fde4097cd5de7416f8f78444f28'


def _holds(path):
    """True when PATH is a file. A probe the system refuses (an access-restricted or sandboxed
    ancestor) counts as not holding it: before Python 3.14 is_file() re-raises errors other than
    not-found, which would stop this module importing on every route, compact or not."""
    try:
        return path.is_file()
    except OSError:
        return False


def task_file(key, folder=None):
    """KEY under the one ancestor of FOLDER (default: this module's folder) that holds it as a file.

    None when no ancestor or more than one does, an ancestor whose probe fails counting as not
    holding it: the caller refuses then, never guesses. Nothing is opened here; the library's
    sha256 pin authenticates its bytes when loaded.
    """
    start = Path(__file__).resolve().parent if folder is None else Path(folder).resolve()
    found = [parent/key for parent in (start, *start.parents) if _holds(parent/key)]
    return found[0] if len(found) == 1 else None


CAPTURE_LIBRARY = task_file(CAPTURE_LIBRARY_KEY)
# Explicit capture ceilings: capture_store's 4 GiB default would stop a run at its
# pre-advance step once the streamed mesh outgrows it (the gzip route had no ceiling).
# 16 GiB is the run's existing logical ceiling; capture streams 64 KiB at a time.
CAPTURE_MAX_BYTES = 16 << 30
_CAPTURE_BACKEND = None


def capture_backend():
    """One pinned ZstdBackend per process."""
    global _CAPTURE_BACKEND
    if _CAPTURE_BACKEND is None:
        if CAPTURE_LIBRARY is None:
            raise FileNotFoundError('pinned capture library is not under exactly one ancestor of %s: %s'
                                    % (Path(__file__).resolve().parent, CAPTURE_LIBRARY_KEY))
        from storage_zstd_backend import ZstdBackend
        _CAPTURE_BACKEND = ZstdBackend(CAPTURE_LIBRARY, expected_sha256=CAPTURE_LIBRARY_SHA256)
    if _CAPTURE_BACKEND.library_sha256 != CAPTURE_LIBRARY_SHA256:
        raise ValueError('pre-advance capture backend identity changed')
    return _CAPTURE_BACKEND


def require_capture_route(store):
    """Refuse at run start, not after the advance, when a compact run cannot write its captures.

    Every entry point that reaches inspect_compact_preadvance calls this before any
    physical work: fresh_interval_driver's advance_first_interval and
    advance_successor_interval, and prepared_interval_driver's advance_prepared_interval.
    The two capture modules are imported, not only found, so inside the selected
    runtime its Loader runs their pin check now; capture_backend() then loads the pinned
    library and checks its sha256. This module itself imports without the capture route,
    so compositions without it still import. Returns the library's sha256 for a compact
    store, else None.

    The store's own class decides which: a store whose class is not named
    CompactRestartStore is another route's store, returns None and imports nothing (a
    legacy run may have no compact store module at all). A store whose class is so named
    is a compact store, and the predicate is then resolved by importing its module, never
    by a module-name lookup, so a folded package's import rewriting covers it. A miss
    fails closed: the module not importable under this name, or a class that is not the
    imported CompactRestartStore (another copy of the module, as a missed fold rewrite
    would load), refuses instead of skipping the check.
    """
    if type(store).__qualname__ != 'CompactRestartStore':
        return None
    try:
        from compact_restart_store import is_compact_restart_store
    except ImportError as error:
        raise ImportError('WP16 pre-advance capture route: a compact store whose module is not importable '
                          'here: '+str(error)) from error
    if not is_compact_restart_store(store):
        raise ValueError('WP16 pre-advance capture route: the store is not the loaded CompactRestartStore '
                         '(another copy of its module: %s)' % (type(store).__module__,))
    # Import statements, not module-name strings: a fold's import rewriting covers them, and a missed rewrite
    # fails its bare-import gate instead of checking another copy of the module.
    try:
        import capture_store  # noqa: F401
        import storage_zstd_backend  # noqa: F401
    except ImportError as error:
        raise ImportError('WP16 pre-advance capture route incomplete: '+str(error)) from error
    return capture_backend().library_sha256


class _CaptureItem(bytes):
    """Canonical bytes keep their booking even in a retained consumer traceback."""
    def __new__(cls, raw, lease):
        result = super().__new__(cls, raw)
        result._lease = lease
        return result


def _capture_canonical(value, budget):
    """Book oversized JSON before serialization, not after its bytes are yielded.

    The existing allocation-free mesh width is a conservative canonical-size
    bound. Twice that bound funds text/bytes and the owned-byte copy. Header
    slack covers small items and bounded per-object overhead. The lease follows
    actual bytes/tracebacks, so failure cannot unbook still-retained memory.
    """
    from capture_store import HEADER_WORK_BYTES, MAX_HEADER_BYTES, _Lease
    from mesh_tables import _width, canonical
    size = _width(value)
    # Leave space for the encoded capture header and the one slice copy.
    slack = HEADER_WORK_BYTES - 2*MAX_HEADER_BYTES - CAPTURE_CHUNK
    if 2*size <= slack:
        return canonical(value)
    lease = _Lease(budget, 2*size, 'canonical-item')
    return _CaptureItem(canonical(value), lease)


def _capture_parts(blocks, check):
    """bytes parts of at most 64 KiB, as write_capture requires.

    A block must be a one-dimensional buffer of single-byte items: a view's length counts items, so a
    wider item type would give parts over 64 KiB in machine byte order; it is refused before any part.
    A larger block is sliced through a view, so one 64 KiB slice is copied at a time. The view and
    the block are released before the next block is produced, so one item and one slice copy are
    held here at most. Large canonical blocks retain their own lease; small blocks
    and the slice copy fit the writer-header slack (see _capture_canonical).
    """
    for block in blocks:
        check()
        if type(block) is bytes and len(block) <= CAPTURE_CHUNK:
            yield block
        else:
            with memoryview(block) as view:
                if view.itemsize != 1 or view.ndim != 1:
                    raise TypeError('capture blocks must be one-dimensional byte buffers')
                for start in range(0, len(view), CAPTURE_CHUNK):
                    yield bytes(view[start:start+CAPTURE_CHUNK])
        del block


def capture_operand(artifacts, name, blocks, *, budget, check):
    """Publish one operand capture exclusively and atomically; returns its receipt row."""
    from capture_store import write_capture
    path = Path(artifacts)/('preadvance-'+name+'.capture')
    result = write_capture(path, _capture_parts(blocks, check), kind=CAPTURE_KINDS[name],
                           representation='exact-bytes', budget=budget, codec='zstd', level=3,
                           backend=capture_backend(), check=check,
                           max_logical_bytes=CAPTURE_MAX_BYTES, max_stored_bytes=CAPTURE_MAX_BYTES)
    if result['format'] != CAPTURE_FORMAT or result['stored_bytes'] != path.stat().st_size:
        raise ValueError('pre-advance capture receipt differs from its file: '+path.name)
    return dict(path=path.name, raw_bytes=result['raw_bytes'], stored_bytes=result['stored_bytes'],
                raw_sha256=result['raw_sha256'], container_sha256=result['container_sha256'],
                format=CAPTURE_FORMAT)


def capture_operands(artifacts, *, budget, check, **operands):
    """Capture counterpart of the coverage helper's save_operands, same order and checks."""
    result = {}
    for name, blob in operands.items():
        if type(blob) is not bytes:
            raise TypeError('Only already-owned immutable geometry bytes may be captured')
        result[name] = capture_operand(artifacts, name, (blob,), budget=budget, check=check)
        if result[name]['raw_bytes'] != len(blob):
            raise ValueError('pre-advance capture length differs from its operand: '+name)
    return result


@contextmanager
def coverage_projection(mesh, *, budget, check):
    """Only the IDs and endpoint header consumed by the unchanged coverage gate."""
    from exterior_mesh_patch import _view
    from native_transfer import _Allocation
    view = _view(mesh)
    if view.budget is not budget:
        raise ValueError('coverage mesh belongs to another budget')
    required = view._arrays['required.face']
    owner = _Allocation(budget, 65536+1024*view.cell_count+768*view.face_count+256*len(required),
                        category='compact-coverage-projection')
    header = view.header()
    names = ('funding_id', 'support_id', 'grid_id', 'trajectory_id', 'time_s',
             'booked_cell_rule')
    projected = {name: header.value[name] for name in names}
    projected['required_thermal_boundary_faces'] = [view.face_id(int(index)) for index in required]
    for field, count, method, keys in (
            ('cells', view.cell_count, view.cell, ('cell_id', 'logical_cell_id')),
            ('faces', view.face_count, view.face, ('face_id',))):
        projected[field] = []
        for index in range(count):
            check()
            row = method(index)
            projected[field].append({key: row.value[key] for key in keys})
            del row
    yield projected
    del projected, header, owner


def inspect_compact_preadvance(coverage, mesh, graph, bounds, resources, budget,
                               cancel, artifacts, record, save):
    """Same physical predicates, with bounded projection and streamed capture."""
    from exterior_mesh_patch import _view
    from atlas_tectonics.integration_mimetic_heat import _q
    coverage.source_bindings()
    view = _view(mesh)
    if type(graph._json) is not bytes or type(bounds._json) is not bytes:
        raise ValueError('coverage graph/bounds require their existing owned exact bytes')
    check = lambda: resources.check(cancel)
    # Writer header slack covers small canonical items; larger items acquire
    # their own lease before serialization and retain it with the yielded bytes.
    mesh_row = capture_operand(artifacts, 'mesh',
        view.iter_legacy_json(encode=lambda value: _capture_canonical(value, budget)),
        budget=budget, check=check)
    if mesh_row['raw_sha256'] != view.geometry_id:
        raise ValueError('compact coverage mesh logical identity changed')
    operands = capture_operands(artifacts, budget=budget, check=check,
                                closed_graph=graph._json, bounds=bounds._json)
    operands['mesh'] = mesh_row
    record['preadvance_operands'] = operands
    save()
    with coverage_projection(mesh, budget=budget, check=check) as projected:
        record['observed_preadvance_counts'] = dict(cells=len(projected['cells']), faces=len(projected['faces']))
        save()
        with resources.decoded(graph._json, budget=budget, cancel=cancel) as decoded:
            with resources.workspace(budget, 65536+4096*sys.getrecursionlimit(),
                    cancel=cancel, category='private-original-coverage-sizing'):
                size = coverage._coverage_bytes(projected, decoded.value, resources, cancel)
            with resources.workspace(budget, size, cancel=cancel, category='private-original-coverage-check'):
                def decode(pair):
                    check()
                    return _q(pair)
                result = coverage.physical_coverage(projected, decoded.value, graph.geometry_id, decode)
                result['minimum_positive_booked_volume_m3'] = coverage._copy_value(
                    result['minimum_positive_booked_volume_m3'], check)
                check()
    record['current_physical_coverage'] = result
    save()
    return result


def accepts_store(store):
    from atlas_tectonics.storage import ArrayStore
    from compact_restart_store import is_compact_restart_store
    return type(store) is ArrayStore or is_compact_restart_store(store)


def postpublication(workflow, parent, row, *, cancel=None):
    """D3: authenticate the persisted envelope before trusting live operands."""
    from compact_restart_store import is_compact_restart_store
    from atlas_tectonics.storage import StoreConflict
    from workflow_transfer import compact_references_verified, digest, workflow_key
    store = workflow._store
    if not is_compact_restart_store(store):
        return
    token = store.change_token()
    root = json.loads(workflow._root)
    if (workflow._head != row or row.get('kind') != 'successor' or
            row.get('key') != workflow_key('successor', parent['key']) or
            row.get('sequence') != parent['sequence'] + 1 or
            row.get('parent_key') != parent['key'] or
            row.get('parent_digest') != digest(parent) or
            row.get('workflow_id') != root['workflow_id'] or
            row.get('funding_id') != root['funding_id'] or
            row['state']['fields']['time_s'] <= parent['state']['fields']['time_s'] or
            store.metadata(row['key']) != row or
            store.metadata(parent['key']) != parent or store.metadata(root['key']) != root or
            store.metadata(workflow_key('successor', row['key'])) is not None):
        raise StoreConflict('compact successor postpublication envelope differs')
    compact_references_verified(store, row, budget=workflow._budget, cancel=cancel)
    if store.change_token() != token:
        raise StoreConflict('compact successor changed during bounded validation')
    # The live result was scientifically admitted before publication. Only a
    # proven, unchanged storage token can suppress its redundant cold restore.
    workflow._token = token


def workflow_source(source):
    """Add explicit facade admission after the WP6 workflow transforms."""
    if (type(source) is not str or 'import compact_restart_patch as _RESTART' in source or
            source.count('type(store) is not ArrayStore') != 3 or
            '_COMPACT_RECORDS.publication_check' not in source):
        raise ValueError('compact restart workflow source seams differ')
    source = source.replace('import json\n', 'import json\nimport compact_restart_patch as _RESTART\n', 1)
    source = source.replace('type(store) is not ArrayStore', 'not _RESTART.accepts_store(store)')
    old = ('        self._differential_partition = differential_partition\n'
           '        return result if exterior_advance is None else CoupledCollarAdvance(result, exterior_advance)')
    if source.count(old) != 1:
        raise ValueError('compact restart postpublication source seam differs')
    return source.replace(old, '        self._differential_partition = differential_partition\n'
        '        _RESTART.postpublication(self, parent, row, cancel=cancel)\n'
        '        return result if exterior_advance is None else CoupledCollarAdvance(result, exterior_advance)', 1)
