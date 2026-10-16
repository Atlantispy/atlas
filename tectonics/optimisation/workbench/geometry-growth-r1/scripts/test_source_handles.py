"""Proof tests for transforms/source_handles.py r2 (admission option 1a(i)). Windows only.

Runs against a throwaway COPY of a composed runtime (it writes, renames and deletes package
sources on purpose) and makes further scratch copies and junctions inside --work-dir (left for
the caller; nothing outside it is touched). Each claim is one check; the summary is JSON,
exit 0 only if all pass:
  open      while a context is open, the OS refuses: append/write, truncate, rename and delete
            of a package source, rename of the package directory, and a write from ANOTHER
            process; verify() still accepts.
  reopen    a context refuses at capture while another process holds a source open for writing.
  junction  (r2) imported through a junction ABOVE the package: retargeting the junction to an
            altered copy is refused by verify() (child process); a junction INSIDE the package
            refuses capture, and one added after capture is refused by verify().
  foreign   (r2) a handle closed behind the context's back is refused by verify().
  release   handles are released on every exit path, checked WHILE the exception is still alive
            where there is one: close(); a `with` block that raises; garbage collection without
            close; a holder dropped without release; failures after locking in source capture,
            in the callable inventory, in the identity computation, and at the end of locking.
  member    an added source file, and an added directory named *.py, are refused by verify().
  timing    median verify_boundary seconds, original (RC1) vs transformed, same package size.
Usage: test_source_handles.py --runtime-copy DIR --work-dir DIR [--baseline-copy DIR]
"""
import _winapi
import argparse
import ctypes
import gc
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[1]
EXTRA = [str(R / 'composed-r1' / 'helpers'), str(R / 'composed-r1' / 'ram'),
         str(HERE.parents[4] / 'heat-repair-20261007' / 'source' / 'tectonics' / 'tests')]

JUNCTION_CHILD = r'''
import json, os, sys, _winapi
link, alt = sys.argv[1], sys.argv[2]
sys.path[:0] = [link, *json.loads(sys.argv[3])]
from atlas_tectonics import reuse
ctx = reuse.ExecutionContext('reference')
ctx.verify()
os.rmdir(link)                       # removes the junction only (allowed: it holds no handle)
_winapi.CreateJunction(alt, link)    # same path, now an altered tree
try:
    ctx.verify()
    print(json.dumps(dict(retarget_refused=False)))
except reuse.TectonicsError as exc:
    print(json.dumps(dict(retarget_refused=True, message=str(exc)[:120])))
'''


