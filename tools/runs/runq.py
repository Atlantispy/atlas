"""Heavy-run queue for a configured Atlas installation.

The operator maintains the queue. The `run` command waits
`run`, which waits until (1) the ticket is first in the queue, (2) nothing else from the queue
is running, (3) the cooperative lock is free and (4) free memory covers the ticket's TOTAL
peak + 1 GiB floor + 4 GiB headroom. It then takes the same lock file as heavy_lock.py,
runs the command and records the outcome. A runner that dies frees its place (its PID is
checked), so a crash can't block the queue.

  python -B -I runq.py status [--all]
  python -B -I runq.py worker TICKET
  python -B -I runq.py worker small [--cores N] [--gib G] [--provider ABSOLUTE_DIR] -- ARGV...
  python -B -I runq.py run [--strict-admission] <ticket> -- <command> [args...]
      (--strict-admission refuses any admission wait or CPU fallback)
  python -B -I runq.py note <ticket> "<one-line result + output path>"   (owner, after done)
  python -B -I runq.py small [--cores N] -- <command> [args...]   (unticketed small work: waits while
      a quiet ticket runs or the cores are taken, then runs at below-normal priority)
  python -B -I runq.py add --owner O --gib G --min M --what W [--why ..] [--runtime ..]
                           [--inputs ..] [--outputs ..] [--pos N] [--status queued|external]
  python -B -I runq.py reorder <ticket> <pos> | cancel <ticket> | finish <ticket> <exit>
  python -B -I runq.py hold on|off [--why TEXT]   (no new ticket starts while on; running ones finish)
  (add/reorder/cancel/finish/hold/setcpu: coordinator only)
  Set RUNQ_DIR to the absolute queue state directory and RUNQ_LOCK to the absolute heavy-lock file.
  RUNQ_MACHINE_RESOURCES selects the resource provider directory. Tracked workers obtain the provider
  from the external launch record or the state directory's worker-settings.json.
"""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

SCRIPT = Path(__file__).resolve()
HERE, LOCK = (Path(os.environ.get(key, '')) for key in ('RUNQ_DIR', 'RUNQ_LOCK'))
if not HERE.is_absolute() or not LOCK.is_absolute():
    raise SystemExit('set RUNQ_DIR and RUNQ_LOCK to absolute queue state and heavy-lock paths')
HERE, LOCK = HERE.resolve(), LOCK.resolve()
QUEUE = HERE / 'queue.json'
MUTEX = HERE / '.mutex'
if LOCK in (HERE, QUEUE, MUTEX, HERE/'peaks.json', HERE/'small-reaped.jsonl', HERE/'worker-settings.json'):
    raise SystemExit('RUNQ_LOCK must name a separate heavy-lock file')
POLL_S = int(os.environ.get("RUNQ_POLL", 30))
MAX_WAIT_S = 12 * 3600
GIB = 2 ** 30


def machine_modules(folder=None):
    """The package's monitor and gate, by path from RUNQ_MACHINE_RESOURCES (each imports nothing of the package).
    Compiled from their bytes so that no bytecode is written into that tree."""
    folder = (os.environ.get('RUNQ_MACHINE_RESOURCES', '') if folder is None else folder).strip()
    if not folder:
        raise SystemExit('RUNQ_MACHINE_RESOURCES is not set: name the folder holding machine_resources_monitor.py '
                         'and resources_gate.py')
    loaded = []
    for name in ('machine_resources_monitor', 'resources_gate'):
        path = Path(folder) / (name + '.py')
        if not path.is_file():
            raise SystemExit('RUNQ_MACHINE_RESOURCES: %s is not a file' % path)
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader('runq_' + name, None, origin=str(path)))
        module.__file__ = str(path)
        exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
        loaded.append(module)
    return loaded


def init_resources(folder=None):
    global monitor, gate, PHYSICAL, FREE_FLOOR_GIB
    monitor, gate = machine_modules(folder)
    PHYSICAL = monitor.machine_cores()
    FREE_FLOOR_GIB = gate.FLOOR_BYTES / GIB


if __name__ != '__main__':
    init_resources()  # existing read-only runpy users
RESERVE_CORES = 2          # desktop app, chats, system
CPU_WAIT_MAX_S = 600       # a ticket waits at most 10 min for free cores, then starts and logs it
# Memory start gate by need (Michael, 16 Oct ~14:05), replacing the blanket TOTAL + 5 GiB. The in-run guards still
# stop a run cleanly; the start gate only avoids starting runs that would hit them. The need is the package
# gate's start_need: the predicted peak, a fifth of it, the free floor and the allowance.
PAUSED_EXIT = 75  # a chain's deliberate pause (driver r31), not a failure
# Pause (Michael, 16 Oct ~14:45, gaming): tickets are paused one by one with hold-ticket (old runners obey a
# status change); new small jobs above this many cores wait, because a worker-count smoke on a loaded machine can
# silently run serial and have to be redone.
PAUSE_SMALL_CORES = 2


def mem_need(gib):
    return round(gate.start_need(math.ceil(gib * GIB)) / GIB, 1)


# Peak prediction (Michael, 16 Oct ~14:08: "Have the gate predict peak usage to decide each threshold").
# Every successful run (ticket or small job) records its measured tree peak under a command key. The gate
# predicts a job's peak as the largest recorded peak for the same key, and falls back to the booking (from the
# owner's smoke) when the command has never run. After each run the measured peak is printed next to the
# prediction so bookings can come down with evidence.
PEAKS = HERE / 'peaks.json'
PEAK_HISTORY = 10


def cmd_key(command):
    """Script, flags and existing inputs. A path that doesn't exist yet (a new output folder) is dropped, so a
    rerun of the same job on the same inputs shares the key. Call it before the job runs."""
    def norm(a):
        s = a.replace('\\', '/')
        if '/' in s or s.endswith(('.py', '.sh', '.json')):
            return s.rstrip('/').rsplit('/', 1)[-1] if os.path.exists(a) else None
        return s
    out = []
    for a in command:
        if a.startswith('-') and '=' in a:
            k, v = a.split('=', 1)
            v = norm(v)
            out.append(k if v is None else '%s=%s' % (k, v))
        else:
            v = norm(a)
            if v is not None:
                out.append(v)
    return ' '.join(out)[:400]


def load_peaks():
    try:
        return json.loads(PEAKS.read_text(encoding='utf8'))
    except (FileNotFoundError, ValueError):
        return {}


def predict_peak(key, fallback):
    # Only peaks measured through the job object count (16 Oct ~15:45). Earlier ones followed the parent chain
    # only and missed children a shell had detached (Git Bash `cmd &`, `timeout`): 0.01 GiB seen for 0.22.
    hist = [h for h in (load_peaks().get(key) or []) if h.get('tracker') == 'job']
    if hist:
        return max(h['peak'] for h in hist), 'max of %d earlier job-tracked run(s) of this command' % len(hist)
    return float(fallback), 'booking (no earlier job-tracked run of this command)'


def record_peak(key, peak, who, tracker):
    """Caller holds the Mutex."""
    peaks = load_peaks()
    peaks[key] = (peaks.get(key) or [])[-(PEAK_HISTORY - 1):] + [dict(peak=round(peak, 2), who=who, when=now(),
                                                                       tracker=tracker)]
    tmp = PEAKS.with_suffix('.tmp')
    tmp.write_text(json.dumps(peaks, indent=1), encoding='utf8')
    os.replace(tmp, PEAKS)


def tree_rss_gib(proc):
    try:
        return sum(p.memory_info().rss for p in [proc] + proc.children(recursive=True) if p.is_running()) / GIB
    except psutil.Error:
        return 0.0


