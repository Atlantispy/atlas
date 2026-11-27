"""Read-only validation of the bounded paired candidate measurements."""
import argparse
import json
from pathlib import Path
import statistics
import numpy as np

parser=argparse.ArgumentParser()
parser.add_argument('root',type=Path)
parser.add_argument('prefix')
parser.add_argument('baseline')
parser.add_argument('candidate')
args=parser.parse_args()
trials={mode:[] for mode in (args.baseline,args.candidate)}
differences=[]
for rep in range(3):
    paths={mode:args.root/f'{args.prefix}-{rep}-{mode}' for mode in trials}
    rows={mode:json.loads((path/'result.json').read_text()) for mode,path in paths.items()}
    for mode,row in rows.items():
        assert row['completed'] and row['source_unchanged'] and row['jit_signatures_unchanged']
        assert row['budget_after_close']['reserved_bytes']==0
        trials[mode].append(row)
    a,b=(rows[mode] for mode in trials)
    assert a['input_hashes']==b['input_hashes'] and a['policies']==b['policies']
    pair=dict(physical_bit_identical=True,diagnostics_within_existing_tolerance=True,max_abs={})
    with np.load(paths[args.baseline]/'arrays.npz',allow_pickle=False) as x, np.load(paths[args.candidate]/'arrays.npz',allow_pickle=False) as y:
        assert set(x.files)==set(y.files)
        for key in x.files:
            assert x[key].shape==y[key].shape
            assert np.isfinite(x[key]).all() and np.isfinite(y[key]).all()
            exact=x[key].tobytes()==y[key].tobytes()
            if key.startswith('step'):
                assert exact, key
            else:
                # Existing velocity/transport regression criterion, not a
                # substitute for each source's strict publication certificates.
                np.testing.assert_allclose(y[key],x[key],rtol=1e-7,atol=1e-9,err_msg=key)
            maximum=float(np.max(x[key]!=y[key])) if x[key].dtype==bool else float(np.max(abs(x[key]-y[key])))
            if maximum: pair['max_abs'][key]=maximum
    differences.append(pair)
timing={}
for key in ('physical_s','snapshot_s','total_s'):
    raw={mode:[r['timing'][key] for r in rows] for mode,rows in trials.items()}
    a,b=(statistics.median(raw[mode]) for mode in trials)
    timing[key]=dict(raw_s=raw,baseline_median_s=a,candidate_median_s=b,saved_s=a-b,saved_percent=100*(a-b)/a)
for mode,rows in trials.items():
    assert all(row['source']==rows[0]['source'] for row in rows)
    # Result identities differ across sources, but must repeat within each one.
    assert all(row['timing']['steps']==rows[0]['timing']['steps'] for row in rows)
print(json.dumps(dict(comparison=args.prefix,baseline=args.baseline,candidate=args.candidate,timing=timing,differences=differences),indent=2))
