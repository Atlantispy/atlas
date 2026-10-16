"""Route (1) step 4: the interval-1 difference ledger, rerun against r9 (read-only, store-free).

Coordinator rule (plan-order review section 7b item 6, amended 16 Oct ~04:15; items
11 and 15 OFF ~05:45). The rerun need not equal r9; this ledger must show that

1. every difference is attributed to a named, approved RC1 change (today only
   cube-witness stopping);
2. both bounds of every differing query are certified, meet the requested width
   and overlap;
3. every downstream heat or transport difference is quantified and traced to
   those bounds;
4. anything unattributed fails.

The trace is exact because both runs save the same three pre-advance heat inputs
(bounds, closed graph, end mesh) with their raw SHA-256, and heat and transport
are deterministic functions of them under one heat method (the same-call
re-proofs show identical certified records on identical inputs). Identical
inputs therefore require identical endpoint arrays, and inputs that differ only
in attributed cells trace every endpoint difference to those bounds.

Query semantics are the geometry chat's (16 Oct 2026): replay rows are keyed by
(full_cell, endpoint), full_cell is the capture's cell_id, ``exact`` is
[lower, upper, positive witness] in m^3, and a record is certified when it is
'met': upper - lower <= the requested width (32,000 m^3 at interval 1, the
supports header's max_volume_error_m3) and (upper == 0 or witness > 0). The
replay of record is the Step 10 configuration (RC1 with items 11 and 15 off
through their reviewed transform); the r7 side is the all-off replay, which
equals r7 on all 7,181 interval-1 queries. Every queried endpoint of the rerun
must equal the Step 10 replay exactly, and every r9 bound must equal the r7
replay exactly, so a difference is attributed only where the replay itself
differs from r7 the same way.

Levels: (1) identity, recorded and never a failure alone; (2) the start state,
every leaf of the root's logical metadata (identity and storage-representation
leaves are listed, not failed); (3) heat inputs: bound cells, face and
finite-exchange intervals, closed graph, mesh; (4) endpoint array records, by
group, name and SHA-256; (5) the rerun's exact-width gate as its reader
recorded it. Value-level quantification of differing endpoint arrays (store
reads) is a separate, later step; this module lists the arrays. Nothing here
writes outside the one exclusive ledger file, runs physics or opens a store.
"""
import argparse
import json
import sys
import zlib
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

LEDGER_SCHEMA = 'atlas.fresh-interval-difference-ledger.v1'
APPROVED_CHANGE = 'cube-witness-stopping'
REQUESTED_WIDTH_M3 = Fraction(32000)
OPERANDS = ('bounds', 'closed_graph', 'mesh')
GROUPS = ('collar', 'native', 'exterior', 'source_audit', 'full_collar', 'spatial_audit')
ENDPOINTS = {'start': 'start_volume_bounds_m3', 'end': 'end_volume_bounds_m3'}
# Storage references: the compact route records the same content through other handles.
REPRESENTATION = frozenset(('record_blobs', 'record_blob', 'compact_mesh', 'compact_partition', 'segment',
                            'array_bindings', 'source_producer'))
MAX_RECORD = 64 << 20


class LedgerRefused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise LedgerRefused(message)


def pinned_bytes(path, pin, limit=None):
    raw = Path(path).read_bytes()
    require((limit is None or len(raw) <= limit) and sha256(raw).hexdigest() == pin,
            'pinned input changed: '+str(path))
    return raw


CAPTURE_FORMAT = 'atlas.diagnostic-capture.v1'
CAPTURE_LIBRARY = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/'
                       'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/'
                       'resumability-r1/compact-geometry-r1/native/wp10_zstd.dll')
CAPTURE_LIBRARY_SHA256 = 'a40c24ad328da37a42c7f69e434c576254f11fde4097cd5de7416f8f78444f28'
# The writer's explicit ceiling (compact_restart_patch.CAPTURE_MAX_BYTES): a receipt beyond it
# refuses before the reader allocates its output buffer.
CAPTURE_MAX_BYTES = 16 << 30
_HEX = frozenset('0123456789abcdef')


