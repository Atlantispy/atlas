"""Authentic separate mesh blocks for the guarded capacity fixture only.

This imports the existing IV1 topology unchanged. Four blocks are not one IV2
topology, and equal content may deduplicate on disk. The caller owns the guard,
original source authentication, shared scope, candidate and simultaneous work.
"""
from hashlib import sha256
import json

import mesh_tables as M


class MeshBlocks:
    """Explicitly close all mesh children before their shared support parent."""
    def __init__(self):
        self.meshes, self.refs = [], []
        self.partition = self.support_source = None
        self.evidence = dict(blocks=[], source_decodes=[],
            scientific_status='NOT_A_REAL_IV2_RUN',
            topology='independent unchanged authentic IV1 blocks',
            support_ownership='one authentic published partition shared by all blocks',
            limitations=[
                'One shared authentic support partition does not measure four times as many distinct successor supports.',
                'Equal payloads may deduplicate on disk; output disk is not a 4x forecast.',
                'Publication is sequential while prior mesh blocks remain resident; four concurrent encoders are not modelled.',
                'Whole legacy source decode is separately charged fixture overhead, not the fresh producer path.',
                'No new cells, physical topology, numerical workspace or scientific IV2 result is asserted.'])

    def close(self):
        # Refuse before teardown when callers still borrow an actual mesh row.
        for mesh in self.meshes:
            mesh._owner.assert_unborrowed()
        for mesh in reversed(self.meshes):
            mesh.close()
        self.meshes.clear()
        if self.support_source is not None:
            self.support_source.close()
            self.support_source = None
        if self.partition is not None:
            self.partition.close()
            self.partition = None


def _read_record(source, binding, *, budget, check, evidence):
    """One paid source JSON decode using the existing audited admission bound."""
    size = binding['filebytes']
    M.require(type(size) is int and 0 < size <= source.limits.max_array_bytes,
              'capacity source record exceeds original array bound')
    owner = M._Allocation(budget, 65536+2*size)
    raw, position, digest = bytearray(size), 0, sha256()
    for start, chunk in source.iter_chunks(binding['snapshot'], binding['array'], budget=budget):
        check()
        M.require(start == position and chunk.dtype.str == '|u1' and chunk.ndim == 1,
                  'capacity source is not a contiguous canonical byte array')
        stop = position+chunk.nbytes
        M.require(stop <= size, 'capacity source exceeds census length')
        block = memoryview(chunk).cast('B')
        raw[position:stop] = block
        digest.update(block)
        position = stop
    M.require(position == size and digest.hexdigest() == binding['sha256'],
              'capacity source differs from authenticated census bytes')
    charge = M._decode_charge(raw)
    decoded_owner = M._Allocation(budget, charge)
    value = json.loads(raw)
    evidence.append(dict(array=binding['array'], snapshot=binding['snapshot'],
        sha256=binding['sha256'], logical_bytes=size, raw_charge_bytes=65536+2*size,
        decoded_charge_bytes=charge, admission='mesh_tables._decode_charge'))
    del raw, owner
    return M.OwnedRow(value, decoded_owner)


def _backing(mesh):
    rows = {}
    for name, array in mesh._arrays.items():
        base = array
        while hasattr(getattr(base, 'base', None), 'dtype'):
            base = base.base
        backing = getattr(base, 'base', None)
        M.require(isinstance(backing, bytes), 'fresh mesh column lacks immutable byte backing')
        rows[name] = dict(bytes=array.nbytes, allocation=id(backing))
    return rows


