"""Q2: real-data census of the compact partition and mesh codecs (Wave 0 probe).

Built and self-tested only; the orchestrator launches it later. It answers one
question before composition: do the compact codecs accept the authenticated r9
head 'partition-record:partition' (~114 MB) and 'spatial-record:mesh' (~190 MB)
within their structural MAX_* bounds, the partition schema gate, the 16 MiB
selected-header cap (partition_native_patch.MAX_HEADER_BYTES) and the 1 MiB
ArrayStore manifest limit, and at what wall/CPU time, RSS and logical booking?

Packing and validation run in memory only, with the real codecs and the real
legacy record decoders (materialise_endpoint.partition_record/spatial_records).
The ORIGINAL opens through historical_admission.open_original_readonly (SQLite
mode=ro plus query_only); head key and store limits come from the two pinned r9
receipts, and the whole database is hashed against its pin before and after.
Nothing is written to the original or to H. Outputs go only to a NEW run
directory: the reviewed successor guard set (guard/), run.json with its guard
sidecars, prepare.json and codec-census.json. A codec refusal or an exceeded
bound is REPORTED (it indicates W2-X or a design decision), never worked around;
no bound, guard or limit changes here. Cancellation propagates (GuardAborted).
Manifest sizes are exact projections of ArrayStore.put's manifest bytes with a
placeholder producer; the composed producer adds its width per occurrence.

  --prepare   verify inputs and print the exact guarded command; writes nothing
  --launch    10 GiB start gate, write the guard set, run the guarded workload
  --workload  the guarded child (ContinuationGuard); never run it directly
Cancel a launched census by creating <output>/run.cancel.

Add --structure-only for the WP0a selected-read baseline. That branch never
packs codecs or composes/migrates a runtime; it writes structure-census.json.

WP0b: --compact CATALOG [--heat-receipt FILE] [--ref FILE] [--verify-files]
--output NEW.json is an exact read-only census of a compact interval catalog
(segment refs and binding indexes, record_tables, mesh v3, partition v2, heat
r4, interval files and catalog), counting logical mentions, unique content
and physical stored bytes separately. Run it on a store copy.
"""
import sys
sys.dont_write_bytecode = True  # never leave bytecode beside frozen sources

import argparse
import ast
from concurrent.futures import CancelledError
from contextlib import contextmanager
from datetime import datetime, timezone
import gc
from hashlib import sha256
import importlib
import json
import math
import os
from pathlib import Path
import subprocess
import time


HERE = Path(__file__).resolve().parent
R = HERE.parent
C = R / 'compact-geometry-r1'
O = R.parent
T = O.parents[2]
I_SRC = O / 'runtime-integration-r1' / 'runtime-src'
DIAGNOSTICS = O / 'monitored-continuation-r1' / 'private_heat_resource_diagnostics_r1.py'
PYTHON = T / '.r44-env' / 'Scripts' / 'python.exe'
DEFAULT_OUTPUT = HERE / 'codec-census-r1'
# Unchanged handoff safeguards; the test cross-checks them against the runner.
RSS_BYTES, FREE_BYTES, START_BYTES, LOGICAL_BYTES = 12 << 30, 1 << 30, 10 << 30, 16 << 30
TARGET_BYTES = 14 << 30  # M19 operational target: below it only a warning
LAUNCH_ENV = dict(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONHASHSEED='0',
                  PYTHONDONTWRITEBYTECODE='1')
REFUSED_ENV = ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONINSPECT')
SCHEMA = 'atlas.private.q2-codec-census.v1'
RUN_SCHEMA = 'atlas.private.q2-codec-census-run.v1'
PREPARE_SCHEMA = 'atlas.private.q2-codec-census-prepare.v1'
STRUCTURE_SCHEMA = 'atlas.private.wp0a-structure-census.v1'
STRUCTURE_RUN_SCHEMA = 'atlas.private.wp0a-structure-census-run.v1'
RUNTIME_MANIFEST = I_SRC.parent / 'manifest.json'
RUNTIME_MANIFEST_PIN = '597c00328bb8aede225a8a936dcea2edab42d3c894eb87caeb974fdfd576979d'
READER_RECEIPT = 'reader-memory-20261013-r3.json'
PRODUCER_RECEIPT = 'heat-original-connected-20261013-r9.json'
ENDPOINT_FIELDS = ('head_key', 'root_key', 'workflow_id', 'store_limits', 'store_compression')
PARTITION_BLOB, STATE_BLOB, MESH_BLOB = 'partition-record:partition', 'spatial-record:state', 'spatial-record:mesh'
NAMED_HEADER_FIELDS = ('native_contacts', 'support_ids', 'identity_start_cells')
# The composed producer (execution identity, collar plan) is unknown until W3;
# manifests are projected with this placeholder and report its occurrences.
PRODUCER_PLACEHOLDER = {'placeholder': 'source producer is bound at composition'}
CHUNK_PLACEHOLDER = '0'*64
# CompactMesh._validate fixed-shape columns; every other column has a row bound.
MESH_FIXED = frozenset(('c.id', 'c.q', 'c.tag', 'c.mask', 'c.support', 'c.face_offset', 'c.lookup',
    'f.id', 'f.q', 'f.tag', 'f.mask', 'f.cut', 'f.vertex_offset', 'f.owner_offset', 'f.cart_offset', 'f.lookup',
    'grid_lines.offset', 'thermal_shared_lines.offset'))
SOURCES = (R/'historical_admission.py', R/'materialise_endpoint.py', R/'workflow_transfer.py',
    R/'native_transfer.py', R/'resource_guard_patch.py', R/'geometry_transfer.py', C/'mesh_tables.py',
    C/'partition_tables.py', C/'partition_native_patch.py', C/'partition_store.py',
    C/'partition_workflow_patch.py', C/'partition_routing_transform.py', C/'partition_routing_patch.py',
    C/'compact_store.py', C/'spatial_workflow_patch.py', C/'spatial_indexed_patch.py', HERE/'probe_codec_census.py')
STRUCTURE_SOURCES = (R/'historical_admission.py', R/'workflow_transfer.py', R/'native_transfer.py',
    R/'materialise_endpoint.py', R/'run_prepared_restart.py', R/'initial_workload.py', R/'resource_guard_patch.py',
    C/'partition_workflow_patch.py', C/'spatial_workflow_patch.py', C/'compact_store.py', C/'partition_store.py',
    C/'spatial_indexed_patch.py', C/'mesh_tables.py', C/'partition_tables.py',
    HERE/'probe_codec_census.py', HERE/'structure_census.py', HERE/'structure_json.py', HERE/'compact_structure.py')
# Historical mapping sources are data-only audit inputs, never import roots.
H_STRUCTURE_PINS = {
    'private_heat_native_projection_r4.py': '662f94b04046e83976a763d016bdcfdc83dbf7941ea6a1a2c307e0a61fcb88e6',
    'private_heat_snapshot_store_r3.py': '7a6d5c3d6f46dd7c64d8f44377e1672ddc8cebcc869b517148e01b9b516fb948',
    'private_heat_joined_consumer_r6.py': 'eed99e320c981867eec67fabba2b6061f1996b91fbfe10a6f765ab88d6765324',
    'private_heat_checkpoint_consumer_r9.py': '95d0840eeedbef6b3b6cea53d737cdda32fb67330ab0016a356990c2d0dea2c9',
}
_END = object()


class CensusRefused(RuntimeError):
    """An input, path or gate differs from the census scope; nothing is measured."""


def require(condition, message):
    if not condition:
        raise CensusRefused(message)


def _nothing(*_args):
    return None


def _now():
    return datetime.now(timezone.utc).isoformat()


def _file_sha(path):
    digest = sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _imports(*front):
    # Final order: front..., C, R, I runtime-src. Never an H root.
    for entry in (I_SRC, R, C, *reversed(front)):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))


def _clock():
    return time.perf_counter(), time.process_time()


def _elapsed(report, label, clock):
    report.setdefault('seconds', {})[label] = round(time.perf_counter()-clock[0], 6)
    report.setdefault('cpu_seconds', {})[label] = round(time.process_time()-clock[1], 6)


@contextmanager
def _timed(report, label):
    clock = _clock()
    try:
        yield
    finally:
        _elapsed(report, label, clock)


def _bound(rows, name, value, bound, source, scope, *, strict=False):
    within = value is not None and (value < bound if strict else value <= bound)
    rows.append(dict(name=name, value=value, bound=bound, rule='<' if strict else '<=',
                     within=bool(within), source=source, scope=scope))


def _canonical_len(value):
    import mesh_tables as M
    try:
        return len(M.canonical(value))
    except (TypeError, ValueError, RecursionError):
        return None


def _width(value):
    import mesh_tables as M
    try:
        return M._width(value)
    except (M.MeshTablesRefused, RecursionError):
        return None


def _string_width(value):
    # mesh_tables._width for strings; printable ASCII needs no per-char loop.
    if value.isascii() and value.isprintable() and '"' not in value and '\\' not in value:
        return len(value)+2
    return _width(value)


def _propagates(error):
    # Cancellation (GuardAborted is a concurrent.futures.CancelledError, an
    # Exception), real allocation failure and probe defects are never data.
    return isinstance(error, (CancelledError, MemoryError, CensusRefused))


def _refusal(stage, error, typed):
    """Codec refusal as data; the traceback (and its charges) is not kept.

    typed=False marks an untyped codec exception on these inputs: still a
    refusal to report, not a value the census works around.
    """
    import mesh_tables as M
    import partition_tables as P
    codec = {os.path.normcase(os.path.abspath(f)) for f in (M.__file__, P.__file__)}
    frames, progress, tb = [], None, error.__traceback__
    while tb is not None:
        frame = tb.tb_frame
        if os.path.normcase(os.path.abspath(frame.f_code.co_filename)) in codec:
            frames.append(frame.f_code.co_name)
            if progress is None:
                progress = _progress(frame.f_locals)
        tb = tb.tb_next
    frame = tb = None
    return dict(stage=stage, type=type(error).__name__, typed=isinstance(error, typed), message=str(error)[:4096],
                codec_frames=frames, progress_at_refusal=progress)


def _progress(local):
    import mesh_tables as M
    import partition_tables as P
    builder, pool = local.get('builder'), local.get('pool')
    if type(builder) is P._Builder:
        pool = builder.pool
        return dict(nodes=len(builder.nodes), edges=sum(len(row[2]) for row in builder.nodes),
                    strings=len(builder.string_values), floats=len(builder.float_values),
                    integers=len(pool.integer_values), rationals=len(pool.rational_values),
                    ids=len(pool.id_values), supports_packed=len(local.get('roots', ())))
    if type(pool) is M._Pools:
        return dict(integers=len(pool.integer_values), rationals=len(pool.rational_values),
                    ids=len(pool.id_values), tags=len(pool.tag_values))
    return None