def _container_pinned(path, container_sha256, raw_bytes, stored_bytes, footer):
    """The whole file hashes to the receipt's container pin, and its footer states raw_bytes.

    The container hash covers every byte, footer included, so once it matches the receipt
    the footer is the writer's own; its raw_bytes must then equal the receipt's. The file is
    read 1 MiB at a time, so nothing the receipt sizes is allocated here.
    """
    digest, left, tail = sha256(), stored_bytes, b''
    with open(path, 'rb') as handle:
        while left:
            block = handle.read(min(left, 1 << 20))
            require(block, 'pre-advance capture is shorter than its receipt: '+str(path))
            digest.update(block)
            tail = block[-footer.size:] if len(block) >= footer.size else (tail+block)[-footer.size:]
            left -= len(block)
        require(not handle.read(1), 'pre-advance capture is longer than its receipt: '+str(path))
    require(digest.hexdigest() == container_sha256, 'pre-advance capture differs from its container pin: '+str(path))
    tag, _, footer_raw_bytes, _, _ = footer.unpack(tail)
    require(tag == b'F' and footer_raw_bytes == raw_bytes,
            'pre-advance capture footer differs from its receipt raw_bytes: '+str(path))


def legacy_bytes(path, raw_bytes, gzip_bytes=None):
    """The exact bytes of one legacy (r9) gzip operand, never decompressed past its receipt.

    The rules are gzip.decompress's (members in sequence, zero padding between them, an
    empty file is empty), but the members together may not produce more than the receipt's
    raw_bytes, so a damaged or hostile file cannot make the ledger allocate past its
    receipt. The file is read 1 MiB at a time, so a large file allocates no more than a
    small one. gzip_bytes, which receipts may omit (the owner's fixtures do), must equal
    the file's size when present. A damaged stream refuses (REFUSED), never a FAIL-coded crash.
    """
    require(type(raw_bytes) is int and 0 <= raw_bytes <= CAPTURE_MAX_BYTES,
            'legacy capture receipt raw_bytes required (at most %d bytes): %s' % (CAPTURE_MAX_BYTES, path))
    size = Path(path).stat().st_size
    require(size <= CAPTURE_MAX_BYTES, 'legacy pre-advance capture exceeds the ceiling: '+str(path))
    require(gzip_bytes is None or (type(gzip_bytes) is int and gzip_bytes == size),
            'legacy pre-advance capture gzip_bytes differs from its file: '+str(path))
    out, member, ended, read = bytearray(), None, False, 0
    try:
        with open(path, 'rb') as handle:
            while True:
                data = handle.read(1 << 20)
                if not data:
                    break
                read += len(data)
                while data:
                    if member is None:
                        if ended:  # zero padding may follow a member, never start the file
                            data = data.lstrip(b'\0')
                            if not data:
                                break
                        member = zlib.decompressobj(wbits=31)
                    out += member.decompress(data, raw_bytes+1-len(out))
                    require(len(out) <= raw_bytes, 'legacy pre-advance capture exceeds its receipt raw_bytes: '+str(path))
                    if member.eof:
                        data, member, ended = member.unused_data, None, True
                    else:
                        data = member.unconsumed_tail
    except zlib.error as error:  # a damaged r9 operand is a bad input: REFUSED, not FAIL
        raise LedgerRefused('legacy pre-advance capture is not a whole gzip stream: %s (%s)' % (path, error)) from None
    require(member is None, 'legacy pre-advance capture is not a whole gzip stream: '+str(path))
    return out


