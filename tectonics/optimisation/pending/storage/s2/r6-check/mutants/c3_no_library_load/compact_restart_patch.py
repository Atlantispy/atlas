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
# raw or gzip fallback: a missing or changed library refuses.
CAPTURE_LIBRARY = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/'
                       'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/'
                       'resumability-r1/compact-geometry-r1/native/wp10_zstd.dll')
CAPTURE_LIBRARY_SHA256 = 'a40c24ad328da37a42c7f69e434c576254f11fde4097cd5de7416f8f78444f28'
# Explicit capture ceilings: capture_store's 4 GiB default would stop a run at its
# pre-advance step once the streamed mesh outgrows it (the gzip route had no ceiling).
# 16 GiB is the run's existing logical ceiling; capture streams 64 KiB at a time.
CAPTURE_MAX_BYTES = 16 << 30
_CAPTURE_BACKEND = None


def capture_backend():
    """One pinned ZstdBackend per process."""
    global _CAPTURE_BACKEND
    if _CAPTURE_BACKEND is None:
        from storage_zstd_backend import ZstdBackend
        _CAPTURE_BACKEND = ZstdBackend(CAPTURE_LIBRARY, expected_sha256=CAPTURE_LIBRARY_SHA256)
    if _CAPTURE_BACKEND.library_sha256 != CAPTURE_LIBRARY_SHA256:
        raise ValueError('pre-advance capture backend identity changed')
    return _CAPTURE_BACKEND


def require_capture_route(store):
    """Refuse at run start, not after the advance, when a compact run cannot write its captures.

    Both callers of inspect_compact_preadvance (fresh_interval_driver.advance_first_interval
    and prepared_interval_driver.advance_prepared_interval) call this before any physical
    work. The two capture modules are imported, not only found, so inside the selected
    runtime its Loader runs their pin check now; capture_backend() then loads the pinned
    library and checks its sha256. Any other store is not checked here and imports
    nothing: the store's module is looked up, never imported, since it is loaded wherever
    a compact store exists. This module itself imports without the capture route, so
    compositions without it still import. Returns the library's sha256 for a compact
    store, else None.
    """
    crs = sys.modules.get('compact_restart_store')
    if crs is None or not crs.is_compact_restart_store(store):
        return None
    import importlib
    try:
        for name in ('capture_store', 'storage_zstd_backend'):
            importlib.import_module(name)
    except ImportError as error:
        raise ImportError('WP16 pre-advance capture route incomplete: '+str(error)) from error
    return CAPTURE_LIBRARY_SHA256


def _capture_parts(blocks, check):
    """bytes parts of at most 64 KiB, as write_capture requires."""
    for block in blocks:
        check()
        if type(block) is bytes and len(block) <= CAPTURE_CHUNK:
            yield block
            continue
        view = memoryview(block)
        for start in range(0, len(view), CAPTURE_CHUNK):
            yield bytes(view[start:start+CAPTURE_CHUNK])


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
    from native_transfer import _Allocation
    from atlas_tectonics.integration_mimetic_heat import _q
    coverage.source_bindings()
    view = _view(mesh)
    if type(graph._json) is not bytes or type(bounds._json) is not bytes:
        raise ValueError('coverage graph/bounds require their existing owned exact bytes')
    check = lambda: resources.check(cancel)
    # Preserve the established explicit replay export without rebuilding the
    # whole compact mesh as JSON in memory. WP16: exact-bytes captures (above).
    io_owner = _Allocation(budget, 1 << 20, category='compact-coverage-export')
    mesh_row = capture_operand(artifacts, 'mesh', view.iter_legacy_json(), budget=budget, check=check)
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
    del io_owner
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
