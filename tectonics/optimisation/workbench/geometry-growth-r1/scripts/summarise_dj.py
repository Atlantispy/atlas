"""Summary of the D-j proof (run_workers_parity_dj.sh). Exit 0 only if every check passes.

Checks (refuter 16 Oct):
- every arm's records and streams equal its set's serial pass on THIS runtime, and that serial
  pass equals r2's serial (RC1+workers_six runtime) for the same set;
- the serial passes wrote timing stores bound to this runtime (no 'no compatible observations');
- IV2 w2 (control): the 'interface-route' gate PASSES and the single-contact route is taken
  (reason 'selected'), i.e. RC1's behaviour at two workers;
- IV2 w4/w6: the 'interface-route' gate is present and NOT passed, and the rolling interface
  batches ran more than two live workers;
- IV1 w4/w6: more than two live batch workers (the interface and wall batch controllers only;
  refuter round 3: a peak from any other controller is not a batch worker).
- every arm ran the same package as its set's serial pass (package_digest).
VOID-ENVIRONMENT (16 Oct, coordinator): a w4/w6 arm whose only failed check is its peak check, and
whose session(s) the machine itself held to at most two workers, is void, not failed: the arm could
not show more than two workers. 'The machine held it' is read from the session gates the runtime
records (decision.interface_batches.gates; IV1 also decision.wall_parallel.rolling.gates). The arm
asked for more than two workers (workers_policy > 2), at least one session has gates, and in each:
- the FIRST gate whose 'workers' is <= 2 is the cpu or memory gate (a budget or predicate-unit trim
  stays a FAIL: that is the design, not the machine);
- that gate's OWN recorded reading shows the machine could not fit 3 workers then, though a quiet
  one could (refuter 16 Oct, P1: the gate's name alone would also void a cap applied before the
  gates, or an over-booked per-worker size). The runtime's tests: cpu fits n when free_cores >= n+1,
  so free_cores < 4 with physical_cores >= 4; memory fits n when available >= n*per_worker+reserve,
  so available < 3*per_worker+reserve <= this machine's physical RAM, where per_worker and reserve
  must be the r6 policy's own booking, 768 MiB and 2 GiB (refuter round 3, P2: any other booking,
  e.g. an over-booked per-worker size that 3 workers still fit in RAM, FAILs);
- the session then ran normally at that count: reason 'selected' and no last_error; or, trimmed to
  0, it was refused by that gate and nothing else ('session not opened', detail '<gate>: ...', no
  gate recorded after it). Any other stop (funding refused, binding changed, a worker error) FAILs.
Every other session the arm has (IV2: the interface session; IV1: interface and wall) must be
present, and one without gates must have stopped for a design reason before any gate was read
('eligible work below threshold') with no last_error (refuter round 3, P3: a gate-less session that
stopped on 'timing binding changed' or a schedule error is not the machine's doing).
free_cores is rounded to 2 places by the runtime, so a reading in [3.995, 4) shows 4.0 and FAILs
(closed). VOID never passes.
Superseded attempts (refuter round 3, P1): run_dj_rearm.sh copies every attempt its merge replaced
into OUT/superseded/<set>-w<n>[-r<k>].json. Each is judged by the same checks against its set's
serial pass and must be PASS or VOID-ENVIRONMENT: a rerun cannot hide a failed attempt.
Exit 0 PASSED; 1 FAILED (any failed check, missing arm or key, failed or unknown superseded attempt);
3 VOID-ENVIRONMENT (no failure, at least one void arm: rerun those arms in a quiet window).
Usage: summarise_dj.py OUT_DIR R2_DIR
"""
import json
import os
import re
import sys
from typing import TypeGuard

