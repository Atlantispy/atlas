"""Read-only additive D6 analysis of completed parity outputs; no runtime imports.

python -B c6_diagnostics.py PARITY_DIR --focused check-full.json --out NEW.json
Requires retained stage checker PASS, exact focused proof source bindings, and completed deep coverage.
Does not claim full-payload persistence or validate a new consumer contract.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import traceback

p = argparse.ArgumentParser()
p.add_argument('directory')
p.add_argument('--focused', required=True)
p.add_argument('--out', required=True)
a = p.parse_args()
root = Path(a.directory)
NATIVE = 'exact-native-retained'
report = dict(scope='D6 done-row diagnostics; exception-attached full payloads are not emitted',
              cases=[], errors=[], skipped_capped_histories=[])

def read(path):
    raw = path.read_bytes()
    report.setdefault('inputs', {})[str(path.resolve())] = sha256(raw).hexdigest()
    return json.loads(raw)

def shard(path):
    rows, tail = [], None
    raw = path.read_bytes()
    report.setdefault('inputs', {})[str(path.resolve())] = sha256(raw).hexdigest()
    for text in raw.decode('utf8').splitlines():
        item = json.loads(text)
        if tail is not None:
            raise ValueError(str(path)+' has data after done')
        if item.get('done'):
            tail = item
        elif 'job_counts' not in item:
            rows.append(item)
    if tail is None or tail.get('queries') != len(rows):
        raise ValueError(str(path)+' incomplete done coverage')
    if path.with_suffix('.exit').read_text().strip() != '0':
        raise ValueError(str(path)+' nonzero exit')
    return rows, tail

def run():
    proof = read(Path(a.focused))
    assert proof['verdict'] == 'PASS'
    assert proof['focused']['D6 ordered cap causal attribution']['ok']
    assert proof['focused']['real Arena near-full Policy A']['ok']
    hashes = proof['focused']['source_hashes']
    expected = {}
    for path, value in hashes.items():
        expected.setdefault(Path(path).name, set()).add(value)
    bound = set()
    def bind(runtime):
        if runtime in bound:
            return
        assert runtime.startswith('test:')
        folder = Path(runtime[5:])/'atlas_tectonics'
        for name in ('integration_wall_measures.py', 'integration_volume.py',
                     'integration_volume_overlap.py', 'resources.py', 'integration_volume_bounds.py',
                     'exact_arithmetic.py', 'integration_exact_twin.py', 'integration_wall_measures_gmp.py'):
            path = folder/name
            if not path.exists() and name in ('integration_exact_twin.py', 'integration_wall_measures_gmp.py'):
                continue
            actual = sha256(path.read_bytes()).hexdigest()
            assert actual in expected[name], 'focused proof source mismatch '+str(path)
        bound.add(runtime)
    for stage in ('iv1-surfaces', 'iv2-sample', 'iv2-extra', 'iv2-deep'):
        if stage == 'iv2-extra':
            extra = root/'iv2-sample-extra-list.jsonl'
            if extra.is_file() and extra.stat().st_size == 0:
                continue
        check = read(root/('check-'+stage+'.json'))
        assert check['status'] == 'PASS', stage+' parity gate not passed'
        for shard_id in check['shards']:
            br, bt = shard(root/f'{stage}-base-s{shard_id}.jsonl')
            cr, ct = shard(root/f'{stage}-gpy-s{shard_id}.jsonl')
            bind(bt['runtime'])
            bind(ct['runtime'])
            label = f'{stage}/s{shard_id}'
            assert len(br) == len(cr)
            if any(row['status'] == 'error' for row in br+cr):
                raise ValueError(label+' error row requires actual error/payload investigation')
            if any(row['status'] == 'capped' for row in br+cr):
                # Time caps stop at arbitrary positions: terminal ledgers are not corresponding histories.
                report['skipped_capped_histories'].append(dict(shard=label,
                    reason='time-capped histories; retained checker requires deep/extra completion coverage',
                    baseline_category_count=len(bt['budget']['categories']),
                    candidate_category_count=len(ct['budget']['categories'])))
                continue
            key = lambda row: (row['kind'], row['support_index'], row['cell'], row.get('other'),
                               row.get('constraint_name'), row.get('axis'), row.get('end'))
            assert [key(row) for row in br] == [key(row) for row in cr], 'ordinary query order changed'
            assert all(x['status'] == y['status'] and x.get('measure_sha_nodigest') == y.get('measure_sha_nodigest')
                       and x.get('measure_sha_nodigest') is not None for x,y in zip(br, cr))
            b, c = bt['budget'], ct['budget']
            bc, cc = b['categories'], c['categories']
            bp, cp = b['category_peaks'], c['category_peaks']
            ordinary = lambda mapping: {k:v for k,v in mapping.items() if k != NATIVE}
            assert c.get('refusals') == b.get('refusals') == 0, label+' refusal needs event-prefix attribution'
            assert c['max_bytes'] == b['max_bytes']
            assert c.get('predicate_work') == b.get('predicate_work'), label+' predicate diagnostics differ'
            row = dict(shard=label, baseline_category_count=len(bc), candidate_category_count=len(cc),
                       baseline_budget=b, candidate_budget=c)
            if ordinary(bc) != ordinary(cc) or ordinary(bp) != ordinary(cp):
                # Saturation alone is not a failure. This is a concrete unexplained terminal-map delta:
                # neither this writer nor comparator emits requested-category order/lifetime traces.
                row.update(status='REVIEW', reason='ordinary diagnostic delta has no per-run ordered '
                           'reservation trace; focused cap proof cannot reconstruct this aggregate peak')
                report['errors'].append(label+': unexplained ordinary category/current/peak delta')
            else:
                assert c['reserved_bytes'] == b['reserved_bytes']+cc.get(NATIVE, 0)
                assert cc.get(NATIVE, 0) == 0, label+' leaked native current'
                assert b['peak_reserved_bytes'] <= c['peak_reserved_bytes'] <= b['peak_reserved_bytes']+cp.get(NATIVE, 0)
                row.update(status='CONSISTENT', cause_evidence='exact source-bound ordered trace/cap proof reused',
                           peak_limit='aggregate inequality is consistency only; not sum-of-component peak equality')
            report['cases'].append(row)
    assert report['cases'], 'no completed corresponding histories assessed'
    report.update(verdict='REVIEW' if report['errors'] else 'PASS',
                  bound_runtimes=sorted(bound),
                  limits=['No full-payload writer or absence of one established.',
                          'No global category inventory claim or named-consumer waiver.',
                          'Capped shard terminal maps are not used as corresponding-history evidence.'])

try:
    run()
except Exception as exc:
    report.update(verdict='FAIL', error=repr(exc), traceback=traceback.format_exc())
Path(a.out).write_text(json.dumps(report, indent=1)+'\n')
print(json.dumps(dict(verdict=report['verdict'], completed_shards=len(report['cases']),
                     skipped_capped_shards=len(report['skipped_capped_histories']), errors=report['errors'])))
sys.exit(0 if report['verdict'] == 'PASS' else 1)
