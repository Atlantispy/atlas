"""Bounded manifest-only storage census; never imports codecs or opens a store.

Input must be the native reader's validated, complete snapshot catalogue. This
checks structural references, not payload contents or scientific admission.
Raw chunk bytes are derived from dtype/count, not compressed physical bytes.
"""
from hashlib import sha256
import json
import math
import re

ARRAY_SCHEMA = 'atlas.array-store.v1'
MESH_SCHEMA = 'atlas.compact-mesh-store.v2'
SUPPORT_SCHEMA = 'atlas.compact-mesh-support.v1'
PARTITION_SCHEMA = 'atlas.compact-partition-store.v1'
LINK_SCHEMA = 'atlas.compact-mesh-link.r1'
MESH_CODEC = 'atlas.compact-exterior-mesh.v1'
PARTITION_CODEC = 'atlas.compact-differential-partition.v1'
WORKFLOW_SCHEMA = 'atlas.funded-collar-workflow.v2'
AUTHORITY = 'storage integrity only; scientific admission required'
SUPPORTED_SCHEMAS = (MESH_SCHEMA, SUPPORT_SCHEMA, PARTITION_SCHEMA, LINK_SCHEMA,
                     MESH_CODEC, PARTITION_CODEC)
SOURCE_PATHS = ('compact-geometry-r1/compact_store.py',
                'compact-geometry-r1/partition_store.py',
                'compact-geometry-r1/spatial_workflow_patch.py',
                'compact-geometry-r1/partition_workflow_patch.py',
                'compact-geometry-r1/spatial_indexed_patch.py',
                'compact-geometry-r1/mesh_tables.py',
                'compact-geometry-r1/partition_tables.py', 'workflow_transfer.py')
MAX_SNAPSHOTS, MAX_ARRAYS, MAX_REFERENCES = 4096, 65536, 1000000
MAX_METADATA_ITEMS = 1000000
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_DTYPE = re.compile(r'([<|])([biuf])([1248])\Z')


class CompactInventoryRefused(ValueError):
    """Malformed, unsupported or incompletely supplied inventory."""


def _require(condition, message):
    if not condition:
        raise CompactInventoryRefused(message)


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                             allow_nan=False).encode()).hexdigest()


def _sha(value):
    _require(type(value) is str and _SHA.fullmatch(value), 'canonical SHA-256 required')
    return value


def _dtype(value):
    match = _DTYPE.fullmatch(value) if type(value) is str else None
    _require(match is not None, 'unsupported noncanonical native dtype: '+repr(value))
    order, kind, width = match.groups()
    width = int(width)
    _require((kind != 'b' or width == 1) and (kind != 'f' or width in (2, 4, 8))
             and order == ('|' if width == 1 else '<'), 'unsupported native dtype: '+value)
    return width


def _metadata_schemas(value, allowance):
    stack = [(value, 0)]
    found = set()
    while stack:
        item, depth = stack.pop()
        allowance[0] -= 1
        _require(allowance[0] >= 0 and depth <= 64, 'metadata census bound exceeded')
        if type(item) is dict:
            schema = item.get('schema')
            if type(schema) is str and 'compact' in schema.lower():
                _require(schema in SUPPORTED_SCHEMAS, 'unsupported compact schema: '+schema)
                found.add(schema)
            for key, child in item.items():
                if type(key) is str and key.startswith('compact_'):
                    _require(key in ('compact_mesh', 'compact_partition'),
                             'unsupported compact metadata location: '+key)
                stack.append((child, depth+1))
        elif type(item) is list:
            stack.extend((child, depth+1) for child in item)
    return found