# Windows job object tracking (16 Oct ~15:45, after Exact kernels found the blind spot). The runq process puts
# itself in a named job before starting the command, so every descendant inherits membership even when a shell
# detaches it from the parent chain. Peaks sum the job's processes (and the parent chain, as before) minus runq.
_K32 = ctypes.WinDLL('kernel32', use_last_error=True) if os.name == 'nt' else None
if _K32 is not None:
    from ctypes import wintypes
    _K32.CreateJobObjectW.restype = wintypes.HANDLE
    _K32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _K32.OpenJobObjectW.restype = wintypes.HANDLE
    _K32.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    _K32.GetCurrentProcess.restype = wintypes.HANDLE
    _K32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _K32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                               ctypes.c_void_p]
    _K32.CloseHandle.argtypes = [wintypes.HANDLE]
    _K32.OpenProcess.restype = wintypes.HANDLE
    _K32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

    class _JobPids(ctypes.Structure):
        _fields_ = [('assigned', wintypes.DWORD), ('listed', wintypes.DWORD), ('ids', ctypes.c_size_t * 4096)]

    class _JobLimits(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION (basic limits, IO counters, four sizes)
        _fields_ = [('per_process_user_time', ctypes.c_int64), ('per_job_user_time', ctypes.c_int64),
                    ('limit_flags', wintypes.DWORD), ('minimum_working_set', ctypes.c_size_t),
                    ('maximum_working_set', ctypes.c_size_t), ('active_process_limit', wintypes.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority_class', wintypes.DWORD),
                    ('scheduling_class', wintypes.DWORD), ('io_counters', ctypes.c_uint64 * 6),
                    ('process_memory_limit', ctypes.c_size_t), ('job_memory_limit', ctypes.c_size_t),
                    ('peak_process_memory_used', ctypes.c_size_t), ('peak_job_memory_used', ctypes.c_size_t)]
    _K32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _K32.SetInformationJobObject.restype = wintypes.BOOL


def pid_exists(pid):
    """Treat a Windows access-denied probe as possibly alive, never as a stale owner.

    Restricted callers can receive False from psutil for an elevated live process.
    Confirm a negative using limited-query access; only INVALID_PARAMETER proves
    an absent Windows PID. Unexpected probe failures stop admission explicitly.
    """
    if psutil.pid_exists(pid):
        return True
    if _K32 is None or pid <= 0 or pid > 0xffffffff:
        return False
    handle = _K32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        _K32.CloseHandle(handle)
        return True
    error = ctypes.get_last_error()
    if error == 5:  # ERROR_ACCESS_DENIED: existence cannot safely be ruled out
        return True
    if error == 87:  # ERROR_INVALID_PARAMETER: no such PID
        return False
    raise ctypes.WinError(error)


def make_job(name, kill_on_close=False):
    """Create the named job and put this process in it; None (parent-chain tracking only) if that fails.

    kill_on_close (small commands only, decision 962): Windows ends every process in the job when its last handle
    closes, which the owner's exit or death is. If the limit cannot be set, None."""
    if _K32 is None:
        return None
    h = _K32.CreateJobObjectW(None, name)
    if not h:
        return None
    if kill_on_close:
        limits = _JobLimits(limit_flags=0x2000)  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _K32.SetInformationJobObject(h, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            _K32.CloseHandle(h)
            return None
    if not _K32.AssignProcessToJobObject(h, _K32.GetCurrentProcess()):
        _K32.CloseHandle(h)
        return None
    return h


def job_pids(h):
    if not h:
        return set()
    buf = _JobPids()
    if not _K32.QueryInformationJobObject(h, 3, ctypes.byref(buf), ctypes.sizeof(buf), None):
        return set()
    return {int(buf.ids[i]) for i in range(buf.listed)}


def tracked_rss_gib(job, root, exclude=()):
    """RSS of the job's processes plus root's parent-chain tree, without the runq process(es) in `exclude`."""
    pids = set(job_pids(job))
    try:
        if root is not None:
            pids |= {root.pid} | {c.pid for c in root.children(recursive=True)}
    except psutil.Error:
        pass
    total = 0
    for pid in pids - set(exclude):
        try:
            total += psutil.Process(pid).memory_info().rss
        except psutil.Error:
            pass
    return total / GIB


def free_cores():
    return PHYSICAL * (1 - psutil.cpu_percent(interval=2) / 100)


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


class Mutex:
    def __init__(self, *, wait=True):
        self.wait = wait

    def __enter__(self):
        for _ in range(600 if self.wait else 1):
            try:
                os.mkdir(MUTEX)
                return self
            except FileExistsError:
                try:
                    if time.time() - MUTEX.stat().st_mtime > 120:
                        os.rmdir(MUTEX)
                        continue
                except OSError:
                    pass
                if not self.wait:
                    raise SystemExit('queue mutex busy (strict admission; no wait)')
                time.sleep(0.2)
        raise SystemExit('queue mutex busy for 2 min' if self.wait else
                         'queue mutex unavailable (strict admission; no wait)')

    def __exit__(self, *exc):
        try:
            os.rmdir(MUTEX)
        except OSError:
            pass


def load():
    if not QUEUE.exists():
        return {'next_id': 1, 'tickets': []}
    return json.loads(QUEUE.read_text(encoding='utf8'))


def save(q):
    tmp = QUEUE.with_suffix('.tmp')
    tmp.write_text(json.dumps(q, indent=1), encoding='utf8')
    os.replace(tmp, QUEUE)


def find(q, tid):
    for t in q['tickets']:
        if t['id'] == tid:
            return t
    raise SystemExit('no ticket %s' % tid)


def pending(reserved, exclude=None):
    return [row for row in reserved if row['status'] == 'queued' and row is not exclude]


def reap(q):
    """Mark tickets whose runner died as 'died' so they can't block the queue."""
    changed = False
    for t in q['tickets']:
        if t['status'] == 'running' and t.get('runner_pid') and not pid_exists(t['runner_pid']):
            t['status'] = 'died'
            t['ended'] = now()
            changed = True
    return changed


def lock_holder():
    try:
        held = json.loads(LOCK.read_text(encoding='utf8'))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {'unreadable': True}
    pid = int(held.get('pid', -1))
    if not pid_exists(pid):
        return None  # stale
    born = held.get('birth')
    if born is not None and small_birth(pid) not in (None, born):
        return None  # stale: the pid now belongs to another process (decision 1188)
    return held


def try_lock(t):
    body = json.dumps(dict(owner=t['owner'], pid=os.getpid(), msys_pid=os.getpid(),
                           expected_peak_gib=float(t['gib']), started=now(), birth=small_birth(os.getpid()),
                           what='queue %s: %s (TOTAL)' % (t['id'], t['what'])))
    for _ in range(2):
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if lock_holder() is not None:
                return False
            try:
                LOCK.unlink()  # stale: holder's PID is dead
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, 'w', encoding='utf8') as f:
            f.write(body)
        return True
    return False


def unlock():
    try:
        held = json.loads(LOCK.read_text(encoding='utf8'))
    except (OSError, ValueError):
        return
    if int(held.get('pid', -1)) == os.getpid():
        LOCK.unlink()


# Plan09: one bounded active-small set in the existing queue file, under Mutex.
SMALL_ACTIVE_KEY = 'small_commands'
SMALL_ACTIVE_LIMIT = 256
SMALL_JOB_GONE = 'recorded small job no longer exists (Windows error 2)'
SMALL_REAPED = HERE / 'small-reaped.jsonl'
SMALL_KILL_MARK = ':k'  # the third part of a row id: its job was made kill-on-close (decision 962)


def small_birth(pid):
    try:
        return psutil.Process(pid).create_time()
    except psutil.Error:
        return None


def small_rows(q):
    rows = q.get(SMALL_ACTIVE_KEY, [])
    if type(rows) is not list or len(rows) > SMALL_ACTIVE_LIMIT:
        raise SystemExit('active small command registry is invalid or exceeds its bound')
    ids = set()
    for row in rows:
        if (type(row) is not dict or set(row) != {'id', 'owner_pid', 'owner_birth', 'child_pid',
                                                'child_birth', 'job_name'} or
                type(row['id']) is not str or not row['id'] or len(row['id']) > 120 or row['id'] in ids):
            raise SystemExit('active small command row is invalid or duplicated')
        ids.add(row['id'])
        for field in ('owner_pid', 'child_pid'):
            if field == 'child_pid' and row[field] is None:
                continue
            if type(row[field]) is not int or not 0 < row[field] <= 0xffffffff:
                raise SystemExit('active small command PID is invalid')
        for field in ('owner_birth', 'child_birth'):
            if row[field] is not None and (type(row[field]) not in (int, float) or not 0 < row[field] < 1e12):
                raise SystemExit('active small command birth time is invalid')
        if row['job_name'] not in (None, 'Local\\runq-small-%d' % row['owner_pid']):
            raise SystemExit('active small command job identity is invalid')
    return rows


def small_job_members(row):
    """Query the existing named job strictly: unavailable is unknown, never empty. A name that no longer exists
    (Windows error 2) returns SMALL_JOB_GONE, which clears only a kill-on-close row whose owner is dead (decision 962)."""
    if _K32 is None or not row['job_name']:
        return None, 'no job identity available'
    handle = _K32.OpenJobObjectW(0x0004, False, row['job_name'])
    if not handle:
        error = ctypes.get_last_error()
        if error == 2:
            return None, SMALL_JOB_GONE
        return None, 'cannot open recorded small job (Windows error %d)' % error
    try:
        buf = _JobPids()
        if not _K32.QueryInformationJobObject(handle, 3, ctypes.byref(buf), ctypes.sizeof(buf), None):
            return None, 'cannot query recorded small job (Windows error %d)' % ctypes.get_last_error()
        if buf.assigned > buf.listed or buf.listed > len(buf.ids):
            return None, 'recorded small job membership exceeds query capacity'
        members = {int(buf.ids[index]) for index in range(buf.listed)}
        if row['owner_pid'] in members:
            born = small_birth(row['owner_pid'])
            if born is None or row['owner_birth'] is None or born != row['owner_birth']:
                return None, 'recorded small owner birth is unavailable or differs'
            members.remove(row['owner_pid'])
        return {pid for pid in members if pid_exists(pid)}, None
    finally:
        _K32.CloseHandle(handle)


def small_process_names():
    """One bounded native snapshot for psutil's unnamed protected processes."""
    if _K32 is None:
        return {}, 'native process names unavailable'
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                    ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
                    ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]

    _K32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _K32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    for api in (_K32.Process32FirstW, _K32.Process32NextW):
        api.restype = wintypes.BOOL
        api.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    handle = _K32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if handle in (None, ctypes.c_void_p(-1).value):
        return {}, 'native process snapshot failed (Windows error %d)' % ctypes.get_last_error()
    names = {}
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        more = _K32.Process32FirstW(handle, ctypes.byref(entry))
        for _ in range(65536):
            if not more:
                error = ctypes.get_last_error()
                return names, None if error == 18 else 'native process enumeration failed (Windows error %d)' % error
            names[int(entry.th32ProcessID)] = entry.szExeFile
            more = _K32.Process32NextW(handle, ctypes.byref(entry))
        return names, 'native process enumeration exceeded its bound'
    finally:
        _K32.CloseHandle(handle)


def scan_small_commands():
    """Legacy discovery plus conservative visibility for Python queue wrappers."""
    def queue_command(command):
        names = ('runq.py', Path(__file__).name.casefold())
        return 'small' in command and any(Path(item).name.casefold() in names for item in command)

    owners, unknown = set(), []
    native_names, native_problem = None, None

    def identify(pid, name):
        nonlocal native_names, native_problem
        if name:
            return name.casefold()
        if native_names is None:
            native_names, native_problem = small_process_names()
        return (native_names.get(pid) or '').casefold()

    for proc in psutil.process_iter(['name', 'cmdline']):
        name, identified_queue = '', False
        try:
            info = proc.info
            command = info.get('cmdline')
            name = identify(proc.pid, info.get('name') or '')
            if not command:
                if name.startswith('python'):
                    unknown.append('PID %d has unavailable Python command line' % proc.pid)
                elif not name:
                    unknown.append('PID %d cannot be identified: %s' % (proc.pid, native_problem or 'empty native name'))
                continue
            if not queue_command(command):
                continue
            identified_queue = True
            for child in proc.children():
                try:
                    if not queue_command(child.cmdline() or []):
                        owners.add(proc.pid)
                        break
                except psutil.NoSuchProcess:
                    continue
                except psutil.Error:
                    unknown.append('small owner %d has an unreadable child' % proc.pid)
                    break
        except psutil.NoSuchProcess:
            continue
        except psutil.Error:
            name = identify(proc.pid, name)
            if identified_queue or not name or name.startswith('python'):
                unknown.append('PID %d has unresolved process visibility' % proc.pid)
    return owners, unknown


def small_owner_gone(row):
    """Decision 962: the owner is dead, or its pid now has another birth; an unreadable birth counts as alive."""
    owner = row['owner_pid']
    if not pid_exists(owner):
        return 'owner %d dead' % owner
    born = small_birth(owner)
    if born is None or row['owner_birth'] is None or born == row['owner_birth']:
        return None
    return 'owner pid %d reused' % owner


def small_reap(row):
    """Caller holds Mutex. A kill-on-close row whose job is gone and whose owner is dead: append its line, then it
    may be left out. Returns (cleared, problem); a failed append keeps the row with an unknown line."""
    if not row['id'].endswith(SMALL_KILL_MARK) or small_job_members(row)[1] != SMALL_JOB_GONE:
        return False, None
    fact = small_owner_gone(row)
    if fact is None:
        return False, None
    text = json.dumps({'time': now(), 'row': row, 'job': SMALL_JOB_GONE, 'owner': fact}, sort_keys=True)
    try:
        with SMALL_REAPED.open('a', encoding='utf8') as log:
            log.write(text + '\n')
    except OSError as error:
        return False, 'small admission %s: reap line not written (%s)' % (row['id'], error)
    print('small: reaped row ' + text, flush=True)
    return True, None


def small_admission_state(q):
    """Caller holds Mutex. Reap a dead recorded child with a proved empty job, or a kill-on-close row whose job is
    gone by name and whose owner is dead (decision 962)."""
    owners, unknown = scan_small_commands()
    retained = []
    for row in small_rows(q):
        child = row['child_pid']
        if child is None or not pid_exists(child):
            cleared, problem = small_reap(row)
            if cleared:
                continue
            if problem:
                retained.append(row)
                owners.add(row['owner_pid'])
                unknown.append(problem)
                continue
        if child is None:
            retained.append(row)
            owners.add(row['owner_pid'])
            unknown.append('small admission %s has no committed child identity' % row['id'])
            continue
        if pid_exists(child):
            born = small_birth(child)
            if born is None or row['child_birth'] is None or born != row['child_birth']:
                unknown.append('small child %d birth is unavailable or differs' % child)
            retained.append(row)
            owners.add(row['owner_pid'])
            continue
        members, problem = small_job_members(row)
        if members is None:
            retained.append(row)
            owners.add(row['owner_pid'])
            unknown.append('small admission %s: %s' % (row['id'], problem))
        elif members:
            retained.append(row)
            owners.add(row['owner_pid'])
        # No members plus conservative pid_exists(False) proves this payload finished.
    if SMALL_ACTIVE_KEY in q or retained:
        q[SMALL_ACTIVE_KEY] = retained
    return len(owners), unknown


def small_exclusive_head(q):
    """Only an unheld, live ready head reserves exclusive admission."""
    if q.get('hold'):
        return False
    ready = live_waiters(q)
    return bool(ready and ready[0].get('exclusive'))


def finish_small_admission(row, code):
    """Own completion can retire its row; live job descendants retain the fence."""
    if code is None:
        return
    with Mutex():
        q = load()
        rows = small_rows(q)
        current = next((item for item in rows if item['id'] == row['id']), None)
        if current is None:
            return
        members, problem = small_job_members(current)
        if members is None or members:
            print('small: retaining admission %s: %s' % (
                row['id'], problem if members is None else '%d job descendant(s) still active' % len(members)), flush=True)
            return  # Descendants or unresolved visibility still block exclusive admission.
        q[SMALL_ACTIVE_KEY] = [item for item in rows if item['id'] != row['id']]
        save(q)



BOOKING_FIELDS = ('cores', 'gib', 'min', 'pos')


def booking_values(row):
    return {key: row.get(key, 1 if key == 'cores' else None) for key in BOOKING_FIELDS}


def isolation(row):
    return {key: bool(row.get(key)) for key in ('quiet', 'exclusive')}


def wait_binding(row):
    return {'booking': booking_values(row), 'mode': 'strict',
            'sha256': row.get('launch', {}).get('sha256')}


def live_waiters(q):
    rows = []
    for row in q['tickets']:
        launch = row.get('launch')
        if row['status'] != 'queued' and not pending_continuation(row):
            continue
        if launch and (row.get('ticket_hold') or row.get('waiting_digest') != launch['sha256']
                       or launch.get('position_changed') or launch.get('go_consumed')
                       or not launch.get('go_at') or not launch.get('ready_at')
                       or not launch.get('authority') or go_expired(launch) or q.get('pause')):
            continue
        if row.get('waiting_pid') and pid_exists(row['waiting_pid']):
            rows.append(row)
    return sorted(rows, key=lambda row: row['pos'])


def absolute_path(value):
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise SystemExit('launch record requires absolute paths')
    return Path(os.path.abspath(value))


def read_launch(path, sha):
    path = absolute_path(path)
    if not isinstance(sha, str) or len(sha) != 64 or any(char not in '0123456789abcdef' for char in sha):
        raise SystemExit('expected a lower-case SHA-256')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise SystemExit('launch descriptor digest mismatch')
    return json.loads(raw)


def validate_launch(record):
    booking = record['booking']
    if (any(type(booking[key]) is not int or booking[key] < 1 for key in ('cores', 'min', 'pos'))
            or type(booking['gib']) not in (int, float) or not math.isfinite(booking['gib'])
            or booking['gib'] <= 0 or booking['mode'] not in ('adaptive', 'fixed')
            or booking['mode'] == 'adaptive' and booking['cores'] != 1):
        raise SystemExit('invalid launch booking')
    if not isinstance(record['owner'], str) or not record['owner'].strip():
        raise SystemExit('launch record requires an owner label')
    for key in ('scope', 'predicted_runtime', 'runtime_basis'):
        if not isinstance(record[key], str) or not record[key].strip():
            raise SystemExit('launch record requires ' + key)
    if not isinstance(record['payload'], list) or not record['payload'] or any(
            not isinstance(arg, str) for arg in record['payload']):
        raise SystemExit('launch record requires an argument list')
    for key in ('cwd', 'queue_python', 'queue_runner'):
        absolute_path(record[key])
    if absolute_path(record['queue_runner']) != SCRIPT:
        raise SystemExit('launch record selects a different queue runner')
    provider = record['environment']['RUNQ_MACHINE_RESOURCES']
    absolute_path(provider)
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in record['environment'].items()):
        raise SystemExit('launch environment must be a string map')
    callback = record['callback']
    for key in ('directory', 'launcher', 'launcher_python', 'codex'):
        absolute_path(callback[key])
    if not isinstance(callback['owner'], str) or callback['failure_notifications'] not in ('all', 'coordinator'):
        raise SystemExit('invalid callback selection')
    if callback['failure_notifications'] == 'coordinator' and not callback.get('coordinator'):
        raise SystemExit('coordinator-only failure delivery needs a coordinator')
    if not isinstance(record['fresh_targets'], list):
        raise SystemExit('launch record requires fresh targets')
    fresh = [absolute_path(target) for target in record['fresh_targets']]
    if len(fresh) != len(set(fresh)) or absolute_path(callback['directory']) not in fresh:
        raise SystemExit('fresh targets must be distinct and include the callback')
    for target in record.get('reopen_targets', []):
        path_to_reopen = absolute_path(target)
        if any(target == path_to_reopen or target in path_to_reopen.parents for target in fresh):
            raise SystemExit('a fresh target covers a retained path')


