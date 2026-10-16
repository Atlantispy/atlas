"""WP18 proof summary (run_wp18_parity.sh): fail closed, exit 0 only on PASS.

Usage: wp18_parity_summary.py <evidence folder>
Each set's serial arm is the reference. Every other arm must exist, carry no error, issue the
same number of records with the same record-list hash, and run the same package. The two arms
that exist to exercise the workers (iv2-w2 at the default threshold, iv1-w2-min30) must also
show the endpoint session at work: jobs started, at least one adopted, none refused. Without
that the equality would hold trivially (the CPU gate can refuse the session and leave the arm
serial, as in q12). iv1-w2 at the default threshold is equality only; its route is reported.
A missing file, key or None counts as FAIL. Gate decisions and memory are printed per arm.
"""
import json
import os
import sys

SETS = (('iv2-serial', (('iv2-w2', True),)),
        ('iv1-serial', (('iv1-w2', False), ('iv1-w2-min30', True))))


def load(out, name):
    path = os.path.join(out, name + '.json')
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf8') as f:
            return json.load(f)
    except ValueError:
        return None


def batches(d):
    decision = d.get('decision')
    return (decision.get('endpoint_batches') if isinstance(decision, dict) else None) or {}


def main():
    out = sys.argv[1]
    ok, lines = True, []
    for base_name, arms in SETS:
        base = load(out, base_name)
        base_ok = (base is not None and base.get('error') is None and type(base.get('records')) is int
                   and base['records'] > 0 and type(base.get('records_sha256')) is str)
        ok = ok and base_ok
        if base is None:
            lines.append('%-14s MISSING  FAIL' % base_name)
        else:
            lines.append('%-14s records %s  wall %s s  parent cpu %s s  parent peak %s MiB  error %s  %s' % (
                base_name, base.get('records'), base.get('wall_s'), base.get('parent_cpu_s'),
                base.get('parent_peak_working_set_mib'), base.get('error'), 'ok' if base_ok else 'FAIL'))
        for name, engaged in arms:
            a = load(out, name)
            if a is None:
                ok = False
                lines.append('%-14s MISSING  FAIL' % name)
                continue
            e, c = batches(a), a.get('concurrency') or {}
            checks = dict(
                no_error=a.get('error') is None,
                same_records=base is not None and base_ok and a.get('records') == base['records'],
                identical=base is not None and base_ok and a.get('records_sha256') == base['records_sha256'],
                same_package=base is not None and a.get('package_digest') is not None
                and a.get('package_digest') == base.get('package_digest'))
            if engaged:
                checks.update(
                    workers_started=type(e.get('started')) is int and e['started'] > 0,
                    adopted=type(e.get('adopted')) is int and e['adopted'] > 0,
                    none_refused=e.get('refused') == 0)
            passed = all(checks.values())
            ok = ok and passed
            lines.append('%-14s records %s  wall %s s  parent cpu %s s  %s  %s' % (
                name, a.get('records'), a.get('wall_s'), a.get('parent_cpu_s'),
                'IDENTICAL' if checks['identical'] else 'DIFFERENT',
                'PASS' if passed else 'FAIL: ' + ' '.join(k for k, v in checks.items() if not v)))
            lines.append('%-14s gate: route %s reason %s detail %s; workers %s started %s jobs %s adopted %s '
                         'declined %s refused %s lookahead supports %s peak live %s' % (
                '', e.get('route'), e.get('reason'), e.get('detail'), e.get('workers'), e.get('started'),
                e.get('jobs'), e.get('adopted'), e.get('declined'), e.get('refused'),
                e.get('lookahead_supports'), c.get('peak_live')))
            lines.append('%-14s memory: parent peak %s MiB; children (sampled) peak %s processes, largest %s MiB, '
                         'total %s MiB; session peak_child_rss %s, peak_child_ledger %s' % (
                '', a.get('parent_peak_working_set_mib'), c.get('peak_child_processes'),
                c.get('peak_single_child_rss_mib'), c.get('peak_children_rss_mib'),
                e.get('peak_child_rss'), e.get('peak_child_ledger')))
    print('\n'.join(lines))
    print('PROOF', 'PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
