"""Review-before-queue for q15: measure_s2.py must fail closed, and a 1-round smoke gives wall time and peak RSS.

measure_s2.py is imported unchanged; each mutant patches ONE of its functions in this process, runs main() with
1 round into a new folder, and must end in an exception or a non-zero SystemExit. The control (no mutant) must pass.
usage: mutants_s2.py OUTPUT_DIR
"""
import json
import sys
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_s2 as MS  # noqa: E402

ORIGINAL = dict(arm_capture=MS.arm_capture, arm_legacy=MS.arm_legacy,
                captured_bytes=MS.LG.captured_bytes, capture=MS.LG.capture)


def flip(blob, at=None):
    at = len(blob)//2 if at is None else at
    return blob[:at]+bytes([blob[at] ^ 1])+blob[at+1:]


def capture_file_byte(artifacts, blocks, geometry_id, graph, bounds, check, budget):
    rows = ORIGINAL['arm_capture'](artifacts, blocks, geometry_id, graph, bounds, check, budget)
    path = Path(artifacts)/rows['bounds']['path']
    path.write_bytes(flip(path.read_bytes()))  # stored container changed after its receipt
    return rows


def operand_byte(artifacts, blocks, geometry_id, graph, bounds, check, budget):
    return ORIGINAL['arm_capture'](artifacts, blocks, geometry_id, flip(graph), bounds, check, budget)


def mesh_block_byte(artifacts, blocks, geometry_id, graph, bounds, check, budget):
    blocks = list(blocks)
    blocks[3] = flip(blocks[3], 0)
    return ORIGINAL['arm_capture'](artifacts, blocks, geometry_id, graph, bounds, check, budget)


def legacy_block_byte(artifacts, blocks, geometry_id, graph, bounds, check):
    blocks = list(blocks)
    blocks[3] = flip(blocks[3], 0)
    return ORIGINAL['arm_legacy'](artifacts, blocks, geometry_id, graph, bounds, check)


def missing_row_key(artifacts, blocks, geometry_id, graph, bounds, check, budget):
    rows = ORIGINAL['arm_capture'](artifacts, blocks, geometry_id, graph, bounds, check, budget)
    del rows['closed_graph']['raw_sha256']
    return rows


def missing_arm_row(artifacts, blocks, geometry_id, graph, bounds, check, budget):
    rows = ORIGINAL['arm_capture'](artifacts, blocks, geometry_id, graph, bounds, check, budget)
    rows.pop('mesh')
    return rows


def decoded_extra_byte(path, container_sha256, raw_bytes, stored_bytes):
    return ORIGINAL['captured_bytes'](path, container_sha256, raw_bytes, stored_bytes)+b' '


def reader_refuses(artifacts, row):
    return None


def decoded_wrong_pin(path, container_sha256, raw_bytes, stored_bytes):
    return ORIGINAL['captured_bytes'](path, '0'*64, raw_bytes, stored_bytes)


MUTANTS = {
    'capture-file-byte': ('arm_capture', capture_file_byte),
    'operand-byte': ('arm_capture', operand_byte),
    'mesh-block-byte': ('arm_capture', mesh_block_byte),
    'legacy-block-byte': ('arm_legacy', legacy_block_byte),
    'missing-row-key': ('arm_capture', missing_row_key),
    'missing-arm-row': ('arm_capture', missing_arm_row),
    'decoded-extra-byte': ('captured_bytes', decoded_extra_byte),
    'reader-refuses': ('capture', reader_refuses),
    'decoded-wrong-pin': ('captured_bytes', decoded_wrong_pin),
}


def run(out, name, rounds=1):
    sys.argv = ['measure_s2.py', str(out/name), str(rounds)]
    started = time.perf_counter()
    try:
        MS.main()
        outcome = 'PASSED'
    except SystemExit as stop:
        outcome = 'EXIT %r' % (stop.code,) if stop.code not in (None, 0) else 'PASSED'
    except Exception as error:  # noqa: BLE001  (any refusal counts as failing closed)
        outcome = 'RAISED %s: %s' % (type(error).__name__, str(error)[:120])
    return outcome, round(time.perf_counter()-started, 2)


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=False)
    results = {}
    for name, (target, replacement) in MUTANTS.items():
        owner = MS.LG if target in ('captured_bytes', 'capture') else MS
        setattr(owner, target, replacement)
        try:
            results[name] = run(out, name)
        finally:
            setattr(owner, target, ORIGINAL[target])
        print(name, *results[name], flush=True)
    results['control'] = run(out, 'control')
    print('control', *results['control'], flush=True)
    peak = psutil.Process().memory_info().peak_wset
    survived = [n for n, (outcome, _) in results.items() if n != 'control' and outcome == 'PASSED']
    verdict = dict(mutants_failed_closed=len(MUTANTS)-len(survived), mutants=len(MUTANTS), survived=survived,
                   control=results['control'][0], peak_wset_bytes=peak, results=results)
    (out/'mutants.json').write_text(json.dumps(verdict, indent=1, sort_keys=True))
    print(json.dumps({k: verdict[k] for k in ('mutants_failed_closed', 'mutants', 'survived', 'control',
                                              'peak_wset_bytes')}))
    if survived or results['control'][0] != 'PASSED':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