def fresh_problem(record, *, claimed):
    directory = absolute_path(record['callback']['directory'])
    for target in record['fresh_targets']:
        target = absolute_path(target)
        if (not claimed or target != directory) and os.path.lexists(target):
            return 'occupied fresh target: ' + str(target)
    return None


def go_expired(launch):
    expires = launch.get('go_expires')
    return bool(expires and datetime.fromisoformat(expires) <= datetime.now(timezone.utc))


def pending_continuation(row):
    launch = row.get('launch', {})
    return row['status'] == 'paused' and bool(launch.get('resume_from')) and not launch.get('go_consumed')


def bound_problem(q, row, bound, *, claimed):
    sha, record = bound
    launch = row.get('launch', {})
    if launch.get('sha256') != sha or ('ticket' in record and record['ticket'] != row['id']):
        return 'launch binding changed'
    if (launch.get('position_changed') or booking_values(row) != booking_values(record['booking'])
            or isolation(row) != isolation(record['booking'])):
        return 'booking changed; bind an explicit successor'
    if row.get('ticket_hold') or q.get('hold') or q.get('pause') or row['status'] not in ('queued', 'paused'):
        return 'queue or ticket is held, paused, or unavailable'
    if launch.get('go_consumed'):
        return 'GO has already been consumed'
    if row['status'] == 'paused' and (not record.get('predecessor') or row.get('exit') != PAUSED_EXIT):
        return 'paused ticket requires a bound successor'
    if not launch.get('ready_at') or not launch.get('authority') or not launch.get('go_at'):
        return 'review, launch authority or GO is outstanding'
    if go_expired(launch):
        return 'GO expired'
    if not claimed:
        return fresh_problem(record, claimed=False)
    return None


