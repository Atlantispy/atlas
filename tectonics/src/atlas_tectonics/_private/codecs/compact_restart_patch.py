"""Step 8 native storage admission and bounded live publication boundary.

Applied to reviewed sources at composition time. No frozen source is edited,
no scientific issuer is replaced, and cold readers retain full validation.
"""
import json
from contextlib import contextmanager
from pathlib import Path
import sys

# WP16, capture-digest generation 2026-10-16: the pre-advance bounds operand is
# written as an atlas.diagnostic-capture.v1 file (exact bytes, zstd level 3) instead
# of gzip level 1. raw_bytes/raw_sha256 remain the codec-independent logical
# identity; container_sha256 only authenticates one file against its own receipt
# and is never compared across runs. The mesh and closed-graph captures had no reader.
CAPTURE_FORMAT = 'atlas.diagnostic-capture.v1'
CAPTURE_KINDS = {'bounds': 'bounds'}
CAPTURE_CHUNK = 65536
# The existing pinned WP10 Zstandard library in its permanent folder; there is no
# raw or gzip fallback: a missing or changed library refuses. It is named by its
# task-relative key (the runtime manifest's data_only key) and found under the one
# ancestor of this module that holds it, so no machine path is written here.
CAPTURE_LIBRARY_KEY = ('atlas_tectonics/_private/native/wp10_zstd.dll')
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
class _CaptureBackendState:
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from atlas_tectonics._private.codecs.storage_zstd_backend import ZstdBackend

    __slots__ = ('backend',)
    backend: 'ZstdBackend | None'

    def __init__(self):
        self.backend = None


_CAPTURE_BACKEND = _CaptureBackendState()


def capture_backend():
    """One pinned ZstdBackend per process."""
    global _CAPTURE_BACKEND
    if _CAPTURE_BACKEND.backend is None:
        from atlas_tectonics._private.codecs.storage_zstd_backend import ZstdBackend
        _CAPTURE_BACKEND.backend = ZstdBackend(CAPTURE_LIBRARY, expected_sha256=CAPTURE_LIBRARY_SHA256)
    return _CAPTURE_BACKEND.backend


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
    is a compact store.
    """
    if type(store).__qualname__ != 'CompactRestartStore':
        return None
    # Import statements, not module-name strings: a fold's import rewriting covers them, and a missed rewrite
    # fails its bare-import gate instead of checking another copy of the module.
    try:
        from atlas_tectonics._private.codecs import capture_store  # noqa: F401
        from atlas_tectonics._private.codecs import storage_zstd_backend  # noqa: F401
    except ImportError as error:
        raise ImportError('WP16 pre-advance capture route incomplete: '+str(error)) from error
    return capture_backend().library_sha256


def _capture_parts(blocks, check):
    """bytes parts of at most 64 KiB, as write_capture requires.

    A block must be a one-dimensional buffer of single-byte items: a view's length counts items, so a
    wider item type would give parts over 64 KiB in machine byte order; it is refused before any part.
    A larger block is sliced through a view, so one 64 KiB slice is copied at a time. The view and
    the block are released before the next block is produced, so one item and one slice copy are
    held here at most.
    """
    for block in blocks:
        check()
        if type(block) is bytes and len(block) <= CAPTURE_CHUNK:
            yield block
        else:
            with memoryview(block) as view:
                for start in range(0, len(view), CAPTURE_CHUNK):
                    yield bytes(view[start:start+CAPTURE_CHUNK])
        del block


def capture_operand(artifacts, name, blocks, *, budget, check):
    """Publish one operand capture exclusively and atomically; returns its receipt row."""
    from atlas_tectonics._private.codecs.capture_store import write_capture
    path = Path(artifacts)/('preadvance-'+name+'.capture')
    result = write_capture(path, _capture_parts(blocks, check), kind=CAPTURE_KINDS[name],
                           representation='exact-bytes', budget=budget, codec='zstd', level=3,
                           backend=capture_backend(), check=check,
                           max_logical_bytes=CAPTURE_MAX_BYTES, max_stored_bytes=CAPTURE_MAX_BYTES)
    return dict(path=path.name, raw_bytes=result['raw_bytes'], stored_bytes=result['stored_bytes'],
                raw_sha256=result['raw_sha256'], container_sha256=result['container_sha256'],
                format=CAPTURE_FORMAT)


def capture_operands(artifacts, *, budget, check, **operands):
    """Capture counterpart of the coverage helper's save_operands, same order and checks."""
    result = {}
    for name, blob in operands.items():
        result[name] = capture_operand(artifacts, name, (blob,), budget=budget, check=check)
    return result


@contextmanager
def coverage_projection(mesh, *, budget, check):
    """Only the IDs and endpoint header consumed by the unchanged coverage gate."""
    from atlas_tectonics._private.integration.geometry.exterior_mesh_patch import _view
    from atlas_tectonics._private.integration.native_transfer import _Allocation
    view = _view(mesh)
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
    from atlas_tectonics.integration.heat.mimetic_heat import _q
    check = lambda: resources.check(cancel)
    record['preadvance_operands'] = capture_operands(artifacts, budget=budget, check=check,
                                                     bounds=bounds._json)
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


def postpublication(workflow, parent, row, *, cancel=None):
    """D3: authenticate the persisted envelope before trusting live operands."""
    from atlas_tectonics._private.codecs.compact_restart_store import is_compact_restart_store
    from atlas_tectonics.codecs.storage import StoreConflict
    from atlas_tectonics._private.integration.workflow_transfer import compact_references_verified, digest, workflow_key
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