MACHINE_GATES = ('cpu', 'memory')
SHOWN = 3   # the smallest worker count that can show more than two live workers
# The r6 policy's memory booking: child_bytes 512 MiB + CHILD_BASELINE 256 MiB, ram_reserve_bytes 2 GiB.
POLICY_PER_WORKER = 805306368
POLICY_RESERVE = 2147483648
DESIGN_REASONS = ('eligible work below threshold',)   # a gate-less session's only accepted stop
BATCH_CONTROLLERS = ('interface_batches', 'wall_batches')
ARMS = (('iv2', ('serial', 'w2', 'w4', 'w6')), ('iv1', ('serial', 'w4', 'w6')))


def load(path):
    return json.load(open(path)) if os.path.exists(path) else None


def number(x) -> TypeGuard[float]:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def physical_ram():
    try:
        import psutil
        return psutil.virtual_memory().total
    except Exception:
        return None   # unknown: no memory gate reading can void an arm


def could_not_fit(gate, ram):
    """True if the gate's own reading shows the machine could not fit SHOWN workers then, though a quiet one could."""
    v = gate.get('value') if isinstance(gate.get('value'), dict) else {}
    if gate.get('gate') == 'cpu':
        free, cores = v.get('free_cores'), v.get('physical_cores')
        return number(free) and number(cores) and free < SHOWN+1 <= cores
    if gate.get('gate') == 'memory':
        avail, one, reserve = v.get('available_bytes'), v.get('per_worker_bytes'), v.get('reserve_bytes')
        if not (number(avail) and number(ram) and type(one) is int and type(reserve) is int
                and one == POLICY_PER_WORKER and reserve == POLICY_RESERVE):
            return False
        return avail < SHOWN*one+reserve <= ram
    return False


def held_by_machine(session, ram):
    """True if this session's first gate down to <= 2 workers is a machine gate whose reading could not
    fit 3, and the session then ran normally at that count (or that gate alone refused it)."""
    gates = session['gates']
    for i, g in enumerate(gates):
        value = g.get('value')
        workers = value.get('workers') if isinstance(value, dict) else None
        if isinstance(workers, int) and not isinstance(workers, bool) and workers <= 2:
            if g.get('gate') not in MACHINE_GATES or not could_not_fit(g, ram) or session.get('last_error'):
                return False
            if workers > 0:
                return session.get('reason') == 'selected'
            return (g.get('passed') is False and i == len(gates)-1 and session.get('reason') == 'session not opened'
                    and str(session.get('detail', '')).startswith(g['gate']+':'))
    return False


def machine_held(name, d, ram):
    """True if the arm asked for > 2 workers, every session it has is present, at least one recorded
    gates, the machine held every such session to <= 2 (held_by_machine), and every gate-less one
    stopped for a design reason with no error."""
    policy, dec = d.get('workers_policy'), d['decision']
    if not (isinstance(policy, int) and not isinstance(policy, bool) and policy > 2):
        return False
    sessions = [dec.get('interface_batches')]
    if name == 'iv1':
        sessions.append((dec.get('wall_parallel') or {}).get('rolling'))
    if not all(isinstance(s, dict) for s in sessions):
        return False
    gated = [s for s in sessions if s.get('gates')]
    plain = [s for s in sessions if not s.get('gates')]
    if any(s.get('reason') not in DESIGN_REASONS or s.get('last_error') for s in plain):
        return False
    return bool(gated) and all(held_by_machine(s, ram) for s in gated)


