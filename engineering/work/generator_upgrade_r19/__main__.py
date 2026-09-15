"""Run a bounded source-backed coastal reference; caching is on by default."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from work.generator_runtime_r12 import _raw

_SOURCE = _raw(Path(__file__))
if sys._getframe().f_code != compile(_SOURCE, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed R19 CLI differs from current source')
_R12_EXECUTED_SHA256 = hashlib.sha256(_SOURCE).hexdigest()

from . import working, driver, provenance as p


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=sorted(working.CASES), default='C1_NATIVE_RIVER_TO_COAST')
    parser.add_argument('--stop-seconds', default='3600')
    parser.add_argument('--max-step-seconds', default='30')
    parser.add_argument('--phase-points', type=int, choices=(16, 32), default=16)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--no-cache', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('outputs/generator-upgrade-r19'))
    args = parser.parse_args(argv)
    start = time.perf_counter(); run = None; error = None
    try:
        if args.resume is None:
            run, _ = working.build_case(args.case, cache=not args.no_cache)
        else:
            run = driver.CoastalRun.restore(json.loads(args.resume.read_bytes()))
        working.run_case(run, args.case, stop_s=args.stop_seconds,
            max_step_s=args.max_step_seconds, phase_points=args.phase_points, cache=not args.no_cache)
    except Exception as exc:
        error = type(exc).__name__+': '+str(exc)
    saved = None
    if run is not None:
        value = run.checkpoint()
        args.output.mkdir(parents=True, exist_ok=True)
        saved = args.output/('run-'+args.case[:2]+'-'+p.sha(value)[:16]+'.json')
        raw = p.encoded(value)
        try:
            with saved.open('xb') as stream:
                stream.write(raw)
        except FileExistsError:
            if saved.read_bytes() != raw:
                raise ValueError('existing coastal output differs; preserved without overwrite')
    print(json.dumps({'status': 'INCOMPLETE' if error else 'PASS', 'error': error,
        'time_s': str(run.time) if run else None, 'checkpoint': str(saved) if saved else None,
        'elapsed_wall_seconds': time.perf_counter()-start,
        'cache': getattr(run, 'cache_reporting', {}) if run else {},
        'scope': 'WORKING NON-CANON MATERIAL/NUMERICAL REFERENCE; NOT ACTUAL SEA GEOGRAPHIC COUPLING'}))
    return 1 if error else 0


if __name__ == '__main__':
    raise SystemExit(main())
