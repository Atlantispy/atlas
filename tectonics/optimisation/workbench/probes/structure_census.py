"""WP0a structure-only census of authenticated stored data.

No codec packing, restore, interval advance, or writes to an ArrayStore. Typed
arrays are described from verified manifests; selected legacy JSON is streamed
to bounded disposable files and scanned, never materialised as a large object.
Compact formats use their own manifest inventory, without expanding geometry.
"""

from hashlib import sha256
import json
import math
from pathlib import Path
import shutil
import time

import structure_json as J

MAX_SCRATCH = 2 << 30
WORKSPACE = 256 << 20
MAX_SMALL = 1 << 20
ROOT_ARRAYS = ('component_mass_kg', 'enthalpy_j', 'tracer:damage',
               'tracer:accumulated_strain_ii', 'tracer:source_kappa',
               'tracer:radial_plastic_kappa')


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def array_bytes(description):
    import numpy as np
    return math.prod(description['shape']) * np.dtype(description['dtype']).itemsize


def manifest_summary(manifest, body_bytes):
    arrays = {name: dict(dtype=row['dtype'], shape=row['shape'],
                        logical_bytes=array_bytes(row), chunk_references=len(row['chunks']))
              for name, row in manifest['arrays'].items()}
    return dict(manifest_bytes=body_bytes, metadata_bytes=len(canonical(manifest['metadata'])),
                array_count=len(arrays), arrays=arrays,
                logical_bytes=sum(row['logical_bytes'] for row in arrays.values()),
                chunk_references=sum(row['chunk_references'] for row in arrays.values()))


def catalogue(store, budget, check):
    import historical_admission as H
    with store._read_scope(budget=budget):
        size, largest, count = store._db.execute(
            'SELECT COALESCE(sum(length(body)),0),COALESCE(max(length(body)),0),count(*) FROM snapshots').fetchone()
        require(count <= 4096 and size <= H.MAX_CAPSULE and largest <= store.limits.max_manifest_bytes,
                'catalogue exceeds existing historical read bounds')
        owner = H._Allocation(budget, 16 * size)
        manifests, summaries = {}, {}
        for key, body_bytes in store._db.execute('SELECT id,length(body) FROM snapshots ORDER BY id'):
            check()
            manifest = store._manifest(key)
            manifests[key] = manifest
            summaries[key] = manifest_summary(manifest, body_bytes)
        count_chunks, payload, descriptors = store._db.execute(
            'SELECT count(*),COALESCE(sum(length(payload)),0),COALESCE(sum(length(descriptor)),0) FROM chunks').fetchone()
        pages = store._db.execute('PRAGMA page_count').fetchone()[0]
        page_size = store._db.execute('PRAGMA page_size').fetchone()[0]
        free_pages = store._db.execute('PRAGMA freelist_count').fetchone()[0]
    return manifests, summaries, dict(snapshot_count=count, manifest_bytes=size,
        stored_chunk_count=count_chunks, stored_payload_bytes=payload, chunk_descriptor_bytes=descriptors,
        file_bytes=Path(store.path).stat().st_size, sqlite_page_bytes=pages * page_size,
        sqlite_free_page_bytes=free_pages * page_size,
        note='Physical chunk rows counted once; logical snapshot arrays may alias the same chunks.'), owner


class Scratch:
    def __init__(self, directory, store, budget, check):
        self.directory = Path(directory).absolute()
        require(self.directory.name == 'structure-scratch' and self.directory.parent.is_dir(),
                'scratch must be the selected run directory child')
        require(not self.directory.exists(), 'exclusive scratch directory required')
        self.directory.mkdir()
        self.store, self.budget, self.check = store, budget, check
        self.files, self.total = [], 0

    def spool(self, key, name, description):
        size = array_bytes(description)
        require(description['dtype'] in ('|u1', '<u1', 'u1') and len(description['shape']) == 1,
                'legacy JSON must be a one-dimensional byte array')
        require(size <= J.MAX_SOURCE_BYTES and self.total + size <= MAX_SCRATCH,
                'selected diagnostic scratch exceeds its byte bound')
        require(shutil.disk_usage(self.directory).free >= size + (256 << 20),
                'insufficient disk space for bounded diagnostic scratch')
        path = self.directory / ('record-%03d.json' % len(self.files))
        self.files.append(path)
        self.total += size
        digest, count = sha256(), 0
        with path.open('xb') as stream:
            for offset, chunk in self.store.iter_chunks(key, name, budget=self.budget):
                self.check()
                require(offset == count, 'noncontiguous byte stream')
                raw = chunk.tobytes()
                require(count + len(raw) <= size, 'stream exceeds declared size')
                stream.write(raw)
                digest.update(raw)
                count += len(raw)
        require(count == size, 'stream size differs from manifest')
        return path, digest.hexdigest()

    def remove(self):
        # Each path was generated here; never recursively remove a computed tree.
        root = self.directory.resolve(strict=True)
        for path in self.files:
            require(path.resolve(strict=True).parent == root and not path.is_symlink(),
                    'scratch path changed before cleanup')
            path.unlink()
        self.directory.rmdir()


