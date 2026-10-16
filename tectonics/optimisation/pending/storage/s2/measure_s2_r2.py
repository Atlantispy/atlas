"""S2 (WP16) before/after on the r9 IV1 pre-advance operands, same input, one process (harness r2).

r2: refuses unless the string-hash seed is 0 (no -I or -E, PYTHONHASHSEED=0); the candidate is s2/r9;
roots come from this file's place; the summary records the seed flag and the loaded files' sha256.

Arm L ("before") is the current code, copied exactly: compact_restart_patch.inspect_compact_preadvance's
streamed gzip-1 mesh writer + coverage.digest(path), and private_heat_original_coverage_r1.save_operands
(gzip-1, no fsync) for closed_graph and bounds. Arm N ("after") is the candidate
s2/compact_restart_patch.capture_operand/capture_operands (zstd-3 captures, fsync + atomic publish).
Both arms get the same operand bytes; the mesh is fed as a block stream (about 16 KiB rows plus a
one-byte separator block each, standing in for iter_legacy_json's per-row yields). check() is the
runner's real pair: resources.check(cancel) -> guard.check() (rate-limited monotonic test), copied.
Timed: the three writes and receipt rows only (input decoding and block generation are excluded).
Control (untimed): every row's raw_sha256/raw_bytes equals the r9 receipt; every capture decodes,
through the candidate ledger reader with its container pin, to the exact r9 bytes.

usage: measure_s2.py OUTPUT_DIR ROUNDS
"""
import gzip
import json
import os
import shutil
import statistics
import sys
import time
from hashlib import sha256, file_digest
from pathlib import Path

if sys.flags.hash_randomization != 0:
    raise SystemExit('refusing: the string-hash seed is not 0 (run without -I or -E, with PYTHONHASHSEED=0)')
HERE = Path(__file__).resolve().parent
T = HERE.parents[1]
R = T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
R9 = T/'fidelity-integration-20261005/heat-repair-20261007'
sys.path[:0] = [str(HERE/'r9'), str(R/'diagnostic-captures'), str(R/'composed-r2'/'helpers'), str(R/'composed-r2'/'src')]

from atlas_tectonics.resources import WorkBudget  # noqa: E402
import compact_restart_patch as CRP  # noqa: E402  (candidate s2/r9)
import ledger_fresh_interval as LG  # noqa: E402  (candidate s2/r9)

NAMES = ('mesh', 'closed_graph', 'bounds')


class Guard:
    """private_heat_continuation_guard_r3.Guard.check, copied (rate-limited; no abort file present)."""
    def __init__(self, interval=1.0, abort_path=None, path=None):
        self._check_interval, self._next_check = interval, 0.0
        self.closed = False
        self.abort_path = abort_path
        self.path = path

    def check(self, force=False):
        if self.closed:
            raise RuntimeError('closed')
        now = time.monotonic()
        if not force and now < self._next_check:
            return False
        self._next_check = now + self._check_interval
        if self.abort_path.exists():
            raise RuntimeError('abort')
        if self.path.exists():
            raise RuntimeError('cancel')
        return False


def resources_check(cancel):
    """private_heat_issuer_resources_r1.check, copied."""
    if cancel is not None and cancel():
        raise RuntimeError('cancelled')


def digest(path):
    """private_heat_original_coverage_r1.digest, copied."""
    with Path(path).open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def legacy_save_operands(artifacts, **operands):
    """private_heat_original_coverage_r1.save_operands, copied."""
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


def arm_legacy(artifacts, blocks, geometry_id, graph, bounds, check):
    """inspect_compact_preadvance lines 56-70 (9d076c80), copied; the projection/physics after it is unchanged."""
    path, hashed, count = Path(artifacts)/'preadvance-mesh.json.gz', sha256(), 0
    with path.open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw,
                                             mtime=0, compresslevel=1) as packed:
        for block in blocks:
            check()
            hashed.update(block)
            count += len(block)
            packed.write(block)
    if hashed.hexdigest() != geometry_id:
        raise ValueError('compact coverage mesh logical identity changed')
    operands = legacy_save_operands(artifacts, closed_graph=graph, bounds=bounds)
    operands['mesh'] = dict(path=path.name, raw_bytes=count, gzip_bytes=path.stat().st_size,
        raw_sha256=hashed.hexdigest(), gzip_sha256=digest(path))
    return operands


def arm_capture(artifacts, blocks, geometry_id, graph, bounds, check, budget):
    """The candidate inspect_compact_preadvance capture lines (s2/compact_restart_patch.py)."""
    mesh_row = CRP.capture_operand(artifacts, 'mesh', blocks, budget=budget, check=check)
    if mesh_row['raw_sha256'] != geometry_id:
        raise ValueError('compact coverage mesh logical identity changed')
    operands = CRP.capture_operands(artifacts, budget=budget, check=check, closed_graph=graph, bounds=bounds)
    operands['mesh'] = mesh_row
    return operands


