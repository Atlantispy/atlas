"""One externally cleared Plan17 phase; importing this module starts nothing.

Long proofs remain held. A manifest hash identifies commands, not permission.
No queue edits, scientific retries, transform promotion or automatic next phase.
"""
import argparse
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
SUPERVISOR = HERE.parents[1] / 'plan15/r2/owned_run.py'
SUPERVISOR_SHA = 'd796ce3c4f11b59c152a00d72de759ca587fd831919bb2dabf6e5a3e84f81e36'
ADMISSION = HERE / 'admission_r7.py'
ADMISSION_SHA = '652c4447893691bb1b892bae450b57d86659ef971452eee40c16e40113e252d2'


def digest(path):
    h = sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def clean_environment(source=None):
    source = os.environ if source is None else source
    remove = {'BASH_ENV', 'ENV', 'RC1_ENV_TEST_HELPERS', 'PYTHONHOME', 'PYTHONPATH'}
    env = {k: v for k, v in source.items() if not k.upper().startswith('PYTHON')
           and k.upper() not in remove}
    env.update(PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1',
               OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
    env['PATH'] = 'C:/Program Files/Git/usr/bin;' + source.get('SystemRoot', 'C:/Windows') + '/System32'
    return env


def seed_problems():
    return (sys.flags.hash_randomization != 0 or sys.flags.ignore_environment or sys.flags.isolated
            or os.environ.get('PYTHONHASHSEED') != '0')


def inventory(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob('*.py'))}


def verify(manifest):
    for path, expected in manifest['pins'].items():
        if digest(path) != expected:
            raise ValueError('changed source/input: ' + path)
    for root, expected in manifest['inventories'].items():
        if inventory(root) != expected:
            raise ValueError('changed Python inventory: ' + root)


@contextmanager
def freeze(paths):
    """Deny writes/deletion of every pinned file until all owned children finish."""
    if os.name != 'nt':
        raise RuntimeError('Windows file freeze required; no fallback')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    held = []
    try:
        for path in paths:
            handle = kernel.CreateFileW(str(Path(path).resolve()), 0x80000000, 1, None, 3, 0x80, None)
            if handle == ctypes.c_void_p(-1).value:
                raise OSError(ctypes.get_last_error(), 'cannot freeze ' + str(path))
            held.append(handle)
        yield
    finally:
        failures = [h for h in reversed(held) if not kernel.CloseHandle(h)]
        if failures:
            raise OSError('failed to release %d source handles' % len(failures))


