"""Exact-source R7 regression evidence. Never a production/scientific release.

This successor does not borrow the old R5 367-test release receipt or shape.
It records each discovered, started, stopped and successful test identity,
the actually compiled local sources, and the preserved predecessor closure.
"""
from __future__ import annotations

if __name__=='__main__':
    from pathlib import Path as _Path
    import sys as _sys
    import types as _types
    _path=_Path(__file__).absolute().with_name('release_source_runtime.py')
    _raw=_path.read_bytes();_helper=_types.ModuleType('_r7_exact_verification_bootstrap')
    _helper.__file__=str(_path);_helper.EXECUTED_SOURCE_BYTES=_raw
    _sys.modules[_helper.__name__]=_helper
    exec(compile(_raw,str(_path),'exec',dont_inherit=True,optimize=0),_helper.__dict__)
    raise SystemExit(_helper.launch(_path.parent))

import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import time
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]/'outputs'/'module-corrections-2026-09-10'


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()


def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from flatten(item)
        else:yield item


def execution_complete(expected,started,stopped,successful):
    return bool(expected) and len(set(expected))==len(expected) and expected==started==stopped==successful


class TrackedResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.started=[];self.stopped=[];self.successful=[]
    def startTest(self,test):
        self.started.append(test.id());super().startTest(test)
    def stopTest(self,test):
        self.stopped.append(test.id());super().stopTest(test)
    def addSuccess(self,test):
        self.successful.append(test.id());super().addSuccess(test)


def main(argv=None,*,runtime=None):
    if runtime is None or not runtime.installed:
        raise ValueError('R7 verification requires the fresh exact-source bootstrap')
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    from r4_io import io as safe_io,verify_dependencies
    output=safe_io.unlinked(args.output.absolute());root=safe_io.unlinked(ROOT)
    if output.parent!=root or output.suffix!='.json' or output.exists():
        raise ValueError('new direct-child JSON verification evidence required')
    started=time.perf_counter();sources=runtime.pins;closure=verify_dependencies()
    inventory=json.loads(runtime.raw['TEST_INVENTORY.json'])
    files=sorted(p.name for p in HERE.glob('test*.py'))
    if files!=inventory['files']:raise ValueError('R7 test file inventory drift')
    loader=unittest.TestLoader();suite=loader.loadTestsFromNames(inventory['modules'])
    ids=[test.id() for test in flatten(suite)]
    if loader.errors or ids!=inventory['test_ids'] or digest(ids)!=inventory['test_ids_sha256']:
        raise ValueError('R7 complete test discovery identity drift')
    runtime.check()
    result=unittest.TextTestRunner(stream=sys.stderr,verbosity=2,resultclass=TrackedResult).run(suite)
    executed=runtime.check();after_closure=verify_dependencies()
    complete=(result.wasSuccessful() and not (result.skipped or result.expectedFailures or result.unexpectedSuccesses)
        and execution_complete(ids,result.started,result.stopped,result.successful) and closure==after_closure
        and all(name in {p['name'] for p in executed} for name in files))
    evidence={'schema':'diadem.terrain.r7.scientific-correction-verification.v1',
        'status':'PASS' if complete else 'FAIL','scope':'BOUNDED_SYNTHETIC_REGRESSIONS_ONLY',
        'tests_run':result.testsRun,'test_ids':ids,'test_ids_sha256':digest(ids),
        'started_test_ids':result.started,'stopped_test_ids':result.stopped,'successful_test_ids':result.successful,
        'failures':[{'test':t.id(),'traceback':trace} for t,trace in result.failures],
        'errors':[{'test':t.id(),'traceback':trace} for t,trace in result.errors],
        'skips':[t.id() for t,_ in result.skipped],
        'expected_failures':[t.id() for t,_ in result.expectedFailures],
        'unexpected_successes':[t.id() for t in result.unexpectedSuccesses],
        'sources':sources,'executed_local_sources':executed,'predecessor_sources':closure,
        'source_snapshot_sha256':digest(sources),'sources_unchanged':True,
        'predecessors_unchanged':closure==after_closure,'elapsed_seconds':time.perf_counter()-started,
        'python':sys.version,'python_optimise_flag':sys.flags.optimize,'platform':platform.platform(),
        'physical_acceptance':False,'production_authorised':False,'diadem_canon_changed':False,
        'inherited_test_mapping':inventory['inherited_mapping']}
    root.mkdir(parents=True,exist_ok=True);safe_io.unlinked(root)
    raw=canonical(evidence)
    with output.open('xb') as stream:stream.write(raw)
    if safe_io.read_bytes(output)!=raw:raise ValueError('verification evidence readback mismatch')
    print(json.dumps({'status':evidence['status'],'tests_run':result.testsRun,
                     'elapsed_seconds':evidence['elapsed_seconds'],'output':str(output),
                     'sha256':hashlib.sha256(raw).hexdigest()},sort_keys=True))
    return 0 if complete else 1