def select(path, kind):
    if not path:
        return False
    # Complete graph fields and one level below its embedded copy.
    if path[:2] == ('finite_proposal', 'graph') and len(path) <= 3:
        return True
    # Partition supports align by direct array position; mesh table IDs are keys.
    if len(path) == 2 and path[0] in ('supports', 'support_ids'):
        return True
    if len(path) == 3 and path[:2] == ('support_tables', 'differential_supports'):
        return True
    return False


def spans(report):
    return {tuple(row['path']): row for row in (*report['fields'], *report['selected'])}


def public_scan(report):
    # Exact selected spans are temporary comparison indexes, not a second ledger.
    return {**{key: value for key, value in report.items() if key != 'selected'},
            'selected_span_count': len(report['selected'])}


def read_small(path, row):
    require(row['bytes'] <= MAX_SMALL, 'selected value exceeds small decode bound')
    with path.open('rb') as stream:
        stream.seek(row['start'])
        raw = stream.read(row['bytes'])
    require(len(raw) == row['bytes'], 'selected file span changed')
    return json.loads(raw)


def same_span(path_a, row_a, path_b, row_b, check):
    if row_a['bytes'] != row_b['bytes']:
        return False
    with path_a.open('rb') as a, path_b.open('rb') as b:
        a.seek(row_a['start'])
        b.seek(row_b['start'])
        left = row_a['bytes']
        while left:
            check()
            width = min(left, 65536)
            raw_a, raw_b = a.read(width), b.read(width)
            require(len(raw_a) == len(raw_b) == width, 'span became truncated')
            if raw_a != raw_b:
                return False
            left -= width
    return True


def span_hash(path, row, check):
    digest = sha256()
    with path.open('rb') as stream:
        stream.seek(row['start'])
        left = row['bytes']
        while left:
            check()
            raw = stream.read(min(left, 65536))
            require(raw, 'span became truncated')
            digest.update(raw)
            left -= len(raw)
    return digest.hexdigest()


def graph_overlap(records, check):
    graph, exchange = records.get('spatial-record:graph'), records.get('spatial-record:exchange')
    if graph is None or exchange is None:
        return dict(status='NOT_PRESENT', note='No legacy graph pair; compact tables are inventoried separately.')
    es = spans(exchange['scan'])
    copy = es.get(('finite_proposal', 'graph'))
    if copy is None:
        return dict(status='NOT_PRESENT', note='Exchange has no finite_proposal.graph field.')
    whole = dict(start=0, bytes=graph['scan']['filebytes'])
    equal = same_span(graph['path'], whole, exchange['path'], copy, check)
    fields = []
    for field in graph['scan']['fields']:
        other = es.get(('finite_proposal', 'graph', field['path'][0]))
        fields.append(dict(name=field['path'][0], graph_bytes=field['bytes'],
            finite_graph_bytes=None if other is None else other['bytes'],
            byte_equal=other is not None and same_span(graph['path'], field, exchange['path'], other, check)))
    return dict(status='MEASURED', graph_bytes=whole['bytes'], embedded_graph_bytes=copy['bytes'],
        complete_byte_equal=equal, fields=fields,
        equal_field_value_bytes=sum(row['graph_bytes'] for row in fields if row['byte_equal']),
        note='Exact byte comparison. Equal field totals exclude object syntax; no semantic equivalence inferred.')


