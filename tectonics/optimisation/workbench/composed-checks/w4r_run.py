"""W4 check 3 (reruns on composed bytes + overhead re-measure): one fresh process per check, in order.

    python -B w4r_run.py                     run the four checks once, write w4r-run.json + w4r-logs/ (all NEW)
    python -B w4r_run.py --receipt N.json    build R/test-results/w4-reruns.json (NEW) from w4r-run.json,
                                             the check outputs and the narrative fields in N.json

Each check refuses to overwrite its output, waits (bounded) for RAM, and verifies
the frozen composed-r1 tree before and after. Only one check process runs at a time.
Other W4 checkers share R/composed-checks, so every file here is prefixed w4r.
"""
import sys
sys.dont_write_bytecode = True

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import w4r_common as W


CHECKS = (   # id, script, output, extra environment, why
    ('endpoint_checkpoints', 'w4r_endpoint_checkpoints.py', 'w4r-endpoint-checkpoints.json', {'PYTHONHASHSEED': '0'},
     'W2-K endpoint-checkpoint suite (24) on a byte-identical copy of the composed natives with composed import roots'),
    ('guard', 'w4r_guard.py', 'w4r-guard.json', {},
     'CR real-job guard suite (15) and W1-G successor drills on the composed guard-set bytes'),
    ('fixtures', 'w4r_fixtures.py', 'w4r-fixtures.json', {},
     'compact spatial fixture (alias test + two-process) and partition fresh-process fixture on composed bytes'),
    ('probe_overhead', 'w4r_probe_overhead.py', 'w4r-checkpoint-overhead.json', {},
     'per-query strict check cost on the composed inventory, with a same-session candidate-w2k control arm'),
)
NEW_SOURCES = ('w4r_common.py', 'w4r_endpoint_checkpoints.py', 'w4r_guard.py', 'w4r_fixtures.py',
               'w4r_probe_overhead.py', 'w4r_run.py')
RUN_RECORD = W.HERE/'w4r-run.json'
LOGS = W.HERE/'w4r-logs'
RECEIPT = W.R/'test-results'/'w4-reruns.json'
MARKERS = ('W4_ENDPOINT_CHECKPOINTS ', 'W4_GUARD ', 'W4_FIXTURES ', 'W4_PROBE ')


def evidence_snapshot():
    """Hashes of existing evidence and source files that these checks must leave untouched."""
    out = {}
    for folder, pattern in ((W.R/'test-results', '*.json'), (W.R/'probes', '*'), (W.E, '*.json'), (W.E, '*.py'),
                            (W.R, '*.py'), (W.R, '*.json'), (W.C, '*.py')):
        for path in sorted(folder.glob(pattern)):
            if path.is_file():
                out['/'.join(path.relative_to(W.R).parts)] = W.file_sha(path)
    return out


def ruff(files):
    executable = shutil.which('ruff')
    if executable is None:
        return dict(available=False)
    command = [executable, 'check', '--no-cache', '--select', 'F821,F841,B905', '--output-format', 'json', *files]
    completed = subprocess.run(command, capture_output=True, text=True, cwd=W.HERE, stdin=subprocess.DEVNULL)
    version = subprocess.run([executable, '--version'], capture_output=True, text=True).stdout.strip()
    findings = json.loads(completed.stdout or '[]')
    return dict(available=True, version=version, command='ruff check --no-cache --select F821,F841,B905 '
                '--output-format json '+' '.join(files), returncode=completed.returncode,
                findings=[dict(code=f.get('code'), file=Path(f.get('filename', '')).name,
                               row=f.get('location', {}).get('row'), message=f.get('message')) for f in findings],
                baseline='none: every file is new, so every finding would be introduced')


def w2_resolution(helpers_loaded):
    """Where W2's fixture closures took each helper the composed fixture children loaded, and whether bytes differ."""
    explicit = {'native_transfer': W.R, 'spatial_transfer': W.R, 'geometry_transfer': W.R, 'workflow_transfer': W.R,
                'materialise_endpoint': W.R, 'historical_admission': W.R, 'mesh_tables': W.C, 'compact_store': W.C,
                'spatial_indexed_patch': W.C, 'spatial_workflow_patch': W.C, 'partition_tables': W.C,
                'partition_native_patch': W.C, 'partition_store': W.C, 'partition_workflow_patch': W.C}
    rows = {}
    for name in helpers_loaded:
        composed = next((root/(name+'.py') for root in (W.HELPERS, W.RAM) if (root/(name+'.py')).exists()), None)
        if name in explicit:
            source = explicit[name]/(name+'.py')
        else:   # F.initialise_child order after the composed tree: I/ram, I/helpers, the H root
            source = next((root/(name+'.py') for root in (W.I/'ram', W.I/'helpers', W.H) if (root/(name+'.py')).exists()), None)
        rows[name] = dict(w2_source=None if source is None else '/'.join(source.relative_to(W.T).parts),
                          identical=None if source is None or composed is None else W.file_sha(source) == W.file_sha(composed))
    return dict(modules=rows, differing=sorted(n for n, r in rows.items() if r['identical'] is False),
                unresolved_in_w2=sorted(n for n, r in rows.items() if r['w2_source'] is None))