def captured_bytes(path, container_sha256, raw_bytes, stored_bytes):
    """The exact bytes of one WP16 capture, after its whole file meets the receipt's container pin.

    Before the one output buffer is allocated, the receipt's sizes must lie between the
    format's minimum and the writer's ceiling, its container pin must be 64 lowercase hex,
    stored_bytes must equal the file's size, the whole file must hash to the container pin
    and the footer that pin covers must state the receipt's raw_bytes, so a receipt never
    sizes an allocation its file does not back. The reader is then held to raw_bytes, so
    each operand is held once. The reader needs the composed helpers and runtime source on
    sys.path; without them the ledger refuses (REFUSED), never a FAIL-coded crash.
    """
    try:
        from atlas_tectonics.resources import WorkBudget
        from capture_store import CaptureReader, FOOTER, PREAMBLE
        from storage_zstd_backend import ZstdBackend
    except ImportError as error:
        raise LedgerRefused('WP16 capture reader unavailable (%s): put the composed helpers and runtime '
                            'source on sys.path' % (error.name or error)) from None
    require(type(raw_bytes) is int and type(stored_bytes) is int and 0 <= raw_bytes <= CAPTURE_MAX_BYTES and
            PREAMBLE.size+32+FOOTER.size <= stored_bytes <= CAPTURE_MAX_BYTES,
            'capture receipt sizes required (at most %d bytes): %s' % (CAPTURE_MAX_BYTES, path))
    require(type(container_sha256) is str and len(container_sha256) == 64 and set(container_sha256) <= _HEX,
            'capture receipt container_sha256 required (64 lowercase hex): '+str(path))
    require(Path(path).stat().st_size == stored_bytes, 'pre-advance capture size differs from its receipt: '+str(path))
    _container_pinned(path, container_sha256, raw_bytes, stored_bytes, FOOTER)
    buffer, filled = bytearray(raw_bytes), 0
    native = ZstdBackend(CAPTURE_LIBRARY, expected_sha256=CAPTURE_LIBRARY_SHA256)
    with CaptureReader(path, budget=WorkBudget(64 << 20), backend=native, expected_sha256=container_sha256,
                       max_logical_bytes=raw_bytes, max_stored_bytes=stored_bytes) as reader:
        with reader.iter_bytes() as stream:
            for owner in stream:
                part = owner.value
                require(filled+len(part) <= raw_bytes, 'pre-advance capture exceeds its receipt: '+str(path))
                buffer[filled:filled+len(part)] = part
                filled += len(part)
                del part
                owner.close()
        require(stream.result is not None and filled == raw_bytes,
                'pre-advance capture was not fully verified: '+str(path))
    return buffer


def capture(directory, operand):
    """One pre-advance capture, decoded only after its raw bytes match the receipt pin.

    The receipt names a plain file name in the run's own folder (both writers record
    path.name). WP16 captures (format atlas.diagnostic-capture.v1) are fully verified
    against their own container_sha256; legacy gzip operands (r9) stay readable, bounded by
    their receipt's raw_bytes. Both then meet the same raw_bytes/raw_sha256 receipt check,
    the codec-independent logical identity.
    """
    name = operand['path']
    require(type(name) is str and name not in ('', '.', '..') and Path(name).name == name,
            'pre-advance capture path must be a plain file name: %r' % (name,))
    if operand.get('format') == CAPTURE_FORMAT:
        raw = captured_bytes(Path(directory, name), operand['container_sha256'],
                             operand['raw_bytes'], operand['stored_bytes'])
    else:
        raw = legacy_bytes(Path(directory, name), operand['raw_bytes'], operand.get('gzip_bytes'))
    require(len(raw) == operand['raw_bytes'] and sha256(raw).hexdigest() == operand['raw_sha256'],
            'pre-advance capture differs from its receipt: '+name)
    return json.loads(raw)


def rational(pair):
    require(type(pair) is list and len(pair) == 2 and all(type(v) is str for v in pair),
            'exact rational pair required')
    numerator, denominator = int(str(pair[0]), 16), int(str(pair[1]), 16)
    require(denominator > 0, 'exact rational with a positive denominator required')
    value = Fraction(numerator, denominator)
    require(pair == [hex(value.numerator), hex(value.denominator)], 'reduced canonical rational pair required')
    return value


def interval(bounds):
    require(type(bounds) is list and len(bounds) == 2, 'exact [lower, upper] bounds required')
    lower, upper = rational(bounds[0]), rational(bounds[1])
    require(lower <= upper, 'ordered exact bounds required')
    return lower, upper


