"""Read-only: every running python process with its start time, memory and command line.

Usage: python -B py_processes.py [SUBSTRING ...]
Lists python processes (optionally only those whose command line contains every SUBSTRING), so
that a source file is not changed while another chat's run has it loaded (a run's loaded-source
fence refuses at its end if a module file changed). Nothing is stopped or changed.
"""
import sys
import time

import psutil


def main():
    wanted = [text.lower() for text in sys.argv[1:]]
    rows = []
    for process in psutil.process_iter(['pid', 'ppid', 'name', 'create_time']):
        try:
            if 'python' not in (process.info['name'] or '').lower():
                continue
            command = ' '.join(process.cmdline())
            if not all(text in command.lower() for text in wanted):
                continue
            rows.append((process.info['create_time'], process.pid, process.info['ppid'],
                         process.memory_info().rss >> 20, command))
        except psutil.Error:
            pass
    for created, pid, ppid, rss, command in sorted(rows):
        started = time.strftime('%H:%M:%S', time.localtime(created))
        print(f'{started} pid {pid:6d} ppid {ppid:6d} {rss:6d} MiB  {command[:400]}')


if __name__ == '__main__':
    main()