def run():
    outputs = {check: W.HERE/output for check, _, output, _, _ in CHECKS}
    W.require(not RUN_RECORD.exists() and not LOGS.exists(), 'a W4 run record or log folder already exists')
    W.require(not any(path.exists() for path in outputs.values()), 'a W4 check output already exists')
    started = datetime.now(timezone.utc).isoformat()
    begun = time.perf_counter()
    sources = {name: W.file_sha(W.HERE/name) for name in NEW_SOURCES}
    evidence = evidence_snapshot()
    before = W.verify_composed()
    W.SCRATCH.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir()
    rows = []
    for check, script, output, extra, why in CHECKS:
        gate = W.ram_gate()
        command = [sys.executable, '-B', script, '--output', str(outputs[check])]
        env = dict(os.environ, TMP=str(W.SCRATCH), TEMP=str(W.SCRATCH), **extra)
        launched = time.perf_counter()
        completed = subprocess.run(command, capture_output=True, text=True, timeout=3600, cwd=W.HERE, env=env,
                                   stdin=subprocess.DEVNULL)
        seconds = time.perf_counter()-launched
        with open(LOGS/(check+'.log'), 'x', encoding='utf8', newline='\n') as log:
            log.write('$ '+' '.join(command)+'\n# env: TMP=TEMP='+str(W.SCRATCH)+''.join(' %s=%s' % kv for kv in extra.items())
                      +'\n# returncode '+str(completed.returncode)+', %.3f s\n--- stdout\n' % seconds
                      +completed.stdout+'\n--- stderr\n'+completed.stderr)
        summary = [json.loads(line.split(' ', 1)[1]) for line in completed.stdout.splitlines() if line.startswith(MARKERS)]
        rows.append(dict(id=check, why=why, command='cd R/composed-checks; '+' '.join(
            ['T/.r44-env/Scripts/python.exe', '-B', script, '--output', output]),
            env=dict(TMP='T/_t/w4-reruns', TEMP='T/_t/w4-reruns', **extra), returncode=completed.returncode,
            seconds=seconds, ram_gate=gate, summary=summary[0] if len(summary) == 1 else None,
            output=output, output_sha256=W.file_sha(outputs[check]) if outputs[check].exists() else None,
            log=LOGS.name+'/'+check+'.log', log_sha256=W.file_sha(LOGS/(check+'.log'))))
    after = W.verify_composed()
    evidence_after = evidence_snapshot()
    # Only pre-existing files count: other W4 checkers may add their own receipts meanwhile.
    changed = sorted(k for k in evidence if evidence_after.get(k) != evidence[k])
    added = sorted(set(evidence_after)-set(evidence))
    sources_after = {name: W.file_sha(W.HERE/name) for name in NEW_SOURCES}
    fixtures = json.loads(outputs['fixtures'].read_bytes()) if outputs['fixtures'].exists() else None
    loaded = sorted({name for key in ('spatial_two_process', 'partition_two_process')
                     for run_ in ((fixtures or {}).get('evidence', {}).get(key, {}).get('runs', []))
                     for name in run_.get('helpers_loaded', [])})
    leftovers = sorted(p.name for p in W.SCRATCH.iterdir())
    record = dict(schema='private.w4-reruns-run.v1', started_utc=started, wall_seconds=time.perf_counter()-begun,
        python=sys.version, executable=sys.executable, harness_sources=sources,
        harness_sources_stable=sources == sources_after, checks=rows,
        all_passed=all(r['returncode'] == 0 for r in rows), composed_before=before, composed_after=after,
        composed_unchanged=before['tree_digest'] == after['tree_digest'],
        evidence_files_checked=len(evidence), evidence_changed=changed, evidence_added_by_others=added,
        fixture_helpers_vs_w2=w2_resolution(loaded), scratch_leftovers=leftovers,
        lint=ruff(list(NEW_SOURCES)))
    digest = W.write_exclusive(RUN_RECORD, record)
    print('W4_RUN '+json.dumps(dict(all_passed=record['all_passed'], composed_unchanged=record['composed_unchanged'],
          evidence_changed=changed, checks={r['id']: [r['returncode'], round(r['seconds'], 1)] for r in rows},
          lint=len(record['lint'].get('findings', [])), record=str(RUN_RECORD), sha256=digest)), flush=True)
    return 0 if record['all_passed'] and record['composed_unchanged'] and not changed else 1


