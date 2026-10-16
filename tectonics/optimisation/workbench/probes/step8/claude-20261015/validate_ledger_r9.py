"""Validate the difference ledger on real interval-1 data before any rerun exists (read-only on r9).

Usage: python -B validate_ledger_r9.py OUT_DIR

Three cases on r9's own receipt and pre-advance bounds capture, with the geometry
chat's interval-1 replay rows (all-off = r7; item11off = cube stop on as a
mechanics stand-in only, NOT the Step 10 replay of record):
  identity      r9 against r9, replay = r7 rows: PASS, nothing attributed;
  substituted   a synthetic rerun = r9's capture with the replayed cube-stop bounds
                substituted where that replay differs from r7: PASS, every
                substituted bound attributed and traced;
  tampered      the substituted rerun with one bound moved off the replay: FAIL.
Writes only OUT_DIR (synthetic captures, receipts, ledgers, summary.json).
"""
import copy
import gzip
import json
import sys
import time
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
T = R.parents[3]
sys.path.insert(0, str(R))
import ledger_fresh_interval as LG  # noqa: E402

H = T/'fidelity-integration-20261005'/'heat-repair-20261007'
RECEIPT = H/'heat-original-connected-20261013-r9.json'
ARTIFACTS = H/'heat-original-connected-20261013-r9.artifacts'
EVIDENCE = R/'geometry-growth-r1'/'evidence'


def pinned(path):
    return path, sha256(path.read_bytes()).hexdigest()


def synthetic_run(out, name, receipt, bounds):
    folder = out/name
    folder.mkdir()
    raw = json.dumps(bounds, separators=(',', ':')).encode()
    (folder/'preadvance-bounds.json.gz').write_bytes(gzip.compress(raw, compresslevel=1))
    value = copy.deepcopy(receipt)
    value['preadvance_operands']['bounds'] = {'path': 'preadvance-bounds.json.gz', 'raw_bytes': len(raw),
                                              'raw_sha256': sha256(raw).hexdigest()}
    return folder, value


# The Step 10 replay of record (geometry chat, 16 Oct 2026): RC1 + items_11_15_off, cube on.
FINAL_F1 = {
    'ref-iv1-endpoints-s0.jsonl': '994dac938a06b427cbc6093e4a20c4fd335e71c9c2c544a6f9eb24fa45ecacb6',
    'ref-iv1-endpoints-s1.jsonl': '7e7c98db105c78e7816ef8c3bd2b3df5098eaf39c8a5c69d10cca025c092be82',
    'ref-iv1-endpoints-s2.jsonl': '194fecb531b34dcbc424eeb07894a8c0480d2e0acde51481bc3d5e62de195992',
    'ref-iv1-endpoints-s3.jsonl': '3799efa01447037cfb8e003f216d22b0e931f9203abc4ec132a1122d9b9a2ad8',
    'ref-iv1-endpoints-s4.jsonl': 'b5692a1186da8f0694ae934f5423297ddcc11987f24043977aab73ce777fbb33',
    'ref-iv1-endpoints-s5.jsonl': '9049d06ce088a350406d09877d2ac1973e39272ef1ad1a5677b4b59411bef00a'}


def main():
    out = Path(sys.argv[1])
    out.mkdir()
    r9 = json.loads(RECEIPT.read_bytes())
    r7 = LG.read_rows([pinned(EVIDENCE/'abl-iv1-alloff-r1.jsonl')], 'all-off replay')
    if '--final-f1' in sys.argv[2:]:
        cube = LG.read_rows([(EVIDENCE/'final-f1'/name, pin) for name, pin in FINAL_F1.items()], 'Step 10 replay')
    else:
        cube = LG.read_rows([pinned(EVIDENCE/'abl-iv1-item11off-r1.jsonl')], 'item11off replay')
    summary, started = {}, time.perf_counter()
    verdict = {'width_gate': {'passed': True, 'note': 'synthetic'}}
    identity = LG.ledger(r9=r9, r9_artifacts=ARTIFACTS, rerun=r9, rerun_artifacts=ARTIFACTS, replay=r7, r7=r7,
                         rerun_verdict=verdict)
    summary['identity'] = {'verdict': identity['verdict'], 'unattributed': len(identity['unattributed']),
                           'attributed': len(identity['heat_inputs']['bounds']['attributed']),
                           'seconds': round(time.perf_counter()-started, 1)}
    bounds = LG.capture(ARTIFACTS, r9['preadvance_operands']['bounds'])
    changed = {key for key in cube if cube[key]['exact'][:2] != r7[key]['exact'][:2]}
    by_id = {cell['cell_id']: cell for cell in bounds['cells']}
    for cell_id, endpoint in changed:
        by_id[cell_id][LG.ENDPOINTS[endpoint]] = cube[(cell_id, endpoint)]['exact'][:2]
    folder, rerun = synthetic_run(out, 'substituted', r9, bounds)
    started = time.perf_counter()
    substituted = LG.ledger(r9=r9, r9_artifacts=ARTIFACTS, rerun=rerun, rerun_artifacts=folder, replay=cube, r7=r7,
                            rerun_verdict=verdict)
    summary['substituted'] = {'verdict': substituted['verdict'], 'replay_differs_from_r7': len(changed),
                              'attributed': len(substituted['heat_inputs']['bounds']['attributed']),
                              'unattributed': len(substituted['unattributed']),
                              'traced': substituted['traced_to_attributed_bounds'],
                              'seconds': round(time.perf_counter()-started, 1)}
    cell_id, endpoint = sorted(changed)[0]
    lower, upper = LG.interval(by_id[cell_id][LG.ENDPOINTS[endpoint]])
    moved = upper+1
    by_id[cell_id][LG.ENDPOINTS[endpoint]] = [by_id[cell_id][LG.ENDPOINTS[endpoint]][0],
                                              [hex(moved.numerator), hex(moved.denominator)]]
    folder, rerun = synthetic_run(out, 'tampered', r9, bounds)
    tampered = LG.ledger(r9=r9, r9_artifacts=ARTIFACTS, rerun=rerun, rerun_artifacts=folder, replay=cube, r7=r7,
                         rerun_verdict=verdict)
    summary['tampered'] = {'verdict': tampered['verdict'],
                           'unattributed': [item.get('reason') for item in tampered['unattributed']]}
    for name, value in (('identity', identity), ('substituted', substituted), ('tampered', tampered)):
        (out/f'ledger-{name}.json').write_text(json.dumps(value, indent=1, sort_keys=True), encoding='utf8')
    summary['ok'] = (summary['identity']['verdict'] == 'PASS' and summary['identity']['attributed'] == 0 and
                     summary['substituted']['verdict'] == 'PASS' and
                     summary['substituted']['attributed'] == len(changed) > 0 and
                     summary['tampered']['verdict'] == 'FAIL')
    (out/'summary.json').write_text(json.dumps(summary, indent=1), encoding='utf8')
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