def internal_argv(row, record):
    return [record['queue_python'], '-B', '-I', record['queue_runner'],
            '_bound', row['id'], row['launch']['sha256']]


def verify_tracked_ancestry(row, record):
    callback = record['callback']
    directory = absolute_path(callback['directory'])
    request = json.loads((directory / 'request.json').read_bytes())
    supervisor = json.loads((directory / 'supervisor.json').read_bytes())
    expected = {
        'argv': internal_argv(row, record), 'owner': callback['owner'],
        'coordinator': callback.get('coordinator'), 'failure_notifications': callback['failure_notifications'],
    }
    if (any(request.get(key) != value for key, value in expected.items())
            or absolute_path(request['cwd']) != absolute_path(record['cwd'])
            or absolute_path(request['codex']) != absolute_path(callback['codex'])
            or absolute_path(request['launcher']) != absolute_path(callback['launcher'])):
        raise SystemExit('tracked request does not match the launch binding')
    # Windows launcher shims can appear between the queue runner, bootstrap and supervisor.
    # Compare the creation identity written before release, without depending on child.json.
    seen_bootstrap = False
    for ancestor in psutil.Process().parents():
        command = ancestor.cmdline()
        if len(command) >= 3 and command[-2] == '_bootstrap':
            seen_bootstrap = (absolute_path(command[-1]) == directory / 'process'
                              and absolute_path(command[-3]) == absolute_path(callback['launcher']))
        if (seen_bootstrap and ancestor.pid == supervisor.get('pid') and len(command) >= 3
                and command[-2] == '_supervise' and absolute_path(command[-1]) == directory
                and absolute_path(command[-3]) == absolute_path(callback['launcher'])):
            # psutil exposes Unix seconds as a float; compare FILETIME instead.
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            api.OpenProcess.restype = ctypes.c_void_p
            api.GetProcessTimes.argtypes = [ctypes.c_void_p, *([ctypes.POINTER(ctypes.c_uint64)] * 4)]
            api.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = api.OpenProcess(0x1000, False, ancestor.pid)
            if handle:
                try:
                    times = [ctypes.c_uint64() for _ in range(4)]
                    if (api.GetProcessTimes(handle, *(ctypes.byref(value) for value in times))
                            and times[0].value == supervisor.get('creation_time')):
                        return
                finally:
                    api.CloseHandle(handle)
            break
    raise SystemExit('internal bound command requires the selected tracked supervisor and bootstrap')


def selected_environment(record):
    env = dict(os.environ)
    env.update(record['environment'])
    for key in list(env):
        if key.upper() in {'RUNQ_DIR', 'RUNQ_LOCK', 'RUNQ_SMALL_CORES', 'RUNQ_TICKET_CORES', 'RUNQ_TICKET_GIB',
                           'RUNQ_PRED_PEAK_GIB', 'RUNQ_MEM_NEED_GIB'}:
            del env[key]
    env.update(RUNQ_DIR=str(HERE), RUNQ_LOCK=str(LOCK))
    return env


def worker_ticket(tid):
    q = load()
    row = find(q, tid)
    launch = row.get('launch')
    if not launch:
        raise SystemExit('ticket has no reviewed launch binding')
    sha = launch['sha256']
    record = read_launch(launch['record'], sha)
    if problem := bound_problem(q, row, (sha, record), claimed=False):
        raise SystemExit(problem)
    # The worker refuses a broken provider before a callback is claimed. Only the actual
    # queue interpreter loads those modules, and it verifies the selection again.
    provider = absolute_path(record['environment']['RUNQ_MACHINE_RESOURCES'])
    for name in ('machine_resources_monitor.py', 'resources_gate.py'):
        if not (provider / name).is_file():
            raise SystemExit('selected provider is missing ' + str(provider / name))
    callback = record['callback']
    argv = [callback['launcher_python'], '-B', '-I', callback['launcher'], 'start',
            '--run-dir', callback['directory'], '--owner', callback['owner'],
            '--failure-notifications', callback['failure_notifications'], '--cwd', record['cwd'],
            '--codex', callback['codex']]
    if callback.get('coordinator'):
        argv.extend(['--coordinator', callback['coordinator']])
    return subprocess.run([*argv, '--', *internal_argv(row, record)],
                          env=selected_environment(record), check=False).returncode


def worker_small(args, argv):
    provider = args.provider
    if provider is None:
        provider = json.loads((HERE / 'worker-settings.json').read_bytes())['small_provider']
    provider = str(absolute_path(provider))
    os.environ['RUNQ_MACHINE_RESOURCES'] = provider
    for key in ('RUNQ_DIR', 'RUNQ_LOCK', 'RUNQ_TICKET_CORES', 'RUNQ_TICKET_GIB'):
        os.environ.pop(key, None)
    init_resources(provider)
    return cmd_small(args.cores, argv, args.gib)


def worker_bound(tid, sha):
    row = find(load(), tid)
    launch = row.get('launch')
    if not launch or launch.get('sha256') != sha:
        raise SystemExit('launch binding changed')
    record = read_launch(launch['record'], sha)
    verify_tracked_ancestry(row, record)
    init_resources(record['environment']['RUNQ_MACHINE_RESOURCES'])
    return cmd_run(tid, record['payload'], strict_admission=True,
                   strict_cpu_wait=bool(row.get('cpu_wait')), bound=(sha, record))


