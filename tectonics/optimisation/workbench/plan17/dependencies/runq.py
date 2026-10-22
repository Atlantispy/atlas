"""Heavy-run queue for the shared Atlas machine (coordinator-owned, 16 Oct 2026).

The coordinator ("Atlas Lead Coodinator") keeps the queue. Each chat runs its job with
`run`, which waits until (1) the ticket is first in the queue, (2) nothing else from the queue
is running, (3) the cooperative lock is free and (4) free memory covers the ticket's TOTAL
peak + 1 GiB floor + 4 GiB headroom. It then takes the same lock file as heavy_lock.py,
runs the command and records the outcome. A runner that dies frees its place (its PID is
checked), so a crash can't block the queue.

  python -B -I runq.py status [--all]
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
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

HERE = Path(os.environ.get('RUNQ_DIR') or Path(__file__).resolve().parent)
QUEUE = HERE / 'queue.json'
MUTEX = HERE / '.mutex'
LOCK = Path(os.environ.get('RUNQ_LOCK') or 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/'
            'fidelity-integration-20261005/heavy-run.lock.json')
POLL_S = int(os.environ.get("RUNQ_POLL", 30))
MAX_WAIT_S = 12 * 3600
GIB = 2 ** 30
PHYSICAL = psutil.cpu_count(logical=False) or 8
RESERVE_CORES = 2          # desktop app, chats, system
CPU_WAIT_MAX_S = 600       # a ticket waits at most 10 min for free cores, then starts and logs it
# Memory start gate by need (Michael, 16 Oct ~14:05), replacing the blanket TOTAL + 5 GiB. The in-run guards
# (12 GiB tree RSS, 1 GiB free floor) still stop a run cleanly; the start gate only avoids starting runs that
# would hit them. Need = TOTAL * (1 + MEM_MARGIN) + FREE_FLOOR + SMALL_ALLOWANCE (small jobs that start later).
MEM_MARGIN = 0.2
FREE_FLOOR_GIB = 1.0
SMALL_ALLOWANCE_GIB = 1.0
# Pause (Michael, 16 Oct ~14:45, gaming): tickets are paused one by one with hold-ticket (old runners obey a
# status change); new small jobs above this many cores wait, because a worker-count smoke on a loaded machine can
# silently run serial and have to be redone.
PAUSE_SMALL_CORES = 2


def mem_need(gib):
    return round(gib * (1 + MEM_MARGIN) + FREE_FLOOR_GIB + SMALL_ALLOWANCE_GIB, 1)


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


def make_job(name):
    """Create the named job and put this process in it; None (parent-chain tracking only) if that fails."""
    if _K32 is None:
        return None
    h = _K32.CreateJobObjectW(None, name)
    if not h:
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


def pending(q):
    return sorted((t for t in q['tickets'] if t['status'] == 'queued'), key=lambda t: t['pos'])


def reap(q):
    """Mark tickets whose runner died as 'died' so they can't block the queue."""
    for t in q['tickets']:
        if t['status'] == 'running' and t.get('runner_pid') and not pid_exists(t['runner_pid']):
            t['status'] = 'died'
            t['ended'] = now()


def lock_holder():
    try:
        held = json.loads(LOCK.read_text(encoding='utf8'))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {'unreadable': True}
    if pid_exists(int(held.get('pid', -1))):
        return held
    return None  # stale


