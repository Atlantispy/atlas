"""S6 / H5a step 1: time functionals r5 `_prepare` (+ `_prepared_bytes` settle) on the saved IV1 mesh.

Read-only on every input. Writes only OUT (T/so/s6/prepare-iv1.json). Unprofiled.
Mirrors functionals_kernel_r5.reconstruct lines 295-303: _prepare under the caller budget,
then, if COUNT.supported(G), _prepared_bytes and a shrink of the prepared reservation.
The payload is the original case's saved thermal mesh (failure/endpoint-mesh.gz, raw sha256
68f3c056...), loaded as the heat-allocation replays did (replay_pass.load): boundary =
every one-owner face a prescribed power, no temperature faces, conductivity Fraction(0.1).

usage: python -B measure_prepare.py MESH.gz HELPERS_DIR SRC_DIR OUT.json
"""
from fractions import Fraction
import gc
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

MESH, HELPERS, SRC, OUT = (Path(a) for a in sys.argv[1:5])
EXPECTED_RAW = '68f3c056769b3cbd61f8279ebf54fa00eafd879f8d3769aa9059974b9b9a4e57'
RSS_LIMIT = int(1.9 * 2**30)      # self-stop well below the 2 GB ceiling
LEDGER = 16 << 30                 # logical ledger only (the replays' value); _prepare books ~2.17 GB
REPEATS = 3

import psutil
PROC = psutil.Process()
record = dict(schema='s6.measure-prepare.r1', mesh=str(MESH), helpers=str(HELPERS), src=str(SRC),
              pythonhashseed=os.environ.get('PYTHONHASHSEED'), python=sys.version, pid=os.getpid(),
              rss_limit_bytes=RSS_LIMIT, status='started')
stop = threading.Event()
samples = dict(max_rss=0)


def save():
    OUT.write_text(json.dumps(record, indent=1, sort_keys=True), encoding='utf-8')


def watch():
    while not stop.is_set():
        rss = PROC.memory_info().rss
        samples['max_rss'] = max(samples['max_rss'], rss)
        if rss > RSS_LIMIT:
            record.update(status='ABORTED_RSS_LIMIT', rss_at_abort=rss)
            save()
            os._exit(9)
        stop.wait(0.2)


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        while block := stream.read(1 << 20):
            h.update(block)
    return h.hexdigest()


threading.Thread(target=watch, daemon=True).start()
try:
    # ---- payload (read-only) ----
    began = time.perf_counter()
    record['mesh_gz_sha256'] = sha(MESH)
    with gzip.open(MESH, 'rb') as stream:
        raw = stream.read()
    record['mesh_raw_sha256'] = hashlib.sha256(raw).hexdigest()
    record['mesh_raw_bytes'] = len(raw)
    record['mesh_raw_sha256_matches_68f3c056'] = record['mesh_raw_sha256'] == EXPECTED_RAW
    text = raw.decode('utf-8')
    del raw
    payload = json.loads(text)
    del text
    gc.collect()
    powers = {face['face_id'] for face in payload['faces'] if len(face['owners']) == 1}
    temperatures = set()
    conductivity = Fraction(0.1)
    record.update(cells=len(payload['cells']), faces=len(payload['faces']), power_faces=len(powers),
                  load_seconds=round(time.perf_counter() - began, 3),
                  rss_after_load=PROC.memory_info().rss)
    save()

    # ---- modules: composed-r2 helpers + src first on the path ----
    sys.path[:0] = [str(HELPERS), str(SRC)]
    import private_heat_functionals_kernel_r5 as FUNCTIONS
    import atlas_tectonics
    from atlas_tectonics.resources import WorkBudget
    G, COUNT = FUNCTIONS.G, FUNCTIONS.COUNT
    record['atlas_tectonics_file'] = atlas_tectonics.__file__
    FUNCTIONS.F.K._require_gmp()
    supported = bool(COUNT.supported(G))
    record['count_supported'] = supported

    def check():
        return False   # the forward's check(): cancel callback that never fires

    def one():
        budget = WorkBudget(LEDGER)
        gc.collect()
        t0 = time.perf_counter()
        owner = FUNCTIONS._prepare(payload, temperatures, powers, conductivity, budget=budget, cancelled=check)
        t1 = time.perf_counter()
        booked = owner._workspace.lease.count
        settled = None
        if supported:
            settled = FUNCTIONS._prepared_bytes(owner.value, check)
            if settled is not None and settled < owner._workspace.lease.count:
                owner._workspace.resize_before_allocation_or_after_drop(settled)
        t2 = time.perf_counter()
        held = owner._workspace.lease.count
        stats = budget.statistics()
        rss = PROC.memory_info().rss
        owner.close()
        del owner
        gc.collect()
        return dict(prepare_seconds=round(t1 - t0, 3), prepared_bytes_seconds=round(t2 - t1, 3),
                    total_seconds=round(t2 - t0, 3), booked_bytes=booked, settled_bytes=settled,
                    held_bytes_after_shrink=held, budget_peak_reserved_bytes=stats.get('peak_reserved_bytes'),
                    rss_with_prepared=rss)

    record['warmup'] = one()
    save()
    record['runs'] = [one() for _ in range(REPEATS)]
    totals = [run['total_seconds'] for run in record['runs']]
    record['T_prepare_total_seconds'] = dict(min=min(totals), max=max(totals),
                                             mean=round(sum(totals) / len(totals), 3))
    record['modules_sha256'] = {Path(m.__file__).name: sha(m.__file__) for name, m in sorted(sys.modules.items())
                                if (name.startswith('private_heat_') or name in ('atlas_tectonics.resources',))
                                and getattr(m, '__file__', None)}
    record['status'] = 'complete'
except BaseException as error:
    record.update(status='FAILED', error=repr(error)[:2000])
    raise
finally:
    stop.set()
    info = PROC.memory_info()
    record.update(peak_working_set_bytes=getattr(info, 'peak_wset', None), max_sampled_rss_bytes=samples['max_rss'],
                  final_rss_bytes=info.rss)
    save()
print(json.dumps({k: record.get(k) for k in ('status', 'mesh_raw_sha256_matches_68f3c056', 'cells', 'faces',
                                              'warmup', 'runs', 'T_prepare_total_seconds',
                                              'peak_working_set_bytes')}, indent=1))