def mesh_blocks(raw, row=16384):
    blocks = []
    for start in range(0, len(raw), row):
        piece = raw[start:start+row]
        blocks.extend((piece[:-1], piece[-1:]) if len(piece) > 1 else (piece,))
    return blocks


def main():
    out, rounds = Path(sys.argv[1]), int(sys.argv[2])
    out.mkdir(parents=True, exist_ok=False)
    receipt = json.loads((R9/'heat-original-connected-20261013-r9.json').read_bytes())['preadvance_operands']
    data = {}
    for name in NAMES:
        raw = gzip.decompress((R9/'heat-original-connected-20261013-r9.artifacts'/receipt[name]['path']).read_bytes())
        if (len(raw), sha256(raw).hexdigest()) != (receipt[name]['raw_bytes'], receipt[name]['raw_sha256']):
            raise SystemExit('r9 operand differs from its receipt: '+name)
        data[name] = raw
    blocks = mesh_blocks(data['mesh'])
    geometry_id = receipt['mesh']['raw_sha256']
    guard = Guard(abort_path=out/'run.guard-abort.json', path=out/'run.cancel')

    def check():
        return resources_check(guard.check)
    budget = WorkBudget(256 << 20)
    CRP.capture_backend()  # load the pinned DLL once, outside timing, as a run would
    order = []
    for index in range(rounds):
        order += ['L', 'N', 'N', 'L'] if index % 2 == 0 else ['N', 'L', 'L', 'N']
    timings = {'L': [], 'N': []}
    sizes = {}
    for at, arm in enumerate(order):
        artifacts = out/(arm+str(at))
        artifacts.mkdir()
        started = time.perf_counter()
        if arm == 'L':
            rows = arm_legacy(artifacts, blocks, geometry_id, data['closed_graph'], data['bounds'], check)
        else:
            rows = arm_capture(artifacts, blocks, geometry_id, data['closed_graph'], data['bounds'], check, budget)
        elapsed = time.perf_counter()-started
        timings[arm].append(elapsed)
        # Untimed control on every arm: logical identity equals the r9 receipt.
        for name in NAMES:
            if (rows[name]['raw_bytes'], rows[name]['raw_sha256']) != (receipt[name]['raw_bytes'],
                                                                       receipt[name]['raw_sha256']):
                raise SystemExit('logical identity differs: '+arm+' '+name)
        if arm not in sizes:
            sizes[arm] = {name: rows[name].get('gzip_bytes', rows[name].get('stored_bytes')) for name in NAMES}
            if arm == 'N':
                for name in NAMES:
                    if LG.captured_bytes(artifacts/rows[name]['path'], rows[name]['container_sha256'],
                                         rows[name]['raw_bytes'], rows[name]['stored_bytes']) != data[name]:
                        raise SystemExit('capture does not decode to the exact r9 bytes: '+name)
                    if LG.capture(artifacts, rows[name]) is None:
                        raise SystemExit('ledger reader refused')
                (out/'capture-rows.json').write_text(json.dumps(rows, indent=1, sort_keys=True))
            else:
                (out/'legacy-rows.json').write_text(json.dumps(rows, indent=1, sort_keys=True))
                for name in NAMES:
                    if rows[name]['gzip_sha256'] != receipt[name]['gzip_sha256']:
                        print('note: legacy gzip container differs from r9 (', name, ') - expected only if zlib differs')
        shutil.rmtree(artifacts)
        print(arm, at, round(elapsed, 3), flush=True)
    if budget.reserved_bytes:
        raise SystemExit('capture bookings leaked')
    stat = budget.statistics()
    summary = {
        'schema': 'so.s2-measure.v1', 'order': order, 'blocks': len(blocks),
        'seconds': timings,
        'median_s': {k: statistics.median(v) for k, v in timings.items()},
        'min_s': {k: min(v) for k, v in timings.items()},
        'disk_bytes': sizes, 'disk_total': {k: sum(v.values()) for k, v in sizes.items()},
        'capture_peak_reserved_bytes': stat['peak_reserved_bytes'],
        'control': 'every arm raw_sha256/raw_bytes == r9 receipt; first N arm decoded to exact r9 bytes',
        'pid': os.getpid(), 'hashseed': os.environ.get('PYTHONHASHSEED'),
        'hash_randomization': sys.flags.hash_randomization,
        'loaded': {m.__name__: [m.__file__, sha256(Path(m.__file__).read_bytes()).hexdigest()] for m in (CRP, LG)}}
    summary['median_gain_s'] = summary['median_s']['L']-summary['median_s']['N']
    (out/'summary.json').write_text(json.dumps(summary, indent=1, sort_keys=True))
    print(json.dumps({k: summary[k] for k in ('median_s', 'min_s', 'median_gain_s', 'disk_total',
                                              'capture_peak_reserved_bytes', 'blocks')}))


if __name__ == '__main__':
    main()
