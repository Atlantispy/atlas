"""Item 19: same-tree comparison of two admission reports (time_admission_initpar.py). Stdlib only.

compare CANDIDATE.json REFERENCE.json [--report OUT.json]
    FAIL CLOSED (exit 1 unless every check is True; a missing or None field fails):
    - both reports exist; the reference passed its own checks; the candidate passed its own checks;
    - same native_root and import_roots, metrics_only False in both, same 'loaded' module digests;
    - workflow_id equal; preparation_ids equal (canonical JSON, non-empty); every identity key
      (union of both) present and equal.
    Store bytes are compared separately (store_rekey.py compare against run A's pinned store).
self-test REFERENCE.json
    The reference against itself must pass; ten planted single-field mutants of it must each fail.
"""
import copy
import json
import sys
from pathlib import Path


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def compare(candidate, reference):
    checks = {}
    checks['reference_passed'] = reference.get('passed') is True
    checks['candidate_passed'] = candidate.get('passed') is True
    for key in ('native_root', 'import_roots', 'loaded'):
        checks[f'same:{key}'] = (candidate.get(key) is not None and reference.get(key) is not None
                                 and _canonical(candidate.get(key)) == _canonical(reference.get(key)))
    checks['metrics_only_false'] = candidate.get('metrics_only') is False and reference.get('metrics_only') is False
    checks['workflow_id'] = candidate.get('workflow_id') is not None and candidate.get('workflow_id') == reference.get('workflow_id')
    prep_c, prep_r = candidate.get('preparation_ids'), reference.get('preparation_ids')
    checks['preparation_ids'] = bool(prep_c) and bool(prep_r) and _canonical(prep_c) == _canonical(prep_r)
    ident_c, ident_r = candidate.get('identity') or {}, reference.get('identity') or {}
    checks['identity_nonempty'] = bool(ident_c) and bool(ident_r)
    for key in sorted(set(ident_c) | set(ident_r)):
        checks[f'identity:{key}'] = ident_c.get(key) is not None and ident_c.get(key) == ident_r.get(key)
    failed = sorted(name for name, value in checks.items() if value is not True)
    return dict(checks=checks, failed=failed, passed=not failed)


def self_test(reference):
    results = {'identity': compare(reference, reference)['passed']}
    mutants = {
        'workflow_id': lambda r: r.update(workflow_id='0'*64),
        'missing_workflow_id': lambda r: r.pop('workflow_id'),
        'preparation_id': lambda r: r['preparation_ids'].update({next(iter(r['preparation_ids'])): '0'*64}),
        'extra_preparation_id': lambda r: r['preparation_ids'].update(extra='x'),
        'bounds_id': lambda r: r['identity'].update({'bounds.bounds_id': '0'*64}),
        'missing_identity_key': lambda r: r['identity'].pop(next(iter(r['identity']))),
        'extra_identity_key': lambda r: r['identity'].update(extra='x'),
        'not_passed': lambda r: r.update(passed=False),
        'other_native_root': lambda r: r.update(native_root=str(r.get('native_root'))+'x'),
        'metrics_only': lambda r: r.update(metrics_only=True),
    }
    for name, mutate in mutants.items():
        mutant = copy.deepcopy(reference)
        mutate(mutant)
        results[name] = compare(mutant, reference)['passed']
    ok = results['identity'] is True and all(results[name] is False for name in mutants)
    return dict(results=results, ok=ok)


def main():
    argv = sys.argv[1:]
    if argv[:1] == ['compare'] and len(argv) in (3, 5):
        paths = [Path(argv[1]), Path(argv[2])]
        if not all(path.is_file() for path in paths):
            print(json.dumps(dict(passed=False, failed=['report_missing'])))
            sys.exit(1)
        candidate, reference = (json.loads(path.read_text(encoding='utf8')) for path in paths)
        result = compare(candidate, reference)
        if len(argv) == 5 and argv[3] == '--report':
            Path(argv[4]).write_text(json.dumps(result, indent=1), encoding='utf8')
        print(json.dumps(dict(passed=result['passed'], failed=result['failed'])))
        sys.exit(0 if result['passed'] else 1)
    if argv[:1] == ['self-test'] and len(argv) == 2:
        result = self_test(json.loads(Path(argv[1]).read_text(encoding='utf8')))
        print(json.dumps(result))
        sys.exit(0 if result['ok'] else 1)
    raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
