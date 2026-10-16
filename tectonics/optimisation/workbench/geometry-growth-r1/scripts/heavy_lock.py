"""Cooperative shared-machine lock (coordinator rule, 16 Oct): acquire / release.

acquire <pid> <expected_peak_gib> <what>: exclusive-create the lock file; if it
exists and its PID is alive, refuse (exit 3); if its PID is dead, replace it.
release <pid>: delete the lock only if it is ours (same owner and pid).
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psutil

LOCK = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/heavy-run.lock.json')
OWNER = 'Geometry, growth and workers'


def acquire(pid, peak, what):
    # Git Bash passes its MSYS pid; record the Windows PID others can check.
    msys, windows = int(pid), int(pid)
    try:
        windows = int(Path('/proc/%d/winpid' % msys).read_text())
    except (OSError, ValueError):
        if os.environ.get('MSYSTEM'):
            pass
    winpid_file = os.environ.get('HEAVY_LOCK_WINPID')
    if winpid_file:
        windows = int(winpid_file)
    body = json.dumps(dict(owner=OWNER, pid=windows, msys_pid=msys, expected_peak_gib=float(peak),
                           started=datetime.now(timezone.utc).isoformat(), what=what))
    for _ in range(2):
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                held = json.loads(LOCK.read_text(encoding='utf8'))
            except (OSError, ValueError):
                print('lock unreadable; not replacing'); return 3
            if psutil.pid_exists(int(held.get('pid', -1))):
                print('lock held:', held); return 3
            LOCK.unlink()          # stale: its PID is dead
            continue
        with os.fdopen(fd, 'w', encoding='utf8') as f:
            f.write(body)
        print('acquired', body); return 0
    return 3


def release(pid):
    try:
        held = json.loads(LOCK.read_text(encoding='utf8'))
    except FileNotFoundError:
        print('no lock'); return 0
    if held.get('owner') == OWNER and int(pid) in (int(held.get('pid', -1)), int(held.get('msys_pid', -1))):
        LOCK.unlink(); print('released'); return 0
    print('not ours; left in place:', held); return 3


if __name__ == '__main__':
    command = sys.argv[1]
    sys.exit(acquire(*sys.argv[2:5]) if command == 'acquire' else release(sys.argv[2]))
