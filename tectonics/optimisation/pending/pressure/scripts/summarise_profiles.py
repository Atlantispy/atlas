"""Compact tables from py-spy raw stacks and cProfile dumps (T/ps). Read-only.

pyspy: summarise_profiles.py pyspy <pyspy.txt> [--top N]
  Splits samples by process (root frame 'process PID:"cmd"') and, in the main process, by
  phase: the first matching marker frame from the leaf side wins
  (check_initial_pressure_force > initial_spatial_owner > initial_metrics > initial_partition >
  radial_differential_fixture > other). Per phase: samples, top functions by SELF and by
  INCLUSIVE samples (function = name + file, line numbers dropped), and self by module file.
  At 100 Hz one sample is about 10 ms of one thread's time.
prof: summarise_profiles.py prof <file.prof> [--top N]
  Top functions by tottime and by cumtime (with call counts), and tottime by module file.
"""
import argparse
import collections
import re
import sys
from pathlib import Path

FRAME = re.compile(r'^(?P<name>.*?) \((?P<file>[^()]*?)(?::(?P<line>\d+))?\)$')
MARKERS = ('check_initial_pressure_force', 'initial_spatial_owner', 'initial_metrics', 'initial_partition',
           'radial_differential_fixture')
# Sub-stage markers inside the pressure call, outermost first (the innermost present wins).
PRESSURE_PARTS = ('PreparedRegionalStokes3D', 'prescribe_reservoir_pressure', 'differential_pressure_forcing',
                  '_cut_torque', 'moving_wall_integrals', '_current_regions', 'balance', 'prepare',
                  'PreparedDifferentialTrace', '_construct', '_independent_constraints',
                  'DifferentialPlateBoundaryLift', 'PreparedRegionalDriving')


def short(path):
    p = path.replace('\\', '/')
    for cut in ('/atlas_tectonics/', '/helpers/', '/tests/', '/Lib/'):
        if cut in p:
            return p[p.index(cut)+1:]
    return p.rsplit('/', 1)[-1]


def parse(frame):
    m = FRAME.match(frame)
    if not m:
        return frame, ''
    return m['name'], short(m['file'])


def pyspy(path, top):
    by_proc = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, collections.Counter(),
                                                                               collections.Counter(), collections.Counter()]))
    parts = collections.Counter()
    procs = {}
    for raw in Path(path).read_text(encoding='utf8', errors='replace').splitlines():
        stack, _, count = raw.rpartition(' ')
        if not stack or not count.isdigit():
            continue
        n = int(count)
        frames = stack.split(';')
        pid = 'main'
        # Nested process frames (venv launcher -> python -> workers): the innermost names the process.
        while frames and frames[0].startswith('process '):
            head = frames.pop(0)
            pid = head.split(':', 1)[0][8:]
            procs.setdefault(pid, head[:160])
        # Skip the interpreter launcher shell frames that are not Python frames.
        names = [parse(f) for f in frames]
        phase = 'other'
        for marker in MARKERS:
            if any(name == marker or name.endswith('.'+marker) for name, _ in names):
                phase = marker
                break
        if phase == 'check_initial_pressure_force':
            part = 'pressure:other'
            for marker in PRESSURE_PARTS:
                if any(name == marker or name.startswith(marker+'.') or name.endswith('.'+marker)
                       or name.endswith('__init__') and marker in name for name, _ in names):
                    part = 'pressure:'+marker
            parts[part] += n
        bucket = by_proc[pid][phase]
        bucket[0] += n
        if names:
            bucket[1][names[-1]] += n                      # self
            for key in set(names):
                bucket[2][key] += n                        # inclusive
            bucket[3][names[-1][1]] += n                   # self by module
    for pid, phases in by_proc.items():
        total = sum(b[0] for b in phases.values())
        print(f'## process {pid}: {total} samples  {procs.get(pid, "")}')
        for phase, (n, self_, incl, mods) in sorted(phases.items(), key=lambda kv: -kv[1][0]):
            if n < max(10, total//200):
                continue
            print(f'### {phase}: {n} samples ({100*n/total:.1f}%)')
            print('  self:')
            for (name, file), k in self_.most_common(top):
                print(f'    {k:7d} {100*k/n:5.1f}%  {name}  [{file}]')
            print('  inclusive:')
            for (name, file), k in incl.most_common(top):
                print(f'    {k:7d} {100*k/n:5.1f}%  {name}  [{file}]')
            print('  self by module:')
            for file, k in mods.most_common(min(top, 15)):
                print(f'    {k:7d} {100*k/n:5.1f}%  {file}')
    if parts:
        print('## pressure sub-stages (innermost marker present on the stack)')
        total = sum(parts.values())
        for part, k in parts.most_common():
            print(f'    {k:7d} {100*k/total:5.1f}%  {part}')


def prof(path, top):
    import pstats
    st = pstats.Stats(str(path))
    rows = []
    for (file, line, name), (cc, nc, tt, ct, _) in st.stats.items():
        rows.append((tt, ct, nc, cc, name, short(file), line))
    total = sum(r[0] for r in rows)
    print(f'## {path}: total tottime {total:.1f} s')
    print('### by tottime')
    for tt, ct, nc, cc, name, file, line in sorted(rows, key=lambda r: -r[0])[:top]:
        print(f'  {tt:8.2f} {100*tt/total:5.1f}%  cum {ct:8.2f}  calls {nc:>9}  {name}  [{file}:{line}]')
    print('### by cumtime')
    for tt, ct, nc, cc, name, file, line in sorted(rows, key=lambda r: -r[1])[:top]:
        print(f'  cum {ct:8.2f}  tt {tt:8.2f}  calls {nc:>9}  {name}  [{file}:{line}]')
    mods = collections.Counter()
    for tt, _, _, _, _, file, _ in rows:
        mods[file] += tt
    print('### tottime by module')
    for file, tt in mods.most_common(min(top, 20)):
        print(f'  {tt:8.2f} {100*tt/total:5.1f}%  {file}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('kind', choices=('pyspy', 'prof'))
    ap.add_argument('path')
    ap.add_argument('--top', type=int, default=25)
    a = ap.parse_args()
    (pyspy if a.kind == 'pyspy' else prof)(a.path, a.top)
    sys.stdout.flush()