def receipt(narrative_path):
    W.require(not RECEIPT.exists(), 'receipt exists; refusing to overwrite '+str(RECEIPT))
    run_ = json.loads(RUN_RECORD.read_bytes())
    narrative = json.loads(Path(narrative_path).read_bytes())
    outputs = {r['id']: json.loads((W.HERE/r['output']).read_bytes()) for r in run_['checks']}
    W.require(all(W.file_sha(W.HERE/r['output']) == r['output_sha256'] for r in run_['checks']), 'check outputs changed')
    W.require(all(W.file_sha(W.HERE/name) == digest for name, digest in run_['harness_sources'].items()),
              'harness sources changed after the run')
    relative = lambda path: 'R/'+'/'.join(Path(path).relative_to(W.R).parts)
    files = [dict(path=relative(W.HERE/name), sha256_before=None, sha256_after=digest)
             for name, digest in run_['harness_sources'].items()]
    files += [dict(path=relative(W.HERE/r['output']), sha256_before=None, sha256_after=r['output_sha256'])
              for r in run_['checks']]
    files += [dict(path=relative(W.HERE/r['log']), sha256_before=None, sha256_after=r['log_sha256']) for r in run_['checks']]
    files.append(dict(path=relative(RUN_RECORD), sha256_before=None, sha256_after=W.file_sha(RUN_RECORD)))
    ep, guard, fx, probe = (outputs[k] for k in ('endpoint_checkpoints', 'guard', 'fixtures', 'probe_overhead'))
    tests = []
    for r in run_['checks']:
        out = outputs[r['id']]
        tests.append(dict(command=r['command'], env=r['env'], why=r['why'],
            tests_run=out.get('tests'), failures=out.get('failures'), errors=out.get('errors'),
            skipped=out.get('skipped'), seconds=round(r['seconds'], 3),
            result=('OK' if r['returncode'] == 0 else 'FAILED (exit %d)' % r['returncode']),
            output=r['output'], output_sha256=r['output_sha256']))
    record = dict(package='w4-reruns', title='Wave 4 check 3: reruns on composed bytes and checkpoint overhead re-measure',
        date=datetime.now(timezone.utc).date().isoformat(),
        status='complete' if run_['all_passed'] and run_['composed_unchanged'] and not run_['evidence_changed'] else 'partial',
        summary=narrative['summary'], files=files,
        digests=dict(manifest_sha256=W.MANIFEST_SHA256, native_source_digest=W.NATIVE_SOURCE_DIGEST,
            composed_tree_digest_before=run_['composed_before']['tree_digest'],
            composed_tree_digest_after=run_['composed_after']['tree_digest'],
            execution_identity_observed_in_fixtures=fx['evidence']['partition_two_process']['execution']['execution_identity'],
            companion_sha256=W.COMPANION_SHA256, successor_guard_sha256=W.SUCCESSOR_GUARD_SHA256,
            run_record_sha256=W.file_sha(RUN_RECORD)),
        tests=tests,
        results=dict(
            endpoint_checkpoints=dict(tests=ep['tests'], identical_to_w2k=ep['comparison_with_w2k']['all_identical'],
                tiny_result=ep['observations'].get('tiny_result'), candidate=ep['observations'].get('candidate'),
                import_counts=ep['import_audit']['counts'], copy_restored=ep['copy_restored_after_mutation_tests'],
                w2k_results_untouched=ep['w2k_results_untouched']),
            guard=dict(tests=guard['tests'], cr_suite=guard['evidence'].get('cr_suite', {}).get('summary'),
                pins=guard['pins'], drills={k: v for k, v in guard['evidence'].items() if k.startswith('drill_')}),
            fixtures={k: {kk: vv for kk, vv in v.items() if kk != 'runs'} for k, v in fx['evidence'].items()},
            fixture_seconds={k: [round(x['seconds'], 1) for x in v.get('runs', [v])] for k, v in fx['evidence'].items()},
            fixture_helpers_vs_w2=run_['fixture_helpers_vs_w2'],
            overhead=dict(decision=probe['decision'], same_session=probe['same_session'], headline=probe['headline'],
                inventory_census={k: v for k, v in probe['inventory_census'].items() if k != 'largest_increase'},
                largest_census_increase=probe['inventory_census']['largest_increase'][:5],
                comparison_with_w2k=probe['comparison'])),
        composed_tree=dict(before=run_['composed_before'], after=run_['composed_after'],
                           unchanged=run_['composed_unchanged']),
        evidence_files_checked=run_['evidence_files_checked'], evidence_changed=run_['evidence_changed'],
        scratch_leftovers=run_['scratch_leftovers'], lint=run_['lint'],
        **{k: narrative[k] for k in ('defects', 'deviations_from_plan', 'open_issues', 'requests_to_other_packages',
                                     'not_run')})
    digest = W.write_exclusive(RECEIPT, record)
    print('W4_RECEIPT '+json.dumps(dict(path=str(RECEIPT), sha256=digest, status=record['status'])), flush=True)
    return 0


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--receipt':
        raise SystemExit(receipt(sys.argv[2]))
    W.require(len(sys.argv) == 1, 'usage: w4r_run.py | w4r_run.py --receipt <narrative.json>')
    raise SystemExit(run())
