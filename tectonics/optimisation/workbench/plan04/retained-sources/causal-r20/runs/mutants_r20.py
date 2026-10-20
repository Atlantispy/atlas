"""Mutation check of the r20 Causal group.

The unmutated baseline must run exactly the adapter's causal case set, every case ok, no skips or errors; only then
are mutants run. Each mutant is declared one of:
  behaviour  - a wrong verdict, proof or FAIL/VOID decision; must be killed by a FAIL (an assertion), never ERROR-only;
  provenance - a lost retained outcome/provenance field with the same verdict; reported separately;
  diagnostic - only a refusal note's wording changes; reported separately, never counted as a semantic kill.
argv: causal-r20 folder, empty scratch folder [--check-only: assert every anchor occurs once; run nothing].
"""
from hashlib import sha256
from pathlib import Path
import json
import re
import subprocess
import sys

SRC = Path(sys.argv[1])          # causal-r20 folder
OUT = Path(sys.argv[2])          # empty scratch folder
CHECK_ONLY = sys.argv[3:] == ['--check-only']
tool = (SRC/'compare_arms_r20.py').read_text(encoding='utf-8')
test = (SRC/'test_retained_r20.py').read_text(encoding='utf-8')
real_sha = sha256((SRC/'compare_arms_r20.py').read_bytes()).hexdigest()
EXPECTED = sorted(set(re.findall(r'^    def (test_causal_\w+)\(', test, re.M)))

