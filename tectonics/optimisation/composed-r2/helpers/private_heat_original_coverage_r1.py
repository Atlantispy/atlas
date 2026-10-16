"""Physical coverage and lossless operands for the current ACTUATED control.

Historical cell counts are reported, not silently treated as version-invariant.
The native issuer still performs all actual endpoint and transported-stock gates.
"""
import gzip
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE/'heat-original-connected-20261012-r1.artifacts/initial-measurements.sqlite'
CACHE_SHA = '253a59fa6a4ce0ac7651f224b9311df0d635fe511b5917b1e1129733c626d785'


def digest(path):
    from hashlib import file_digest
    with Path(path).open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def copy_verified_cache(artifacts):
    """Copy the closed same-runtime cache; native lookup revalidates every hit."""
    if digest(CACHE) != CACHE_SHA or any(Path(str(CACHE)+s).exists() for s in ('-wal', '-journal')):
        raise ValueError('Retained initial cache changed or is not closed')
    target = Path(artifacts)/'initial-measurements.sqlite'
    with CACHE.open('rb') as source, target.open('xb') as destination:
        for block in iter(lambda: source.read(1 << 20), b''):
            destination.write(block)
    if digest(target) != CACHE_SHA or digest(CACHE) != CACHE_SHA:
        raise ValueError('Copied initial cache differs; no stale-hit admission')


def physical_coverage(mesh, graph, graph_id, decode):
    """Exact positive-volume inclusion, derived from the current closed graph."""
    if mesh.get('booked_cell_rule', {}).get('closed_graph_id') != graph_id:
        raise ValueError('Thermal mesh is not bound to this exact closure')
    pairs = (('funding_id', 'funding_id'), ('support_id', 'end_support_id'),
             ('grid_id', 'grid_id'), ('trajectory_id', 'trajectory_id'), ('time_s', 'end_time_s'))
    if any(mesh[a] != graph[b] for a, b in pairs):
        raise ValueError('Mesh and closed graph endpoints differ')
    graph_ids = [row['cell_id'] for row in graph['cells']]
    cell_ids = [row['cell_id'] for row in mesh['cells']]
    face_ids = [row['face_id'] for row in mesh['faces']]
    if any(len(ids) != len(set(ids)) for ids in (graph_ids, cell_ids, face_ids)):
        raise ValueError('Duplicate graph, thermal-cell or face identity')
    volumes = [(decode(row['end_volume_m3']), row) for row in graph['cells']]
    if any(volume < 0 for volume, _ in volumes):
        raise ValueError('Closed graph contains negative booked material')
    positive = [(volume, row) for volume, row in volumes if volume > 0]
    if not positive or {row['logical_cell_id'] for row in mesh['cells']} != {row['cell_id'] for _, row in positive}:
        raise ValueError('Every and only positive booked material cell must be represented')
    required = mesh['required_thermal_boundary_faces']
    if len(required) != len(set(required)) or not set(required) <= set(face_ids):
        raise ValueError('Required thermal boundary coverage is inconsistent')
    smallest = min(positive, key=lambda pair: pair[0])[1]
    return dict(cells=len(cell_ids), faces=len(face_ids), graph_cells=len(graph_ids),
        positive_booked_cells=len(positive), required_boundary_faces=len(required),
        exact_positive_cell_coverage=True, endpoint_binding_verified=True,
        minimum_positive_booked_volume_m3=smallest['end_volume_m3'],
        historical_counts=dict(cells=855, faces=7523),
        historical_counts_match=(len(cell_ids), len(face_ids)) == (855, 7523),
        historical_mesh_equality_proven=False,
        scope='current original physical fixture; historical mesh is a separate saved numerical control')


def save_operands(artifacts, **operands):
    """Stream existing immutable bytes, before a gate can discard their owners."""
    result = {}
    for name, blob in operands.items():
        if type(blob) is not bytes:
            raise TypeError('Only already-owned immutable geometry bytes may be captured')
        path = Path(artifacts)/('preadvance-'+name+'.json.gz')
        checksum = sha256()
        with path.open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw,
                                                  mtime=0, compresslevel=1) as stream:
            view = memoryview(blob)
            for start in range(0, len(view), 65536):
                chunk = view[start:start+65536]
                checksum.update(chunk)
                stream.write(chunk)
        result[name] = dict(path=path.name, raw_bytes=len(blob), gzip_bytes=path.stat().st_size,
                            raw_sha256=checksum.hexdigest(), gzip_sha256=digest(path))
    return result


def inspect_preadvance(mesh, graph, bounds, resources, budget, cancel, artifacts, record, save):
    record['preadvance_operands'] = save_operands(artifacts, mesh=mesh._json,
        closed_graph=graph._json, bounds=bounds._json)
    save()
    with resources.decoded(mesh._json, budget=budget, cancel=cancel) as mv, \
            resources.decoded(graph._json, budget=budget, cancel=cancel) as gv:
        # Record actual counts even when the subsequent scientific gate refuses.
        record['observed_preadvance_counts'] = dict(cells=len(mv.value['cells']), faces=len(mv.value['faces']))
        save()
        from atlas_tectonics.integration_mimetic_heat import _q
        with budget.reserve(65536+512*(len(mv.value['cells'])+len(mv.value['faces'])+
                len(gv.value['cells'])), category='private-original-coverage-check'):
            result = physical_coverage(mv.value, gv.value, graph.geometry_id, _q)
    # Do not keep decoded mesh/graph aliases beyond their funded scopes.
    record['current_physical_coverage'] = result
    save()
    return result