def _walk(roots, check):
    """Raw JSON shape with pack_partition's value classification and depths.

    Raw value/edge counts are upper bounds on the deduplicated DAG; the exact
    counts come from the real packed arrays when the codec accepts.
    """
    kinds = dict.fromkeys(('null', 'bool', 'integer', 'float', 'string', 'id', 'rational',
                           'list', 'object', 'unsupported'), 0)
    shape = dict(values=0, edges=0, max_container_items=0, max_object_keys=0, max_depth=0,
                 max_container_depth=-1, max_rational_depth=-1, max_string_width=0,
                 max_integer_bytes=0, max_rational_text=0, nonfinite_floats=0, kinds=kinds)
    stack = [(iter(roots), 0)]
    while stack:
        items, depth = stack[-1]
        value = next(items, _END)
        if value is _END:
            stack.pop()
            continue
        shape['values'] += 1
        if not shape['values'] & 4095:
            check()
        shape['max_depth'] = max(shape['max_depth'], depth)
        kind = type(value)
        if kind is list and len(value) == 2 and all(type(v) is str and v.startswith(('0x', '-0x')) for v in value):
            kinds['rational'] += 1
            shape['max_rational_depth'] = max(shape['max_rational_depth'], depth)
            shape['max_rational_text'] = max(shape['max_rational_text'], len(value[0]), len(value[1]))
        elif kind is list or kind is dict:
            kinds['list' if kind is list else 'object'] += 1
            shape['edges'] += len(value)
            shape['max_container_items'] = max(shape['max_container_items'], len(value))
            shape['max_container_depth'] = max(shape['max_container_depth'], depth)
            if kind is dict:
                shape['max_object_keys'] = max(shape['max_object_keys'], len(value))
                for key in value:
                    if type(key) is str:
                        shape['max_string_width'] = max(shape['max_string_width'], _string_width(key) or 0)
                    else:
                        kinds['unsupported'] += 1
                stack.append((iter(value.values()), depth+1))
            else:
                stack.append((iter(value), depth+1))
        elif kind is str:
            if len(value) == 64 and not value.strip('0123456789abcdef'):
                kinds['id'] += 1
            else:
                kinds['string'] += 1
                shape['max_string_width'] = max(shape['max_string_width'], _string_width(value) or 0)
        elif kind is bool:
            kinds['bool'] += 1
        elif kind is int:
            kinds['integer'] += 1
            shape['max_integer_bytes'] = max(shape['max_integer_bytes'], (abs(value).bit_length()+7)//8)
        elif kind is float:
            kinds['float'] += 1
            shape['nonfinite_floats'] += not math.isfinite(value)
        elif value is None:
            kinds['null'] += 1
        else:
            kinds['unsupported'] += 1
    # mesh_tables._width also descends into rational strings (one level deeper).
    shape['width_depth'] = max(shape['max_depth'], shape['max_rational_depth']+1)
    shape['validation_depth'] = shape['max_container_depth']+1
    return shape


def _array_rows(arrays, limits):
    from atlas_tectonics.storage import _dtype
    rows = {}
    for name, array in sorted(arrays.items()):
        dtype = _dtype(array.dtype.str)
        width = limits.chunk_bytes // dtype.itemsize
        rows[name] = dict(dtype=dtype.str, shape=list(array.shape), nbytes=int(array.nbytes),
                          chunks=(int(array.size)+width-1)//width)
    return rows


def _placeholder(rows):
    return {name: dict(chunks=[CHUNK_PLACEHOLDER]*row['chunks'], dtype=row['dtype'], shape=row['shape'])
            for name, row in rows.items()}


def _digests(rows):
    """Reference array_bindings: one 64-hex ArrayReference descriptor digest per array."""
    return {name: CHUNK_PLACEHOLDER for name in rows}


def _manifest(invocation, rows, metadata):
    """Exact ArrayStore.put manifest bytes (strict mode) with placeholder chunk IDs."""
    from atlas_tectonics.storage import _SCHEMA, _json
    meta = len(_json(metadata))
    chunks = sum(row['chunks'] for row in rows.values())
    body = len(_json(dict(schema=_SCHEMA, invocation=invocation, arrays=_placeholder(rows), metadata=metadata)))
    return dict(invocation=invocation, body_bytes=body, metadata_bytes=meta, arrays=len(rows),
                chunk_references=chunks, put_precheck_bytes=meta+68*chunks+256*len(rows),
                total_bytes=sum(row['nbytes'] for row in rows.values()),
                largest_array_bytes=max((row['nbytes'] for row in rows.values()), default=0))


def _exceeded(report):
    report['bounds_exceeded'] = [r['name'] for r in report['bounds'] if not r['within'] and r['scope'] != 'information']
    report['information_exceeded'] = [r['name'] for r in report['bounds'] if not r['within'] and r['scope'] == 'information']


def _store_bounds(rows, label, manifest, limits, scope):
    _bound(rows, label+' manifest body bytes', manifest['body_bytes'], limits.max_manifest_bytes,
           'StoreLimits.max_manifest_bytes (ArrayStore.put/_manifest)', scope)
    _bound(rows, label+' put projected manifest bytes', manifest['put_precheck_bytes'], limits.max_manifest_bytes,
           'ArrayStore.put meta+68*chunks+256*arrays', scope)
    _bound(rows, label+' metadata bytes', manifest['metadata_bytes'], limits.max_manifest_bytes,
           'ArrayStore.put metadata limit', scope)
    _bound(rows, label+' chunk references', manifest['chunk_references'],
           min(limits.max_chunks, limits.max_manifest_bytes // 68), 'ArrayStore.put min(max_chunks, max_manifest_bytes//68)', scope)
    _bound(rows, label+' snapshot bytes (full read)', manifest['total_bytes'], limits.max_array_bytes,
           'StoreLimits.max_array_bytes (put/get full read)', scope)


class PartitionCensus:
    """Two steps so a caller can release the decoded JSON before validation.

    pack() measures the decoded body/supports and runs the real pack_partition;
    finish() validates with the real CompactPartition, measures selected headers
    on the sealed view, checks descriptor identity and projects the root manifest.
    """

    def __init__(self, *, expected_partition_id, budget, limits, check=_nothing, descriptor=None,
                 source_producer=PRODUCER_PLACEHOLDER, observe=_nothing):
        _imports()
        self.expected, self.budget, self.limits, self.check = expected_partition_id, budget, limits, check
        self.descriptor, self.producer, self.observe = descriptor, source_producer, observe
        self.report = dict(kind='partition', partition_id=expected_partition_id, status='STARTED',
                           refusal=None, schema_gate='not-reached', bounds=[], seconds={}, cpu_seconds={})
        self._metadata = self._arrays = self._rows = None

    def _refused(self):
        import mesh_tables as M
        import partition_tables as P
        from atlas_tectonics.resources import MemoryLimitError
        return (P.PartitionTablesRefused, M.MeshTablesRefused, MemoryLimitError)

    def pack(self, body, supports):
        import mesh_tables as M
        import partition_tables as P
        import partition_native_patch as PN
        require(type(body) is dict and type(supports) is list, 'decoded partition body and ordered support list required')
        report, rows = self.report, self.report['bounds']
        with _timed(report, 'input_scan'):
            shape = _walk([body, *supports], self.check)
            fields = {str(name): _canonical_len(body[name]) for name in sorted(body, key=str)}
            lists = {}
            for name, value in body.items():
                if type(value) is list and value:
                    largest = 0
                    for row in value:
                        self.check()
                        largest = max(largest, _canonical_len(row) or 0)
                    lists[str(name)] = dict(count=len(value), largest_row_bytes=largest)
            sizes = [_canonical_len(row) for row in supports]
            ids = body.get('support_ids')
            report['input'] = dict(shape, top_level_fields=len(body), field_bytes=fields, list_rows=lists,
                body_bytes=sum(v for v in fields.values() if v is not None), supports=len(supports),
                support_ids=len(ids) if type(ids) is list else None,
                distinct_support_ids=len(set(ids)) if type(ids) is list and all(type(i) is str for i in ids) else None,
                largest_support_bytes=max((s for s in sizes if s is not None), default=0),
                total_support_bytes=sum(s for s in sizes if s is not None),
                unencodable_supports=sum(s is None for s in sizes))
        del sizes
        self.observe('partition-input-scanned')
        source = 'partition_tables.'
        _bound(rows, 'builder depth', shape['max_depth'], P.MAX_DEPTH, source+'MAX_DEPTH (_Builder.add)', 'codec')
        _bound(rows, 'record width nesting', shape['width_depth'], 128, 'mesh_tables._width depth 128', 'codec')
        _bound(rows, 'longest string or key width', shape['max_string_width'], P.MAX_STRING_BYTES,
               source+'MAX_STRING_BYTES', 'codec')
        _bound(rows, 'largest container items', shape['max_container_items'], P.MAX_EDGES, source+'MAX_EDGES (per container)', 'codec')
        _bound(rows, 'largest JSON integer bytes', shape['max_integer_bytes'], M.MAX_INTEGER_BYTES, 'mesh_tables.MAX_INTEGER_BYTES', 'codec')
        _bound(rows, 'longest rational hex text', shape['max_rational_text'], 2*M.MAX_INTEGER_BYTES+3,
               '2*mesh_tables.MAX_INTEGER_BYTES+3', 'codec')
        _bound(rows, 'support_ids entries', report['input']['support_ids'], P.MAX_NODES, source+'MAX_NODES (pack_partition)', 'codec')
        _bound(rows, 'body canonical bytes', report['input']['body_bytes'], M.MAX_BYTES,
               'mesh_tables.MAX_BYTES (gate uses _width >= canonical bytes)', 'codec')
        _bound(rows, 'largest support canonical bytes', report['input']['largest_support_bytes'], M.MAX_BYTES,
               'mesh_tables.MAX_BYTES (pack support size)', 'codec')
        _bound(rows, 'largest support legacy bytes', report['input']['largest_support_bytes'], PN.MAX_NATIVE_SUPPORT_BYTES,
               'partition_native_patch.MAX_NATIVE_SUPPORT_BYTES (materialise_support)', 'consumer')
        _bound(rows, 'largest object keys', shape['max_object_keys'], P.MAX_ROW_ITEMS,
               'partition_tables.MAX_ROW_ITEMS (NodeRef.row only; field()/at() unbounded)', 'information')
        for name, row in sorted(lists.items()):
            _bound(rows, 'largest '+name+' row bytes', row['largest_row_bytes'], PN.MAX_HEADER_BYTES,
                   'partition_native_patch.MAX_HEADER_BYTES (partition_rows)', 'consumer')
        try:
            with _timed(report, 'pack'):
                self._metadata, self._arrays = P.pack_partition(body, iter(supports), expected_partition_id=self.expected,
                                                                budget=self.budget, check=self.check)
        except Exception as error:
            if _propagates(error):
                raise
            report['refusal'] = _refusal('pack', error, self._refused())
        self.observe('partition-packed')

    def finish(self):
        import mesh_tables as M
        import numpy as np
        import partition_tables as P
        import partition_native_patch as PN
        report, rows, arrays, metadata = self.report, self.report['bounds'], self._arrays, self._metadata
        self._metadata = self._arrays = None
        view = None
        if arrays is not None:
            report['arrays'] = self._rows = _array_rows(arrays, self.limits)
            offsets = arrays['int.offset']
            counts = report['counts'] = dict(nodes=len(arrays['node.kind']), edges=len(arrays['edge.child']),
                supports=len(arrays['support.node']), integers=len(arrays['int.sign']),
                integer_bytes=len(arrays['int.bytes']), rationals=len(arrays['q.pair']), ids=len(arrays['id.bytes']),
                strings=len(arrays['string.offset'])-1, string_bytes=len(arrays['string.bytes']),
                floats=len(arrays['float.value']), max_integer_bytes=int(np.max(np.diff(offsets))) if len(offsets) > 1 else 0,
                array_bytes=sum(row['nbytes'] for row in self._rows.values()),
                array_chunks=sum(row['chunks'] for row in self._rows.values()), metadata_width=_width(metadata))
            _bound(rows, 'DAG nodes', counts['nodes'], P.MAX_NODES, 'partition_tables.MAX_NODES', 'codec')
            _bound(rows, 'DAG edges', counts['edges'], P.MAX_EDGES, 'partition_tables.MAX_EDGES', 'codec')
            _bound(rows, 'supports', counts['supports'], P.MAX_NODES, 'partition_tables.MAX_NODES (support count)', 'codec')
            for name in ('integers', 'rationals', 'ids'):
                _bound(rows, name+' pool', counts[name], M.MAX_ITEMS, 'mesh_tables.MAX_ITEMS (_Pools)', 'codec')
            _bound(rows, 'largest pooled integer bytes', counts['max_integer_bytes'], M.MAX_INTEGER_BYTES,
                   'mesh_tables.MAX_INTEGER_BYTES', 'codec')
            _bound(rows, 'compact array bytes', counts['array_bytes'], M.MAX_BYTES, 'mesh_tables.MAX_BYTES (_freeze)', 'codec')
            _bound(rows, 'compact metadata width', counts['metadata_width'], 65536, 'CompactPartition metadata', 'codec', strict=True)
            try:
                with _timed(report, 'validate'):
                    view = P.CompactPartition(metadata, arrays, expected_partition_id=self.expected,
                                              budget=self.budget, check=self.check)
            except Exception as error:
                if _propagates(error):
                    raise
                report['refusal'] = _refusal('validate', error, self._refused())
            self.observe('partition-validated')
        refusal = report['refusal']
        report['schema_gate'] = ('pass' if view is not None else 'refused' if refusal and refusal['stage'] == 'validate'
                                 and '_schema_gate' in refusal['codec_frames'] else 'not-reached')
        if view is not None:
            with _timed(report, 'selected_headers'):
                report['headers'] = self._headers(view)
            for name in NAMED_HEADER_FIELDS:
                # _view_fields skips an absent optional field: it selects 0 bytes.
                _bound(rows, name+' selected bytes', report['headers']['view_bytes'].get(name, 0), PN.MAX_HEADER_BYTES,
                       'partition_native_patch.MAX_HEADER_BYTES', 'consumer')
            for label, row in report['headers']['selections'].items():
                # 'named' is the three fields together, not one consumer's selection.
                _bound(rows, label+' selection bytes', row['bytes'], PN.MAX_HEADER_BYTES,
                       'partition_native_patch._view_fields cumulative', 'information' if label == 'named' else 'consumer')
            self.observe('partition-headers-measured')
            if self.descriptor is not None:
                import partition_workflow_patch as PW
                with _timed(report, 'descriptor_identity'):
                    found = PW.descriptor_stats(view)
                report['descriptor_identity'] = dict(expected=self.descriptor, found=found, match=found == self.descriptor)
                self.observe('partition-descriptor-identity')
        if arrays is not None:
            with _timed(report, 'manifest_projection'):
                if view is not None:
                    owned = view.storage_payload()
                    metadata = owned.value[0]
                    del owned
                report['manifest'] = self._manifest(metadata)
            _store_bounds(rows, 'partition root', report['manifest']['root'], self.limits, 'store')
            _bound(rows, 'partition store open bytes', report['manifest']['root']['total_bytes'],
                   min(M.MAX_BYTES, self.limits.max_array_bytes), 'partition_store.open min(MAX_BYTES, max_array_bytes)', 'store')
            self.observe('partition-projected')
        identity = report.get('descriptor_identity', {}).get('match', True)
        report['status'] = 'REFUSED' if view is None else 'ACCEPTED' if identity else 'IDENTITY_DIFFERS'
        _exceeded(report)
        del view, arrays, metadata
        return report

    def _headers(self, view):
        import partition_native_patch as PN
        import partition_routing_patch as RP
        import partition_routing_transform as RT
        import partition_workflow_patch as PW
        import geometry_transfer as G
        selections = dict(ale=RT.ALE_FIELDS, trace=RT.TRACE_FIELDS, workflow_header=PW.HEADER_KEYS[1:],
                          geometry_transfer_parent=G.PARENT_COMPACT_FIELDS,
                          routing_continuation=RP.CONTINUATION_FIELDS, named=NAMED_HEADER_FIELDS)
        fields = self.report['input']['field_bytes']
        wanted = sorted({name for names in selections.values() for name in names if name in fields})
        root, sizes = view.root(), {}
        for name in wanted:
            self.check()
            size = 0
            for part in view.iter_legacy_json(root.field(name)):
                size += len(part)
            sizes[name] = size
        totals = {}
        for label, names in selections.items():
            total, first = 0, None
            for name in names:
                total += sizes.get(name, 0)
                if first is None and total > PN.MAX_HEADER_BYTES:
                    first = name
            totals[label] = dict(fields=list(names), bytes=total, first_field_over_bound=first)
        return dict(bound=PN.MAX_HEADER_BYTES, view_bytes=sizes, selections=totals,
                    absent_selected_fields=sorted({n for names in selections.values() for n in names} - set(sizes)),
                    view_dict_mismatch=sorted(n for n in sizes if sizes[n] != fields[n]))

    def _manifest(self, metadata):
        import partition_store as PS
        from atlas_tectonics.storage import _json
        record = dict(PS.binding(self.expected, self.producer), codec_metadata=metadata, authority=PS.AUTHORITY)
        key = PS.key_for(self.expected, self.producer)
        return dict(root_key=key, root=_manifest(key, self._rows, record), descriptions=self._rows,
                    source_producer_bytes=len(_json(self.producer)), producer_occurrences=dict(root=1))


def partition_census(body, supports, **kwargs):
    """Both steps while the caller keeps the decoded record (tests/small inputs)."""
    census = PartitionCensus(**kwargs)
    census.pack(body, supports)
    return census.finish()


def mesh_census(record, *, expected_geometry_id, budget, limits, check=_nothing,
                source_producer=PRODUCER_PLACEHOLDER, observe=_nothing, partition_root=None, report=None):
    """Real pack_mesh/CompactMesh on one decoded legacy mesh, in memory only.

    The record stays alive through validation, as in spatial_workflow_patch.
    convert_mesh. Support blobs are not duplicated: the reader re-encodes one
    support from the record (the real route reads it back from its store).
    A supplied report is filled in place, so a cancelled census keeps its part.
    """
    _imports()
    import numpy as np
    import mesh_tables as M
    from atlas_tectonics.resources import MemoryLimitError
    refused = (M.MeshTablesRefused, MemoryLimitError)
    require(type(record) is dict, 'decoded legacy mesh record required')
    report = {} if report is None else report
    report.update(kind='mesh', geometry_id=expected_geometry_id, status='STARTED', refusal=None, bounds=[])
    report.setdefault('seconds', {})
    report.setdefault('cpu_seconds', {})
    rows = report['bounds']
    with _timed(report, 'input_scan'):
        shape, contents = _mesh_input(record, check)
    report['input'] = shape
    observe('mesh-input-scanned')
    _bound(rows, 'cells', shape['cells'], M.MAX_ITEMS, 'mesh_tables.MAX_ITEMS', 'codec')
    _bound(rows, 'faces', shape['faces'], M.MAX_ITEMS, 'mesh_tables.MAX_ITEMS', 'codec')
    _bound(rows, 'support entries', shape['support_entries'], M.MAX_ITEMS, 'mesh_tables.MAX_ITEMS', 'codec')
    _bound(rows, 'header width', shape['header_width'], M.MAX_HEADER_BYTES, 'mesh_tables.MAX_HEADER_BYTES', 'codec')
    _bound(rows, 'largest support canonical bytes', shape['largest_support_bytes'], M.MAX_SUPPORT_BYTES,
           'mesh_tables.MAX_SUPPORT_BYTES', 'codec')
    _bound(rows, 'largest cell face list', shape['max_cell_faces'], M.MAX_ITEMS, 'mesh_tables.MAX_ITEMS', 'codec')
    _bound(rows, 'largest face polygon', shape['max_face_vertices'], M.MAX_ITEMS, 'mesh_tables.MAX_ITEMS', 'codec')
    _bound(rows, 'largest row annotation width', shape['max_tag_width'], M.MAX_TAG_BYTES, 'mesh_tables.MAX_TAG_BYTES', 'codec')
    written = {}
    tables = record.get('support_tables')

    def writer(content, raw):
        check()
        require(content in contents and type(raw) is bytes, 'support blob outside the scanned inventory')
        require(written.setdefault(content, len(raw)) == len(raw), 'one support identity has different lengths')

    def reader(content, size):
        require(content in contents, 'support blob outside the scanned inventory')
        table, ident = contents[content]
        return M.canonical(tables[table][ident])

    metadata = arrays = view = None
    try:
        with _timed(report, 'pack'):
            metadata, arrays = M.pack_mesh(record, support_writer=writer, budget=budget, check=check)
    except Exception as error:
        if _propagates(error):
            raise
        report['refusal'] = _refusal('pack', error, refused)
    observe('mesh-packed')
    if arrays is not None:
        array_rows = report['arrays'] = _array_rows(arrays, limits)
        offsets = arrays['int.offset']
        counts = report['counts'] = dict(cells=len(arrays['c.mask']), faces=len(arrays['f.mask']),
            incidences=len(arrays['c.face']), vertices=len(arrays['f.vertex']), owners=len(arrays['f.owner']),
            cartesian_supports=len(arrays['f.cart']), integers=len(arrays['int.sign']),
            integer_bytes=len(arrays['int.bytes']), rationals=len(arrays['q.pair']), ids=len(arrays['id.bytes']),
            tags=len(arrays['tag.offset'])-1, tag_bytes=len(arrays['tag.bytes']), supports=len(arrays['s.id']),
            max_integer_bytes=int(np.max(np.diff(offsets))) if len(offsets) > 1 else 0,
            array_bytes=sum(row['nbytes'] for row in array_rows.values()),
            array_chunks=sum(row['chunks'] for row in array_rows.values()), metadata_width=_width(metadata))
        for name in ('ids', 'integers', 'rationals', 'tags'):
            _bound(rows, name+' pool', counts[name], M.MAX_ITEMS, 'mesh_tables.MAX_ITEMS (_Pools)', 'codec')
        for name, row in array_rows.items():
            if name not in MESH_FIXED:
                bound = M.MAX_BYTES if name in ('int.bytes', 'tag.bytes') else M.MAX_ITEMS
                _bound(rows, 'column rows '+name, row['shape'][0], bound, 'CompactMesh._validate variable column', 'codec')
        _bound(rows, 'largest pooled integer bytes', counts['max_integer_bytes'], M.MAX_INTEGER_BYTES,
               'mesh_tables.MAX_INTEGER_BYTES', 'codec')
        _bound(rows, 'compact array bytes', counts['array_bytes'], M.MAX_BYTES, 'mesh_tables.MAX_BYTES', 'codec')
        _bound(rows, 'compact metadata width', counts['metadata_width'], 4*M.MAX_HEADER_BYTES,
               '4*mesh_tables.MAX_HEADER_BYTES (CompactMesh)', 'codec')
        try:
            with _timed(report, 'validate'):
                view = M.CompactMesh(metadata, arrays, support_reader=reader, expected_geometry_id=expected_geometry_id,
                                     budget=budget, check=check)
        except Exception as error:
            if _propagates(error):
                raise
            report['refusal'] = _refusal('validate', error, refused)
        observe('mesh-validated')
        with _timed(report, 'manifest_projection'):
            if view is not None:
                owned = view.storage_payload()
                metadata = owned.value[0]
                del owned
                bindings = {}
                for content, size in view.support_bindings():
                    bindings.setdefault(content, size)
            else:
                bindings = dict(written)
            report['manifest'] = _mesh_manifest(metadata, array_rows, bindings, expected_geometry_id,
                                                source_producer, limits, partition_root)
        manifest = report['manifest']
        _store_bounds(rows, 'mesh root', manifest['root'], limits, 'store')
        _store_bounds(rows, 'mesh link', manifest['link'], limits, 'store')
        _bound(rows, 'compact_store root support inventory', manifest['compact_store_inventory_bytes'],
               limits.max_manifest_bytes, 'compact_store.publish base+160*supports', 'store')
        _bound(rows, 'compact_store open array bytes', manifest['open_array_bytes'], limits.max_array_bytes,
               'compact_store.open max_array_bytes', 'store')
        if manifest['largest_support_snapshot'] is not None:
            _store_bounds(rows, 'largest support snapshot', manifest['largest_support_snapshot'], limits, 'store')
        _store_bounds(rows, 'workflow aliases (lower bound)', manifest['workflow_aliases_lower_bound'], limits,
                      'store-workflow')
        observe('mesh-projected')
    report['status'] = 'ACCEPTED' if view is not None else 'REFUSED'
    _exceeded(report)
    del view, arrays, metadata
    return report


def _mesh_input(record, check):
    import mesh_tables as M
    cells, faces, tables = record.get('cells'), record.get('faces'), record.get('support_tables')
    cells = cells if type(cells) is list else []
    faces = faces if type(faces) is list else []
    header = {k: v for k, v in record.items() if k not in M.SPECIAL}
    shape = dict(fields=sorted(map(str, record)), cells=len(cells), faces=len(faces),
                 header_width=_width(header), header_canonical_bytes=_canonical_len(header),
                 max_cell_faces=0, incidences=0, max_face_vertices=0, vertices=0, owners=0,
                 cartesian_supports=0, max_tag_width=0, unmeasurable_tags=0)
    counted = ((cells, M.CELL_TAGS, (('faces', 'incidences', 'max_cell_faces'),)),
               (faces, M.FACE_TAGS, (('vertices_m', 'vertices', 'max_face_vertices'), ('owners', 'owners', None),
                                     ('cartesian_support', 'cartesian_supports', None))))
    for rows, names, lists in counted:
        for i, row in enumerate(rows):
            if not i & 1023:
                check()
            if type(row) is not dict:
                continue
            for field, total, largest in lists:
                value = row.get(field)
                if type(value) is list:
                    shape[total] += len(value)
                    if largest:
                        shape[largest] = max(shape[largest], len(value))
            tag = _width({k: v for k, v in row.items() if k in names})
            if tag is None:
                shape['unmeasurable_tags'] += 1
            else:
                shape['max_tag_width'] = max(shape['max_tag_width'], tag)
    contents, per_table, largest, total, unencodable = {}, {}, 0, 0, 0
    if type(tables) is dict:
        for table, entries in sorted(tables.items(), key=lambda item: str(item[0])):
            if type(entries) is not dict:
                continue
            per_table[str(table)] = len(entries)
            for ident, value in entries.items():
                check()
                try:
                    raw = M.canonical(value)
                except (TypeError, ValueError, RecursionError):
                    unencodable += 1
                    continue
                contents.setdefault(sha256(raw).hexdigest(), (table, ident))
                largest, total = max(largest, len(raw)), total+len(raw)
                del raw
    grids = {}
    for field in ('grid_lines', 'thermal_shared_lines'):
        axes = record.get(field)
        if type(axes) is list:
            grids[field] = [len(axis) if type(axis) is list else None for axis in axes]
    required = record.get('required_thermal_boundary_faces')
    shape.update(support_tables=per_table, support_entries=sum(per_table.values()), distinct_support_blobs=len(contents),
                 largest_support_bytes=largest, total_support_bytes=total, unencodable_supports=unencodable,
                 grid_lines=grids, required_boundary_faces=len(required) if type(required) is list else None)
    return shape, contents


def _mesh_manifest(metadata, array_rows, bindings, geometry_id, producer, limits, partition_root):
    import compact_store as CS
    import native_transfer as N
    import spatial_workflow_patch as Y
    from atlas_tectonics.storage import _json
    rows = {'mesh:'+name: row for name, row in array_rows.items()}
    width = limits.chunk_bytes
    supports = dict(bindings)
    packed = sum(supports.values())
    if supports:
        # compact_store v2: one packed array of every blob, in content order.
        rows[CS.SUPPORT_ARRAY] = dict(dtype='|u1', shape=[packed], nbytes=packed, chunks=(packed+width-1)//width)
    record = dict(schema=CS.SCHEMA, geometry_id=geometry_id, codec_metadata=metadata, supports=supports,
                  source_producer=producer, parent_snapshot=None, authority=CS.AUTHORITY)
    key = CS._digest(record)
    reference = dict(schema=CS.SCHEMA, snapshot_key=key, geometry_id=geometry_id, source_producer=producer,
                     array_bindings=_digests(rows))
    binding = Y._link_record(geometry_id, producer)
    link_key = sha256(N._json(binding)).hexdigest()
    largest = None
    if supports:
        content = max(supports, key=lambda c: (supports[c], c))
        size = supports[content]
        support = CS._support_record(content, size)
        largest = _manifest(CS._digest(support), {'bytes': dict(dtype='|u1', shape=[size], nbytes=size,
                                                                chunks=(size+width-1)//width)}, support)
    aliases = {Y.PREFIX+name: row for name, row in rows.items()}
    workflow = {'exterior_state': {'compact_mesh': reference}}
    if partition_root is not None:
        import partition_store as PS
        import partition_workflow_patch as PW
        aliases.update({PW.PREFIX+name: row for name, row in partition_root['descriptions'].items()})
        workflow['compact_partition'] = dict(schema=PS.SCHEMA, snapshot_key=partition_root['root_key'],
            partition_id=partition_root['partition_id'], source_producer=producer,
            array_bindings=_digests(partition_root['descriptions']))
    return dict(root_key=key, link_key=link_key, root=_manifest(key, rows, record),
        link=_manifest(link_key, rows, dict(binding=binding, mesh_reference=reference)),
        compact_store_inventory_bytes=len(_json(metadata))+len(_json(producer))+1024+160*len(supports),
        open_array_bytes=sum(row['nbytes'] for row in array_rows.values()), largest_support_snapshot=largest,
        supports=dict(distinct=len(supports), bytes=packed,
                      chunks=sum((s+width-1)//width for s in supports.values()),
                      packed_chunks=(packed+width-1)//width),
        workflow_aliases_lower_bound=dict(_manifest(CHUNK_PLACEHOLDER, aliases, workflow),
            scope='partition and mesh aliases plus both references only; ordinary workflow arrays/metadata excluded',
            includes_partition=partition_root is not None),
        source_producer_bytes=len(_json(producer)),
        producer_occurrences=dict(root=1, link=2, workflow_aliases_lower_bound=1+(partition_root is not None)))


def decision(partition, mesh):
    """Codec refusals/bounds indicate W2-X; store/consumer limits need a design decision."""
    exceeded = [dict(kind=report['kind'], **row) for report in (partition, mesh) if report
                for row in report.get('bounds', ()) if not row['within'] and row['scope'] != 'information']
    refusals = {report['kind']: report['refusal'] for report in (partition, mesh) if report and report.get('refusal')}
    codec = [row['kind']+': '+row['name'] for row in exceeded if row['scope'] == 'codec']
    return dict(partition_status=partition and partition.get('status'), mesh_status=mesh and mesh.get('status'),
        partition_schema_gate=partition and partition.get('schema_gate'), codec_refusals=refusals,
        codec_bounds_exceeded=codec,
        other_limits_exceeded=[row['kind']+': '+row['name'] for row in exceeded if row['scope'] != 'codec'],
        w2x_indicated=bool(refusals or codec),
        basis='measurement only; no bound, guard, tolerance or limit is changed by this census')


def read_blobs(store, key, refs, *, budget, check):
    """Named canonical record blobs from one pinned read snapshot, owned and charged first."""
    _imports()
    import numpy as np
    import historical_admission as H
    import native_transfer as N
    require(type(refs) is dict and refs, 'record blob bindings required')
    for name, ref in refs.items():
        require(type(ref) is dict and set(ref) == {'array', 'bytes', 'sha256'} and ref['array'] == name and
                type(ref['bytes']) is int and ref['bytes'] > 0, 'exact record blob binding required: '+name)
    owner = N._Allocation(budget, sum(ref['bytes'] for ref in refs.values())+512*len(refs)+4096,
                          category='codec-census-record-blobs')
    arrays = {}
    with store._read_scope(budget=budget):
        token = store.change_token()
        manifest = store._manifest(key)
        require(manifest is not None, 'head snapshot is missing')
        for name, ref in sorted(refs.items()):
            description = manifest['arrays'].get(name)
            require(type(description) is dict and description['dtype'] == '|u1' and description['shape'] == [ref['bytes']],
                    'record blob layout differs: '+name)
            owned = H._array_bytes(store, description, owner, budget, check, byte_type=N._RecordBytes)
            require(sha256(owned).hexdigest() == ref['sha256'], 'record blob bytes differ: '+name)
            arrays[name] = np.frombuffer(owned, dtype=np.uint8)
            owned = None
        check()
        require(store.change_token() == token and store._manifest(key) == manifest, 'store changed during census read')
    return arrays


def census_store(store, head_key, *, budget, limits, check, bounded=None, observe=_nothing,
                 source_producer=PRODUCER_PLACEHOLDER, result=None):
    """Both censuses from one ArrayStore head; reads only, one child budget per stage.

    The partition's decoded record and raw blob are released before validation,
    as in partition_workflow_patch.historical_partition; the mesh record lives
    through validation, as in spatial_workflow_patch.convert_mesh.
    """
    _imports()
    import materialise_endpoint as E
    from atlas_tectonics.resources import WorkBudget
    bounded = check if bounded is None else bounded
    result = {} if result is None else result
    head = store.metadata(head_key)
    require(type(head) is dict and head.get('key') == head_key, 'head workflow snapshot identity differs')
    header, exterior = head.get('differential_partition'), head.get('exterior_state')
    require(type(header) is dict and type(exterior) is dict and type(header.get('record_blobs')) is dict and
            type(exterior.get('record_blobs')) is dict and set(header['record_blobs']) == {'partition'} and
            set(exterior['record_blobs']) == {'state', 'mesh'}, 'legacy partition and spatial record blobs required')
    p_ref, s_refs = header['record_blobs']['partition'], exterior['record_blobs']
    result['head'] = dict(key=head_key, workflow_id=head.get('workflow_id'), partition_id=header.get('partition_id'),
        thermal_mesh_id=exterior.get('thermal_mesh_id'), mesh_blob_is_thermal_mesh_id=
        s_refs['mesh'].get('sha256') == exterior.get('thermal_mesh_id'),
        blobs={PARTITION_BLOB: p_ref, STATE_BLOB: s_refs['state'], MESH_BLOB: s_refs['mesh']})
    stage = WorkBudget(budget.max_bytes, parent=budget)
    census = PartitionCensus(expected_partition_id=header['partition_id'], budget=stage, limits=limits, check=bounded,
        descriptor=dict(sha256=p_ref['sha256'], nbytes=p_ref['bytes']), source_producer=source_producer, observe=observe)
    result['partition'] = census.report
    with _timed(census.report, 'read'):
        arrays = read_blobs(store, head_key, {PARTITION_BLOB: p_ref}, budget=stage, check=check)
    observe('partition-blob-read')
    clock = _clock()
    with E.partition_record(header, arrays, stage) as decoded:
        _elapsed(census.report, 'decode', clock)
        observe('partition-decoded')
        record = decoded.value
        require(record.get('partition_id') == header['partition_id'] and type(record.get('supports')) is list,
                'historical partition descriptor shape differs')
        census.pack({k: v for k, v in record.items() if k not in ('partition_id', 'supports')}, record['supports'])
        del record
    # The decoded graph and raw blob die before validation, as in the real route.
    del decoded, arrays
    gc.collect()
    observe('partition-decoded-released')
    result['partition'] = report = census.finish()
    root = report.get('manifest')
    partition_root = None if root is None else dict(root_key=root['root_key'], partition_id=header['partition_id'],
                                                     descriptions=root['descriptions'])
    del census
    gc.collect()
    report['logical_budget'] = _stage_statistics(stage)
    observe('partition-released')
    stage = WorkBudget(budget.max_bytes, parent=budget)
    result['mesh'] = report = dict(kind='mesh', status='STARTED')
    with _timed(report, 'read'):
        arrays = read_blobs(store, head_key, {STATE_BLOB: s_refs['state'], MESH_BLOB: s_refs['mesh']},
                            budget=stage, check=check)
    observe('mesh-blobs-read')
    clock = _clock()
    with E.spatial_records(exterior, arrays, stage) as decoded:
        _elapsed(report, 'decode', clock)
        observe('mesh-decoded')
        mesh = decoded.value['thermal_mesh']
        mesh_census(mesh, expected_geometry_id=s_refs['mesh']['sha256'], budget=stage, limits=limits,
                    check=bounded, source_producer=source_producer, observe=observe,
                    partition_root=partition_root, report=report)
        del mesh
    del decoded, arrays
    gc.collect()
    report['logical_budget'] = _stage_statistics(stage)
    observe('mesh-released')
    result['decision'] = decision(result['partition'], result['mesh'])
    return result


def _stage_statistics(budget):
    stats = budget.statistics()
    return dict(peak_reserved_bytes=stats['peak_reserved_bytes'], reserved_after_release=stats['reserved_bytes'],
                refusals=stats['refusals'], category_peaks=stats['category_peaks'])


def historical_endpoint(check=_nothing):
    """Head key and store configuration from the two pinned r9 receipts (JSON only)."""
    _imports()
    import historical_admission as H
    pins = dict(H._REVIEWED_ORIGINAL.evidence)
    reader = H._json_file(H._inside(H.HISTORICAL_ROOT, READER_RECEIPT), pins[READER_RECEIPT], check)
    producer = H._json_file(H._inside(H.HISTORICAL_ROOT, PRODUCER_RECEIPT), pins[PRODUCER_RECEIPT], check)
    recovered, completed = reader.get('recovered_endpoint'), producer.get('completed_endpoint')
    require(type(recovered) is dict and type(completed) is dict and
            all(recovered.get(k) == completed.get(k) for k in ENDPOINT_FIELDS) and
            reader.get('database_sha256') == H._REVIEWED_ORIGINAL.database_sha256,
            'pinned reader and producer endpoint records differ')
    return dict({k: recovered[k] for k in ENDPOINT_FIELDS},
                receipts={READER_RECEIPT: pins[READER_RECEIPT], PRODUCER_RECEIPT: pins[PRODUCER_RECEIPT]})


def start_gate(available):
    require(type(available) is int and available >= START_BYTES,
            'census requires at least 10 GiB available at start; available bytes: '+str(available))
    return dict(available_bytes=available, hard_gate_bytes=START_BYTES, operational_target_bytes=TARGET_BYTES,
                below_operational_target=available < TARGET_BYTES)


def _new_directory(output):
    output = Path(os.path.abspath(output))
    require(output.parent.is_dir(), 'existing parent directory required for the census output')
    output = output.parent.resolve(strict=True)/output.name
    require(not output.exists(), 'exclusive new census output directory required: '+str(output))
    return output


def _structure_source_pins():
    """Bind current selected adapters to the existing, fixed I runtime manifest."""
    require(_file_sha(RUNTIME_MANIFEST) == RUNTIME_MANIFEST_PIN, 'frozen I manifest changed')
    manifest = json.loads(RUNTIME_MANIFEST.read_text(encoding='utf8'))
    require(manifest.get('schema') == 'atlas.private.integrated-runtime.r1' and
            type(manifest.get('source_hashes')) is dict, 'frozen I source manifest shape differs')
    pins = {str(path.relative_to(T)).replace('\\', '/'): _file_sha(path) for path in STRUCTURE_SOURCES}
    pins[str(RUNTIME_MANIFEST.relative_to(T)).replace('\\', '/')] = RUNTIME_MANIFEST_PIN
    for name, digest in H_STRUCTURE_PINS.items():
        path = O.parents[1]/'heat-repair-20261007'/name
        require(_file_sha(path) == digest, 'historical mapping source changed: '+name)
        pins[str(path.relative_to(T)).replace('\\', '/')] = digest
    for name, digest in manifest['source_hashes'].items():
        path = I_SRC / name
        require(type(name) is str and not Path(name).is_absolute() and
                path.resolve().is_relative_to(I_SRC.resolve()) and type(digest) is str and
                len(digest) == 64 and not digest.strip('0123456789abcdef'), 'invalid frozen I source binding')
        pins[str(path.relative_to(T)).replace('\\', '/')] = digest
    return pins


def _verify_structure_sources(output, *, check=_nothing, loaded=False):
    """Refuse missing/drifted prepared inputs; do not refresh any recorded pin."""
    path = Path(output)/'prepare.json'
    require(path.is_file() and path.stat().st_size <= 1 << 20, 'bounded prepared source bindings required')
    plan = json.loads(path.read_text(encoding='utf8'))
    require(plan.get('schema') == PREPARE_SCHEMA and plan.get('structure_only') is True and
            type(plan.get('sources')) is dict, 'structure-only prepared source bindings required')
    expected, prepared = _structure_source_pins(), plan['sources']
    require(set(prepared) == set(expected), 'prepared selected-source set differs')
    for name, digest in prepared.items():
        check()
        require(digest == expected[name] and _file_sha(T/name) == digest,
                'prepared source changed: '+name)
    if loaded:
        for name, module in tuple(sys.modules.items()):
            if name != 'atlas_tectonics' and not name.startswith('atlas_tectonics.'):
                continue
            filename = getattr(module, '__file__', None)
            require(filename is not None, 'runtime module lacks a source identity: '+name)
            source = Path(filename).resolve()
            require(source.is_relative_to(I_SRC.resolve()), 'runtime module outside frozen I: '+name)
            relative = str(source.relative_to(T)).replace('\\', '/')
            require(relative in prepared and _file_sha(source) == prepared[relative],
                    'loaded runtime source not prepared: '+name)
    return dict(files=len(prepared), frozen_runtime_manifest_sha256=RUNTIME_MANIFEST_PIN,
                prepared_source_pins_sha256=sha256(json.dumps(prepared, sort_keys=True).encode()).hexdigest())


def _plan(output, python=None, *, structure_only=False):
    _imports()
    import historical_admission as H
    import resource_guard_patch as RG
    out = _new_directory(output)
    python = Path(python or sys.executable).resolve()
    require(python == PYTHON.resolve(), 'the task .r44-env interpreter is required')
    raw = {}
    for name, path in ((RG.GUARD_NAME, H._inside(H.HISTORICAL_ROOT, RG.GUARD_NAME)),
                       (RG.JOB_NAME, H._inside(H.HISTORICAL_ROOT, RG.JOB_NAME)), (RG.DIAGNOSTICS_NAME, DIAGNOSTICS)):
        raw[name] = Path(path).read_bytes()
    files = RG.successor_files(raw[RG.GUARD_NAME], raw[RG.JOB_NAME], raw[RG.DIAGNOSTICS_NAME])
    require(sha256(files[RG.GUARD_NAME]).hexdigest() == RG.SUCCESSOR_PIN == H.GUARD_PIN,
            'successor guard differs from the reviewed pin')
    if not structure_only:
        tree = ast.parse((R/'materialise_endpoint.py').read_text(encoding='utf8'))
        decoders = {node.name: [a.arg for a in node.args.args] for node in tree.body if isinstance(node, ast.FunctionDef)}
        require(decoders.get('partition_record') == ['header', 'arrays', 'budget'] and
                decoders.get('spatial_records', [])[:3] == ['header', 'arrays', 'budget'],
                'materialise_endpoint legacy record decoders changed; review the census before launch')
    guard = out/'guard'/RG.GUARD_NAME
    command = [str(python), '-B', str(guard), '--launch', '--output', str(out/'run.json'), '--',
               str(python), '-B', str(Path(__file__).resolve()), '--workload', '--output', str(out)]
    if structure_only:
        command.append('--structure-only')
    original = H.HISTORICAL_ROOT/H._REVIEWED_ORIGINAL.database_name
    import psutil
    available = psutil.virtual_memory().available
    plan = dict(schema=PREPARE_SCHEMA, status='PREPARED_COMMAND_ONLY_NOT_LAUNCHED', created_utc=_now(),
        command=command, cwd=str(out), environment=LAUNCH_ENV, output_directory=str(out),
        run_json=str(out/'run.json'), census_json=str(out/('structure-census.json' if structure_only else 'codec-census.json')),
        cancel_file=str(out/'run.cancel'), structure_only=structure_only,
        guard=dict(directory=str(out/'guard'), files={n: sha256(b).hexdigest() for n, b in files.items()},
                   successor_pin=RG.SUCCESSOR_PIN, historical_input_pin=RG.GUARD_PIN),
        limits=dict(rss_bytes=RSS_BYTES, free_floor_bytes=FREE_BYTES, start_available_bytes=START_BYTES,
                    logical_budget_bytes=LOGICAL_BYTES, operational_target_bytes=TARGET_BYTES),
        available_bytes_now=available, start_gate_passes_now=available >= START_BYTES,
        original=dict(path=str(original), pinned_sha256=H._REVIEWED_ORIGINAL.database_sha256,
                      opened='never by --prepare; mode=ro plus query_only by the workload'),
        sources=_structure_source_pins() if structure_only else
            {str(path.relative_to(T)).replace('\\', '/'): _file_sha(path) for path in SOURCES},
        writes='nothing', production_acceptance=False)
    return plan, files


def prepare(output=DEFAULT_OUTPUT, python=None, *, structure_only=False):
    """Exact guarded command and its pinned inputs; writes nothing, opens no database."""
    return _plan(output, python, structure_only=structure_only)[0]


def launch(output=DEFAULT_OUTPUT, python=None, available=None, *, structure_only=False):
    plan, files = _plan(output, python, structure_only=structure_only)
    require(not any(os.environ.get(name) for name in REFUSED_ENV), 'import-path or startup variables must be unset')
    if available is None:
        import psutil
        available = lambda: psutil.virtual_memory().available
    plan['start_gate'] = start_gate(available())
    out = Path(plan['output_directory'])
    out.mkdir()
    guard = out/'guard'
    guard.mkdir()
    for name, raw in sorted(files.items()):
        with (guard/name).open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        require(_file_sha(guard/name) == sha256(raw).hexdigest(), 'written guard file differs: '+name)
    plan.update(status='LAUNCHED', writes='this new run directory only')
    with (out/'prepare.json').open('x', encoding='utf8') as stream:
        json.dump(plan, stream, indent=2, sort_keys=True)
    print(json.dumps(dict(status='LAUNCHING', command=plan['command'], cancel_file=plan['cancel_file'])), flush=True)
    code = subprocess.call(plan['command'], env=dict(os.environ, **LAUNCH_ENV), cwd=str(out))
    print(json.dumps(dict(status='GUARD_EXITED', exit_code=code, run_json=plan['run_json'],
                          census_json=plan['census_json'])), flush=True)
    return code


def _identity(path):
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _sidecars(path):
    return [suffix for suffix in ('-wal', '-journal', '-shm') if Path(str(path)+suffix).exists()]


def _observer(guard, record, budget):
    import psutil
    process, started = psutil.Process(), time.perf_counter()
    rows = record.setdefault('observations', [])

    def observe(label):
        info, stats = process.memory_info(), budget.statistics()
        rows.append(dict(label=label, seconds=round(time.perf_counter()-started, 3), rss_bytes=info.rss,
            peak_wset_bytes=getattr(info, 'peak_wset', None), private_bytes=getattr(info, 'private', None),
            available_bytes=psutil.virtual_memory().available, logical_reserved_bytes=stats['reserved_bytes'],
            logical_peak_bytes=stats['peak_reserved_bytes']))
        guard.phase(label)  # forced check; the guard's per-phase RSS peaks key on this label
    return observe


def _selected_census(store, endpoint, *, budget, limits, check, observe, result,
                     structure_only=False, scratch_directory=None):
    if structure_only:
        import structure_census as S
        return S.census_store(store, endpoint, budget=budget, limits=limits, check=check,
                              observe=observe, result=result, scratch_directory=scratch_directory)
    import partition_workflow_patch as PW
    return census_store(store, endpoint['head_key'], budget=budget, limits=limits, check=check,
                        bounded=PW.throttled(check), observe=observe, result=result)


def _guarded_census(guard, record, *, structure_only=False, output=None):
    import psutil
    import historical_admission as H
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import execution_mode
    from atlas_tectonics.storage import StoreLimits, Compression

    def check():
        guard.check(force=True)
    guard.budget = budget = WorkBudget(LOGICAL_BYTES)
    H.guardian_fence(guard, budget=budget, check=check)
    require(guard._control['limits'] == dict(rss_bytes=RSS_BYTES, free_floor_bytes=FREE_BYTES),
            'exact retained 12 GiB / 1 GiB guard limits required')
    record['memory_at_start'] = start_gate(psutil.virtual_memory().available)
    require(execution_mode() == 'strict', 'strict execution mode required; manifests are projected for it')
    record.update(guard_limits=dict(rss_bytes=RSS_BYTES, free_floor_bytes=FREE_BYTES, start_available_bytes=START_BYTES,
        logical_budget_bytes=LOGICAL_BYTES), execution_mode='strict',
        interpreter=dict(executable=sys.executable, version=sys.version, hash_seed=os.environ.get('PYTHONHASHSEED'),
                         dont_write_bytecode=sys.dont_write_bytecode))
    observe, census = _observer(guard, record, budget), record['census']
    observe('authenticate-original-before')
    original = H._inside(H.HISTORICAL_ROOT, H._REVIEWED_ORIGINAL.database_name)
    before = _identity(original)
    require(not _sidecars(original), 'original database must be closed without SQLite sidecars')
    pinned = H._REVIEWED_ORIGINAL.database_sha256
    census['original'] = dict(path=str(original), pinned_sha256=pinned)
    try:
        census['original']['sha256_before'] = H._hash_file(original, H.MAX_DATABASE, check)
        require(census['original']['sha256_before'] == pinned, 'original database differs from its pin; nothing measured')
        census['endpoint'] = endpoint = historical_endpoint(check)
        limits = StoreLimits(**endpoint['store_limits'])
        compression = Compression(**endpoint['store_compression'])
        observe('open-original-readonly')
        with H.open_original_readonly(limits=limits, compression=compression, budget=budget) as store:
            require(getattr(store, '_historical_readonly', None) is H._READONLY and
                    store._db.execute('PRAGMA query_only').fetchone() == (1,), 'census requires the readonly ORIGINAL view')
            token = store.change_token()
            try:
                _selected_census(store, endpoint, budget=budget, limits=limits, check=check, observe=observe,
                    result=census, structure_only=structure_only,
                    scratch_directory=None if output is None else Path(output)/'structure-scratch')
            finally:
                token_in_flight = sys.exc_info()[0] is not None
                try:
                    census['store_token_unchanged'] = store.change_token() == token
                except BaseException as error:
                    census['store_token_unchanged'] = None
                    census['store_token_error'] = dict(type=type(error).__name__, message=str(error)[:4096])
                    if not token_in_flight:
                        raise
    finally:
        # Retain the workload's primary exception if final verification also fails.
        # Guard checks stay active: cancellation may leave verification INCOMPLETE.
        in_flight = sys.exc_info()[0] is not None
        try:
            census['original'].update(identity_unchanged=_identity(original) == before,
                                      sidecars_after=_sidecars(original), verification_status='INCOMPLETE')
            observe('authenticate-original-after')
            census['original']['sha256_after'] = H._hash_file(original, H.MAX_DATABASE, check)
            census['original']['unchanged'] = (census['original']['sha256_after'] == pinned and
                census['original']['identity_unchanged'] and not census['original']['sidecars_after'])
            require(census['original']['unchanged'] and census.get('store_token_unchanged', True),
                    'original database or store token changed during the census')
            census['original']['verification_status'] = 'PASS'
        except BaseException as error:
            census['original']['verification_error'] = dict(type=type(error).__name__, message=str(error)[:4096])
            if not in_flight:
                raise
            record.setdefault('errors', []).append(dict(type='OriginalVerificationFailed', message=str(error)[:4096]))


def _loaded_sources(*roots):
    loaded, historical = {}, []
    for module in list(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if not name or not name.endswith('.py'):
            continue
        path = Path(name).resolve()
        if path.is_relative_to(O.parents[1]/'heat-repair-20261007'):
            historical.append(str(path))
        elif any(path.is_relative_to(root) for root in roots):
            loaded[str(path.relative_to(T)).replace('\\', '/')] = _file_sha(path)
    return dict(sorted(loaded.items())), sorted(historical)


def workload(output, *, structure_only=False):
    require(sys.dont_write_bytecode, 'run with -B to preserve frozen sources')
    out = Path(output).resolve(strict=True)
    run, guard_dir = out/'run.json', out/'guard'
    _imports(guard_dir)
    import resource_guard_patch as RG
    for name, pin in ((RG.GUARD_NAME, RG.SUCCESSOR_PIN), (RG.JOB_NAME, RG.JOB_PIN),
                      (RG.DIAGNOSTICS_NAME, RG.DIAGNOSTICS_PIN)):
        require(_file_sha(guard_dir/name) == pin, 'reviewed successor guard set differs: '+name)
    record = dict(schema=STRUCTURE_RUN_SCHEMA if structure_only else RUN_SCHEMA, status='STARTED', pid=os.getpid(),
                  started_utc=_now(), errors=[], structure_only=structure_only,
                  production_acceptance=False, census={}, scope='measurement only; no scientific acceptance')
    with run.open('x', encoding='utf8') as stream:
        json.dump(record, stream)
    G = importlib.import_module(Path(RG.GUARD_NAME).stem)
    require(Path(G.__file__).resolve() == (guard_dir/RG.GUARD_NAME).resolve(), 'guard imported from another path')

    def save():
        G._write(run, record)
    guard = None
    try:
        guard = G.ContinuationGuard(run, record, save)
        if structure_only:
            record['prepared_sources_before'] = _verify_structure_sources(out, check=lambda: guard.check(force=True), loaded=True)
        _guarded_census(guard, record, structure_only=structure_only, output=out)
        record['status'] = 'CENSUS_COMPLETE'
    except BaseException as error:
        record['status'] = 'INTERRUPTED' if guard is not None and isinstance(error, CancelledError) else 'FAILED'
        record['errors'].append(dict(type=type(error).__name__, message=str(error)[:4096]))
    finally:
        gc.collect()
        if structure_only:
            try:
                record['prepared_sources_after'] = _verify_structure_sources(out, loaded=True)
            except BaseException as error:
                record['errors'].append(dict(type='PreparedSourceVerificationFailed', message=str(error)[:4096]))
        budget = getattr(guard, 'budget', None)
        if budget is not None:
            record['final_reserved_bytes'] = budget.reserved_bytes
            record['logical_budget_final'] = _stage_statistics(budget)
            if budget.reserved_bytes:
                record['errors'].append(dict(type='RetainedReservations', message=str(budget.reserved_bytes)))
        record['loaded_sources'], record['historical_modules_loaded'] = _loaded_sources(R, I_SRC, guard_dir)
        if record['historical_modules_loaded']:
            record['errors'].append(dict(type='HistoricalModuleLoaded', message=str(record['historical_modules_loaded'])))
        try:
            if guard is not None:
                guard.check(force=True)
                guard.close()
        except BaseException as error:
            record['errors'].append(dict(type=type(error).__name__, message=str(error)[:4096]))
        if record['errors'] and record['status'] == 'CENSUS_COMPLETE':
            record['status'] = 'FAILED'
        record['finished_utc'] = _now()
        try:
            output = dict(schema=STRUCTURE_SCHEMA if structure_only else SCHEMA, status=record['status'],
                errors=record['errors'], created_utc=record['finished_utc'], structure_only=structure_only,
                run_json=str(run), census=record['census'], observations=record.get('observations', []),
                guard=dict(resources=record.get('resources'), supervisor=record.get('supervisor')),
                memory_at_start=record.get('memory_at_start'), guard_limits=record.get('guard_limits'),
                logical_budget_final=record.get('logical_budget_final'), loaded_sources=record['loaded_sources'],
                production_acceptance=False, scope='WP0a read-only structure census; no codec conversion or IV2' if structure_only
                    else 'codec census only; refusals are reported, never repaired here')
            if structure_only:
                output['prepared_sources_before'] = record.get('prepared_sources_before')
                output['prepared_sources_after'] = record.get('prepared_sources_after')
            with (out/('structure-census.json' if structure_only else 'codec-census.json')).open('x', encoding='utf8') as stream:
                json.dump(output, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException as error:
            record['errors'].append(dict(type=type(error).__name__, message=str(error)[:4096]))
        save()
    return 0 if not record['errors'] else 1


# ---------------------------------------------------------------------------
# WP0b: census handlers for the frozen compact physical formats (Step 10).
#
# Exact and read-only. Every read goes through the verified sealed paths:
# IntervalStoreSet.open_catalog, SegmentBackend.open (which authenticates the
# complete binding tree once) and digest-checked index pages. Domain handlers
# walk the binding index and read only the small columns they need; no record
# is decoded to legacy JSON, CompactRecord.from_segment is never required and
# referenced bytes are never counted again as storage. Three counts are kept
# apart everywhere (COUNT_DEFINITIONS): logical mentions, unique content and
# physical stored bytes. Array classes are keyed '<record_schema>/<column>'.
# ---------------------------------------------------------------------------
COMPACT_SCHEMA = 'atlas.private.wp0b-compact-census.v1'
COMPACT_SOURCES = (C/'compact_contracts.py', C/'segment_store.py', C/'interval_store_set.py', C/'interval_catalog.py',
    C/'content_cache.py', C/'record_tables.py', C/'record_views.py', C/'compact_store.py', C/'mesh_tables.py',
    C/'partition_v2.py', C/'support_source.py', C/'heat_ledger_tables.py', C/'private_heat_snapshot_store_r4.py',
    HERE/'probe_codec_census.py')
COUNT_DEFINITIONS = {
    'logical': 'every reference as it is mentioned: binding leaves (chunk references) with the typed bytes they '
               'name, DAG/pool references from the node table, support entries, SegmentRef mentions and index-page '
               'visits; repeated or shared content counts every time it is mentioned',
    'unique': 'content deduplicated by its content hash across the whole census: native typed chunk ID, support ID, '
              'hash-consed DAG node or interned pool row, content-addressed page/root key; each counted once, '
              'attributed to the first class that mentions it',
    'physical': 'bytes actually stored in the interval files after the codec: chunk payload and descriptor per '
                'stored row, manifest bodies per stored snapshot, file bytes; a mention of content owned by another '
                'interval, record or class adds no physical bytes'}
COMPACT_BLOCK = 65536
COMPACT_PINS = 4                 # borrowed interval handles kept pinned at once (of the eight allowed)
COMPACT_COLUMN_BLOCKS = 32       # owned 64 KiB column blocks kept for random access (2 MiB)
COMPACT_INDEX_ENTRY = 320        # booked bytes per tracked chunk/snapshot identity
COMPACT_RUN_BYTES = 1 << 30
_KIND_NAMES = ('null', 'bool', 'integer', 'float', 'text', 'ident', 'hex', 'array', 'object', 'rational')


def _counts():
    return {'logical': {'leaves': 0, 'mentions': 0, 'bytes': 0, 'cross_interval_mentions': 0,
                        'cross_interval_bytes': 0},
            'unique': {'chunks': 0, 'bytes': 0, 'repeated_within_class': 0, 'shared_with_other_class': 0},
            'physical': {'rows': 0, 'payload_bytes': 0, 'descriptor_bytes': 0, 'codecs': {}}}


def _merge_counts(target, source):
    for part in ('logical', 'unique', 'physical'):
        for name, value in source[part].items():
            if name == 'codecs':
                for codec, count in value.items():
                    target[part]['codecs'][codec] = target[part]['codecs'].get(codec, 0)+count
            else:
                target[part][name] += value


def _codec_family(label):
    return label.split(':', 1)[0]


class _Columns:
    """Random access to authenticated record columns through owned 64 KiB reads.

    At most COMPACT_COLUMN_BLOCKS owned blocks stay held (each charged to the
    retained scope by SegmentView.read); sequential scans reuse one block.
    """

    def __init__(self, view, descriptors, check):
        import numpy as np
        self.view, self.check, self.np = view, check, np
        self.columns = {name: (np.dtype(row['dtype']), math.prod(row['shape'])) for name, row in descriptors.items()}
        self.blocks = {}   # insertion order is the LRU order

    def count(self, name):
        return self.columns[name][1]

    def _block(self, name, block):
        key = (name, block)
        held = self.blocks.pop(key, None)
        if held is not None:
            self.blocks[key] = held
            return held[1]
        self.check()
        dtype, count = self.columns[name]
        per = COMPACT_BLOCK // dtype.itemsize
        start = block*per
        owned = self.view.read(name, start, min(count, start+per), max_owned_bytes=2*COMPACT_BLOCK)
        values = self.np.frombuffer(owned.value, dtype=dtype)
        self.blocks[key] = (owned, values)
        while len(self.blocks) > COMPACT_COLUMN_BLOCKS:
            old, _values = self.blocks.pop(next(iter(self.blocks)))
            del _values
            old.close()
        return values

    def value(self, name, index):
        dtype, count = self.columns[name]
        require(type(index) is int and 0 <= index < count, 'column index outside authenticated extent: '+name)
        per = COMPACT_BLOCK // dtype.itemsize
        return int(self._block(name, index // per)[index % per])

    def raw(self, name, start, stop):
        """Bytes of a u1 column range (at most one native block per call)."""
        dtype, count = self.columns[name]
        require(dtype.itemsize == 1 and 0 <= start <= stop <= count and stop-start <= COMPACT_BLOCK,
                'bounded u1 column range required: '+name)
        if stop == start:
            return b''
        parts = []
        for block in range(start // COMPACT_BLOCK, (stop-1) // COMPACT_BLOCK+1):
            values = self._block(name, block)
            lo, hi = max(start, block*COMPACT_BLOCK), min(stop, (block+1)*COMPACT_BLOCK)
            parts.append(values[lo-block*COMPACT_BLOCK:hi-block*COMPACT_BLOCK].tobytes())
        return b''.join(parts)

    def close(self):
        while self.blocks:
            _, (owned, _values) = self.blocks.popitem()
            del _values
            owned.close()


class CompactCensus:
    """Logical/unique/physical census of one opened catalog (IntervalStoreSet).

    Construct with an IntervalStoreSet opened by open_catalog; call ref(),
    heat_r4() or catalog_heads(), then report(). close() releases every pin
    and held column block; the store set stays owned by the caller.
    """

    def __init__(self, stores, *, check=_nothing, verify_payload=True):
        _imports()
        from interval_store_set import IntervalStoreSet
        require(type(stores) is IntervalStoreSet and stores.head is not None,
                'an opened, promoted interval catalog is required')
        self.stores, self.scope, self.check, self.verify_payload = stores, stores.scope, check, verify_payload
        self.workflow_id = stores.workflow_id
        self.classes = {}        # '<record_schema>/<column>' -> three counts
        self.chunks = {}         # chunk_id -> [first class key, owner intervals]
        self.snapshots = {}      # (interval, snapshot key) -> [kind, body bytes, mentions]
        self.segments = {}       # (interval, root key) -> segment summary (counted once)
        self.ref_mentions = {}   # (interval, root key) -> SegmentRef mention row
        self.records = []        # domain reports, census order
        self.partition_supports = {}  # partition root key -> {support id: canonical bytes}
        self.support_totals = {'logical': {'mentions': 0, 'bytes': 0}, 'unique': {'supports': 0, 'bytes': 0},
                               'seen': set()}
        self.pins = {}
        self.limit = None

    # ----- verified physical rows -------------------------------------------------
    def _reader(self, interval):
        held = self.pins.get(interval)
        if held is None:
            if len(self.pins) >= COMPACT_PINS:
                for old in list(self.pins):
                    self.pins.pop(old).close()
            held = self.pins[interval] = self.stores.borrow_handle(interval)
        reader = held.value
        reader._check_identity()
        return reader

    def _track(self):
        require(self.limit is None or len(self.chunks)+len(self.snapshots) < self.limit,
                'census identity index exceeds the catalog row bound')

    def _chunk_row(self, interval, chunk_id, descriptor):
        """Stored row of one referenced chunk: codec label, payload and descriptor bytes."""
        reader = self._reader(interval)
        if self.verify_payload:
            row = reader._db.execute('SELECT descriptor,codec,stored_sha,payload FROM chunks WHERE id=?',
                                     (chunk_id,)).fetchone()
            require(row is not None, 'referenced chunk row missing in interval '+str(interval))
            desc, codec, stored, payload = row
            require(desc == descriptor and sha256(desc+b'\0'+codec.encode()+b'\0'+payload).hexdigest() == stored,
                    'stored chunk row does not authenticate')
            result = codec, len(payload), len(desc)
            del payload
        else:
            row = reader._db.execute('SELECT codec,length(payload),length(descriptor) FROM chunks WHERE id=?',
                                     (chunk_id,)).fetchone()
            require(row is not None, 'referenced chunk row missing in interval '+str(interval))
            result = row
        reader._check_identity()
        return result

    def _snapshot(self, locator, kind):
        key = (locator.interval, locator.snapshot_key)
        row = self.snapshots.get(key)
        if row is not None:
            row[2] += 1
            return False, row[1]
        self._track()
        reader = self._reader(locator.interval)
        found = reader._db.execute('SELECT length(body) FROM snapshots WHERE id=?', (locator.snapshot_key,)).fetchone()
        require(found is not None, 'referenced manifest missing in interval '+str(locator.interval))
        reader._check_identity()
        self.snapshots[key] = [kind, found[0], 1]
        return True, found[0]

    # ----- generic segment (binding index, Merkle pages, chunks) ------------------
    def _open(self, ref, role):
        """(view, summary, first) for one SegmentRef; the view is authenticated by open()."""
        from compact_contracts import SegmentRef
        from segment_store import SegmentBackend
        require(type(ref) is SegmentRef and ref.root_key.workflow_id == self.workflow_id,
                'same-workflow SegmentRef required')
        self.check()
        key = (ref.root_key.interval, ref.root_key.snapshot_key)
        mention = self.ref_mentions.setdefault(key, {'record_schema': ref.identity.record_schema,
                                                     'interval': ref.root_key.interval, 'mentions': 0, 'roles': []})
        mention['mentions'] += 1
        if role not in mention['roles'] and len(mention['roles']) < 16:
            mention['roles'].append(role)
        if key in self.segments:
            return None, self.segments[key], False
        view = SegmentBackend().open(self.stores, ref, scope=self.scope)
        try:
            summary = self.segments[key] = self._walk(view, ref, role)
        except BaseException:
            view.close()
            raise
        return view, summary, True

    def _walk(self, view, ref, role):
        import numpy as np
        from compact_contracts import SnapshotLocator
        root = view._owner.value
        schema, requester = ref.identity.record_schema, ref.root_key.interval
        _, root_bytes = self._snapshot(ref.root_key, 'segment-root')
        pages = {'mentions': 0, 'unique': 0, 'leaf_pages': 0, 'branch_pages': 0, 'physical_bytes': 0, 'depth': 0}
        columns = {}
        stack = [(root['index'], 1)]
        while stack:
            node, depth = stack.pop()
            self.check()
            owner = view._load_page(node)   # digest-checked against its authenticated parent
            try:
                page = owner.value
                first, size = self._snapshot(SnapshotLocator.from_wire(node['locator']), 'binding-page')
                pages['mentions'] += 1
                pages['depth'] = max(pages['depth'], depth)
                pages['leaf_pages' if page['kind'] == 'leaves' else 'branch_pages'] += 1
                if first:
                    pages['unique'] += 1
                    pages['physical_bytes'] += size
                if page['kind'] == 'leaves':
                    for entry in page['entries']:
                        body = entry['content']
                        local = columns.setdefault(body['name'], {**_counts(), 'dtype': body['dtype'],
                                                                  'shape': list(body['shape'])})
                        self._leaf(schema+'/'+body['name'], entry, requester, local, np)
                else:
                    stack.extend((child, depth+1) for child in reversed(page['entries']))
            finally:
                owner.close()
        totals = _counts()
        for row in columns.values():
            _merge_counts(totals, row)
        require(len(columns) == ref.array_bindings.count and totals['logical']['bytes'] == ref.logical_bytes,
                'census walk differs from the authenticated SegmentRef inventory')
        return {'role': role, 'interval': requester, 'root_key': ref.root_key.snapshot_key, 'record_schema': schema,
                'identity': ref.identity.to_wire(), 'representation_profile': root['representation_profile'],
                'producer': root['producer'], 'arrays': ref.array_bindings.count, 'logical_bytes': ref.logical_bytes,
                'merkle_root': ref.merkle_root, 'root_manifest_bytes': root_bytes,
                'root_metadata_bytes': len(canonical_json(root['metadata'])), 'index': pages,
                'columns': columns, 'totals': totals}

    def _leaf(self, key, entry, requester, local, np):
        body = entry['content']
        target = self.classes.setdefault(key, {**_counts(), 'dtype': body['dtype']})
        for row in (target, local):
            row['logical']['leaves'] += 1
        if not body['count']:
            return
        size = body['count']*np.dtype(body['dtype']).itemsize
        owner, chunk = entry['owner'], body['chunk_id']
        for row in (target, local):
            row['logical']['mentions'] += 1
            row['logical']['bytes'] += size
            if owner != requester:
                row['logical']['cross_interval_mentions'] += 1
                row['logical']['cross_interval_bytes'] += size
        seen = self.chunks.get(chunk)
        if seen is None:
            self._track()
            seen = self.chunks[chunk] = [key, []]
            for row in (target, local):
                row['unique']['chunks'] += 1
                row['unique']['bytes'] += size
        else:
            part = 'repeated_within_class' if seen[0] == key else 'shared_with_other_class'
            for row in (target, local):
                row['unique'][part] += 1
        if owner not in seen[1]:
            # One stored row per owning interval file: the physical count.
            codec, payload, descriptor = self._chunk_row(owner, chunk, canonical_json(entry['descriptor']))
            seen[1].append(owner)
            family = _codec_family(codec)
            for row in (target, local):
                row['physical']['rows'] += 1
                row['physical']['payload_bytes'] += payload
                row['physical']['descriptor_bytes'] += descriptor
                row['physical']['codecs'][family] = row['physical']['codecs'].get(family, 0)+1

    # ----- dispatch -----------------------------------------------------------------
    def ref(self, ref, *, role='explicit'):
        """Census one SegmentRef with the handler its authenticated root selects."""
        import compact_store as CS
        import partition_v2 as PV
        import private_heat_snapshot_store_r4 as S
        import record_tables as RT
        from segment_store import parse
        view, summary, first = self._open(ref, role)
        if not first:
            return {'handler': 'already-counted', 'root_key': summary['root_key'], 'role': role}
        try:
            profile, schema = summary['representation_profile'], ref.identity.record_schema
            with view.metadata_bytes() as held:
                raw = held.value
            metadata = parse(raw)
            if profile == PV.PROFILE and schema == PV.DESCRIPTOR:
                report = self._record(view, ref, summary, raw, domain='partition-v2')
            elif profile == CS.V3_PROFILE:
                report = self._mesh_v3(view, ref, summary, metadata)
            elif profile == S.PROFILE and schema == S.FIELDS_SCHEMA:
                report = self._heat_fields(summary, metadata)
            elif type(metadata) is dict and metadata.get('schema') == RT.SCHEMA:
                report = self._record(view, ref, summary, raw, domain='heat-ledger-r4' if schema == S.LEDGER_SCHEMA
                                      else 'record-tables')
            else:
                # Chunks, pages and roots are still counted exactly; no domain mentions exist to count.
                report = {'handler': 'segment', 'domain': None,
                          'metadata_schema': metadata.get('schema') if type(metadata) is dict else None}
        finally:
            view.close()
        report.update(root_key=summary['root_key'], role=role, record_schema=ref.identity.record_schema,
                      interval=ref.root_key.interval)
        self.records.append(report)
        return report

    # ----- record_tables (generic DAG columns) ----------------------------------------
    def _record(self, view, ref, summary, raw, *, domain):
        import record_tables as RT
        from record_views import _metadata
        meta, identity = _metadata(raw)     # explicit physical-schema dispatch; unknown features refuse
        require(identity == ref.identity, 'record metadata identity differs from its SegmentRef')
        for name, descriptor in meta['arrays'].items():
            column = summary['columns'].get(name)
            require(column is not None and column['dtype'] == descriptor['dtype'] and
                    column['shape'] == descriptor['shape'], 'record column descriptor differs: '+name)
        shape = {name: row['shape'][0] for name, row in meta['arrays'].items()}
        kinds = self._stream(view, meta, 'node.kind', 'bincount')
        largest_int = self._stream(view, meta, 'int.offset', 'max-diff')
        # Dyadic integers store only an exponent (int.mode 1): magnitude 2**e is e//8+1 binary bytes.
        largest_exponent = self._stream(view, meta, 'int.exponent', 'max')
        largest_token = self._stream(view, meta, 'token.offset', 'max-diff')
        n, edges, pairs = shape['node.kind'], shape['edge.child'], shape['q.numerator']
        by_kind = dict(zip(_KIND_NAMES, kinds, strict=True))
        columns = summary['columns']

        def physical(*names):
            return sum(columns[name]['physical']['payload_bytes'] for name in names)

        def stored(*names):
            return sum(columns[name]['logical']['bytes'] for name in names)
        node_columns = ('node.kind', 'node.payload', 'node.shape', 'node.length', 'node.charge', 'node.offset')
        int_columns = ('int.offset', 'int.bytes', 'int.sign', 'int.mode', 'int.exponent')
        pools = {
            'node': {'logical_references': edges+2*pairs+1, 'unique_rows': n, 'ceiling': RT.MAX_ITEMS,
                     'column_bytes': stored(*node_columns), 'physical_bytes': physical(*node_columns)},
            'edge': {'rows': edges, 'ceiling': 4*RT.MAX_ITEMS, 'column_bytes': stored('edge.child'),
                     'physical_bytes': physical('edge.child')},
            'token': {'logical_references': by_kind['text']+shape['shape.key'], 'unique_rows': shape['token.offset']-1,
                      'unique_bytes': shape['token.bytes'], 'largest_bytes': largest_token,
                      'largest_ceiling': RT.MAX_TOKEN_BYTES, 'ceiling': RT.MAX_ITEMS,
                      'physical_bytes': physical('token.offset', 'token.bytes')},
            'integer': {'logical_references': by_kind['integer']+by_kind['hex'], 'unique_rows': shape['int.sign'],
                        'unique_bytes': shape['int.bytes'], 'largest_stored_magnitude_bytes': largest_int,
                        'largest_dyadic_exponent': largest_exponent,
                        'largest_magnitude_bytes': max(largest_int, largest_exponent//8+1 if largest_exponent else 0),
                        'largest_ceiling': RT.MAX_INTEGER_BYTES, 'ceiling': RT.MAX_ITEMS,
                        'physical_bytes': physical(*int_columns)},
            'id': {'logical_references': by_kind['ident'], 'unique_rows': shape['id.bytes']//32,
                   'unique_bytes': shape['id.bytes'], 'ceiling': RT.MAX_ITEMS, 'physical_bytes': physical('id.bytes')},
            'float': {'logical_references': by_kind['float'], 'unique_rows': shape['float.value'],
                      'ceiling': RT.MAX_ITEMS, 'physical_bytes': physical('float.value')},
            'rational': {'logical_references': by_kind['rational'], 'unique_rows': pairs, 'ceiling': RT.MAX_ITEMS,
                         'physical_bytes': physical('q.numerator', 'q.denominator')},
            'shape': {'logical_references': by_kind['object'], 'unique_rows': shape['shape.offset']-1,
                      'keys': shape['shape.key'], 'ceiling': RT.MAX_ITEMS,
                      'physical_bytes': physical('shape.offset', 'shape.key')}}
        report = {'handler': 'record-tables', 'domain': domain, 'record_metadata_bytes': len(raw),
                  'canonical_bytes': identity.canonical_bytes, 'column_bytes': summary['logical_bytes'],
                  'node_kinds': by_kind, 'pools': pools,
                  'pool_note': 'pool rows are interned by exact value at pack time and nodes are hash-consed; '
                               'unique_rows are the authenticated row counts, not re-hashed here'}
        if domain == 'partition-v2':
            report['partition'] = self._partition(view, meta, ref)
        return report

    def _stream(self, view, meta, name, mode):
        """One authenticated column pass (digest equals the record metadata)."""
        import numpy as np
        descriptor = meta['arrays'][name]
        dtype = np.dtype(descriptor['dtype'])
        digest = sha256()
        counts = np.zeros(len(_KIND_NAMES), dtype=np.int64)
        largest, previous = 0, None
        with view.iter(name, block_bytes=COMPACT_BLOCK, max_owned_bytes=2*COMPACT_BLOCK) as stream:
            for block in stream:
                with block:
                    self.check()
                    digest.update(block.value)
                    values = np.frombuffer(block.value, dtype=dtype)
                    if mode == 'bincount':
                        require(not len(values) or int(values.max()) < len(_KIND_NAMES), 'unknown node tag')
                        counts += np.bincount(values, minlength=len(_KIND_NAMES)).astype(np.int64)
                    elif mode == 'max':
                        largest = max(largest, int(values.max())) if len(values) else largest
                    elif len(values):
                        series = values.astype(np.uint64)
                        if previous is not None:
                            largest = max(largest, int(series[0])-previous)
                        if len(series) > 1:
                            largest = max(largest, int(np.max(np.diff(series))))
                        previous = int(series[-1])
                    del values
        require(digest.hexdigest() == descriptor['sha256'], 'record column digest differs: '+name)
        return [int(v) for v in counts] if mode == 'bincount' else largest

    # ----- partition v2 (descriptor, ordered support rows) ------------------------------
    def _partition(self, view, meta, ref):
        import record_tables as RT
        columns = _Columns(view, meta['arrays'], self.check)
        try:
            fields = self._object_fields(columns, meta['root'])
            for name in ('partition_id', 'support_ids', 'supports'):
                require(name in fields, 'partition v2 descriptor lacks '+name)
            supports, ids = fields['supports'], fields['support_ids']
            require(columns.value('node.kind', supports) == RT.ARRAY and columns.value('node.kind', ids) == RT.ARRAY,
                    'partition support inventory must be arrays')
            s_lo, s_hi = columns.value('node.offset', supports), columns.value('node.offset', supports+1)
            i_lo, i_hi = columns.value('node.offset', ids), columns.value('node.offset', ids+1)
            require(s_hi-s_lo == i_hi-i_lo, 'partition support IDs and rows differ in count')
            mapping, nodes = {}, set()
            mentions = unique = mention_bytes = unique_bytes = 0
            for position in range(s_hi-s_lo):
                self.check()
                node = columns.value('edge.child', s_lo+position)
                length = columns.value('node.length', node)
                ident = self._ident(columns, columns.value('edge.child', i_lo+position))
                require(ident not in mapping, 'duplicate partition support ID')
                mapping[ident] = length
                mentions += 1
                mention_bytes += length
                if node not in nodes:
                    nodes.add(node)
                    unique += 1
                    unique_bytes += length
            partition_id = self._ident(columns, fields['partition_id'])
        finally:
            columns.close()
        self.partition_supports[ref.root_key.snapshot_key] = mapping
        self._supports(mapping, mapping.keys())
        return {'partition_id': partition_id, 'body_fields': sorted(set(fields)-{'partition_id', 'supports'}),
                'supports': {'logical': {'mentions': mentions, 'bytes': mention_bytes},
                             'unique': {'nodes': unique, 'bytes': unique_bytes},
                             'physical': 'inside the partition DAG columns (record pools); not separable per support'},
                'support_id_note': 'IDs are read from the authenticated id pool; support bodies are not re-hashed'}

    def _supports(self, sizes, mentioned):
        totals = self.support_totals
        for ident in mentioned:
            totals['logical']['mentions'] += 1
            totals['logical']['bytes'] += sizes[ident]
            if ident not in totals['seen']:
                totals['seen'].add(ident)
                totals['unique']['supports'] += 1
                totals['unique']['bytes'] += sizes[ident]

    def _object_fields(self, columns, node):
        import record_tables as RT
        require(columns.value('node.kind', node) == RT.OBJECT, 'object node required')
        shape = columns.value('node.shape', node)
        a, b = columns.value('shape.offset', shape), columns.value('shape.offset', shape+1)
        lo = columns.value('node.offset', node)
        require(columns.value('node.offset', node+1)-lo == b-a, 'object shape/row cardinality differs')
        fields = {}
        for position in range(b-a):
            token = columns.value('shape.key', a+position)
            t0, t1 = columns.value('token.offset', token), columns.value('token.offset', token+1)
            require(t1-t0 <= COMPACT_BLOCK, 'object key exceeds bounded census read')
            fields[json.loads(columns.raw('token.bytes', t0, t1))] = columns.value('edge.child', lo+position)
        return fields

    def _ident(self, columns, node):
        import record_tables as RT
        require(columns.value('node.kind', node) == RT.IDENT, 'content-ID node required')
        payload = columns.value('node.payload', node)
        return columns.raw('id.bytes', 32*payload, 32*payload+32).hex()

    # ----- mesh v3 (columns, header layout r2, shared supports) ---------------------------
    def _mesh_v3(self, view, ref, summary, metadata):
        import compact_store as CS
        import mesh_tables as M
        from support_source import SupportBinding
        require(type(metadata) is dict and set(metadata) == {'schema', 'codec', 'support_source', 'arrays',
                'header_support_ids'} and metadata['schema'] in (CS.V3_SCHEMA, CS.V3_HEADER_SCHEMA),
                'unsupported mesh v3 root')
        r2 = metadata['schema'] == CS.V3_HEADER_SCHEMA
        require(('header' in metadata['codec']) != r2, 'mesh v3 header layout differs')
        for name, descriptor in metadata['arrays'].items():
            column = summary['columns'].get(name)
            require(column is not None and column['dtype'] == descriptor['dtype'] and
                    column['shape'] == descriptor['shape'], 'mesh v3 column descriptor differs: '+name)
        binding = SupportBinding.from_wire(metadata['support_source'])
        partition_key = binding.partition.root_key.snapshot_key
        if partition_key not in self.partition_supports:
            self.ref(binding.partition, role='mesh-v3-support-source')
        else:
            self._open(binding.partition, 'mesh-v3-support-source')
        sizes = self.partition_supports.get(partition_key)
        require(sizes is not None and len(sizes) == binding.count, 'mesh v3 support source inventory differs')
        columns = _Columns(view, metadata['arrays'], self.check)
        try:
            entries = columns.count('s.id')
            require(columns.count('s.table') == entries, 'mesh v3 support columns differ')
            tables = {name: 0 for name in M.TABLES}
            shared_rows = set()
            shared_mentions = 0
            for index in range(entries):
                self.check()
                table = M.TABLES[columns.value('s.table', index)]
                tables[table] += 1
                if table == 'differential_supports':
                    shared_mentions += 1
                    shared_rows.add(columns.value('s.id', index))
            shared_ids = [columns.raw('id.bytes', 32*row, 32*row+32).hex() for row in sorted(shared_rows)]
            static = {'mentions': 0, 'bytes': 0, 'unique': 0, 'unique_bytes': 0}
            blobs = set()
            rows = columns.count('static.index') // 4
            for row in range(rows):
                self.check()
                blob, size = columns.value('static.index', 4*row+1), columns.value('static.index', 4*row+2)
                static['mentions'] += 1
                static['bytes'] += size
                if blob not in blobs:
                    blobs.add(blob)
                    static['unique'] += 1
                    static['unique_bytes'] += size
        finally:
            columns.close()
        require(shared_mentions == len(shared_ids) and all(i in sizes for i in shared_ids),
                'mesh v3 shared support IDs are not in the bound partition inventory')
        self._supports(sizes, shared_ids)
        header = (summary['columns'][CS.HEADER_COLUMN]['logical']['bytes'] if r2
                  else len(canonical_json(metadata['codec']['header'])))
        static_physical = summary['columns'].get('static.bytes', _counts())['physical']['payload_bytes']
        header_physical = summary['columns'][CS.HEADER_COLUMN]['physical']['payload_bytes'] if r2 else 0
        return {'handler': 'mesh-v3', 'domain': 'mesh-v3', 'layout': 'header-column-r2' if r2 else 'v3',
                'geometry_id': metadata['codec'].get('geometry_id'), 'header_bytes': header,
                'header_physical_bytes': header_physical, 'header_support_ids': metadata['header_support_ids'],
                'support_entries': entries, 'tables': tables,
                'shared': {'logical': {'mentions': shared_mentions, 'bytes': sum(sizes[i] for i in shared_ids)},
                           'unique': {'supports': len(shared_ids)},
                           'physical': {'bytes': 0, 'owner': 'partition v2 '+partition_key}},
                'static': {'logical': {'mentions': static['mentions'], 'bytes': static['bytes']},
                           'unique': {'blobs': static['unique'], 'bytes': static['unique_bytes']},
                           'physical': {'bytes': static_physical}},
                'support_source': {'partition_root_key': partition_key, 'count': binding.count,
                                   'inventory_digest': binding.inventory_digest}}

    # ----- heat r4 (ledger record, native fields, shared mesh IDs) ------------------------
    def _heat_fields(self, summary, metadata):
        import numpy as np
        require(type(metadata) is dict and set(metadata) == {'fields'} and type(metadata['fields']) is list,
                'heat field payload metadata differs')
        fields = []
        for row in metadata['fields']:
            column = summary['columns'].get(row['array'])
            logical = 8*math.prod(row['shape'])
            require(column is not None and column['dtype'] == np.dtype(np.float64).str and
                    column['shape'] == row['shape'] and column['logical']['bytes'] == logical,
                    'heat field descriptor differs: '+row['array'])
            fields.append({'name': row['name'], 'array': row['array'], 'logical_bytes': logical,
                           'unique_bytes': column['unique']['bytes'],
                           'physical_bytes': column['physical']['payload_bytes']})
        return {'handler': 'heat-fields', 'domain': 'heat-fields-r4', 'fields': fields}

    def heat_r4(self, receipt, *, role='heat-receipt'):
        import private_heat_snapshot_store_r4 as S
        from compact_contracts import SegmentRef
        if type(receipt) is dict and 'receipt' in receipt and 'invocation' not in receipt:
            # A caller's saved wrapper (e.g. Step 8 saved.json): only its exact receipt is used.
            receipt = receipt['receipt']
        require(type(receipt) is dict and set(receipt) == {'invocation', 'metadata'}, 'exact heat r4 receipt required')
        meta = receipt['metadata']
        S._manifest(meta, compact=True)
        require(sha256(canonical_json(meta)).hexdigest() == receipt['invocation'], 'heat receipt invocation differs')
        ledger, payload = SegmentRef.from_wire(meta['ledger']), SegmentRef.from_wire(meta['field_payload'])
        producer = sha256(canonical_json(meta['bindings'])).hexdigest()
        reports = {'ledger': self.ref(ledger, role=role+':ledger'), 'fields': self.ref(payload, role=role+':fields')}
        for name, ref in (('ledger', ledger), ('fields', payload)):
            row = self.segments[(ref.root_key.interval, ref.root_key.snapshot_key)]
            require(row['representation_profile'] == S.PROFILE and row['producer'] == producer,
                    'heat '+name+' representation/producer differs')
        shared = meta['shared_mesh']
        mesh = None
        if shared is not None:
            mesh_ref = SegmentRef.from_wire(shared['segment'])
            mention = self.ref_mentions.setdefault((mesh_ref.root_key.interval, mesh_ref.root_key.snapshot_key),
                {'record_schema': mesh_ref.identity.record_schema, 'interval': mesh_ref.root_key.interval,
                 'mentions': 0, 'roles': []})
            mention['mentions'] += 1
            if len(mention['roles']) < 16:
                mention['roles'].append(role+':shared-mesh')
            mesh = {'geometry_id': shared['geometry_id'], 'cell_ids': shared['cell_count'],
                    'face_ids': shared['face_count'], 'caller_ids': shared['caller_ids'],
                    'logical': {'id_mentions': shared['cell_count']+shared['face_count']},
                    'physical': {'bytes': 0, 'owner': 'mesh segment '+mesh_ref.root_key.snapshot_key}}
        report = {'handler': 'heat-r4', 'domain': 'heat-r4', 'result_id': meta['result_id'],
                  'receipt_bytes': len(canonical_json(meta)), 'metadata_bytes': meta['metadata_bytes'],
                  'logical_bytes': meta['logical_bytes'], 'ledger_root_key': ledger.root_key.snapshot_key,
                  'fields_root_key': payload.root_key.snapshot_key, 'shared_mesh': mesh,
                  'receipt_note': 'the receipt is caller-retained: logical only, no interval-file bytes'}
        if reports['ledger'].get('handler') == 'already-counted':
            report['ledger_already_counted'] = True
        self.records.append(report)
        return report

    # ----- interval store set and catalog ------------------------------------------------
    def catalog_heads(self):
        for entry in self.stores._catalog.entries:
            self.ref(entry.head, role='catalog-head:'+str(entry.interval))

    def _files(self, verify_files):
        from interval_catalog import file_token
        from interval_store_set import seal_key
        catalog = self.stores._catalog
        files = []
        for entry in catalog.entries:
            self.check()
            reader = self._reader(entry.interval)
            db = reader._db
            chunks = db.execute('SELECT count(*),coalesce(sum(length(payload)),0),coalesce(sum(length(descriptor)),0) '
                                'FROM chunks').fetchone()
            snaps = db.execute('SELECT count(*),coalesce(sum(length(body)),0) FROM snapshots').fetchone()
            seal = db.execute('SELECT length(body) FROM snapshots WHERE id=?',
                              (seal_key(self.workflow_id, entry.interval),)).fetchone()
            pages = [db.execute('PRAGMA '+name).fetchone()[0] for name in ('page_size', 'page_count', 'freelist_count')]
            reader._check_identity()
            size = file_token(reader.path, reject_sidecars=True)[2]
            attributed = sum(1 for row in self.chunks.values() if entry.interval in row[1])
            seen_snaps = sum(1 for key in self.snapshots if key[0] == entry.interval)
            files.append({'interval': entry.interval, 'filename': entry.filename, 'file_bytes': size,
                'file_sha256': entry.file_sha256, 'logical_seal': entry.logical_seal,
                'parent_interval': entry.parent_interval, 'references': [list(p) for p in entry.references],
                'head_root_key': entry.head.root_key.snapshot_key, 'chunk_rows': chunks[0],
                'chunk_payload_bytes': chunks[1], 'chunk_descriptor_bytes': chunks[2], 'snapshot_rows': snaps[0],
                'snapshot_body_bytes': snaps[1], 'seal_snapshot_bytes': seal[0] if seal else None,
                'sqlite_page_size': pages[0], 'sqlite_pages': pages[1], 'sqlite_free_pages': pages[2],
                'sqlite_overhead_bytes': size-chunks[1]-chunks[2]-snaps[1],
                'attributed_chunk_rows': attributed, 'unattributed_chunk_rows': chunks[0]-attributed,
                'attributed_snapshots': seen_snaps, 'unattributed_snapshots': snaps[0]-seen_snaps-(1 if seal else 0),
                'file_sha256_verified': self.stores.verify_file_sha256(entry.interval) if verify_files else None})
        return files

    def report(self, *, verify_files=False):
        from interval_catalog import file_token
        catalog = self.stores._catalog
        files = self._files(verify_files)
        totals = _counts()
        for row in self.classes.values():
            _merge_counts(totals, row)
        snapshot_kinds = {}
        for kind, size, mentions in self.snapshots.values():
            row = snapshot_kinds.setdefault(kind, {'logical_mentions': 0, 'unique': 0, 'physical_bytes': 0})
            row['logical_mentions'] += mentions
            row['unique'] += 1
            row['physical_bytes'] += size
        support = self.support_totals
        physical_files = {'file_bytes': sum(f['file_bytes'] for f in files),
                          'chunk_payload_bytes': sum(f['chunk_payload_bytes'] for f in files),
                          'snapshot_body_bytes': sum(f['snapshot_body_bytes'] for f in files)}
        return {'schema': COMPACT_SCHEMA, 'definitions': COUNT_DEFINITIONS, 'workflow_id': self.workflow_id,
            'catalog': {'schema': catalog_schema(), 'generation': catalog.generation, 'entries': len(catalog.entries),
                        'catalog_bytes': file_token(self.stores.catalog_path)[2],
                        'catalog_digest': self.stores.catalog_digest,
                        'cross_interval_references': sum(len(e.references) for e in catalog.entries)},
            'files': files,
            'segment_refs': {'logical_mentions': sum(r['mentions'] for r in self.ref_mentions.values()),
                             'unique': len(self.ref_mentions), 'counted_segments': len(self.segments),
                             'rows': [{'root_key': k[1], **r} for k, r in sorted(self.ref_mentions.items())]},
            'segments': list(self.segments.values()), 'records': self.records,
            'classes': dict(sorted(self.classes.items())), 'snapshots': snapshot_kinds,
            'supports': {'logical': dict(support['logical']), 'unique': dict(support['unique'])},
            'totals': {**totals, 'physical_files': physical_files}, 'verify_payload': self.verify_payload}

    def close(self):
        for held in self.pins.values():
            held.close()
        self.pins.clear()


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def catalog_schema():
    from interval_catalog import CATALOG_SCHEMA
    return CATALOG_SCHEMA


def compact_census(stores, *, refs=(), heat_receipts=(), check=_nothing, verify_payload=True, verify_files=False,
                   catalog_heads=True):
    """Exact WP0b census of an opened catalog; reads only, bounded by the catalog's rows."""
    census = CompactCensus(stores, check=check, verify_payload=verify_payload)
    try:
        rows = 0
        for entry in stores._catalog.entries:
            reader = census._reader(entry.interval)
            rows += sum(reader._db.execute('SELECT (SELECT count(*) FROM chunks)+(SELECT count(*) FROM snapshots)'
                                           ).fetchone())
            reader._check_identity()
        census.limit = rows+1
        clock = _clock()
        with stores.scope.run_budget.reserve(COMPACT_INDEX_ENTRY*census.limit+(1 << 20), category='wp0b-census-index'):
            if catalog_heads:
                census.catalog_heads()
            for ref in refs:
                census.ref(ref, role='explicit')
            for receipt in heat_receipts:
                census.heat_r4(receipt)
            result = census.report(verify_files=verify_files)
        result['booked_index_bytes'] = COMPACT_INDEX_ENTRY*census.limit+(1 << 20)
        _elapsed(result, 'census', clock)
        return result
    finally:
        census.close()


def compact_main(catalog, *, refs=(), receipts=(), output, verify_files=False):
    """Read-only CLI census of one catalog copy; writes only the new output JSON."""
    _imports()
    import psutil
    from atlas_tectonics.resources import WorkBudget
    from compact_contracts import SegmentRef
    from content_cache import create_retained_scope
    from interval_store_set import IntervalStoreSet
    output = Path(os.path.abspath(output))
    require(output.parent.is_dir() and not output.exists(), 'new census output file required')
    catalog = Path(catalog).resolve(strict=True)
    loaded_refs = [SegmentRef.from_wire(json.loads(Path(p).read_text(encoding='utf8'))) for p in refs]
    loaded_receipts = [json.loads(Path(p).read_text(encoding='utf8')) for p in receipts]
    inputs = sorted(path for path in catalog.parent.iterdir() if path.is_file() and path.name != output.name)
    before = {str(path): (_file_sha(path), _identity(path)) for path in inputs}
    budget = WorkBudget(COMPACT_RUN_BYTES)
    scope = create_retained_scope(budget, process_epoch='wp0b-compact-census')
    clock = _clock()
    stores = IntervalStoreSet.open_catalog(catalog, scope=scope)
    try:
        result = compact_census(stores, refs=loaded_refs, heat_receipts=loaded_receipts, verify_files=verify_files)
        result['retained'] = {k: getattr(scope.stats(), k) for k in ('retained_bytes', 'peak_retained_bytes')
                              if hasattr(scope.stats(), k)}
    finally:
        stores.close()
        gc.collect()
        scope.close()
    _elapsed(result, 'total', clock)
    after = {str(path): (_file_sha(path), _identity(path)) for path in inputs}
    info = psutil.Process().memory_info()
    result.update(inputs={k: v[0] for k, v in before.items()}, inputs_unchanged=before == after,
                  run_budget=_stage_statistics(budget), final_reserved_bytes=budget.reserved_bytes,
                  process={'rss_bytes': info.rss, 'peak_wset_bytes': getattr(info, 'peak_wset', None)},
                  sources={str(p.relative_to(T)).replace('\\', '/'): _file_sha(p) for p in COMPACT_SOURCES},
                  created_utc=_now(), scope_note='read-only census of a store copy; measurement only')
    require(result['inputs_unchanged'] and budget.reserved_bytes == 0, 'census inputs changed or reservations retained')
    with output.open('x', encoding='utf8') as stream:
        json.dump(result, stream, indent=1, sort_keys=True, allow_nan=False)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--launch', action='store_true')
    mode.add_argument('--workload', action='store_true')
    mode.add_argument('--compact', type=Path, metavar='CATALOG', help='WP0b read-only census of a compact catalog copy')
    parser.add_argument('--structure-only', action='store_true', help='WP0a selected-read baseline without codec conversion')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--heat-receipt', action='append', default=[], help='--compact: heat r4 receipt JSON file')
    parser.add_argument('--ref', action='append', default=[], help='--compact: SegmentRef wire JSON file')
    parser.add_argument('--verify-files', action='store_true', help='--compact: also hash every interval file')
    args = parser.parse_args(argv)
    if args.compact is not None:
        result = compact_main(args.compact, refs=args.ref, receipts=args.heat_receipt, output=args.output,
                              verify_files=args.verify_files)
        print(json.dumps({'totals': result['totals'], 'seconds': result['seconds']}, sort_keys=True), flush=True)
        return 0
    if args.workload:
        return workload(args.output, structure_only=args.structure_only)
    if args.prepare:
        print(json.dumps(prepare(args.output, structure_only=args.structure_only), indent=2, sort_keys=True), flush=True)
        return 0
    return launch(args.output, structure_only=args.structure_only)


if __name__ == '__main__':
    raise SystemExit(main())