B, P, D = 'behaviour', 'provenance', 'diagnostic'
MUTANTS = {
    # retained from r19 (anchors unchanged in r20)
    'events never explain': (B, "    if (row.get('classification') != 'VOID-SUSPECT'", "    if True or (row.get('classification') != 'VOID-SUSPECT'"),
    'unproved stop excusable': (B, "row.get('class') == 'missing' or\n            row.get('unproved_stop_fail')):", "row.get('class') == 'missing'):"),
    'requested explains': (B, "EXPLAINING_OUTCOMES = frozenset(('acknowledged', 'independently_observed'))", "EXPLAINING_OUTCOMES = EVENT_OUTCOMES"),
    'no producer pin': (B, "    prove(producer['entry_sha256'] == pins['evidence_producers'][kind],", "    prove(True or producer['entry_sha256'] == pins['evidence_producers'][kind],"),
    'no nonce check': (B, "            prove(guard == ({'nonce': nonce}", "            prove(True or guard == ({'nonce': nonce}"),
    'no process check': (B, "            prove(parent is not None and process == parent,", "            prove(True or parent is not None and process == parent,"),
    'no sealed refs': (B, "prove(observed['record']['payload']['sealed_arm_refs'] == proofs[arm][stage]['pins'],", "prove(True or observed['record']['payload']['sealed_arm_refs'] == proofs[arm][stage]['pins'],"),
    'observer event unchecked': (B, "                if event['event_type'] in EXPLAINING_EVENTS and event['request_outcome'] in EXPLAINING_OUTCOMES:\n                    interrupted", "                if True:\n                    interrupted"),
    'observer process unchecked': (B, "    prove(event['binding']['step'] == 'observer' and event['binding']['interval'] == binding['interval'] and\n          event['process'] == record['process'],", "    prove(True,"),
    'environment over suspect': (B, "    void_status = ('VOID-SUSPECT' if 'VOID-SUSPECT' in void_kinds or not void_kinds else\n                   'VOID-ENVIRONMENT' if 'VOID-ENVIRONMENT' in void_kinds else 'VOID-OBSERVER')", "    void_status = ('VOID-ENVIRONMENT' if 'VOID-ENVIRONMENT' in void_kinds else 'VOID-SUSPECT' if 'VOID-SUSPECT' in void_kinds or not void_kinds else 'VOID-OBSERVER')"),
    'repeat passes': (B, "            review.append('%s arm is diagnostic repeat", "            (lambda *a: None)('%s arm is diagnostic repeat"),
    'second repeat admitted': (B, "            prove(found['repeat'] is None,", "            prove(True,"),
    'ordinal unchecked': (B, "    prove(payload['repeat_ordinal'] == 1 and", "    prove(True or payload['repeat_ordinal'] == 1 and"),
    'same attempt allowed': (B, "    prove(distinct, where+' repeat must", "    prove(True, where+' repeat must"),
    'profile keys unchecked': (B, "    prove(not changed, where+' repeat changes", "    prove(True, where+' repeat changes"),
    'approvers subset': (B, "set(principals) == required,", "set(principals) <= required,"),
    'rejection counts': (B, "        prove(a['decision'] == 'approve' and", "        prove(True or a['decision'] == 'approve' and"),
    'owner optional': (B, "len(set(approvers)) == len(approvers) >= 3 and REPEAT_REQUIRED_APPROVER in approvers,", "len(set(approvers)) == len(approvers) >= 3,"),
    'retained bytes unchecked': (B, "    prove(file_sha(path) == row['sha256'], where+' retained file bytes", "    prove(True, where+' retained file bytes"),
    'binding unchecked': (B, "    prove(binding['arm'] == arm['name'] and same and", "    prove(True or binding['arm'] == arm['name'] and same and"),
    'pre-start traces ignored': (B, "            prove(parent is None and guard is None and not started,", "            prove(parent is None and guard is None,"),
    'event step ignored': (B, "        if binding['stage'] != stage or binding['step'] != step:", "        if binding['stage'] != stage:"),
    'host restart explains': (B, "EXPLAINING_EVENTS = frozenset(('operator_cancel',))", "EXPLAINING_EVENTS = frozenset(('operator_cancel', 'host_restart'))"),
    # equivalent verdict under the r19 ordering: an automatic action then gets the host-binding note instead
    'automatic not refused': (D, "    if payload['request_outcome'] not in EXPLAINING_OUTCOMES or payload['event_type'] in AUTOMATIC_EVENTS:\n", "    if payload['request_outcome'] not in EXPLAINING_OUTCOMES:\n"),
    'first trigger ignored': (B, "    if reason != 'user_cancel':\n", "    if False:\n"),
    'cleanup ignored': (B, "    if not (guard.get('status') in GUARD_EXITED and guard.get('workload_exit_confirmed') is True and\n", "    if False and (guard.get('status') in GUARD_EXITED and guard.get('workload_exit_confirmed') is True and\n"),
    'observer path unchecked': (B, "    prove(entry is not None and file_sha(entry) == observer_pin,\n", "    prove(True,\n"),
    'termination unbound': (B, "    prove(set(retained) == OBSERVER_TERMINATION_KEYS and", "    prove(True or set(retained) == OBSERVER_TERMINATION_KEYS and"),
    'observer void breaks': (B, "                dumps[arm].pop(interval, None)\n            continue\n", "                dumps[arm].pop(interval, None)\n            break\n"),
    'observer void pops proofs': (B, "                dumps[arm].pop(interval, None)\n            continue\n", "                dumps[arm].pop(interval, None)\n                proofs[arm].pop(stage)\n            continue\n"),
    'chain only without void': (B, "        if set(proofs[arm]) == {name for name, _ in STAGES}:\n", "        if not void and set(proofs[arm]) == {name for name, _ in STAGES}:\n"),
    # r20: the pre-start claim keeps its explicit no-workload outcome (same VOID-SUSPECT verdict)
    'pre-start outcome lost': (P, "    if event['process'] == {'pre_start': True}:\n        return PRESTART_NOTE\n", "    if False:\n        return PRESTART_NOTE\n"),
    # r20: unresolved-peer FAIL precedence
    'claimant gate needs peer': (B, "    if 'after' in gates and gates['after']['passed'] is not True:\n", "    if len(gates) == 2 and gates['after']['passed'] is not True:\n"),
    'claimed gate ignored': (B, "        proved = proofs[arm].get('interval') or claimed[arm].get('interval')\n", "        proved = proofs[arm].get('interval')\n"),
    'peer branch breaks': (B, "                    live.discard(arm)\n            continue\n", "                    live.discard(arm)\n            break\n"),
    'unreached arm counted': (B, "        effective = {arm: classes[arm] if arm in live else 'unreached' for arm in arms}\n", "        effective = dict(classes)\n"),
}
for label, (category, old, new) in MUTANTS.items():
    assert category in (B, P, D), label
    assert tool.count(old) == 1, label
    assert tool.replace(old, new) != tool, label
assert len(EXPECTED) == 18, EXPECTED
if CHECK_ONLY:
    print(json.dumps({'tool_sha256': real_sha, 'mutants': len(MUTANTS), 'expected_causal': len(EXPECTED),
                      'anchors': 'each once'}))
    sys.exit(0)

