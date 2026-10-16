"""Coordinator decision 16 Oct ~13:40: stop q03 cleanly once proof arm 2 has finished.

Waits until evidence/h12-r1/arm-2.log carries the child's final '"mode": "proof"' line (printed
after arm-2.json is written), then ends ONLY the q03 runner's own process tree: the runner PID
recorded in T/q/queue.json for q03, checked to be `runq.py run q03`, and its descendants,
deepest first. Nothing else is touched.
"""
import json
import sys
import time
from pathlib import Path

import psutil

HS = Path(__file__).resolve().parents[1]
T = HS.parent
OUT = HS/'evidence'/'h12-r1'
log = OUT/'arm-2.log'
while not (log.exists() and '"mode": "proof"' in log.read_text(encoding='utf8', errors='replace')):
    time.sleep(10)
print(time.strftime('%H:%M:%S'), 'arm-2 finished:', log.read_text(encoding='utf8', errors='replace').strip().splitlines()[-1])
queue = json.loads((T/'q'/'queue.json').read_text(encoding='utf8'))
items = queue if isinstance(queue, list) else queue.get('tickets', queue)
items = list(items.values()) if isinstance(items, dict) else items
ticket = next(t for t in items if isinstance(t, dict) and t.get('id') == 'q03')
runner = psutil.Process(int(ticket['runner_pid']))
cmd = ' '.join(runner.cmdline())
if 'runq.py' not in cmd or ' q03' not in cmd:
    sys.exit('runner PID %d is not the q03 runner: %s' % (runner.pid, cmd))
tree = runner.children(recursive=True)
for p in reversed(tree):
    try:
        print('stop', p.pid, ' '.join(p.cmdline())[:160])
        p.kill()
    except psutil.NoSuchProcess:
        pass
psutil.wait_procs(tree, timeout=30)
print(time.strftime('%H:%M:%S'), 'q03 children stopped; runner', runner.pid, 'records the exit itself')