def support_overlap(records, check):
    partition, mesh = records.get('partition-record:partition'), records.get('spatial-record:mesh')
    if partition is None or mesh is None:
        return dict(status='NOT_PRESENT', note='Legacy support pair absent; compact references counted separately.')
    ps, ms = spans(partition['scan']), spans(mesh['scan'])
    support_rows = {path[1]: row for path, row in ps.items() if len(path) == 2 and path[0] == 'supports'}
    id_rows = {path[1]: row for path, row in ps.items() if len(path) == 2 and path[0] == 'support_ids'}
    require(set(support_rows) == set(id_rows), 'partition support and ID positions differ')
    table = {path[2]: row for path, row in ms.items()
             if len(path) == 3 and path[:2] == ('support_tables', 'differential_supports')}
    equal_count = equal_bytes = mismatches = id_mismatches = 0
    referenced = set()
    for index, row in support_rows.items():
        ident = read_small(partition['path'], id_rows[index])
        require(type(ident) is str, 'partition support ID is not text')
        id_mismatches += span_hash(partition['path'], row, check) != ident
        other = table.get(ident)
        if other is None:
            continue
        referenced.add(ident)
        equal = same_span(partition['path'], row, mesh['path'], other, check)
        equal_count += equal
        mismatches += not equal
        if equal:
            equal_bytes += other['bytes']
    return dict(status='MEASURED', partition_supports=len(support_rows), mesh_supports=len(table),
        matching_ids=len(referenced), identical_supports=equal_count, different_bytes_for_same_id=mismatches,
        partition_id_hash_mismatches=id_mismatches, shared_mesh_value_bytes=equal_bytes,
        mesh_total_support_value_bytes=sum(row['bytes'] for row in table.values()),
        mesh_ids_absent_from_partition=len(set(table) - referenced),
        note='Support ID is the SHA-256 of the complete canonical support; matched bodies also compared byte-for-byte.')


def static_comparisons(records, root_mesh, check):
    mesh, partition = records.get('spatial-record:mesh'), records.get('partition-record:partition')
    rows = []
    def compare(label, left, right, path):
        a = None if left is None else next((r for r in left['scan']['nested_fields'] if r['path'] == list(path)), None)
        b = None if right is None else next((r for r in right['scan']['nested_fields'] if r['path'] == list(path)), None)
        status = 'ABSENT'
        if a is not None and b is not None:
            require(a['occurrences'] == b['occurrences'] == 1, 'static path is not a single value')
            status = 'BYTE_EQUAL' if same_span(left['path'], a, right['path'], b, check) else 'DIFFERENT'
        rows.append(dict(comparison=label, path=list(path), status=status,
                         left_bytes=None if a is None else a['bytes'], right_bytes=None if b is None else b['bytes']))
    compare('head mesh versus partition', mesh, partition, ('grid_lines',))
    for path in (('grid_lines',), ('support_tables', 'voxels'),
                 ('support_tables', 'radial_layers'), ('support_tables', 'cones')):
        compare('root mesh versus head mesh', root_mesh, mesh, path)
    return dict(status='MEASURED', comparisons=rows,
        source_contract='prepare_interval_partition reuses parent grid_lines. Differential mesh copies funding geometry; '
                        'ordinary radial/cone tables are route-specific. Membership is not universally invariant.',
        limitation='Equality only covers the saved endpoints compared here; no IV2 invariance or cache eligibility is inferred.')


