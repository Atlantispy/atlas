"""Run the optimised independent structural audit; not a tectonic simulation."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from work.generator_runtime_r12 import _raw

_SOURCE = _raw(Path(__file__))
if sys._getframe().f_code != compile(_SOURCE,__file__,'exec',dont_inherit=True):
    raise ValueError('executed Tectonics R3 entrypoint differs')
_R12_EXECUTED_SHA256 = hashlib.sha256(_SOURCE).hexdigest()
from . import provenance

def run_audit(package, replay_root, visual_review=None):
    started = time.perf_counter()
    sources = provenance.sources()
    primary = None
    try:
        from . import audit
        result = audit.audit_package(Path(package),Path(replay_root),visual_review)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            provenance.verify(sources)
        except BaseException as exc:
            if primary is not None:
                primary.tectonics_r3_cleanup_errors = [str(exc)]
            else:
                raise
    return {'schema':'diadem.tectonics-r3-audit-execution.v1','audit':result,
        'elapsed_seconds':time.perf_counter()-started,'sources':sources,
        'science_or_acceptance_changed':False}

def main():
    parser = argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--replay-root',type=Path,required=True)
    parser.add_argument('--visual-review',type=Path)
    args = parser.parse_args()
    result = run_audit(args.package,args.replay_root,args.visual_review)
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0 if result['audit']['overall_status'] == 'PASS' else 2

if __name__ == '__main__':
    raise SystemExit(main())