def cmd_run(tid, command, *, strict_admission=False, strict_cpu_wait=False, bound=None):
    if strict_cpu_wait and not strict_admission:
        raise SystemExit('--strict-cpu-wait requires --strict-admission and an authorised booking')
    if not command:
        raise SystemExit('give the command after --')
    start = time.time()
    said = None
    key = cmd_key(command)  # before the run, while new output folders don't exist yet
    job_nm = 'Local\\runq-run-%s-%d' % (tid, os.getpid())
    job = make_job(job_nm)
    tracker = 'job' if job else 'children'
    cpu_wait_deadline = time.monotonic() + 90 if strict_cpu_wait else None
    cpu_observations = 0
    while True:
        with Mutex(wait=not strict_admission):
            q = load()
            reap(q)
            t = find(q, tid)
            if bound is None and t.get('launch'):
                raise SystemExit('enrolled ticket requires the worker command')
            binding_problem = bound_problem(q, t, bound, claimed=True) if bound is not None else None
            if binding_problem:
                if t.get('waiting_pid') == os.getpid():
                    t.pop('waiting_pid')
                    t.pop('waiting_digest', None)
                    save(q)
                raise SystemExit('strict admission refused (no command started): ' + binding_problem)
            pred, basis = predict_peak(key, t['gib'])
            need = mem_need(pred)
            if bound is None and t['status'] == 'paused':  # legacy exit-75 continuation
                others = reservations(q, exclude=tid)
                if any(row.get('launch') for row in others) and any(row['pos'] == t['pos'] for row in others):
                    insertion_position(others, t['pos'])
                t['status'] = 'queued'
                t.pop('ended', None); t.pop('exit', None)
            if t['status'] != 'queued' and bound is None:
                if strict_admission and t.get('waiting_pid') == os.getpid():
                    t.pop('waiting_pid')
                save(q)
                raise SystemExit('ticket %s is %s, not queued' % (tid, t['status']))
            if (strict_admission and t.get('waiting_pid') not in (None, os.getpid())
                    and pid_exists(t['waiting_pid'])):
                raise SystemExit('strict admission refused: ticket already has a live waiting runner')
            t['waiting_pid'] = os.getpid()
            if bound is not None:
                t['waiting_digest'] = bound[0]
            busy = [x['id'] for x in q['tickets'] if x['status'] == 'running']
            # Order applies among tickets whose runner is actually waiting, so a ticket that
            # hasn't been launched yet can't block the ones behind it.
            ready = live_waiters(q)
            head = ready[0]['id'] if ready else None
            free = monitor.free_memory() / GIB
            why = None
            cpu_gate_sample = None
            retry_cpu = False
            if strict_cpu_wait and t.get('cpu_wait') != wait_binding(t):
                why = '%s booking changed or CPU wait withdrawn' % tid
            elif strict_cpu_wait and time.monotonic() >= cpu_wait_deadline:
                why = 'strict CPU wait expired'
            elif strict_cpu_wait and q.get('pause'):
                why = 'queue paused: %s' % q['pause']
            elif q.get('hold'):
                why = 'queue on hold: %s' % q['hold']
            elif busy:
                why = 'waiting for %s' % ','.join(busy)
            elif bound is not None and go_expired(t['launch']):
                why = 'GO expired'
            elif head != tid:
                why = 'waiting: %s is ahead' % head
            elif t.get('exclusive') and (small_state := small_admission_state(q))[1]:
                why = 'waiting for unresolved small visibility: ' + '; '.join(small_state[1][:3])
            elif t.get('exclusive') and small_state[0]:
                why = 'waiting for %d active small command(s) to drain' % small_state[0]
            elif free < need:
                why = 'waiting for memory: %.1f GiB free, need %.1f (predicted peak %.2f GiB from %s)' % (
                    free, need, pred, basis)
            elif (holder := lock_holder()):
                why = 'waiting for the lock: %s' % holder.get('what', '?')
            elif strict_admission:
                # The qualifying unrounded observation both admits and records the start.
                cpu_gate_sample = free_cores()
                cpu_observations += 1
                if strict_cpu_wait and time.monotonic() >= cpu_wait_deadline:
                    why = 'strict CPU wait expired'
                elif strict_cpu_wait and not 0 <= cpu_gate_sample <= PHYSICAL:
                    why = 'invalid strict CPU sample (observed %.9g)' % cpu_gate_sample
                elif not cpu_gate_sample >= t.get('cores', 1):
                    why = 'waiting for %d free cores (observed %.9g)' % (t.get('cores', 1), cpu_gate_sample)
                    retry_cpu = (strict_cpu_wait and cpu_observations < 3
                                 and time.monotonic() + 30 < cpu_wait_deadline)
            elif (t.get('cores', 1) > 1
                  and time.time() - t.setdefault('cpu_wait_from', time.time()) < CPU_WAIT_MAX_S
                  and (cpu_gate_sample := free_cores()) < t['cores']):
                why = 'waiting for %d free cores (quiet machine)' % t['cores']
            if bound is not None and (why is None or retry_cpu):
                late_problem = fresh_problem(bound[1], claimed=True)
                if late_problem or go_expired(t['launch']):
                    why = late_problem or 'GO expired'
                    retry_cpu = False
            if why is None:
                if not try_lock(t):
                    why = 'waiting for the lock: %s' % (lock_holder() or {}).get('what', '?')
                elif bound is not None and go_expired(t['launch']):
                    unlock()
                    why = 'GO expired'
            if strict_admission and why is not None and not retry_cpu:
                if t.get('waiting_pid') == os.getpid():
                    t.pop('waiting_pid')
                    t.pop('waiting_digest', None)
                save(q)
                raise SystemExit('strict admission refused (no command started): ' + why)
            if why is None:
                fc = cpu_gate_sample if strict_admission else round(free_cores(), 1)
                t.update(status='running', started=now(), runner_pid=os.getpid(), free_cores_at_start=fc,
                         free_gib_at_start=round(free, 1), mem_need_gib=need,
                         pred_peak_gib=round(pred, 2), pred_basis=basis, cmd_key=key,
                         job_name=job_nm if job else None, tracker=tracker)
                t.pop('waiting_pid', None)
                t.pop('waiting_digest', None)
                if bound is not None:
                    t['launch']['admitted_at'] = t['started']
                    t['launch']['go_consumed'] = True
                    t.pop('ended', None)
                    t.pop('exit', None)
                    t.pop('runner_outcome', None)
                if fc < t.get('cores', 1):
                    age = max(0, time.time() - t.get('cpu_wait_from', start))
                    sample = 'not sampled' if cpu_gate_sample is None else '%.3f' % cpu_gate_sample
                    t['cpu_note'] = ('started with %.1f free cores (wanted %d); CPU wait timer age %.1f s; '
                                     'admission sample %s, start sample %.1f') % (fc, t['cores'], age, sample, fc)
                    print('%s %s WARNING %s' % (time.strftime('%H:%M:%S'), tid, t['cpu_note']), flush=True)
                save(q)
                break
            save(q)
        if strict_cpu_wait:
            print('%s %s CPU observation %d/3: %s' %
                  (time.strftime('%H:%M:%S'), tid, cpu_observations, why), flush=True)
            time.sleep(30)
            continue
        if (why or '').split(':')[0] != (said or '').split(':')[0]:
            print('%s %s %s' % (time.strftime('%H:%M:%S'), tid, why), flush=True)
            said = why
        if time.time() - start > MAX_WAIT_S:
            raise SystemExit('gave up after 12 h waiting')
        time.sleep(POLL_S)
    print('%s %s started (%s GiB TOTAL declared)' % (time.strftime('%H:%M:%S'), tid, t['gib']), flush=True)
    env = dict(os.environ)
    if bound is not None:
        for key in ('RUNQ_DIR', 'RUNQ_LOCK'):
            env.pop(key, None)
    for k, v in (('PYTHONHASHSEED', '0'), ('PYTHONDONTWRITEBYTECODE', '1'), ('OMP_NUM_THREADS', '1'),
                 ('OPENBLAS_NUM_THREADS', '1'), ('MKL_NUM_THREADS', '1')):
        env.setdefault(k, v)
    # Harnesses size their own per-arm start gates from the ticket's booking (Michael, 16 Oct ~14:05).
    env['RUNQ_TICKET_GIB'] = str(t['gib'])
    if t.get('cores', 1) > 1 or bound is not None and bound[1]['booking']['mode'] == 'fixed':
        env['RUNQ_TICKET_CORES'] = str(t['cores'])
    elif bound is not None:
        env.pop('RUNQ_TICKET_CORES', None)
    env['RUNQ_PRED_PEAK_GIB'] = str(round(pred, 2))
    env['RUNQ_MEM_NEED_GIB'] = str(need)
    peak = 0.0
    code = None
    small_max, last_scan = 0, 0.0
    try:
        proc = subprocess.Popen(command, env=env)
        me = psutil.Process(proc.pid)
        while code is None:
            peak = max(peak, tracked_rss_gib(job, me, exclude={os.getpid()}))
            if time.time() - last_scan > 30:
                last_scan = time.time()
                small_max = max(small_max, small_running())
            try:
                code = proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
    finally:
        unlock()
        with Mutex():
            q = load()
            t = find(q, tid)
            t.update(status='done' if code == 0 else 'paused' if code == PAUSED_EXIT else 'failed', exit=code, ended=now(),
                     peak_rss_gib=round(peak, 2), small_jobs_max=small_max)
            if bound is not None and code is not None:
                t['runner_outcome'] = 'payload_exit'
            save(q)
            if code == 0:  # a failed run's peak may be partial, so it never lowers a prediction
                record_peak(key, peak, tid, tracker)
    print('%s %s exit %s, tree peak RSS %.2f GiB (predicted %.2f, declared %s; tracked by %s)'
          % (time.strftime('%H:%M:%S'), tid, code, peak, pred, t['gib'], tracker), flush=True)
    if peak + gate.RESERVE_BYTES / GIB > need:
        print('%s %s WARNING: peak exceeded the prediction by more than its fifth; book from this peak next time'
              % (time.strftime('%H:%M:%S'), tid), flush=True)
    return code or 0