def restart_inventory(manifests, summaries, endpoint, groups):
    head_key, root_key = endpoint['head_key'], endpoint['root_key']
    head_names = manifests[head_key]['arrays']
    selections = [
        ('historical source audit', head_key, ['source-audit:' + r['name'] for r in groups['source_audit']]),
        ('full collar', head_key, [r['name'] for r in groups['full_collar']]),
        ('root funding', root_key, list(ROOT_ARRAYS)),
        ('exterior', head_key, ['exterior-fv:' + r['name'] for r in groups['exterior']]),
        ('spatial first conversion', head_key, ['spatial-record:state', 'spatial-record:mesh']),
        ('differential geometry', head_key, [n for n in head_names if n == 'differential-record:geometry' or n.startswith('differential-network:')]),
        ('partition first conversion', head_key, ['partition-record:partition']),
        ('initial workload duplicate read', root_key, ['component_mass_kg', 'enthalpy_j'])]
    rows, unique = [], set()
    for stage, key, names in selections:
        require(all(name in manifests[key]['arrays'] for name in names), 'restart selection missing from historical manifest')
        rows.append(dict(stage=stage, snapshot=key, arrays=names,
                         logical_bytes=sum(summaries[key]['arrays'][n]['logical_bytes'] for n in names)))
        unique.update((key, name) for name in names)
    additional = [n for n in head_names if n.startswith('spatial-record:') and (head_key, n) not in unique]
    return dict(status='SOURCE_MAPPED_AND_MANIFEST_MEASURED', stages=rows,
        unique_selected_array_bytes=sum(summaries[k]['arrays'][n]['logical_bytes'] for k, n in unique),
        decoded_bytes_with_documented_rereads=sum(row['logical_bytes'] for row in rows),
        additional_head_census_arrays=sorted(additional),
        source_functions=['historical_admission._admit/_audit', 'materialise_endpoint.materialise',
                          'native_transfer._REQUIRED_ARRAYS', 'initial_workload.initial_workload_state'],
        limitation='Source mapping, not an executed restart trace. Excludes whole-database hashes/copy, '
                   'manifest authentication and successor writes/reopens. Existing compact conversions skip raw mesh/partition reads.')


def heat_measure(records, manifests, summaries, scratch, check, observe, result):
    reference = records.get('spatial-record:heat')
    if reference is None:
        return dict(status='NOT_PRESENT')
    require(reference['scan']['filebytes'] <= MAX_SMALL, 'heat reference exceeds metadata bound')
    data = json.loads(reference['path'].read_bytes())
    checkpoint = data.get('checkpoint')
    require(type(checkpoint) is dict and checkpoint.get('invocation') in manifests, 'heat CAS reference unresolved')
    key = checkpoint['invocation']
    manifest = manifests[key]
    require(manifest['metadata'] == checkpoint['metadata'], 'heat checkpoint metadata differs')
    desc = manifest['arrays']['metadata_utf8']
    path, digest = scratch.spool(key, 'metadata_utf8', desc)
    metadata = manifest['metadata']
    require(digest == metadata['metadata_sha256'] and path.stat().st_size == metadata['metadata_bytes'],
            'heat ledger bytes differ from checkpoint binding')
    scan = J.scan(path, check=check)
    result['records']['heat:metadata_utf8'] = dict(snapshot=key, array='metadata_utf8', sha256=digest, **public_scan(scan))
    fields = spans(scan)
    n, nf = fields[('cell_ids',)]['items'], fields[('face_ids',)]['items']
    for name in ('exact_corrected_enthalpy_j', 'exact_retained_solver_residual_j',
                 'exact_stock_projection_residual_j', 'exact_cell_storage_residual_j'):
        require(fields[(name,)]['items'] == n, 'heat cell ledger coverage differs')
    require(fields[('exact_paired_face_energy_j',)]['items'] == nf, 'heat face ledger coverage differs')
    arrays = summaries[key]['arrays']
    numeric = {name: row for name, row in arrays.items() if name != 'metadata_utf8'}
    require(len(numeric) == 5 and all(row['shape'] == [n] and row['dtype'] == '<f8' for row in numeric.values()),
            'heat native field inventory differs')
    observe('structure-heat-ledger-complete')
    return dict(status='MEASURED', snapshot=key, n=n, nf=nf, metadata_bytes=scan['filebytes'],
        native_field_bytes=sum(row['logical_bytes'] for row in numeric.values()), native_fields=numeric,
        native_field_bindings=metadata['fields'], rational_strings=scan['rational_strings'],
        note='Additional historical D6/future migration investigation; current materialisation does not decode this ledger.')


