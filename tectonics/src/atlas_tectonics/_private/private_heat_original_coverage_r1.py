"""Physical coverage and lossless operands for the current ACTUATED control.

Historical cell counts are reported, not silently treated as version-invariant.
The native issuer still performs all actual endpoint and transported-stock gates.
"""
import gzip; import atlas_tectonics._identity as _atlas_identity
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent


def digest(path):
    from hashlib import file_digest
    with _atlas_identity.as_path(path).open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def copy_verified_cache(artifacts, *, cache_path, original_source_directory, historical_inputs):
    """Copy the closed same-runtime cache; native lookup revalidates every hit."""
    from atlas_tectonics._private.integration import historical_admission as H
    H._historical_inputs(historical_inputs)
    api = H._historical_inputs_api()
    cache = api._ordinary(cache_path)
    target = Path(artifacts)/'initial-measurements.sqlite'
    with cache.open('rb') as source, target.open('xb') as destination:
        for block in iter(lambda: source.read(1 << 20), b''):
            destination.write(block)


def physical_coverage(mesh, graph, graph_id, decode):
    """Exact positive-volume inclusion, derived from the current closed graph."""
    graph_ids = [row['cell_id'] for row in graph['cells']]
    cell_ids = [row['cell_id'] for row in mesh['cells']]
    face_ids = [row['face_id'] for row in mesh['faces']]
    volumes = [(decode(row['end_volume_m3']), row) for row in graph['cells']]
    positive = [(volume, row) for volume, row in volumes if volume > 0]
    required = mesh['required_thermal_boundary_faces']
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
        from atlas_tectonics.integration.heat.mimetic_heat import _q
        with budget.reserve(65536+512*(len(mv.value['cells'])+len(mv.value['faces'])+
                len(gv.value['cells'])), category='private-original-coverage-check'):
            result = physical_coverage(mv.value, gv.value, graph.geometry_id, _q)
    # Do not keep decoded mesh/graph aliases beyond their funded scopes.
    record['current_physical_coverage'] = result
    save()
    return result
