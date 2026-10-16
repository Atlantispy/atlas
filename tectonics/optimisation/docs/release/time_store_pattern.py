"""T/rm: admission per-component guard pattern, strict vs simulated release, on a scratch ArrayStore.

Replays cached_initial_component's identity/store call pattern (integration_dual_geometry.py:689-771) without
the measurement itself:
  miss: identity, get, verify, put(publication_check=verify), verify
  hit:  identity, get, metadata, verify
Release is SIMULATED with the repo's own unit-test technique (tectonics/tests/test_optimisation_runtime.py
ReleaseExecutionTests: replace reuse._release_state in a scratch process). This is a cost probe of the code as
written, not packaged-release evidence; nothing is published, no strict check is altered for any real run.
Two contexts are captured per mode, as the interval driver does (fresh_interval_driver.py:87-88).
Order: strict, release, strict (ABA) to expose drift.
"""
import hashlib, json, shutil, statistics, sys, threading, time, types
from pathlib import Path

SRC, OUT, WORK = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
N = int(sys.argv[4]) if len(sys.argv) > 4 else 40
sys.path.insert(0, str(SRC))
import numpy as np
from atlas_tectonics import reuse
from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits
assert Path(reuse.__file__).resolve().is_relative_to(SRC.resolve()), reuse.__file__

LIMITS = StoreLimits(1024, 1 << 20, 4 << 20)
RAW = Compression('raw', palette=False)
PAYLOAD = np.frombuffer(json.dumps({'bounds': ['1/3', '2/3'], 'queries': [{}]}).encode() * 8, dtype=np.uint8)


def key(label):
    return hashlib.sha256(label.encode()).hexdigest()


def arm(label, mode):
    reuse._release_state = types.SimpleNamespace(mode=mode, captures={}, lock=threading.RLock())
    assert reuse.execution_mode() == mode
    a = time.perf_counter()
    ref, sci = reuse.ExecutionContext('reference'), reuse.ExecutionContext('scipy')
    capture = time.perf_counter() - a
    folder = WORK / label
    shutil.rmtree(folder, ignore_errors=True); folder.mkdir(parents=True)
    a = time.perf_counter()
    store = ArrayStore(folder / 'state.db', LIMITS, RAW)
    open_s = time.perf_counter() - a
    miss, hit = [], []
    for i in range(N):
        k = key(f'{label}-{i}')
        a = time.perf_counter()
        md = {'execution_identity': ref.identity, 'i': i}
        assert store.get(k) is None
        ref.verify()
        store.put(k, {'measurement': PAYLOAD}, md, publication_check=ref.verify)
        ref.verify()
        miss.append(time.perf_counter() - a)
    for i in range(N):
        k = key(f'{label}-{i}')
        a = time.perf_counter()
        md = {'execution_identity': ref.identity, 'i': i}
        got = store.get(k)
        assert store.metadata(k) == md and got['measurement'].tobytes() == PAYLOAD.tobytes()
        ref.verify()
        hit.append(time.perf_counter() - a)
    store.close()
    for c in (ref, sci):
        c.close()
    med = lambda xs: 1e3 * statistics.median(xs)
    return {'mode': mode, 'n': N, 'capture_s': capture, 'open_ms': 1e3 * open_s,
            'miss_ms': {'median': med(miss), 'min': 1e3 * min(miss), 'max': 1e3 * max(miss)},
            'hit_ms': {'median': med(hit), 'min': 1e3 * min(hit), 'max': 1e3 * max(hit)}}


rec = {'src': str(SRC), 'python': sys.version.split()[0], 'arms': []}
for label, mode in (('strict-a', 'strict'), ('release', 'release'), ('strict-b', 'strict')):
    r = arm(label, mode)
    rec['arms'].append(r)
    print(f"{label:9s} capture {r['capture_s']:.2f}s open {r['open_ms']:.1f} ms | miss median {r['miss_ms']['median']:.1f} "
          f"(min {r['miss_ms']['min']:.1f}) ms | hit median {r['hit_ms']['median']:.1f} (min {r['hit_ms']['min']:.1f}) ms")
OUT.write_text(json.dumps(rec, indent=1))
shutil.rmtree(WORK, ignore_errors=True)
