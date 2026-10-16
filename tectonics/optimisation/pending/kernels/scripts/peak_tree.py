"""Run one command and report its process tree's peak memory (Windows working set).

Usage: python -B -I peak_tree.py <label> -- <command> [args]
Polls every 0.1 s: the sum of RSS over the child and its descendants (tree peak), and the
child's own peak_wset (the OS's exact per-process peak, read while it is alive). Prints one
JSON line: label, exit code, seconds, tree_peak_mib, child_peak_wset_mib.
"""
import json
import subprocess
import sys
import time

import psutil

label = sys.argv[1]
if sys.argv[2] != '--':
    raise SystemExit('usage: peak_tree.py <label> -- <command> [args]')
begun = time.perf_counter()
child = subprocess.Popen(sys.argv[3:])
process = psutil.Process(child.pid)
tree_peak = own_peak = 0
while child.poll() is None:
    total = 0
    try:
        members = [process] + process.children(recursive=True)
    except psutil.Error:
        members = []
    for member in members:
        try:
            info = member.memory_info()
        except psutil.Error:
            continue
        total += info.rss
        if member.pid == child.pid:
            own_peak = max(own_peak, getattr(info, 'peak_wset', info.rss))
    tree_peak = max(tree_peak, total)
    time.sleep(0.1)
print(json.dumps(dict(label=label, exit=child.returncode, seconds=round(time.perf_counter()-begun, 1),
                      tree_peak_mib=round(tree_peak/2**20, 1), child_peak_wset_mib=round(own_peak/2**20, 1))))
sys.exit(child.returncode)