def try_lock(t):
    body = json.dumps(dict(owner=t['owner'], pid=os.getpid(), msys_pid=os.getpid(),
                           expected_peak_gib=float(t['gib']), started=now(),
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
    """Query the existing named job strictly: unavailable is unknown, never empty."""
    if _K32 is None or not row['job_name']:
        return None, 'no job identity available'
    handle = _K32.OpenJobObjectW(0x0004, False, row['job_name'])
    if not handle:
        return None, 'cannot open recorded small job (Windows error %d)' % ctypes.get_last_error()
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


def small_admission_state(q):
    """Caller holds Mutex. Reap only a dead recorded child with a proved empty job."""
    owners, unknown = scan_small_commands()
    retained = []
    for row in small_rows(q):
        child = row['child_pid']
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
    ready = [ticket for ticket in pending(q)
             if ticket.get('waiting_pid') and pid_exists(ticket['waiting_pid'])]
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


def cmd_run(tid, command, *, strict_admission=False):
    if not command:
        raise SystemExit('give the command after --')
    start = time.time()
    said = None
    key = cmd_key(command)  # before the run, while new output folders don't exist yet
    job_nm = 'Local\\runq-run-%s-%d' % (tid, os.getpid())
    job = make_job(job_nm)
    tracker = 'job' if job else 'children'
    while True:
        with Mutex(wait=not strict_admission):
            q = load()
            reap(q)
            t = find(q, tid)
            pred, basis = predict_peak(key, t['gib'])
            if t['status'] != 'queued':
                if strict_admission and t.get('waiting_pid') == os.getpid():
                    t.pop('waiting_pid')
                save(q)
                raise SystemExit('ticket %s is %s, not queued' % (tid, t['status']))
            if (strict_admission and t.get('waiting_pid') not in (None, os.getpid())
                    and pid_exists(t['waiting_pid'])):
                raise SystemExit('strict admission refused: ticket already has a live waiting runner')
            t['waiting_pid'] = os.getpid()
            busy = [x['id'] for x in q['tickets'] if x['status'] == 'running']
            # Order applies among tickets whose runner is actually waiting, so a ticket that
            # hasn't been launched yet can't block the ones behind it.
            ready = [x for x in pending(q) if x.get('waiting_pid') and pid_exists(x['waiting_pid'])]
            head = ready[0]['id']
            free = psutil.virtual_memory().available / GIB
            why = None
            cpu_gate_sample = None
            if q.get('hold'):
                why = 'queue on hold: %s' % q['hold']
            elif busy:
                why = 'waiting for %s' % ','.join(busy)
            elif head != tid:
                why = 'waiting: %s is ahead' % head
            elif t.get('exclusive') and (small_state := small_admission_state(q))[1]:
                why = 'waiting for unresolved small visibility: ' + '; '.join(small_state[1][:3])
            elif t.get('exclusive') and small_state[0]:
                why = 'waiting for %d active small command(s) to drain' % small_state[0]
            elif free < mem_need(pred):
                why = 'waiting for memory: %.1f GiB free, need %.1f (predicted peak %.2f GiB from %s)' % (
                    free, mem_need(pred), pred, basis)
            elif lock_holder():
                why = 'waiting for the lock: %s' % (lock_holder() or {}).get('what', '?')
            elif strict_admission:
                # This one unrounded observation both admits and records the start.
                # No timer, second sample or CPU-wait fallback may override it.
                cpu_gate_sample = free_cores()
                if not cpu_gate_sample >= t.get('cores', 1):
                    why = 'waiting for %d free cores (observed %.9g)' % (t.get('cores', 1), cpu_gate_sample)
            elif (t.get('cores', 1) > 1
                  and time.time() - t.setdefault('cpu_wait_from', time.time()) < CPU_WAIT_MAX_S
                  and (cpu_gate_sample := free_cores()) < t['cores']):
                why = 'waiting for %d free cores (quiet machine)' % t['cores']
            if why is None and not try_lock(t):
                why = 'waiting for the lock: %s' % (lock_holder() or {}).get('what', '?')
            if strict_admission and why is not None:
                if t.get('waiting_pid') == os.getpid():
                    t.pop('waiting_pid')
                save(q)
                raise SystemExit('strict admission refused (no command started): ' + why)
            if why is None:
                fc = cpu_gate_sample if strict_admission else round(free_cores(), 1)
                t.update(status='running', started=now(), runner_pid=os.getpid(), free_cores_at_start=fc,
                         free_gib_at_start=round(free, 1), mem_need_gib=mem_need(pred),
                         pred_peak_gib=round(pred, 2), pred_basis=basis, cmd_key=key,
                         job_name=job_nm if job else None, tracker=tracker)
                if fc < t.get('cores', 1):
                    age = max(0, time.time() - t.get('cpu_wait_from', start))
                    sample = 'not sampled' if cpu_gate_sample is None else '%.3f' % cpu_gate_sample
                    t['cpu_note'] = ('started with %.1f free cores (wanted %d); CPU wait timer age %.1f s; '
                                     'admission sample %s, start sample %.1f') % (fc, t['cores'], age, sample, fc)
                    print('%s %s WARNING %s' % (time.strftime('%H:%M:%S'), tid, t['cpu_note']), flush=True)
                save(q)
                break
            save(q)
        if (why or '').split(':')[0] != (said or '').split(':')[0]:
            print('%s %s %s' % (time.strftime('%H:%M:%S'), tid, why), flush=True)
            said = why
        if time.time() - start > MAX_WAIT_S:
            raise SystemExit('gave up after 12 h waiting')
        time.sleep(POLL_S)
    print('%s %s started (%s GiB TOTAL declared)' % (time.strftime('%H:%M:%S'), tid, t['gib']), flush=True)
    env = dict(os.environ)
    for k, v in (('PYTHONHASHSEED', '0'), ('PYTHONDONTWRITEBYTECODE', '1'), ('OMP_NUM_THREADS', '1'),
                 ('OPENBLAS_NUM_THREADS', '1'), ('MKL_NUM_THREADS', '1')):
        env.setdefault(k, v)
    # Harnesses size their own per-arm start gates from the ticket's booking (Michael, 16 Oct ~14:05).
    env['RUNQ_TICKET_GIB'] = str(t['gib'])
    env['RUNQ_PRED_PEAK_GIB'] = str(round(pred, 2))
    env['RUNQ_MEM_NEED_GIB'] = str(mem_need(pred))
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
            t.update(status='done' if code == 0 else 'failed', exit=code, ended=now(),
                     peak_rss_gib=round(peak, 2), small_jobs_max=small_max)
            save(q)
            if code == 0:  # a failed run's peak may be partial, so it never lowers a prediction
                record_peak(key, peak, tid, tracker)
    print('%s %s exit %s, tree peak RSS %.2f GiB (predicted %.2f, declared %s; tracked by %s)'
          % (time.strftime('%H:%M:%S'), tid, code, peak, pred, t['gib'], tracker), flush=True)
    if peak > pred * (1 + MEM_MARGIN):
        print('%s %s WARNING: peak exceeded the prediction by more than %d%%; book from this peak next time'
              % (time.strftime('%H:%M:%S'), tid, MEM_MARGIN * 100), flush=True)
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
                spare = psutil.virtual_memory().available / GIB - sum(unrealised_gib(t) for t in running)
                if spare < gib + FREE_FLOOR_GIB:
                    why = 'waiting for memory: %.1f GiB spare after running tickets, need %.1f (%s)' % (
                        spare, gib + FREE_FLOOR_GIB, basis)
            if why is None:
                rows = small_rows(q)
                if len(rows) >= SMALL_ACTIVE_LIMIT:
                    raise SystemExit('active small command registry is full; resolve retained admissions')
                owner = os.getpid()
                job_name = 'Local\\runq-small-%d' % owner
                job = make_job(job_name)
                if os.name == 'nt' and not job:
                    raise SystemExit('small: Windows job tracking unavailable; no command started')
                tracker = 'job' if job else 'children'
                row = dict(id='%d:%d' % (owner, time.time_ns()), owner_pid=owner,
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
        reap(q)
        save(q)
    held = lock_holder()
    print('lock:', held.get('what', held) if held else 'free',
          '| free RAM %.1f GiB' % (psutil.virtual_memory().available / GIB),
          '| QUEUE ON HOLD: %s' % q['hold'] if q.get('hold') else '',
          '| PAUSED: %s' % q['pause'] if q.get('pause') else '')
    order = {'running': 0, 'external': 0, 'queued': 1, 'held': 1}
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


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('status'); s.add_argument('--all', action='store_true')
    r = sub.add_parser('run'); r.add_argument('--strict-admission', action='store_true')
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
        a.add_argument('--' + k, required=True)
    a.add_argument('--gib', type=float, required=True); a.add_argument('--min', type=int, required=True)
    for k in ('why', 'runtime', 'inputs', 'outputs'):
        a.add_argument('--' + k, default='')
    a.add_argument('--pos', type=int); a.add_argument('--status', default='queued', choices=['queued', 'external'])
    a.add_argument('--cores', type=int, default=1); a.add_argument('--quiet', action='store_true')
    o = sub.add_parser('reorder'); o.add_argument('ticket'); o.add_argument('pos', type=int)
    c = sub.add_parser('cancel'); c.add_argument('ticket')
    f = sub.add_parser('finish'); f.add_argument('ticket'); f.add_argument('exit')
    args = p.parse_args()
    if args.cmd == 'status':
        return cmd_status(args.all)
    if args.cmd == 'run':
        cmd = args.command[1:] if args.command[:1] == ['--'] else args.command
        return cmd_run(args.ticket, cmd, strict_admission=args.strict_admission)
    if args.cmd == 'small':
        cmd = args.command[1:] if args.command[:1] == ['--'] else args.command
        return cmd_small(args.cores, cmd, args.gib)
    with Mutex():
        q = load()
        if args.cmd == 'add':
            tid = 'q%02d' % q['next_id']; q['next_id'] += 1
            live = pending(q)
            pos = len(live) + 1 if args.pos is None else args.pos
            for t in live:
                if t['pos'] >= pos:
                    t['pos'] += 1
            q['tickets'].append(dict(id=tid, owner=args.owner, gib=args.gib, min=args.min, what=args.what,
                                     why=args.why, runtime=args.runtime, inputs=args.inputs,
                                     outputs=args.outputs, pos=pos, status=args.status, added=now(),
                                     cores=args.cores, quiet=args.quiet))
            print('added', tid, 'at position', pos)
        elif args.cmd == 'reorder':
            live = [t for t in pending(q) if t['id'] != args.ticket]
            live.insert(args.pos - 1, find(q, args.ticket))
            for i, t in enumerate(live, 1):
                t['pos'] = i
            print('order:', ' '.join(t['id'] for t in live))
        elif args.cmd == 'hold':
            # Waiting runners (old code included) exit on their next poll once their ticket is no longer
            # 'queued'; running tickets are untouched and finish. 'hold off' re-queues; owners relaunch.
            q['hold'] = args.why if args.state == 'on' else None
            for t in q['tickets']:
                if args.state == 'on' and t['status'] == 'queued':
                    t['status'] = 'held'
                elif args.state == 'off' and t['status'] == 'held' and not t.get('ticket_hold'):
                    t['status'] = 'queued'; t.pop('waiting_pid', None)
            print('hold', args.state, args.why if args.state == 'on' else '')
        elif args.cmd == 'pause':
            q['pause'] = args.why if args.state == 'on' else None
            print('pause', args.state, args.why if args.state == 'on' else '')
        elif args.cmd == 'hold-ticket':
            # One ticket only (e.g. its review is still running): its waiting runner exits on the next poll and it
            # stops blocking the tickets behind it. 'off' re-queues it unless the whole queue is on hold; the owner
            # relaunches. A global 'hold off' leaves ticket holds in place.
            t = find(q, args.ticket)
            if args.state == 'on':
                if t['status'] not in ('queued', 'held'):
                    raise SystemExit('ticket %s is %s; only a queued ticket can be held' % (t['id'], t['status']))
                t['status'] = 'held'; t['ticket_hold'] = args.why
            else:
                t.pop('ticket_hold', None)
                if t['status'] == 'held' and not q.get('hold'):
                    t['status'] = 'queued'; t.pop('waiting_pid', None)
            print('ticket', t['id'], t['status'], t.get('ticket_hold', ''))
        elif args.cmd == 'setcpu':
            find(q, args.ticket).update(cores=args.cores, quiet=args.quiet, exclusive=args.exclusive)
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
