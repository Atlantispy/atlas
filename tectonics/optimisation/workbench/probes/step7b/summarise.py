"""Bind the completed Step 7B observations to their unchanged saved fixtures."""
from hashlib import sha256
import json
from pathlib import Path
from statistics import median

P = Path(__file__).resolve().parent
R = P.parents[1]
C = R/'compact-geometry-r1'

def read(path):
    return json.loads(path.read_text(encoding='utf8'))

def digest(path):
    return sha256(path.read_bytes()).hexdigest()

baseline = read(P/'baseline.json')
fixtures = {'small':R/'probes/step7/matched-r2/compact',
            'large':R/'probes/step7-heat-ledger-large-r1'}
for size, files in baseline['fixtures'].items():
    for name, expected in files.items():
        path = fixtures[size]/name
        assert path.stat().st_size == expected['bytes']
        assert digest(path) == expected['sha256']
for name, expected in baseline['baseline_copies'].items():
    assert digest(P/'baseline-src'/name) == expected

before = baseline['current_sources_before']
after = {name:digest(R/name) for name in before}
all_changes = {name:dict(before=before[name],after=after[name]) for name in before if before[name] != after[name]}
changed = {name:row for name,row in all_changes.items()
           if Path(name).name in {'record_views.py','segment_store.py','heat_ledger_tables.py'}}
assert {Path(name).name for name in changed} == {'record_views.py','segment_store.py','heat_ledger_tables.py'}
concurrent = {name:row for name,row in all_changes.items() if name not in changed}
dependencies = read(P/'dependency-check.json')
loaded = {Path(row['path']) for row in dependencies['loaded_local_modules'].values()}
assert all(R/name not in loaded for name in concurrent), 'changed shared benchmark dependency'

metrics = ('seconds','tracked_peak_bytes','sampled_peak_rss_bytes',
           'sampled_peak_private_bytes','lifetime_peak_wset_bytes','retained_at_open',
           'physical_store_bytes')
results = {}
probe_hash = digest(P/'compare_reopen.py')
for size in fixtures:
    samples = {}
    for mode in ('baseline','candidate'):
        files = sorted(P.glob(mode+'-'+size+'-*.json'))
        assert len(files) == (3 if size == 'small' else 1)
        samples[mode] = [read(path) for path in files]
        for row in samples[mode]:
            assert row['probe_sha256'] == probe_hash
            assert row['reserved_after_close'] == 0
            for name, source_hash in row['source_sha256'].items():
                assert digest(Path(name)) == source_hash
    first = samples['baseline'][0]
    for row in samples['baseline']+samples['candidate']:
        for key in ('result_id','metadata_sha256','metadata_bytes','array_hashes','physical_store_bytes','runtime','scope','sample_ms'):
            assert row[key] == first[key], (size,key)
    comparison = {}
    for key in metrics:
        old,new = (median([row[key] for row in samples[mode]]) for mode in ('baseline','candidate'))
        comparison[key] = dict(before=old,after=new,difference=new-old,
                               reduction_percent=100*(1-new/old),before_over_after=old/new)
    results[size] = dict(samples=samples,comparison=comparison,
        aggregation='median of three fresh processes per version' if size=='small' else 'one fresh process per version',
        fixture_hashes_unchanged=baseline['fixtures'][size])
report = dict(status='PASS',date='2026-10-15',baseline='Preserved final Step 7 compact reader',
    candidate='Step 7B compact reader',source_changes=changed,
    unchanged_source_sha256={k:v for k,v in after.items() if k not in all_changes},
    concurrent_changes_outside_read_path=concurrent,
    dependency_check=dict(path='dependency-check.json',sha256=digest(P/'dependency-check.json')),
    probe_sha256=probe_hash,results=results,
    configuration=dict(work_budget_bytes=1<<30,shared_retained_cap_bytes=256<<20,
                       OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',
                       max_array_bytes=512<<20,native_chunk_bytes=65536),
    limitations=[
        'Synthetic saved fixtures; the large fixture deliberately uses extreme sharing.',
        'Fresh process is not an evicted OS disk cache; OS cache and unrelated system load uncontrolled.',
        'One large observation per version; no confidence interval or end-to-end workflow speedup.',
        'Sampled process working set/private bytes differ from tracked allocations and minimum required RAM.',
        'No write/packing rerun or historical-r3 performance comparison in Step 7B.',
        'The earlier 206.60 s large observation remains historical; this matched baseline is 189.08 s.',
        'Step 7 genuine owner result retained at its original source-bound scope, not rerun here.'
    ])