def inventory(manifests, *, chunk_bytes):
    """Count logical mentions and unique typed raw chunks; retain alias edges.

    Unknown compact versions fail explicitly. Descriptor checks do not validate
    codec payloads. Physical encoded bytes require the caller's SQL aggregate.
    """
    _require(type(manifests) is dict and len(manifests) <= MAX_SNAPSHOTS,
             'bounded complete manifest dictionary required')
    _require(type(chunk_bytes) is int and 8 <= chunk_bytes <= 16*1024*1024,
             'native chunk_bytes outside supported bounds')
    chunks, by_snapshot, arrays_total, references = {}, {}, 0, 0
    observed, schema_by_snapshot, allowance = set(), {}, [MAX_METADATA_ITEMS]
    for key, manifest in manifests.items():
        _sha(key)
        _require(type(manifest) is dict and manifest.get('schema') == ARRAY_SCHEMA
                 and manifest.get('invocation') == key and type(manifest.get('arrays')) is dict
                 and bool(manifest['arrays']), 'native validated manifest required')
        schema_by_snapshot[key] = _metadata_schemas(manifest.get('metadata'), allowance)
        observed.update(schema_by_snapshot[key])
        local_ids, logical, local_refs = set(), 0, 0
        arrays_total += len(manifest['arrays'])
        _require(arrays_total <= MAX_ARRAYS, 'array census bound exceeded')
        for name, description in manifest['arrays'].items():
            _require(type(name) is str and type(description) is dict
                     and set(description) == {'dtype', 'shape', 'chunks'}, 'native array descriptor required')
            size = _dtype(description['dtype'])
            shape, ids = description['shape'], description['chunks']
            _require(type(shape) is list and len(shape) <= 16
                     and all(type(n) is int and 0 <= n <= (1 << 63)-1 for n in shape)
                     and type(ids) is list, 'bounded native shape and chunks required')
            count, width = math.prod(shape), chunk_bytes//size
            _require(count*size <= (1 << 63)-1 and len(ids) == (count+width-1)//width,
                     'chunk count differs from exact array shape')
            references += len(ids)
            _require(references <= MAX_REFERENCES, 'chunk-reference census bound exceeded')
            logical += count*size
            local_refs += len(ids)
            for index, ident in enumerate(ids):
                _sha(ident)
                signature = (description['dtype'], min(width, count-index*width)*size)
                _require(ident not in chunks or chunks[ident] == signature,
                         'same chunk ID has incompatible dtype or byte count: '+ident)
                chunks[ident] = signature
                local_ids.add(ident)
        by_snapshot[key] = dict(arrays=len(manifest['arrays']), logical_array_bytes=logical,
                                chunk_references=local_refs, unique_chunk_references=len(local_ids),
                                unique_referenced_raw_bytes=sum(chunks[c][1] for c in local_ids))

    roots, supports, aliases, classified = [], [], [], set()

    def typed_codec(metadata, arrays, schema, identity, prefix):
        codec = metadata.get('codec_metadata')
        fields = ({'schema', 'geometry_id', 'header', 'grid_fields', 'support_tables',
                   'required_faces_present', 'cell_count', 'face_count', 'arrays'} if schema == MESH_CODEC
                  else {'schema', 'partition_id', 'body_node', 'support_count', 'arrays'})
        _require(type(codec) is dict and set(codec) == fields and codec['schema'] == schema
                 and codec[identity] == metadata[identity] and type(codec['arrays']) is dict,
                 'unsupported or incomplete compact codec metadata')
        for name, desc in codec['arrays'].items():
            _require(type(desc) is dict and set(desc) == {'dtype', 'shape', 'sha256'},
                     'complete codec typed descriptor required')
            _sha(desc['sha256'])
            actual = arrays.get(prefix+name)
            _require(actual is not None and actual['dtype'] == desc['dtype']
                     and actual['shape'] == desc['shape'], 'codec/manifest dtype or shape differs')
        return codec

    for key, manifest in manifests.items():
        meta, arrays = manifest['metadata'], manifest['arrays']
        if type(meta) is not dict:
            continue
        schema = meta.get('schema')
        if schema == MESH_SCHEMA:
            _require(set(meta) == {'schema', 'geometry_id', 'codec_metadata', 'supports',
                                  'source_producer', 'parent_snapshot', 'authority'}
                     and meta['authority'] == AUTHORITY and _digest(meta) == key,
                     'compact mesh root identity differs')
            _sha(meta['geometry_id'])
            codec = typed_codec(meta, arrays, MESH_CODEC, 'geometry_id', 'mesh:')
            _require(type(meta['supports']) is dict, 'mesh support inventory required')
            total = 0
            for content, size in meta['supports'].items():
                _sha(content)
                _require(type(size) is int and 0 < size <= (1 << 63)-1, 'positive support byte size required')
                total += size
            expected = {'mesh:'+n for n in codec['arrays']}
            if meta['supports']:
                expected.add('support-blobs')
                packed = arrays.get('support-blobs', {})
                _require(packed.get('dtype') == '|u1' and packed.get('shape') == [total],
                         'packed support-blobs descriptor differs')
            _require(set(arrays) == expected, 'mesh root array coverage differs')
            parent = meta['parent_snapshot']
            if parent is not None:
                _sha(parent)
                _require(parent in manifests and manifests[parent]['metadata'].get('schema') == MESH_SCHEMA,
                         'mesh parent root absent or unsupported')
            roots.append(dict(key=key, kind='mesh', schema=schema, geometry_id=meta['geometry_id'],
                              codec_schema=MESH_CODEC, support_count=len(meta['supports']),
                              packed_support_bytes=total, parent_snapshot=parent,
                              cell_count=codec['cell_count'], face_count=codec['face_count'],
                              **by_snapshot[key]))
            classified.add(key)
        elif schema == PARTITION_SCHEMA:
            _require(set(meta) == {'schema', 'partition_id', 'source_producer', 'codec_metadata', 'authority'}
                     and meta['authority'] == AUTHORITY and type(meta['source_producer']) is dict
                     and bool(meta['source_producer']), 'compact partition root metadata differs')
            _sha(meta['partition_id'])
            binding = {n: meta[n] for n in ('schema', 'partition_id', 'source_producer')}
            _require(_digest(binding) == key, 'partition root identity differs')
            codec = typed_codec(meta, arrays, PARTITION_CODEC, 'partition_id', '')
            _require(set(arrays) == set(codec['arrays']), 'partition root array coverage differs')
            roots.append(dict(key=key, kind='partition', schema=schema, partition_id=meta['partition_id'],
                              codec_schema=PARTITION_CODEC, support_count=codec['support_count'],
                              **by_snapshot[key]))
            classified.add(key)
        elif schema == SUPPORT_SCHEMA:
            _require(set(meta) == {'schema', 'content_sha256', 'nbytes', 'authority'}
                     and meta['authority'] == AUTHORITY and _digest(meta) == key
                     and type(meta['nbytes']) is int and meta['nbytes'] > 0
                     and set(arrays) == {'bytes'} and arrays['bytes']['dtype'] == '|u1'
                     and arrays['bytes']['shape'] == [meta['nbytes']], 'support snapshot metadata differs')
            _sha(meta['content_sha256'])
            supports.append(dict(key=key, content_sha256=meta['content_sha256'], **by_snapshot[key]))
            classified.add(key)

    root_keys = {row['key'] for row in roots}

    def alias(key, reference, kind, prefix, location):
        schema, identity = ((MESH_SCHEMA, 'geometry_id') if kind == 'mesh'
                            else (PARTITION_SCHEMA, 'partition_id'))
        _require(type(reference) is dict and set(reference) == {'schema', 'snapshot_key', identity,
                 'source_producer', 'array_bindings'} and reference['schema'] == schema,
                 'unsupported or incomplete compact reference')
        target = reference['snapshot_key']
        _require(target in root_keys, 'compact alias target missing from complete inventory')
        root = manifests[target]
        _require(root['metadata']['schema'] == schema and root['metadata'][identity] == reference[identity]
                 and root['metadata']['source_producer'] == reference['source_producer'],
                 'compact alias target identity differs')
        bindings = reference['array_bindings']
        _require(type(bindings) is dict and set(bindings) == set(root['arrays']),
                 'compact alias binding coverage differs')
        source = manifests[key]['arrays']
        actual = {n for n in source if not prefix or n.startswith(prefix)}
        _require(actual == {prefix+n for n in bindings}, 'compact alias array coverage differs')
        for name, digest in bindings.items():
            _require(digest == _digest(root['arrays'][name]) == _digest(source[prefix+name]),
                     'compact alias descriptor binding differs')
        aliases.append(dict(key=key, target_snapshot=target, kind=kind, location=location,
                            prefix=prefix, array_count=len(bindings),
                            logical_array_bytes=by_snapshot[target]['logical_array_bytes'],
                            unique_referenced_raw_bytes=by_snapshot[target]['unique_referenced_raw_bytes']))
        classified.add(key)

    for key, manifest in manifests.items():
        meta, arrays = manifest['metadata'], manifest['arrays']
        if type(meta) is not dict:
            continue
        binding = meta.get('binding')
        if type(binding) is dict and binding.get('schema') == LINK_SCHEMA:
            _require(set(meta) == {'binding', 'mesh_reference'}
                     and set(binding) == {'schema', 'geometry_id', 'source_producer'}
                     and _digest(binding) == key, 'compact mesh link binding differs')
            reference = meta['mesh_reference']
            _require(type(reference) is dict and binding['geometry_id'] == reference.get('geometry_id')
                     and binding['source_producer'] == reference.get('source_producer'),
                     'mesh link identity differs from reference')
            alias(key, reference, 'mesh', '', 'mesh-link')
        partition = meta.get('differential_partition')
        refs = [r for r in (meta.get('compact_partition'),
                partition.get('compact_partition') if type(partition) is dict else None) if r is not None]
        exterior = meta.get('exterior_state')
        mesh = exterior.get('compact_mesh') if type(exterior) is dict else None
        has_partition = any(n.startswith('partition-dag:') for n in arrays)
        has_mesh = any(n.startswith('spatial-mesh:') for n in arrays)
        if refs or mesh is not None or has_partition or has_mesh:
            _require(meta.get('schema') == WORKFLOW_SCHEMA, 'unsupported compact workflow schema')
            _require(len(refs) <= 1 and bool(refs) == has_partition and (mesh is not None) == has_mesh,
                     'compact workflow reference/alias coverage differs')
            if refs:
                alias(key, refs[0], 'partition', 'partition-dag:',
                      'workflow-root' if 'compact_partition' in meta else 'workflow-partition-header')
            if mesh is not None:
                alias(key, mesh, 'mesh', 'spatial-mesh:', 'workflow-exterior-header')
        schemas = schema_by_snapshot[key]
        _require(not schemas or key in classified, 'compact metadata in unsupported snapshot location')

    unique = sum(size for _, size in chunks.values())
    logical = sum(row['logical_array_bytes'] for row in by_snapshot.values())
    compact_chunks = {ident for key in classified for desc in manifests[key]['arrays'].values()
                      for ident in desc['chunks']}
    return dict(status='PASS_MANIFEST_INVENTORY_ONLY',
                scope='complete supplied manifests; descriptors only; no payload or scientific validation',
                totals=dict(snapshots=len(manifests), arrays=arrays_total, logical_array_bytes=logical,
                            chunk_references=references, unique_chunk_references=len(chunks),
                            unique_referenced_raw_bytes=unique, repeated_reference_raw_bytes=logical-unique,
                            physical_encoded_bytes=None,
                            physical_encoded_bytes_status='REQUIRES_CALLER_SQL_AGGREGATE'),
                compact=dict(status='PRESENT' if classified else 'ABSENT',
                             supported_schemas=list(SUPPORTED_SCHEMAS), observed_schemas=sorted(observed),
                             format='mesh packed-support v2; partition typed DAG v1; descriptor-bound aliases',
                             roots=sorted(roots, key=lambda r: r['key']),
                             aliases=sorted(aliases, key=lambda r: (r['key'], r['kind'])),
                             support_snapshots=sorted(supports, key=lambda r: r['key']),
                             compact_snapshot_count=len(classified),
                             logical_array_bytes=sum(by_snapshot[key]['logical_array_bytes'] for key in classified),
                             unique_chunk_references=len(compact_chunks),
                             unique_referenced_raw_bytes=sum(chunks[c][1] for c in compact_chunks),
                             other_snapshot_count=len(manifests)-len(classified),
                             source_paths=list(SOURCE_PATHS), codec_payloads_decoded=False,
                             scientific_admission=False))