def is_identity(name):
    return name in ('key', 'workflow_id', 'bounds_id', 'geometry_id', 'sha256') or name.endswith(('_id', '_ids'))


def leaf_differences(left, right, path=()):
    """Every differing leaf as (path, kind): 'identity', 'representation' or 'value'."""
    if left == right:
        return []
    if type(left) is dict and type(right) is dict:
        found = []
        for name in sorted(set(left) | set(right)):
            if name in REPRESENTATION:
                if left.get(name) != right.get(name):
                    found.append(('.'.join((*path, name)), 'representation'))
            elif name not in left or name not in right:
                found.append(('.'.join((*path, name)), 'identity' if is_identity(name) else 'value'))
            else:
                found.extend(leaf_differences(left[name], right[name], (*path, name)))
        return found
    if type(left) is list and type(right) is list and len(left) == len(right):
        return [item for index, (a, b) in enumerate(zip(left, right, strict=True))
                for item in leaf_differences(a, b, (*path, str(index)))]
    name = path[-1] if path else ''
    return [('.'.join(path), 'identity' if is_identity(name) else 'value')]


def classified(differences):
    result = {'identity': [], 'representation': [], 'value': []}
    for path, kind in differences:
        result[kind].append(path)
    return result


def read_rows(paths, label):
    """Replay rows by (full_cell, endpoint) from one or more shards; shard headers are skipped."""
    found = {}
    for path, pin in paths:
        for line in pinned_bytes(path, pin).splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if 'full_cell' not in row:
                continue
            key = (row['full_cell'], row['endpoint'])
            require(row['endpoint'] in ENDPOINTS and key not in found,
                    'duplicate or unknown replay query key in '+label+': '+repr(key))
            found[key] = row
    require(found, 'empty replay: '+label)
    return found


def certified(row, width=REQUESTED_WIDTH_M3):
    """The record's own criterion: met, within the requested width, witness positive unless upper is zero."""
    lower, upper, witness = (rational(value) for value in row['exact'])
    return (row['status'] == 'met' and lower <= upper and upper-lower <= width and
            (upper == 0 or witness > 0))


def cell_differences(r9, rerun, replay, r7):
    """Bound cells by cell ID and endpoint against the two replays; returns (attributed, unattributed, counts)."""
    def cells(value):
        found = {}
        for cell in value['cells']:
            require(cell['cell_id'] not in found, 'duplicate cell in a bounds capture')
            found[cell['cell_id']] = cell
        return found
    left, right = cells(r9), cells(rerun)
    require(set(replay) == set(r7), 'Step 10 and r7 replay query inventories differ')
    require({cell for cell, _ in replay} <= set(left), 'replay queries name cells absent from r9')
    attributed, unattributed = [], []
    counts = {'cells': len(left), 'queried_endpoints': 0, 'unqueried_endpoints': 0}
    for cell_id in sorted(set(left) | set(right)):
        if cell_id not in left or cell_id not in right:
            unattributed.append({'cell_id': cell_id, 'reason': 'cell present in one run only'})
            continue
        for endpoint, field in ENDPOINTS.items():
            key, before, after = (cell_id, endpoint), left[cell_id][field], right[cell_id][field]
            ours, original = replay.get(key), r7.get(key)
            counts['queried_endpoints' if ours is not None else 'unqueried_endpoints'] += 1
            row = {'cell_id': cell_id, 'endpoint': endpoint}
            if ours is not None and after != ours['exact'][:2]:
                unattributed.append(dict(row, reason='rerun bound differs from the Step 10 replay', rerun=after,
                                         replay=ours['exact'][:2]))
            if original is not None and before != original['exact'][:2]:
                unattributed.append(dict(row, reason='r9 bound differs from the r7 replay', r9=before,
                                         replay=original['exact'][:2]))
            if before == after:
                continue
            (lo0, hi0), (lo1, hi1) = interval(before), interval(after)
            row.update(r9=before, rerun=after, overlap=max(lo0, lo1) <= min(hi0, hi1),
                       r9_width=str(hi0-lo0), rerun_width=str(hi1-lo1))
            if ours is None:
                unattributed.append(dict(row, reason='difference at an endpoint without a query'))
            elif not (row['overlap'] and certified(ours) and certified(original)):
                unattributed.append(dict(row, reason='differing bounds are not both certified and overlapping'))
            else:
                attributed.append(dict(row, change=APPROVED_CHANGE))
        others = sorted(name for name in set(left[cell_id]) | set(right[cell_id])
                        if name not in ENDPOINTS.values() and left[cell_id].get(name) != right[cell_id].get(name))
        if others:
            unattributed.append({'cell_id': cell_id, 'reason': 'non-bound cell fields differ', 'fields': others})
    return attributed, unattributed, counts