def census_store(store, endpoint, *, budget, limits, check, observe, result, scratch_directory):
    import compact_structure as K
    import historical_admission as H
    require(getattr(store, '_historical_readonly', None) is H._READONLY and
            store._db.execute('PRAGMA query_only').fetchone() == (1,), 'read-only original required')
    result['scope'] = 'WP0a selected-source structural census; no simulation, migration, packing or scientific acceptance'
    result['records'], result['seconds'] = {}, {}
    with budget.reserve(WORKSPACE, category='structure-census-workspace'):
        manifests, summaries, physical, catalogue_owner = catalogue(store, budget, check)
        result.update(snapshots=summaries, physical=physical)
        result['compact_inventory'] = K.inventory(manifests, chunk_bytes=limits.chunk_bytes)
        head_key, root_key = endpoint['head_key'], endpoint['root_key']
        require(head_key in manifests and root_key in manifests, 'endpoint snapshots absent')
        head = manifests[head_key]
        result['head'] = dict(snapshot=head_key, **summaries[head_key])
        result['targets'] = dict(logical_per_put_bytes=128 << 20, chunk_references_per_put=2048,
            full_manifest_bytes=256 << 10, root_metadata_bytes=64 << 10,
            head_exceeds_logical_target=summaries[head_key]['logical_bytes'] > 128 << 20,
            head_exceeds_manifest_target=summaries[head_key]['manifest_bytes'] > 256 << 10,
            head_exceeds_metadata_target=summaries[head_key]['metadata_bytes'] > 64 << 10,
            note='Design targets, not changed store limits. No extrapolation establishes an IV2 memory bound.')
        observe('structure-catalogue-complete')
        scratch = Scratch(scratch_directory, store, budget, check)
        result['scratch'] = dict(directory=str(scratch.directory), cap_bytes=MAX_SCRATCH,
                                 workspace_reservation_bytes=WORKSPACE,
                                 catalogue_reservation_bytes=16 * physical['manifest_bytes'], status='ACTIVE')
        records = {}
        try:
            for name, description in head['arrays'].items():
                if '-record:' not in name:
                    continue
                started = time.perf_counter()
                path, digest = scratch.spool(head_key, name, description)
                scan = J.scan(path, check=check, select=select)
                records[name] = dict(path=path, scan=scan)
                result['records'][name] = dict(snapshot=head_key, array=name, sha256=digest, **public_scan(scan))
                result['seconds'][name] = round(time.perf_counter() - started, 6)
                observe('structure-' + name + '-complete')
            result['graph_overlap'] = graph_overlap(records, check)
            result['support_overlap'] = support_overlap(records, check)
            observe('structure-sharing-complete')
            root_mesh = None
            if 'spatial-record:mesh' in manifests[root_key]['arrays']:
                path, digest = scratch.spool(root_key, 'spatial-record:mesh', manifests[root_key]['arrays']['spatial-record:mesh'])
                scan = J.scan(path, check=check)
                root_mesh = dict(path=path, scan=scan)
                result['records']['root:spatial-record:mesh'] = dict(snapshot=root_key, array='spatial-record:mesh', sha256=digest, **public_scan(scan))
            result['static_tables'] = static_comparisons(records, root_mesh, check)
            observe('structure-static-tables-complete')
            result['heat'] = heat_measure(records, manifests, summaries, scratch, check, observe, result)
            if 'partition-record:partition' in head['arrays'] and 'spatial-record:mesh' in head['arrays']:
                receipt = 'heat-original-connected-20261013-r9.json'
                pins = dict(H._REVIEWED_ORIGINAL.evidence)
                producer = H._json_file(H._inside(H.HISTORICAL_ROOT, receipt), pins[receipt], check)
                completed = producer['completed_endpoint']
                require(all(completed[k] == endpoint[k] for k in ('head_key', 'root_key')), 'producer endpoint differs')
                result['restart_reads'] = restart_inventory(manifests, summaries, endpoint, completed['array_records'])
            else:
                result['restart_reads'] = dict(status='FORMAT_SPECIFIC',
                    note='Compact manifest inventory measured; historical raw-conversion selections do not apply.')
            observe('structure-restart-inventory-complete')
            result['scratch'].update(total_spooled_bytes=scratch.total, status='CLEANED')
            scratch.remove()
            result['status'] = 'MEASURED'
        except BaseException:
            result['scratch'].update(total_spooled_bytes=scratch.total, status='RETAINED_AFTER_FAILURE')
            raise
        finally:
            # Retain catalogue accounting through all consumers, including exceptions.
            _ = catalogue_owner

