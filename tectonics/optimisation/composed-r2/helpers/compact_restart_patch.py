"""Step 8 native storage admission and bounded live publication boundary.

Applied to reviewed sources at composition time. No frozen source is edited,
no scientific issuer is replaced, and cold readers retain full validation.
"""
import json
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import gzip
import sys


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
    # whole compact mesh as JSON in memory. WP16 owns broader capture changes.
    io_owner = _Allocation(budget, 1 << 20, category='compact-coverage-export')
    path, digest, count = Path(artifacts)/'preadvance-mesh.json.gz', sha256(), 0
    with path.open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw,
                                             mtime=0, compresslevel=1) as packed:
        for block in view.iter_legacy_json():
            check()
            digest.update(block)
            count += len(block)
            packed.write(block)
    if digest.hexdigest() != view.geometry_id:
        raise ValueError('compact coverage mesh logical identity changed')
    operands = coverage.save_operands(artifacts, closed_graph=graph._json, bounds=bounds._json)
    operands['mesh'] = dict(path=path.name, raw_bytes=count, gzip_bytes=path.stat().st_size,
        raw_sha256=digest.hexdigest(), gzip_sha256=coverage.digest(path))
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