(P/'measurement.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf8')

receipt_path = R/'test-results/step7-heat-ledger.json'
receipt = read(receipt_path)
assert 'step7b' not in receipt, 'do not overwrite a completed checkpoint'
receipt['current_sources_scope'] = 'Original Step 7 completion snapshot; latest Step 7B sources are bound in step7b.current_sources.'
test_paths = [C/name for name in ('test_step7b_segments.py','test_step7b_mesh_stream.py','test_step7b_record_reuse.py')]
test_paths += [R/'test-results'/name for name in ('step7b-segment-tests.json','step7b-record-tests.txt','step7b-reuse-tests.txt','step7b-integration-tests.txt')]
receipt['step7b'] = dict(status='COMPLETE',date='2026-10-15',
    scope='Bounded compact reopening; no production migration, frozen-source repin, IV2 or numerical-kernel change.',
    changes=[
        'Sealed admission scans every authenticated native leaf once, including empty columns.',
        'Typed NumPy views share existing paid page borrows within a read batch.',
        'A per-traversal optional 1 MiB LRU reuses exact small DAG bytes, at most 64 KiB per entry and 1024 entries, with separately paid bounded construction.',
        'Canonical hashes still consume every ordered logical byte; structural and reachability checks remain complete.',
        'Generic and shared-mesh streams recheck cancellation/freshness around each output block.'
    ],
    current_sources=[dict(path=str(C/name),sha256=digest(C/name)) for name in
                     ('record_views.py','segment_store.py','heat_ledger_tables.py','private_heat_snapshot_store_r4.py')],
    measurement=dict(path='probes/step7b/measurement.json',sha256=digest(P/'measurement.json')),
    tests=dict(unique_focused_passes=65,final_combined_suite=dict(tests=46,seconds=28.740,status='PASS'),
               record_reuse=dict(tests=8,seconds=37.897,status='PASS'),
               segment_and_mesh=dict(tests=11,status='PASS'),
               reuse_scope='The final 46-test suite covers the last structural traversal optimisation; the eight reuse tests cover unchanged memo/page/stream behaviour and the eleven segment/mesh tests cover their unchanged implementations.',
               lint=dict(rules=['F821','F841','B905'],findings=[],mode='native Ruff check-only'),
               evidence=[dict(path=str(path.relative_to(R)),sha256=digest(path)) for path in test_paths]),
    diagnostics=[
        'Initial measurement invocation failed before opening a store because cancellation requires is_set(), not a bare callback; corrected once before all matched observations.',
        'The segment worker recorded unavailable python -m ruff and successful installed native Ruff fallback in step7b-segment-tests.json.',
        'The initial broad source assertion detected concurrent WP10 storage_codec_runtime changes. A separate dependency-only reopen confirmed that module and its integration patch were absent from this read path; its observation is excluded from matched timings. No concurrent source was reverted or repinned.',
        'No runtime test or measured identity failure.'
    ],
    continuation='Step 8: materialisation/runner/reader and authenticated historical admission; then Step 9 frozen composition. WP14 combined live RAM and WP0b actual-data measurements remain required.')
receipt_path.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n',encoding='utf8')
print(json.dumps(dict(status='PASS',fixture_hashes_unchanged=True,changed_sources=list(changed),
                     comparison={k:v['comparison'] for k,v in results.items()}),indent=2))

