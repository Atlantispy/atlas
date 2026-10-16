"""Does runq's tree sampler (psutil children(recursive=True)) see python started by Git Bash?

Usage: python -B -I tree_probe.py PYTHON
Starts bash -c with three shapes of child (direct, timeout, timeout in background + wait), each python
holding 200 MiB for 8 s, and samples like runq.tree_rss_gib every 0.5 s. Prints the peak seen per shape.
"""
import subprocess
import sys
import time

import psutil

PY = sys.argv[1].replace('\\', '/')
HOLD = '"%s" -B -I -c "import time; x = bytearray(200*2**20); time.sleep(8)"' % PY
POPEN = ('"%s" -B -I -c "import subprocess, sys; ps = [subprocess.Popen([sys.executable, \'-B\', \'-I\', \'-c\', '
         '\'import time; x = bytearray(200*2**20); time.sleep(8)\']) for _ in range(2)]; [p.wait() for p in ps]"' % PY)
SHAPES = {
    'direct': HOLD,
    'timeout': 'timeout 60 ' + HOLD,
    'timeout-bg-wait': 'timeout 60 %s & wait' % HOLD,
    'bg-wait': '%s & wait' % HOLD,
    'two-bg-wait': '%s & %s & wait' % (HOLD, HOLD),
    'python-popen-2': POPEN,
    'timeout-python-popen-2': 'timeout 60 ' + POPEN,
    'subshell-timeout-true-bg': '( timeout 60 %s; true ) & wait' % HOLD,
    'subshell-timeout-bg': '( timeout 60 %s ) & wait' % HOLD,
    'run1-bg-wait-2': ('"{py}" -B -I "{r1}" 60 {h} & "{py}" -B -I "{r1}" 60 {h} & wait'
                       .format(py=PY, r1=sys.argv[0].replace('\\', '/').rsplit('/', 2)[0] + '/scripts/run1.py',
                               h=HOLD)),
}
if len(sys.argv) > 2:
    SHAPES = {k: v for k, v in SHAPES.items() if k in sys.argv[2:]}
for name, script in SHAPES.items():
    proc = subprocess.Popen(['bash', '-c', script])
    me = psutil.Process(proc.pid)
    peak, errors, seen = 0.0, 0, set()
    while proc.poll() is None:
        try:
            kids = me.children(recursive=True)
            seen.update(k.name() for k in kids)
            peak = max(peak, sum(p.memory_info().rss for p in [me] + kids if p.is_running()) / 2**30)
        except psutil.Error:
            errors += 1
        time.sleep(0.5)
    print('%-16s tree peak %.2f GiB, sample errors %d, children seen %s' % (name, peak, errors, sorted(seen)))