def small_running():
    owners, unknown = scan_small_commands()
    return len(owners) + len(unknown)


def unrealised_gib(t):
    """Memory a running ticket is predicted to need but has not yet used: its predicted peak (the booking if
    it started before prediction existed) minus its tree's current RSS."""
    job = _K32.OpenJobObjectW(0x0004, False, t['job_name']) if _K32 is not None and t.get('job_name') else None
    try:
        root = psutil.Process(t['runner_pid'])
        rss = tracked_rss_gib(job, root) if job else tree_rss_gib(root)
    except (psutil.Error, KeyError):
        rss = 0.0
    finally:
        if job:
            _K32.CloseHandle(job)
    return max(0.0, t.get('pred_peak_gib', t['gib']) - rss)


def cmd_small(cores, command, gib=None):
    """Existing small policy, with admission and child creation serialised under Mutex."""
    if not command:
        raise SystemExit('give the command after --')
    start, said = time.time(), None
    key = 'small: ' + cmd_key(command)
    if gib is None:
        gib, basis = predict_peak(key, 1.0)
    else:
        basis = '--gib'
    while True:
        with Mutex():
            q = load()
            reap(q)
            save(q)
            running = [t for t in q['tickets'] if t['status'] == 'running']
            held = lock_holder()
            why = None
            if q.get('pause') and cores > PAUSE_SMALL_CORES:
                why = 'queue paused (%s): small jobs above %d cores wait for resume' % (q['pause'], PAUSE_SMALL_CORES)
            elif any(t.get('exclusive') for t in running):
                why = 'exclusive worker-route ticket running: %s' % ','.join(t['id'] for t in running)
            elif not running and small_exclusive_head(q):
                why = 'exclusive ready ticket waiting for small commands to drain'
            elif not running and any(t.get('exclusive') and t.get('cpu_wait_from') and t['status'] == 'queued'
                                     and time.time() - t['cpu_wait_from'] < CPU_WAIT_MAX_S for t in q['tickets']):
                why = 'exclusive ticket waiting for free cores'
            else:
                spare = monitor.free_memory() / GIB - sum(unrealised_gib(t) for t in running)
                if spare < gib + FREE_FLOOR_GIB:
                    why = 'waiting for memory: %.1f GiB spare after running tickets, need %.1f (%s)' % (
                        spare, gib + FREE_FLOOR_GIB, basis)
            if why is None:
                rows = small_rows(q)
                if len(rows) >= SMALL_ACTIVE_LIMIT:
                    raise SystemExit('active small command registry is full; resolve retained admissions')
                owner = os.getpid()
                job_name = 'Local\\runq-small-%d' % owner
                job = make_job(job_name, kill_on_close=True)
                if os.name == 'nt' and not job:
                    raise SystemExit('small: Windows job tracking unavailable; no command started')
                tracker = 'job' if job else 'children'
                row = dict(id='%d:%d%s' % (owner, time.time_ns(), SMALL_KILL_MARK if job else ''), owner_pid=owner,
                           owner_birth=small_birth(owner), child_pid=None, child_birth=None,
                           job_name=job_name if job else None)
                q[SMALL_ACTIVE_KEY] = [*rows, row]
                save(q)  # A crash during Popen remains a visible unresolved admission.
                env = dict(os.environ)
                env['RUNQ_PRED_PEAK_GIB'] = str(round(gib, 2))
                env['RUNQ_MEM_NEED_GIB'] = str(round(gib + FREE_FLOOR_GIB, 2))
                env['RUNQ_SMALL_CORES'] = str(cores)
                proc = None
                try:
                    proc = subprocess.Popen(command, env=env)
                    row.update(child_pid=proc.pid, child_birth=small_birth(proc.pid))
                    save(q)
                except BaseException:
                    if proc is None:
                        members, problem = small_job_members(row)
                        if members is not None and not members:
                            q[SMALL_ACTIVE_KEY] = [item for item in q[SMALL_ACTIVE_KEY] if item['id'] != row['id']]
                            save(q)
                        else:
                            print('small: retaining incomplete creation %s: %s' % (
                                row['id'], problem if members is None else 'job has a possible partial child'), flush=True)
                    raise
                break
        if (why or '').split(':')[0] != (said or '').split(':')[0]:
            print('%s small: %s' % (time.strftime('%H:%M:%S'), why), flush=True)
            said = why
        if time.time() - start > 4 * 3600:
            raise SystemExit('small: gave up after 4 h')
        time.sleep(POLL_S)
    try:
        me = psutil.Process(proc.pid)
        me.nice(getattr(psutil, 'BELOW_NORMAL_PRIORITY_CLASS', 10))
    except psutil.Error:
        me = None
    peak, code = 0.0, None
    try:
        while code is None:
            peak = max(peak, tracked_rss_gib(job, me, exclude={os.getpid()}))
            try:
                code = proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        if code == 0 and peak > 0:
            with Mutex():
                record_peak(key, peak, 'small', tracker)
    finally:
        finish_small_admission(row, code)
    print('%s small: exit %s, tree peak RSS %.2f GiB (predicted %.2f from %s; tracked by %s)'
          % (time.strftime('%H:%M:%S'), code, peak, gib, basis, tracker), flush=True)
    return code


def cmd_status(show_all):
    with Mutex():
        q = load()
        if reap(q):
            save(q)
    held = lock_holder()
    print('lock:', held.get('what', held) if held else 'free',
          '| free RAM %.1f GiB' % (monitor.free_memory() / GIB),
          '| QUEUE ON HOLD: %s' % q['hold'] if q.get('hold') else '',
          '| PAUSED: %s' % q['pause'] if q.get('pause') else '')
    order = {'running': 0, 'external': 0, 'queued': 1, 'held': 1, 'paused': 1}
    rows = [t for t in q['tickets'] if show_all or t['status'] in order]
    rows.sort(key=lambda t: (order.get(t['status'], 2), t.get('pos', 0)))
    for t in rows:
        extra = t.get('note') or t.get('why', '')
        if t['status'] == 'queued':
            wp = t.get('waiting_pid')
            extra = ('[launched] ' if wp and pid_exists(wp) else '[not launched] ') + extra
        elif t['status'] == 'held' and t.get('ticket_hold'):
            extra = '[HELD: %s] ' % t['ticket_hold'] + extra
        print('%-5s %-9s %-36s %4.1fG %2sc%s ~%3smin  %s | %s' % (
            t['id'], t['status'], t['owner'][:36], t['gib'], t.get('cores', 1),
            'X' if t.get('exclusive') else ('Q' if t.get('quiet') else ' '),
            t['min'], t['what'], extra))
        if t.get('launch'):
            print_launch_status(t)



def reservations(q, exclude=None):
    return sorted((row for row in q['tickets'] if row['id'] != exclude
                   and (row['status'] in ('queued', 'held') or pending_continuation(row))),
                  key=lambda row: row['pos'])


def withdraw_go(row):
    launch = row.get('launch')
    if launch and not launch.get('go_consumed'):
        launch.pop('go_at', None)
        launch.pop('go_expires', None)


def move_position(row, position):
    if row['pos'] != position:
        row['pos'] = position
        if row.get('launch'):
            row['launch']['position_changed'] = True
            withdraw_go(row)
            row.pop('cpu_wait', None)


def insertion_position(rows, position):
    if position is not None and position < 1:
        raise SystemExit('position must be positive')
    # Insert ahead of ties, preserving relative order and repairing old collisions.
    next_free = 1
    for row in rows:
        next_free = max(next_free, row['pos'])
        if next_free == position:
            next_free += 1
        move_position(row, next_free)
        next_free += 1
    return next_free if position is None else position


def attempt_reference(launch):
    return {key: launch[key] for key in ('record', 'sha256', 'callback')}


def confirm_predecessor(previous, expected_exit=None):
    callback = absolute_path(previous['callback'])
    if not os.path.lexists(callback):
        if expected_exit is not None:
            raise SystemExit('predecessor callback is missing')
        return
    try:
        result = json.loads((callback / 'result.json').read_bytes())
        request = json.loads((callback / 'request.json').read_bytes())
        tree = result['process']
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit('reconcile predecessor callback before rebinding: ' + str(error)) from error
    if (result['run_id'] != request['run_id'] or not tree.get('tree_final') or tree.get('active_members') != 0
            or expected_exit is not None and tree.get('exit_code') != expected_exit):
        raise SystemExit('predecessor callback is not terminal at the required exit')


