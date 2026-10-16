"""Read-only snapshot of machine load for timing caveats: CPU clock, busy CPUs, top CPU users.

Usage: python -B machine_load.py [SECONDS]
"""
import sys
import time

import psutil


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 3.
    processes = {}
    for process in psutil.process_iter(['pid', 'name']):
        try:
            processes[process.pid] = (process, process.cpu_times())
        except psutil.Error:
            pass
    psutil.cpu_percent(None)
    time.sleep(seconds)
    busy = psutil.cpu_percent(None)
    rows = []
    for pid, (process, before) in processes.items():
        try:
            after = process.cpu_times()
            used = (after.user+after.system)-(before.user+before.system)
            if used > .05*seconds:
                rows.append((used/seconds, pid, process.info['name'], process.memory_info().rss >> 20))
        except psutil.Error:
            pass
    frequency = psutil.cpu_freq()
    memory = psutil.virtual_memory()
    print(f'logical {psutil.cpu_count()} physical {psutil.cpu_count(logical=False)} busy {busy:.0f}% '
          f'(= {busy*psutil.cpu_count()/100:.1f} logical CPUs) clock {frequency.current:.0f}/{frequency.max:.0f} MHz '
          f'available {memory.available >> 30} of {memory.total >> 30} GiB')
    for cpus, pid, name, rss in sorted(rows, reverse=True)[:12]:
        print(f'  {cpus:5.2f} CPUs  pid {pid:6d}  {name:<24} {rss:6d} MiB')


if __name__ == '__main__':
    main()