def keyed_differences(r9, rerun, key, label):
    """Face or finite-exchange intervals by a stable key; any difference is listed."""
    def index(items):
        found = {}
        for item in items:
            name = tuple(item[k] for k in key)
            require(name not in found, 'duplicate '+label+' key')
            found[name] = item
        return found
    left, right = index(r9), index(rerun)
    return [{'key': list(name), 'in_r9': name in left, 'in_rerun': name in right}
            for name in sorted(set(left) | set(right)) if left.get(name) != right.get(name)]


def array_differences(r9, rerun):
    """The six endpoint groups by name and SHA-256 (receipt level)."""
    result = {}
    for group in GROUPS:
        left = {row['name']: row for row in r9[group]}
        right = {row['name']: row for row in rerun[group]}
        result[group] = {'identical': sorted(n for n in left if n in right and left[n] == right[n]),
                         'different': sorted(n for n in left if n in right and left[n] != right[n]),
                         'r9_only': sorted(set(left)-set(right)), 'rerun_only': sorted(set(right)-set(left))}
    return result


def ledger(*, r9, r9_artifacts, rerun, rerun_artifacts, replay, r7, rerun_verdict):
    """The closed comparison; returns the ledger record with its verdict."""
    unattributed = []
    r9_end, rerun_end = r9['completed_endpoint'], rerun['completed_endpoint']
    identity = classified(leaf_differences({k: v for k, v in r9_end.items() if k not in ('array_records',
                                                                                      'root_metadata')},
                                           {k: v for k, v in rerun_end.items() if k not in ('array_records',
                                                                                         'root_metadata')}))
    start = classified(leaf_differences(r9_end['root_metadata'], rerun_end['root_metadata'], ('root_metadata',)))
    unattributed += [{'level': 'start_state', 'path': path} for path in start['value']]
    operands = {name: {'r9_raw_sha256': r9['preadvance_operands'][name]['raw_sha256'],
                       'rerun_raw_sha256': rerun['preadvance_operands'][name]['raw_sha256']} for name in OPERANDS}
    for row in operands.values():
        row['identical'] = row['r9_raw_sha256'] == row['rerun_raw_sha256']
    bounds: dict = {'replay_queries': len(replay), 'replay_differs_from_r7': sum(
        replay[key]['exact'][:2] != r7[key]['exact'][:2] for key in replay if key in r7)}
    attributed = []
    left, right = (capture(directory, report['preadvance_operands']['bounds'])
                   for directory, report in ((r9_artifacts, r9), (rerun_artifacts, rerun)))
    attributed, cell_unattributed, counts = cell_differences(left, right, replay, r7)
    bounds.update(counts, attributed=attributed)
    unattributed += [dict(row, level='bounds') for row in cell_unattributed]
    for label, key, field in (('face interval', ('face_id',), 'face_intervals'),
                              ('finite exchange interval', ('face_id', 'direction', 'stock_id'),
                               'finite_exchange_intervals')):
        rows = keyed_differences(left[field], right[field], key, label)
        bounds[field] = rows
        unattributed += [dict(row, level='bounds', reason=label+' differs; no approved change covers it')
                         for row in rows]
    scalars = classified(leaf_differences({k: v for k, v in left.items() if k not in
                                           ('cells', 'face_intervals', 'finite_exchange_intervals')},
                                          {k: v for k, v in right.items() if k not in
                                           ('cells', 'face_intervals', 'finite_exchange_intervals')}, ('bounds',)))
    bounds['other_fields'] = scalars
    unattributed += [{'level': 'bounds', 'path': path} for path in scalars['value']]
    del left, right
    traced = bool(attributed) and not unattributed
    if not operands['mesh']['identical']:
        unattributed.append({'level': 'mesh', 'reason': 'the end mesh differs; no approved change touches it'})
    if not operands['closed_graph']['identical'] and not traced:
        unattributed.append({'level': 'closed_graph', 'reason': 'graph differs without attributed bound differences'})
    arrays = array_differences(r9_end['array_records'], rerun_end['array_records'])
    for group, row in arrays.items():
        if row['r9_only'] or row['rerun_only']:
            unattributed.append({'level': 'arrays', 'group': group, 'reason': 'array inventories differ'})
        if row['different'] and not traced:
            unattributed.append({'level': 'arrays', 'group': group, 'different': row['different'],
                                 'reason': 'endpoint arrays differ with no attributed input difference'})
    return {'schema': LEDGER_SCHEMA, 'verdict': 'PASS' if not unattributed else 'FAIL',
            'approved_change': APPROVED_CHANGE, 'requested_width_m3': str(REQUESTED_WIDTH_M3),
            'identity': identity, 'start_state': start, 'heat_inputs': {'operands': operands, 'bounds': bounds},
            'traced_to_attributed_bounds': traced, 'endpoint_arrays': arrays,
            'value_quantification': 'pending: read both stores for every differing endpoint array',
            'width_gate': rerun_verdict.get('width_gate'), 'unattributed': unattributed,
            'production_acceptance': False}