def retain_mesh_blocks(scope, candidate, source, census, *, count=4,
                       check=lambda: None, checkpoint=lambda name: None):
    """Return MeshBlocks; caller must retain it through seal/commit then close.

    ``census`` is the authenticated document's ``census`` object. The original
    source is already hash-authenticated by the caller and must remain open.
    All decoded inputs are dropped before return. Failure frames retain their
    paid owners; this helper never clears a caller's diagnostic traceback.
    """
    from compact_store import CompactMeshStoreV3
    from live_mesh_patch import _pack
    from partition_v2 import PartitionV2, DESCRIPTOR
    from partition_store import publish_partition_v2
    from record_tables import RecordCodec
    from spatial_workflow_patch import _token
    from support_source import SupportSource
    budget = scope.run_budget
    M.require(candidate.scope is scope and source._budget is budget and
              source._db.execute('PRAGMA query_only').fetchone() == (1,),
              'capacity import requires the exact shared scope and readonly original')
    M.require(type(count) is int and 1 <= count <= 4, 'one to four separate mesh blocks required')
    token = source.change_token()
    result = MeshBlocks()
    partition_binding = census['records']['partition-record:partition']
    mesh_binding = census['records']['spatial-record:mesh']
    checkpoint('authentic-mesh-partition-source-decode')
    held = _read_record(source, partition_binding, budget=budget, check=check,
                        evidence=result.evidence['source_decodes'])
    compact = RecordCodec().pack_record(held.value, record_schema=DESCRIPTOR, scope=scope, check=check)
    identity = compact.identity()
    M.require(identity.sha256 == partition_binding['sha256'] and
              identity.canonical_bytes == partition_binding['filebytes'],
              'authentic partition descriptor changed during compact import')
    partition = PartitionV2(compact, expected_partition_id=held.value['partition_id'], check=check)
    result.partition = partition
    del held, compact
    checkpoint('authentic-mesh-partition-publish')
    partition_ref = publish_partition_v2(candidate, partition,
        producer=sha256(b'capacity authentic mesh support partition').hexdigest(), check=check)
    support = SupportSource(partition, check=check)
    result.support_source = support
    result.evidence['partition'] = dict(reference=partition_ref.to_wire(),
        partition_id=partition.partition_id, support_count=partition.support_count)
    checkpoint('authentic-mesh-source-decode')
    held = _read_record(source, mesh_binding, budget=budget, check=check,
                        evidence=result.evidence['source_decodes'])
    record = held.value
    differential = record['support_tables'].get('differential_supports', {})
    # Verify each original body against the published authentic support before
    # replacing it with a paid-parent reference. The original row is discarded.
    for ident in differential:
        check()
        row = differential[ident]
        temporary = M._Allocation(budget, 65536+2*M._width(row))
        raw = M.canonical(row)
        found = support.identity(ident)
        M.require(sha256(raw).hexdigest() == ident == found.sha256 and
                  len(raw) == found.canonical_bytes, 'authentic mesh support differs from its partition')
        differential[ident] = M.SharedSupportRecord(support, ident)
        del raw, row, temporary
    adapter = CompactMeshStoreV3(candidate, scope=scope, support_source=support)
    seen = set()
    for index in range(count):
        check(); checkpoint('authentic-mesh-block-'+str(index+1)+'-pack')
        metadata, arrays, scratch, reader, dependencies = _pack(held, budget=budget, scope=scope, source=support)
        mesh = M.CompactMesh(metadata, arrays, support_reader=reader,
            expected_geometry_id=mesh_binding['sha256'], budget=budget, scope=scope,
            dependencies=dependencies, check=check)
        result.meshes.append(mesh)
        del metadata, arrays, scratch, reader, dependencies
        identity = mesh.identity()
        M.require(identity.canonical_bytes == mesh_binding['filebytes'],
                  'authentic mesh logical length changed')
        inventory = _backing(mesh)
        allocations = {row['allocation'] for row in inventory.values() if row['bytes'] > 1}
        M.require(not allocations & seen, 'independent mesh blocks share material column backing')
        seen.update(allocations)
        checkpoint('authentic-mesh-block-'+str(index+1)+'-publish')
        ref = adapter.publish(mesh, producer=sha256(('capacity authentic mesh block '+str(index)).encode()).hexdigest(),
                              cancel=_token(check))
        result.refs.append(ref)
        result.evidence['blocks'].append(dict(index=index, identity=identity.to_wire(),
            cells=mesh.cell_count, faces=mesh.face_count, reference=ref.to_wire(),
            packed_column_bytes=sum(row['bytes'] for row in inventory.values()),
            possible_singleton_bytes=sum(row['bytes'] for row in inventory.values() if row['bytes'] <= 1),
            independently_owned_columns=len(allocations)))
        del mesh, inventory, allocations
    del record, differential, held, adapter
    M.require(source.change_token() == token, 'original source changed during mesh capacity import')
    result.evidence['decoded_sources_released_before_return'] = True
    checkpoint('authentic-mesh-blocks-retained-source-released')
    return result