TEST_LINE = re.compile(r'^(test_\w+) \(.*\) \.\.\. (ok|FAIL|ERROR|skipped.*)$')
HEADER = re.compile(r'^(FAIL|ERROR): (test_\w+) ')


def run(folder, source):
    folder.mkdir()
    (folder/'compare_arms_r20.py').write_text(source, encoding='utf-8', newline='\n')
    digest = sha256((folder/'compare_arms_r20.py').read_bytes()).hexdigest()
    t = test.replace(real_sha, digest).replace("WORK = HERE.parent", "WORK = Path(%r)" % str(SRC.parent))
    (folder/'test_retained_r20.py').write_text(t, encoding='utf-8', newline='\n')
    done = subprocess.run([sys.executable, '-B', '-s', '-P', str(folder/'test_retained_r20.py'), '--group', 'causal'],
                          capture_output=True, text=True, timeout=300)
    (folder/'stderr.txt').write_text(done.stderr, encoding='utf-8', newline='\n')
    outcomes = {}
    for line in done.stderr.splitlines():
        match = TEST_LINE.match(line)
        if match:
            outcomes[match.group(1)] = 'skipped' if match.group(2).startswith('skipped') else match.group(2)
        # unittest's failure headers also name subTest failures, which the progress line may not
        match = HEADER.match(line)
        if match and outcomes.get(match.group(2)) != 'FAIL':
            outcomes[match.group(2)] = match.group(1)
    failed = sorted(k for k, v in outcomes.items() if v == 'FAIL')
    errored = sorted(k for k, v in outcomes.items() if v == 'ERROR')
    kind = ('ASSERTION' if failed else 'ERROR-ONLY' if errored else 'SURVIVED' if done.returncode == 0 else
            'NONZERO-UNATTRIBUTED')
    return {'exit': done.returncode, 'kind': kind, 'failed': failed, 'errored': errored, 'outcomes': outcomes,
            'stderr': str(folder/'stderr.txt'), 'stderr_sha256': sha256(done.stderr.encode('utf-8')).hexdigest(),
            'stderr_tail': done.stderr.splitlines()[-12:]}


baseline = run(OUT/'baseline', tool)
baseline_clean = (baseline['exit'] == 0 and sorted(baseline['outcomes']) == EXPECTED and
                  all(v == 'ok' for v in baseline['outcomes'].values()))
print('baseline', baseline['exit'], len(baseline['outcomes']), 'clean' if baseline_clean else 'NOT CLEAN', flush=True)
results = {}
if baseline_clean:
    for label, (category, old, new) in MUTANTS.items():
        row = run(OUT/('m%02d' % len(results)), tool.replace(old, new))
        row['category'] = category
        results[label] = row
        print(label, category, row['kind'], row['failed'] or row['errored'], flush=True)
behaviour = {k: v for k, v in results.items() if v['category'] == B}
summary = {
    'tool_sha256': real_sha, 'expected_causal': EXPECTED, 'baseline_clean': baseline_clean, 'baseline': baseline,
    'behaviour': {'mutants': len(behaviour), 'killed_by_assertion': sorted(k for k, v in behaviour.items()
                                                                           if v['kind'] == 'ASSERTION'),
                  'survivors': sorted(k for k, v in behaviour.items() if v['kind'] == 'SURVIVED'),
                  'error_or_unattributed_only': sorted(k for k, v in behaviour.items()
                                                       if v['kind'] in ('ERROR-ONLY', 'NONZERO-UNATTRIBUTED'))},
    'provenance_controls': {k: v['kind'] for k, v in results.items() if v['category'] == P},
    'diagnostic_controls_not_semantic': {k: v['kind'] for k, v in results.items() if v['category'] == D},
    'results': results}
print(json.dumps({k: summary[k] for k in ('baseline_clean', 'behaviour', 'provenance_controls',
                                          'diagnostic_controls_not_semantic')}))
(OUT/'mutants-result.json').write_text(json.dumps(summary, indent=1), encoding='utf-8')
ok = (baseline_clean and len(results) == len(MUTANTS) and
      len(summary['behaviour']['killed_by_assertion']) == len(behaviour))
sys.exit(0 if ok else 1)