def enroll(q, args):
    record = read_launch(args.record, args.sha256)
    existing = next((row for row in q['tickets'] if row.get('launch', {}).get('sha256') == args.sha256), None)
    if existing is not None:
        if args.ticket and args.ticket != existing['id']:
            raise SystemExit('exact record already booked on another ticket')
        return existing, False
    validate_launch(record)
    booking = booking_values(record['booking'])
    if args.ticket:
        row = find(q, args.ticket)
    else:
        row = None
    if row is None:
        if record.get('ticket') or record.get('predecessor'):
            raise SystemExit('an already numbered record or continuation needs an existing ticket')
        ticket = 'q%02d' % q['next_id']
    else:
        ticket = row['id']
    if record.get('ticket', ticket) != ticket:
        raise SystemExit('record names a different ticket')
    if problem := fresh_problem(record, claimed=False):
        raise SystemExit(problem)
    launch = {
        'record': str(absolute_path(args.record)), 'sha256': args.sha256,
        'callback': str(absolute_path(record['callback']['directory'])),
        'predicted_runtime': record['predicted_runtime'], 'runtime_basis': record['runtime_basis'],
        'authority_pending': record.get('authority_owner', 'Test Control'),
    }
    if row is None:
        position = insertion_position(reservations(q), booking['pos'])
        row = dict(booking, id=ticket, pos=position, status='held', added=now(), owner=record['owner'],
                   what=record['scope'], ticket_hold='exact review and authority pending', launch=launch,
                   **isolation(record['booking']))
        q['next_id'] += 1
        q['tickets'].append(row)
    else:
        if row.get('waiting_pid') and pid_exists(row['waiting_pid']):
            raise SystemExit('ticket has a live waiting runner')
        previous = row.get('launch')
        if previous and args.replaces != previous['sha256']:
            raise SystemExit('an explicit predecessor descriptor digest is required')
        if not previous and args.replaces:
            raise SystemExit('ticket has no enrolled attempt to replace')
        if row['status'] == 'paused':
            if not previous or row.get('exit') != PAUSED_EXIT:
                raise SystemExit('paused continuation requires a previously executed attempt')
            expected = record.get('predecessor', {})
            source = previous if previous.get('go_consumed') else previous.get('resume_from', {})
            if (expected.get('sha256') != source.get('sha256')
                    or absolute_path(expected.get('callback')) != absolute_path(source.get('callback'))):
                raise SystemExit('paused continuation must identify the last executed attempt')
            checkpoint = absolute_path(record.get('checkpoint'))
            if (not checkpoint.exists() or checkpoint not in
                    [absolute_path(path) for path in record.get('reopen_targets', [])]
                    or source.get('checkpoint', str(checkpoint)) != str(checkpoint)):
                raise SystemExit('paused continuation requires the existing retained checkpoint')
            if previous.get('go_consumed'):
                confirm_predecessor(source, PAUSED_EXIT)
            launch['resume_from'] = dict(attempt_reference(source), checkpoint=str(checkpoint),
                                         exit=row['exit'], ended=row['ended'],
                                         admitted_at=source['admitted_at'])
            insertion_position(reservations(q, exclude=ticket), booking['pos'])
            row.update(booking, **isolation(record['booking']))
        else:
            if row['status'] not in ('queued', 'held') or row.get('started'):
                raise SystemExit('only an unstarted reservation can take this descriptor')
            if (row['pos'] != booking['pos'] or not previous
                    and (booking_values(row) != booking or isolation(row) != isolation(record['booking']))):
                raise SystemExit('descriptor booking does not match the reservation')
            if record.get('predecessor'):
                raise SystemExit('predecessor continuation requires a paused ticket')
            insertion_position(reservations(q, exclude=ticket), booking['pos'])
            row.update(booking, status='held', **isolation(record['booking']))
        if previous and not previous.get('go_consumed'):
            confirm_predecessor(previous)
            launch['replaced_attempts'] = [*previous.get('replaced_attempts', []), attempt_reference(previous)]
        row['launch'] = launch
        row['ticket_hold'] = 'exact review and authority pending'
        row.pop('waiting_pid', None)
        row.pop('waiting_digest', None)
        row.pop('cpu_wait', None)
    if args.bounded_cpu_wait:
        row['cpu_wait'] = wait_binding(row)
    return row, True


def launch_update(q, args):
    row = find(q, args.ticket)
    launch = row.get('launch')
    if not launch or launch['sha256'] != args.sha256 or launch.get('position_changed'):
        raise SystemExit('attempt binding changed')
    if row['status'] not in ('held', 'queued', 'paused') or launch.get('go_consumed'):
        raise SystemExit('attempt is no longer eligible for launch updates')
    action = args.action
    if action in ('review', 'authority', 'pending') and not args.ref:
        raise SystemExit('this decision needs a source or authority owner')
    if action == 'review':
        if launch.get('review') and launch['review'] != args.ref:
            raise SystemExit('exact attempt already has a review verdict')
        launch.setdefault('review', args.ref)
        launch.setdefault('ready_at', now())
    elif action == 'authority':
        launch.setdefault('authority', args.ref)
        launch.pop('authority_pending', None)
    elif action == 'pending':
        launch['authority_pending'] = args.ref
        launch.pop('authority', None)
        withdraw_go(row)
    elif action == 'withdraw':
        withdraw_go(row)
    elif action == 'go':
        if (not launch.get('ready_at') or not launch.get('authority') or q.get('hold') or q.get('pause')
                or row.get('ticket_hold') or row['status'] not in ('queued', 'paused')):
            raise SystemExit('release the hold and record review and authority before GO')
        if args.expires:
            expiry = datetime.fromisoformat(args.expires)
            if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                raise SystemExit('GO expiry must be a future timestamp with a time zone')
        if launch.get('go_at') and launch.get('go_expires') != args.expires:
            raise SystemExit('withdraw the previous GO before changing its expiry')
        if not launch.get('go_at') and os.path.lexists(launch['callback']):
            raise SystemExit('claimed callback requires reconciliation and a fresh successor')
        launch.setdefault('go_at', now())
        if args.expires:
            launch.setdefault('go_expires', args.expires)


def set_cpu_wait(q, args):
    row = find(q, args.ticket)
    launch = row.get('launch')
    if (launch or args.sha256) and (not launch or args.sha256 != launch['sha256']
                                   or launch.get('position_changed') or launch.get('go_consumed')):
        raise SystemExit('CPU wait selection requires the current descriptor digest')
    if row['status'] not in ('queued', 'held', 'paused'):
        raise SystemExit('CPU wait selection requires an unstarted booking')
    if args.state == 'on':
        row['cpu_wait'] = wait_binding(row)
    else:
        row.pop('cpu_wait', None)