def _pairs(values):
    require(len(values) % 2 == 0, 'path and SHA-256 pairs required')
    return list(zip(values[0::2], values[1::2], strict=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('r9-receipt', 'rerun-receipt', 'rerun-verdict'):
        parser.add_argument('--'+name, type=Path, required=True)
        parser.add_argument('--'+name+'-sha256', required=True)
    parser.add_argument('--replay', nargs='+', required=True, help='Step 10 replay shards: PATH SHA256 ...')
    parser.add_argument('--r7-replay', nargs='+', required=True, help='all-off replay shards: PATH SHA256 ...')
    parser.add_argument('--r9-artifacts', type=Path, required=True)
    parser.add_argument('--rerun-artifacts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        inputs = {name: json.loads(pinned_bytes(getattr(args, name.replace('-', '_')),
                                                getattr(args, name.replace('-', '_')+'_sha256'), MAX_RECORD))
                  for name in ('r9-receipt', 'rerun-receipt', 'rerun-verdict')}
        replay, r7 = _pairs(args.replay), _pairs(args.r7_replay)
        value = ledger(r9=inputs['r9-receipt'], r9_artifacts=args.r9_artifacts, rerun=inputs['rerun-receipt'],
                       rerun_artifacts=args.rerun_artifacts, replay=read_rows(replay, 'the Step 10 replay'),
                       r7=read_rows(r7, 'the r7 replay'), rerun_verdict=inputs['rerun-verdict'])
    except (LedgerRefused, KeyError, TypeError, ValueError, OSError) as error:
        print(json.dumps({'status': 'REFUSED', 'type': type(error).__name__, 'reason': str(error)}), flush=True)
        return 2
    value['inputs'] = {'r9_receipt': [str(args.r9_receipt), args.r9_receipt_sha256],
                       'rerun_receipt': [str(args.rerun_receipt), args.rerun_receipt_sha256],
                       'rerun_verdict': [str(args.rerun_verdict), args.rerun_verdict_sha256],
                       'replay': [[str(p), s] for p, s in replay], 'r7_replay': [[str(p), s] for p, s in r7]}
    with open(args.output, 'x', encoding='utf8') as stream:
        json.dump(value, stream, indent=1, sort_keys=True)
    print(json.dumps({'status': value['verdict'], 'unattributed': len(value['unattributed']),
                      'attributed': len(value['heat_inputs']['bounds']['attributed']),
                      'output': str(args.output)}), flush=True)
    return 0 if value['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
