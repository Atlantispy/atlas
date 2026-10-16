"""Run one heavy command under the cooperative heavy-run lock (coordinator rule, 16 Oct 2026).

Usage: python -B run_with_heavy_lock.py OWNER EXPECTED_PEAK_GIB WHAT -- COMMAND [ARG ...]

Before any run expected to exceed 2 GiB real, the chats on this machine take
fidelity-integration-20261005/heavy-run.lock.json, created exclusively with
{"owner", "pid", "expected_peak_gib", "started", "what"}. If the lock exists
and its PID is alive, nothing starts: exit code 75, so the caller does lighter
work and retries later. A lock whose PID is dead is stale and is replaced
(remove, then exclusive create; losing that race also exits 75). The lock
names this wrapper's PID, which lives exactly as long as the command, and is
removed when the command ends, only if it still names this PID.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
LOCK = HERE.parents[5]/'heavy-run.lock.json'
BUSY = 75


def holder():
    try:
        value = json.loads(LOCK.read_text(encoding='utf-8'))
        return value if type(value) is dict else None
    except (OSError, ValueError):
        return None


def create(record):
    descriptor = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        json.dump(record, handle)


def acquire(record):
    try:
        create(record)
        return True
    except FileExistsError:
        pass
    current = holder()
    pid = current.get('pid') if current else None
    if type(pid) is int and psutil.pid_exists(pid):
        print(f'heavy-run lock held by {current.get("owner")} (pid {pid}, {current.get("what")}); not starting',
              file=sys.stderr)
        return False
    print(f'replacing stale heavy-run lock: {current}', file=sys.stderr)
    try:
        LOCK.unlink()
        create(record)
        return True
    except (FileNotFoundError, FileExistsError):
        print('lost the stale-lock race; not starting', file=sys.stderr)
        return False


def main():
    split = sys.argv.index('--')
    owner, peak, what = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    command = sys.argv[split+1:]
    record = {'owner': owner, 'pid': os.getpid(), 'expected_peak_gib': peak,
              'started': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'what': what}
    if not acquire(record):
        raise SystemExit(BUSY)
    print('heavy-run lock taken:', json.dumps(record), flush=True)
    try:
        code = subprocess.run(command, check=False).returncode
    finally:
        current = holder()
        if current and current.get('pid') == os.getpid():
            LOCK.unlink()
            print('heavy-run lock released', flush=True)
    raise SystemExit(code)


if __name__ == '__main__':
    main()