def load_supervisor():
    if digest(SUPERVISOR) != SUPERVISOR_SHA:
        raise ValueError('reviewed supervisor changed')
    spec = importlib.util.spec_from_file_location('plan17_owned', SUPERVISOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def queue_admission(manifest, phase, *, manifest_path, manifest_sha256):
    """The additive exact-byte shared-gate successor; never edits queue state."""
    if digest(ADMISSION) != ADMISSION_SHA or manifest['pins'].get(str(ADMISSION)) != ADMISSION_SHA:
        raise ValueError('request does not pin the exact admission successor')
    spec = importlib.util.spec_from_file_location('plan17_admission_r2', ADMISSION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.live_admission(manifest, phase, manifest_path=manifest_path,
        manifest_sha256=manifest_sha256, dispatcher=Path(__file__).resolve(), argv=list(sys.orig_argv))


def load_overrun(manifest):
    path = HERE.parent / 'r4/overrun.py'
    if digest(path) != manifest['pins'].get(str(path)):
        raise ValueError('request does not pin the overrun successor')
    spec = importlib.util.spec_from_file_location('plan17_overrun', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def proof_results(manifest, phase):
    out = Path(phase['scientific_output'])
    for stage, count in [('iv1-surfaces', 40968), ('iv2-sample', 901), ('iv2-deep', 216)]:
        result = json.loads((out / ('check-' + stage + '.json')).read_bytes())
        if result.get('status') != 'PASS' or result.get('errors') or result.get('expect_rows') != count:
            raise ValueError('missing/failed stage proof: ' + stage)
        ids = [0, 10, 20, 30, 40, 50] if stage == 'iv2-sample' else list(range(6))
        for arm in phase['arms']:
            expected = phase['runtimes'][('iv1' if stage == 'iv1-surfaces' else 'iv2') + '-' + arm]
            for shard in ids:
                path = out / ('%s-%s-s%d.jsonl' % (stage, arm, shard))
                tail = None
                with path.open(encoding='utf8') as stream:
                    for line in stream:
                        tail = json.loads(line)
                if (not tail or tail.get('done') is not True or tail.get('runtime') != expected['name']
                        or tail.get('package_digest') != expected['package_digest']):
                    raise ValueError('loaded runtime identity differs: ' + str(path))
    return True


def repeat_bindings(phase, manifest_sha):
    path = Path(phase['proof_result'])
    raw = path.read_bytes()
    previous = json.loads(raw)
    if (previous.get('status') != 'PASS' or previous.get('phase') != phase['proof_phase']
            or previous.get('manifest_sha256') != manifest_sha or not previous.get('artifacts')):
        raise ValueError('repeat comparisons require their complete genuine proof first')
    return {str(path): sha256(raw).hexdigest(), **previous['artifacts']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--phase', choices=['controls', 'q23', 'q24', 'repeats23', 'repeats24'], required=True)
    args = parser.parse_args()
    if seed_problems():
        raise ValueError('seed-zero launch required without -I/-E')
    raw = args.manifest.read_bytes()
    if sha256(raw).hexdigest() != args.sha256:
        raise ValueError('request identity changed')
    manifest = json.loads(raw)
    phase = manifest['phases'][args.phase]
    out = Path(phase['result_directory'])
    if any(Path(p).exists() or Path(p).is_symlink() for p in phase['fresh_paths']):
        raise FileExistsError('a planned fresh output/log exists; preserve it')
    repeated = repeat_bindings(phase, args.sha256) if args.phase.startswith('repeats') else {}
    with freeze([str(args.manifest), *manifest['pins'], *repeated]):
        verify(manifest)
        for path, expected in repeated.items():
            if digest(path) != expected:
                raise ValueError('proof artifact changed before repeats: ' + path)
        owned = load_supervisor()
        admission = (queue_admission(manifest, phase, manifest_path=args.manifest,
                     manifest_sha256=args.sha256) if args.phase in ('q23', 'q24') else None)
        out.mkdir(parents=True, exist_ok=False)
        record = dict(schema='plan17-phase.r1', phase=args.phase, manifest_sha256=args.sha256,
                      status='INCOMPLETE', admission=admission, commands=[], long_runs_held_by_default=True)
        env = clean_environment()
        started = time.monotonic()
        overrun = load_overrun(manifest)
        notice_config = dict(manifest['notifications'], phase=args.phase,
            event_id='plan17-' + args.sha256 + '-' + args.phase + '-overrun',
            manifest_sha256=args.sha256, manifest_path=str(args.manifest.resolve()),
            result_directory=str(out), projected_minutes=phase['projected_minutes'])
        event = overrun.GuardedEvent(None, owned, notice_config, env)

        try:
            for index, command in enumerate(phase['commands']):
                log = Path(command.get('stdout', str(out / ('%02d.stdout.log' % index))))
                err = out / ('%02d.stderr.log' % index)
                job = owned.backend()()
                try:
                    with log.open('xb') as stdout, err.open('xb') as stderr:
                        try:
                            job.start(command['argv'], command['cwd'], env, stdout, stderr)
                        except BaseException:
                            job.terminate_owned()
                            raise
                        event.proof = job
                        result = owned.supervise(event, sample=event.sample, sleep=event.sleep)
                    result['ownership'] = dict(job.identity)
                finally:
                    job.close()
                result['argv'] = command['argv']
                result['passed'] = (not result['errors'] and result['finality'] == 'COMPLETE'
                                    and result['exit_code'] == 0)
                record['commands'].append(result)
                if not result['passed']:
                    raise ValueError('owned command failed; no retry or next command')
            verify(manifest)
            record['sources_unchanged'] = True
            if args.phase in ('q23', 'q24'):
                record['pinned_loaded_packages'] = proof_results(manifest, phase)
                scientific = Path(phase['scientific_output'])
                record['artifacts'] = {str(p): digest(p) for p in sorted(scientific.rglob('*'))
                                       if p.is_file() and p.suffix in ('.json', '.jsonl', '.exit')}
            record['status'] = 'PASS'
        except BaseException as failure:
            record['status'] = 'FAIL'
            record['error'] = type(failure).__name__ + ': ' + str(failure)
        finally:
            try:
                record['overrun'] = event.outcome()
                event.close()
            except Exception as failure:
                record['status'] = 'FAIL'
                record['notification_cleanup_error'] = type(failure).__name__ + ': ' + str(failure)
            record['wall_seconds'] = time.monotonic() - started
            with (out / 'result.json').open('x', encoding='utf8') as handle:
                json.dump(record, handle, indent=2)
        print(json.dumps(dict(status=record['status'], phase=args.phase, result=str(out / 'result.json'))))
        return 0 if record['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
