"""T/rm: unprofiled cost of the identity guard's parts on composed-r2 (strict mode, read-only).

Times, per backend actually captured by the interval driver (reference, scipy):
  strict verify()             = verify_boundary with Windows source handles (what strict pays per inner call)
  handles.check()             = strict's source part
  _source_bytes()             = release's source part (release takes no handles; reuse.py:827, 900-904)
  _verify_callable_inventory  = the live in-memory binding walk, same in both modes
A release boundary per backend is _source_bytes + callable walk; release_boundary() runs it for every
captured backend. Nothing here enters release mode, edits source or caches a result.
"""
import json, statistics, sys, time
from pathlib import Path

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2])
N = int(sys.argv[3]) if len(sys.argv) > 3 else 20
sys.path.insert(0, str(SRC))

t0 = time.perf_counter()
import atlas_tectonics
from atlas_tectonics import reuse
import_s = time.perf_counter() - t0
assert Path(reuse.__file__).resolve().is_relative_to(SRC.resolve()), reuse.__file__
assert reuse.execution_mode() == 'strict'


def timed(fn, n=N):
    fn()  # warm once, not counted
    xs = []
    for _ in range(n):
        a = time.perf_counter(); fn(); xs.append(time.perf_counter() - a)
    return {'n': n, 'median_ms': 1e3 * statistics.median(xs), 'min_ms': 1e3 * min(xs), 'max_ms': 1e3 * max(xs)}


rec = {'src': str(SRC), 'python': sys.version.split()[0], 'import_s': import_s, 'backends': {}}
contexts = []
for backend in ('reference', 'scipy'):
    a = time.perf_counter()
    ctx = reuse.ExecutionContext(backend)
    capture_s = time.perf_counter() - a
    contexts.append(ctx)
    r = {'capture_s': capture_s, 'modules': len(ctx._modules), 'tokens': len(ctx._tokens),
         'source_files': len(ctx._sources), 'handles': ctx._source_handles is not None}
    r['strict_verify'] = timed(ctx.verify)
    if ctx._source_handles is not None:
        r['handles_check'] = timed(ctx._source_handles.check)
    r['source_bytes'] = timed(reuse._source_bytes)
    assert ctx._expected is not None
    r['callable_walk'] = timed(lambda: reuse._verify_callable_inventory(
        ctx.backend, ctx._expected, ctx._constants, ctx._modules, ctx._immutable))
    r['projected_release_boundary_ms'] = r['source_bytes']['median_ms'] + r['callable_walk']['median_ms']
    rec['backends'][backend] = r
rec['projected_release_boundary_all_backends_ms'] = sum(
    b['projected_release_boundary_ms'] for b in rec['backends'].values())
for ctx in contexts:
    ctx.close()
OUT.write_text(json.dumps(rec, indent=1))
for name, b in rec['backends'].items():
    print(f"{name}: capture {b['capture_s']:.2f}s modules {b['modules']} tokens {b['tokens']} files {b['source_files']} "
          f"| strict verify {b['strict_verify']['median_ms']:.1f} ms | handles {b.get('handles_check', {}).get('median_ms', float('nan')):.2f} "
          f"| source_bytes {b['source_bytes']['median_ms']:.1f} | walk {b['callable_walk']['median_ms']:.1f} "
          f"| release boundary {b['projected_release_boundary_ms']:.1f} ms")
print(f"release_boundary() over both backends: {rec['projected_release_boundary_all_backends_ms']:.1f} ms")