def mechanics_check():
    """Tiny plumbing control only; never an IV1/IV2 capacity measurement."""
    from pathlib import Path
    from contextlib import ExitStack
    import sys
    import tempfile
    here = Path(__file__).resolve().parent
    sys.path[:0] = [str(here.parents[1]/'runtime-integration-r1/runtime-src'), str(here.parent)]
    import numpy as np
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore, StoreLimits
    from content_cache import create_retained_scope
    from interval_store_set import IntervalStoreSet
    from test_mesh_tables import small_mesh_record
    from test_partition_tables import tiny_partition
    budget = WorkBudget(256 << 20)
    task = here.parents[4]
    with tempfile.TemporaryDirectory(prefix='lmc-', dir=task/'_t') as directory, ExitStack() as owners:
        scope = create_retained_scope(budget, process_epoch='mesh-capacity-mechanics')
        stores = IntervalStoreSet.create_migration(Path(directory)/'catalog.json',
            workflow_id='a'*64, scope=scope)
        owners.callback(stores.close)
        candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
        owners.callback(candidate.close)
        body, supports = tiny_partition(budget, count=1, depth=0)
        partition = dict(body, partition_id=M.digest(body), supports=supports)
        mesh = small_mesh_record(budget)
        mesh['support_tables']['differential_supports'] = {M.digest(row): row for row in supports}
        mesh['support_ids'] = body['support_ids']
        values = {'partition-record:partition': M.canonical(partition), 'spatial-record:mesh': M.canonical(mesh)}
        key = 'd'*64
        census = dict(records={name: dict(filebytes=len(raw), sha256=sha256(raw).hexdigest(),
            snapshot=key, array=name) for name, raw in values.items()})
        limits = StoreLimits(chunk_bytes=65536, max_array_bytes=16 << 20, max_store_bytes=64 << 20)
        with ArrayStore(Path(directory)/'source.sqlite', limits, budget=budget) as source:
            source.put(key, {name: np.frombuffer(raw, dtype='u1') for name, raw in values.items()}, {})
            source._db.execute('PRAGMA query_only=ON')
            retained = retain_mesh_blocks(scope, candidate, source, census, count=2)
            M.require(len(retained.meshes) == 2 and retained.meshes[0].geometry_id == M.digest(mesh),
                      'tiny capacity mesh identity differs')
            M.require(retained.refs[0].identity == retained.refs[1].identity,
                      'independent capacity blocks changed their logical mesh')
            held = retained.meshes[0].cell(0)
            try:
                try:
                    retained.close()
                except RuntimeError as error:
                    M.require(str(error) == 'owner has live child borrows', 'unexpected close refusal')
                else:
                    raise AssertionError('escaped mesh row must refuse parent close')
                M.require(retained.meshes[0].identity().sha256 == M.digest(mesh),
                          'refused close destructively changed the retained mesh')
            finally:
                del held
            retained.close()
            evidence = retained.evidence
        owners.close(); scope.close()
    M.require(budget.reserved_bytes == 0, 'tiny capacity mechanics retained a reservation')
    print(json.dumps(dict(status='PASS', mechanics_only=True, blocks=len(evidence['blocks']),
        escaped_row_close_refused=True, final_reserved_bytes=budget.reserved_bytes), sort_keys=True))


if __name__ == '__main__':
    mechanics_check()