def print_launch_status(row):
    launch = row['launch']
    readiness = launch.get('ready_at', 'pending exact review')
    authority = launch.get('authority', 'pending ' + launch.get('authority_pending', 'Test Control'))
    started = launch.get('admitted_at')
    outcome = 'payload start unknown'
    callback = Path(launch['callback'])
    if started and type(row.get('exit')) is int and row.get('runner_outcome') == 'payload_exit':
        outcome = 'payload exited %s' % row['exit']
    elif not started and (callback / 'result.json').exists():
        try:
            result = json.loads((callback / 'result.json').read_bytes())['process']
            if result.get('tree_final') and result.get('active_members') == 0:
                outcome = 'ended before payload admission'
        except (OSError, ValueError, KeyError, TypeError):
            pass
    elapsed = ''
    if started and launch.get('ready_at'):
        seconds = (datetime.fromisoformat(started) - datetime.fromisoformat(launch['ready_at'])).total_seconds()
        elapsed = ' | ready to admission %.0fs' % seconds
    go = launch.get('go_at', 'pending')
    if launch.get('position_changed'):
        go = 'successor required'
    elif not launch.get('go_consumed') and go_expired(launch):
        go = 'expired'
    print('      booked %s | ready %s | authority %s | GO %s | admitted %s | %s | predicted %s (%s)%s'
          % (row['added'], readiness, authority, go, started or 'pending', outcome,
             launch['predicted_runtime'], launch['runtime_basis'], elapsed))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('status'); s.add_argument('--all', action='store_true')
    worker = sub.add_parser('worker')
    worker.add_argument('target')
    worker.add_argument('args', nargs=argparse.REMAINDER)
    bound = sub.add_parser('_bound')
    bound.add_argument('ticket')
    bound.add_argument('sha256')
    decision = sub.add_parser('launch-decision')
    decision.add_argument('ticket')
    decision.add_argument('sha256')
    decision.add_argument('action', choices=('review', 'authority', 'pending', 'go', 'withdraw'))
    decision.add_argument('--ref')
    decision.add_argument('--expires')
    cpu = sub.add_parser('cpu-wait')
    cpu.add_argument('ticket')
    cpu.add_argument('state', choices=('on', 'off'))
    cpu.add_argument('--sha256')
    r = sub.add_parser('run'); r.add_argument('--strict-admission', action='store_true')
    r.add_argument('--strict-cpu-wait', action='store_true')
    r.add_argument('ticket'); r.add_argument('command', nargs=argparse.REMAINDER)
    m = sub.add_parser('small'); m.add_argument('--cores', type=int, default=1)
    m.add_argument('--gib', type=float, default=None)
    m.add_argument('command', nargs=argparse.REMAINDER)
    h = sub.add_parser('hold'); h.add_argument('state', choices=['on', 'off']); h.add_argument('--why', default='wind-down')
    ht = sub.add_parser('hold-ticket'); ht.add_argument('ticket'); ht.add_argument('state', choices=['on', 'off'])
    ht.add_argument('--why', default='review pending')
    pz = sub.add_parser('pause'); pz.add_argument('state', choices=['on', 'off']); pz.add_argument('--why', default='paused')
    k = sub.add_parser('setcpu'); k.add_argument('ticket'); k.add_argument('cores', type=int)
    k.add_argument('--quiet', action='store_true'); k.add_argument('--exclusive', action='store_true')
    n = sub.add_parser('note'); n.add_argument('ticket'); n.add_argument('text')
    a = sub.add_parser('add')
    for k in ('owner', 'what'):
        a.add_argument('--' + k)
    a.add_argument('--gib', type=float); a.add_argument('--min', type=int)
    a.add_argument('--record'); a.add_argument('--sha256')
    a.add_argument('--ticket'); a.add_argument('--replaces')
    a.add_argument('--bounded-cpu-wait', action='store_true')
    for k in ('why', 'runtime', 'inputs', 'outputs'):
        a.add_argument('--' + k, default='')
    a.add_argument('--pos', type=int); a.add_argument('--status', default='queued', choices=['queued', 'external'])
    a.add_argument('--cores', type=int, default=1); a.add_argument('--quiet', action='store_true')
    o = sub.add_parser('reorder'); o.add_argument('ticket'); o.add_argument('pos', type=int)
    c = sub.add_parser('cancel'); c.add_argument('ticket')
    f = sub.add_parser('finish'); f.add_argument('ticket'); f.add_argument('exit')
    args = p.parse_args()
    if args.cmd == 'worker':
        if args.target == 'small':
            small = argparse.ArgumentParser(prog='runq.py worker small')
            small.add_argument('--provider')
            small.add_argument('--cores', type=int, default=1)
            small.add_argument('--gib', type=float)
            small.add_argument('command', nargs=argparse.REMAINDER)
            options = small.parse_args(args.args)
            argv = options.command
            return worker_small(options, argv[1:] if argv[:1] == ['--'] else argv)
        if args.args:
            p.error('worker TICKET accepts no payload or policy overrides')
        return worker_ticket(args.target)
    if args.cmd == '_bound':
        return worker_bound(args.ticket, args.sha256)
    if args.cmd in ('status', 'run', 'small'):
        init_resources()
    if args.cmd == 'status':
        return cmd_status(args.all)
    if args.cmd == 'run':
        cmd = args.command[1:] if args.command[:1] == ['--'] else args.command
        return cmd_run(args.ticket, cmd, strict_admission=args.strict_admission,
                       strict_cpu_wait=args.strict_cpu_wait)
    if args.cmd == 'small':
        cmd = args.command[1:] if args.command[:1] == ['--'] else args.command
        return cmd_small(args.cores, cmd, args.gib)
    with Mutex():
        q = load()
        if args.cmd == 'add':
            if args.record:
                if not args.sha256:
                    p.error('--record requires --sha256')
                t, changed = enroll(q, args)
                if changed:
                    save(q)
                print('booked', t['id'], 'at position', t['pos'], t['status'])
                return 0
            if args.sha256 or args.ticket or args.replaces or not all(
                    value is not None for value in (args.owner, args.what, args.gib, args.min)):
                p.error('free-form add requires --owner, --what, --gib and --min')
            tid = 'q%02d' % q['next_id']; q['next_id'] += 1
            reserved = reservations(q) if args.status != 'external' else []
            if args.status == 'external':
                pos = 0 if args.pos is None else args.pos
            elif any(t.get('launch') for t in reserved):
                pos = insertion_position(reserved, args.pos)
            else:
                live = pending(reserved)
                pos = len(live) + 1 if args.pos is None else args.pos
                for t in live:
                    if t['pos'] >= pos:
                        move_position(t, t['pos'] + 1)
            t = dict(id=tid, owner=args.owner, gib=args.gib, min=args.min, what=args.what,
                     why=args.why, runtime=args.runtime, inputs=args.inputs, outputs=args.outputs,
                     pos=pos, status=args.status, added=now(), cores=args.cores, quiet=args.quiet)
            if args.bounded_cpu_wait:
                t['cpu_wait'] = wait_binding(t)
            q['tickets'].append(t)
            print('added', tid, 'at position', pos)
        elif args.cmd == 'launch-decision':
            launch_update(q, args)
        elif args.cmd == 'cpu-wait':
            set_cpu_wait(q, args)
        elif args.cmd == 'reorder':
            t = find(q, args.ticket)
            reserved = reservations(q)
            if t not in reserved or args.pos < 1:
                raise SystemExit('reorder requires a reserved ticket and positive position')
            if any(row.get('launch') for row in reserved):
                old = t['pos']
                for row in reserved:
                    if row is t:
                        continue
                    pos = row['pos']
                    if args.pos <= pos < old:
                        move_position(row, pos + 1)
                    elif old < pos <= args.pos:
                        move_position(row, pos - 1)
                move_position(t, args.pos)
                live = sorted(reserved, key=lambda row: row['pos'])
            else:
                live = pending(reserved, t)
                live.insert(args.pos - 1, t)
                for i, row in enumerate(live, 1):
                    move_position(row, i)
            print('order:', ' '.join(row['id'] for row in live))
        elif args.cmd == 'hold':
            # Waiting runners (old code included) exit on their next poll once their ticket is no longer
            # 'queued'; running tickets are untouched and finish. 'hold off' re-queues; owners relaunch.
            q['hold'] = args.why if args.state == 'on' else None
            for t in q['tickets']:
                if args.state == 'on':
                    withdraw_go(t)
                if args.state == 'on' and t['status'] == 'queued':
                    t['status'] = 'held'
                elif args.state == 'off' and t['status'] == 'held' and not t.get('ticket_hold'):
                    t['status'] = 'queued'; t.pop('waiting_pid', None)
            print('hold', args.state, args.why if args.state == 'on' else '')
        elif args.cmd == 'pause':
            q['pause'] = args.why if args.state == 'on' else None
            if q['pause']:
                for row in q['tickets']:
                    withdraw_go(row)
            print('pause', args.state, args.why if args.state == 'on' else '')
        elif args.cmd == 'hold-ticket':
            # One ticket only (e.g. its review is still running): its waiting runner exits on the next poll and it
            # stops blocking the tickets behind it. 'off' re-queues it unless the whole queue is on hold; the owner
            # relaunches. A global 'hold off' leaves ticket holds in place.
            t = find(q, args.ticket)
            if args.state == 'on':
                if t['status'] not in ('queued', 'held') and not (t['status'] == 'paused' and t.get('launch')):
                    raise SystemExit('ticket %s is %s; no hold can be added' % (t['id'], t['status']))
                if t['status'] != 'paused':
                    t['status'] = 'held'
                t['ticket_hold'] = args.why
                withdraw_go(t)
            else:
                t.pop('ticket_hold', None)
                if t['status'] == 'held' and not q.get('hold'):
                    t['status'] = 'queued'; t.pop('waiting_pid', None)
            print('ticket', t['id'], t['status'], t.get('ticket_hold', ''))
        elif args.cmd == 'setcpu':
            t = find(q, args.ticket)
            if t.get('launch'):
                raise SystemExit('enrolled CPU or isolation changes require an explicit successor')
            t.update(cores=args.cores, quiet=args.quiet, exclusive=args.exclusive)
            print('set', args.ticket, args.cores, 'cores', 'quiet' if args.quiet else '', 'exclusive' if args.exclusive else '')
        elif args.cmd == 'cancel':
            find(q, args.ticket).update(status='cancelled', ended=now()); print('cancelled', args.ticket)
        elif args.cmd == 'finish':
            find(q, args.ticket).update(status='done', exit=args.exit, ended=now()); print('finished', args.ticket)
        elif args.cmd == 'note':
            find(q, args.ticket)['note'] = args.text; print('noted', args.ticket)
        save(q)
    return 0


if __name__ == '__main__':
    sys.exit(main())