def refused(action):
    try:
        action()
    except PermissionError:
        return True
    except OSError as exc:
        return getattr(exc, 'winerror', None) in (5, 32, 33)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runtime-copy', required=True)
    ap.add_argument('--work-dir', required=True)
    ap.add_argument('--baseline-copy', default=None)
    args = ap.parse_args()
    root = Path(args.runtime_copy).resolve()
    work = Path(args.work_dir).resolve()
    work.mkdir(parents=True, exist_ok=False)
    sys.path[:0] = [str(root), *EXTRA]
    from atlas_tectonics import reuse
    package = root / 'atlas_tectonics'
    victim = package / 'integration_volume.py'
    original = victim.read_bytes()
    writable = lambda: not refused(lambda: open(victim, 'ab').close())
    results = {}

    # open: OS refusals while a context is open.
    ctx = reuse.ExecutionContext('reference')
    checks = dict(
        append=refused(lambda: open(victim, 'ab').close()),
        truncate=refused(lambda: open(victim, 'wb').close()),
        rename=refused(lambda: os.replace(victim, victim.with_suffix('.moved'))),
        delete=refused(lambda: os.remove(victim)),
        rename_package_dir=refused(lambda: os.rename(package, package.with_name('atlas_moved'))),
        other_process_write=subprocess.run([sys.executable, '-c', 'open(r"%s", "ab").close()' % victim],
                                           capture_output=True).returncode != 0,
    )
    ctx.verify()
    checks['verify_accepts'] = True
    ctx.close()
    checks['write_after_close'] = writable()
    results['open'] = checks

    # reopen: another process holds a source open for writing -> capture refuses.
    holder = subprocess.Popen([sys.executable, '-c', 'import time\nf = open(r"%s", "r+b")\ntime.sleep(30)' % victim])
    time.sleep(2)
    try:
        reuse.ExecutionContext('reference')
        results['reopen'] = dict(capture_refused=False)
    except reuse.TectonicsError as exc:
        results['reopen'] = dict(capture_refused=True, message=str(exc)[:200])
    finally:
        holder.kill()
        holder.wait()

    # junction: above the package (child process imports through it), and inside the package.
    base, alt, link = work / 'base', work / 'alt', work / 'link'
    shutil.copytree(root, base)
    shutil.copytree(root, alt)
    with open(alt / 'atlas_tectonics' / 'integration_volume.py', 'ab') as stream:
        stream.write(b'\n')
    _winapi.CreateJunction(str(base), str(link))
    child = subprocess.run([sys.executable, '-B', '-c', JUNCTION_CHILD, str(link), str(alt), json.dumps(EXTRA)],
                           capture_output=True, text=True, env=dict(os.environ, PYTHONHASHSEED='0'))
    junction = json.loads(child.stdout.strip().splitlines()[-1]) if child.returncode == 0 else dict(
        retarget_refused=False, child_error=child.stderr[-400:])
    inner_target = work / 'inner'
    inner_target.mkdir()
    (inner_target / 'extra.py').write_text('# probe\n')
    inner = package / 'zz_inner_link'
    _winapi.CreateJunction(str(inner_target), str(inner))
    try:
        reuse.ExecutionContext('reference')
        junction['inside_capture_refused'] = False
    except reuse.TectonicsError:
        junction['inside_capture_refused'] = True
    junction['inside_capture_released'] = writable()
    os.rmdir(inner)
    ctx = reuse.ExecutionContext('reference')
    _winapi.CreateJunction(str(inner_target), str(inner))
    try:
        ctx.verify()
        junction['inside_after_capture_refused'] = False
    except reuse.TectonicsError:
        junction['inside_after_capture_refused'] = True
    os.rmdir(inner)
    ctx.verify()
    ctx.close()
    results['junction'] = junction

    # foreign: one held handle closed behind the context's back.
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    ctx = reuse.ExecutionContext('reference')
    box = ctx._source_handles._box
    stolen = box[len(box) // 2]
    kernel32.CloseHandle(stolen)
    try:
        ctx.verify()
        results['foreign'] = dict(closed_handle_refused=False)
    except reuse.TectonicsError:
        results['foreign'] = dict(closed_handle_refused=True)
    box.remove(stolen)              # so close() does not close the value a second time
    try:
        ctx.close()
    except reuse.TectonicsError:
        pass

    # release on every exit path (checked while any exception is still alive).
    release = {}
    ctx = reuse.ExecutionContext('reference')
    ctx.close()
    release['close'] = writable()
    try:
        with reuse.ExecutionContext('reference'):
            raise RuntimeError('inside')
    except RuntimeError:
        release['with_raises'] = writable()
    ctx = reuse.ExecutionContext('reference')
    del ctx
    gc.collect()
    release['garbage_collected'] = writable()
    held = reuse._SourceHandles()
    release['holder_locks'] = not writable()
    del held
    gc.collect()
    release['holder_dropped'] = writable()

    def inject(name, failing_call=1):
        saved = getattr(reuse, name)
        calls = [0]

        def failing(*a, **k):
            calls[0] += 1
            if calls[0] == failing_call:
                raise MemoryError('injected failure in ' + name)
            return saved(*a, **k)
        setattr(reuse, name, failing)
        try:
            reuse.ExecutionContext('reference')
            return False
        except MemoryError:
            return writable()
        finally:
            setattr(reuse, name, saved)
    release['fail_source_capture'] = inject('_source_bytes')
    release['fail_callable_inventory'] = inject('_callable_inventory')
    release['fail_identity'] = inject('_normal_code')
    release['fail_end_of_locking'] = inject('_directory_id', failing_call=2)
    results['release'] = release

    # member: an added source, and an added directory named *.py, are refused.
    member = {}
    for label, make, undo in (('added_file_refused', lambda p: p.write_text('# probe\n'), Path.unlink),
                              ('added_dir_named_py_refused', Path.mkdir, Path.rmdir)):
        ctx = reuse.ExecutionContext('reference')
        extra = package / 'zz_added_probe.py'
        make(extra)
        try:
            ctx.verify()
            member[label] = False
        except reuse.TectonicsError:
            member[label] = True
        finally:
            undo(extra)
            try:
                ctx.close()
            except reuse.TectonicsError:
                pass
    results['member'] = member

    # timing: transformed verify_boundary.
    ctx = reuse.ExecutionContext('reference')
    times = []
    for _ in range(30):
        t = time.perf_counter()
        ctx.verify_boundary()
        times.append(time.perf_counter() - t)
    ctx.close()
    times.sort()
    results['timing'] = dict(transformed_median_s=round(times[len(times)//2], 4))
    victim.write_bytes(original)
    if args.baseline_copy:
        out = subprocess.run([sys.executable, '-B', '-c', (
            'import sys,time\nsys.path[:0]=[r"%s", *%r]\nfrom atlas_tectonics import reuse\n'
            'c=reuse.ExecutionContext("reference")\nts=[]\n'
            'for _ in range(30):\n    t=time.perf_counter(); c.verify_boundary(); ts.append(time.perf_counter()-t)\n'
            'ts.sort(); print(ts[len(ts)//2])') % (Path(args.baseline_copy).resolve(), EXTRA)],
            capture_output=True, text=True)
        results['timing']['original_median_s'] = round(float(out.stdout.strip() or 'nan'), 4)
    ok = (all(results['open'].values()) and results['reopen']['capture_refused']
          and all(v for k, v in results['junction'].items() if k != 'message')
          and results['foreign']['closed_handle_refused']
          and all(results['release'].values()) and all(results['member'].values()))
    print(json.dumps(dict(ok=ok, **results), indent=1))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