def judge(name, arm, d, serial, ram):
    """(verdict, failed checks, interface-route gate, interface peak, batch peak) of one arm's output."""
    base = (serial['records_sha256'], serial['streams_sha256'])
    dec = d['decision']
    same = (d['records_sha256'], d['streams_sha256']) == base and d['error'] is None
    gate = next((g for g in dec.get('gates') or [] if g.get('gate') == 'interface-route'), None)
    ctrl = d.get('concurrency', {}).get('controllers', {})
    peak_if = ctrl.get('interface_batches', {}).get('peak_live', 0)
    peak = max((ctrl[k]['peak_live'] for k in BATCH_CONTROLLERS if k in ctrl), default=0)
    checks = dict(identical=same,
                  same_package=d.get('package_digest') is not None
                  and d.get('package_digest') == serial.get('package_digest'))
    if arm != 'serial':
        checks['profile_bound'] = dec.get('reason') != 'no compatible observations'
    if name == 'iv2' and arm == 'w2':
        checks['gate_passes'] = gate is not None and gate.get('passed') is True
        checks['single_contact_taken'] = dec.get('reason') == 'selected'
    if name == 'iv2' and arm in ('w4', 'w6'):
        checks['gate_refuses'] = gate is not None and gate.get('passed') is False
        checks['interface_peak_gt_2'] = peak_if > 2
    if name == 'iv1' and arm in ('w4', 'w6'):
        checks['peak_gt_2'] = peak > 2
    failed = [k for k, v in checks.items() if not v]
    if failed in (['interface_peak_gt_2'], ['peak_gt_2']) and machine_held(name, d, ram):
        verdict = 'VOID-ENVIRONMENT'
    else:
        verdict = 'FAIL' if failed else 'PASS'
    return verdict, failed, gate, peak_if, peak


def main():
    out, r2 = sys.argv[1], sys.argv[2]
    ok, lines, void, ram, serials = True, [], [], physical_ram(), {}
    for name, arms in ARMS:
        serial, old = load('%s/%s-serial.json' % (out, name)), load('%s/%s-serial.json' % (r2, name))
        if serial is None:
            ok = False
            lines.append('%s serial MISSING' % name)
            continue
        serials[name] = serial
        base = (serial['records_sha256'], serial['streams_sha256'])
        cross = old is not None and (old['records_sha256'], old['streams_sha256']) == base
        ok &= cross
        lines.append('%s serial equals r2 serial: %s' % (name, cross))
        for arm in arms:
            d = load('%s/%s-%s.json' % (out, name, arm))
            if d is None:
                ok = False
                lines.append('%s %s MISSING' % (name, arm))
                continue
            verdict, failed, gate, peak_if, peak = judge(name, arm, d, serial, ram)
            if verdict == 'VOID-ENVIRONMENT':
                void.append('%s %s' % (name, arm))
            ok &= verdict != 'FAIL'
            lines.append('%s %-6s %s wall_s %s reason %r gate %s peak(if/batch) %d/%d parent_mib %s children_mib %s %s' % (
                name, arm, verdict, d['wall_s'], d['decision'].get('reason'),
                None if gate is None else gate.get('passed'), peak_if, peak, d.get('parent_peak_working_set_mib'),
                d.get('concurrency', {}).get('peak_children_rss_mib'), ' '.join(failed)))
    folder = os.path.join(out, 'superseded')
    for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        m = re.fullmatch(r'(iv[12])-(w[1-9][0-9]*)(?:-r[1-9][0-9]*)?\.json', f)
        known = m is not None and m.group(2) in dict(ARMS)[m.group(1)]
        if m is None or not known or m.group(1) not in serials:
            ok = False
            lines.append('superseded %s FAIL (%s)' % (f, 'not a D-j arm attempt' if not known else 'no serial pass'))
            continue
        verdict, failed, _, peak_if, peak = judge(m.group(1), m.group(2), load(os.path.join(folder, f)),
                                                  serials[m.group(1)], ram)
        ok &= verdict != 'FAIL'
        lines.append('superseded %s %s peak(if/batch) %d/%d %s' % (f, verdict, peak_if, peak, ' '.join(failed)))
    print('\n'.join(lines))
    if not ok:
        print('D-J PROOF FAILED')
        sys.exit(1)
    if void:
        print('D-J PROOF VOID-ENVIRONMENT: rerun %s in a quiet window' % ', '.join(void))
        sys.exit(3)
    print('D-J PROOF PASSED')
    sys.exit(0)


if __name__ == '__main__':
    main()
