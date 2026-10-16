"""Read-only status of Python processes whose command line contains TEXT.

Usage: python -B proc_status.py TEXT [SECONDS]
Prints pid, parent pid, CPU percent over SECONDS (default 2), RSS, private
bytes, thread count, age and the command tail. Never signals or stops anything.
"""
import sys
import time

import psutil


def main():
    text, seconds = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
    found = []
    for process in psutil.process_iter(['pid', 'ppid', 'name', 'cmdline', 'create_time']):
        try:
            line = ' '.join(process.info['cmdline'] or [])
        except (psutil.Error, TypeError):
            continue
        if text in line and 'proc_status.py' not in line:
            found.append(process)
    for process in found:
        try:
            process.cpu_percent(None)
        except psutil.Error:
            pass
    time.sleep(seconds)
    now = time.time()
    for process in found:
        try:
            info = process.memory_info()
            print(f"pid {process.pid} ppid {process.info['ppid']} cpu {process.cpu_percent(None):.0f}% "
                  f"rss {info.rss/1e6:.0f} MB private {getattr(info, 'private', 0)/1e6:.0f} MB "
                  f"threads {process.num_threads()} age {now-process.info['create_time']:.0f} s "
                  f"cmd ...{' '.join(process.info['cmdline'])[-110:]}")
        except psutil.Error as error:
            print(f'pid {process.pid} gone: {error!r}')


if __name__ == '__main__':
    main()
