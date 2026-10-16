"""Second refuter batch for compare_arms.py (same fixture builder as repro_cmp.py).

Usage: repro_cmp2.py REAL_DUMP_DIR COMPARE_ARMS_PY NEW_OUT_DIR
A3  a face's two owners swapped (orientation flip) on the real mesh;
A4  state.cells reversed on the real state record while the per-cell arrays (539 rows) keep their order;
V1  after-arm-only deterministic RSS blow-up at the interval runner (guard reason rss_limit) vs before adopted.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repro_cmp as R  # noqa: E402  (the builder; json/numpy only)


def main():
    real_dir, compare, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    R.COMPARE = compare
    out.mkdir()
    plan = []
    raw_state = (real_dir/'records'/'state.json').read_bytes()
    mesh = json.loads((real_dir/'records'/'mesh.json').read_bytes())
    base = R.canon(mesh)
    face = next(f for f in mesh['faces'] if len(f['owners']) == 2)
    owners = list(face['owners'])
    face['owners'].reverse()
    swapped = R.canon(mesh)
    del mesh
    rows = np.arange(539, dtype=np.float64)*1.5
    case = R.case_dirs(out, 'A3_face_owners_swapped')
    b = R.build_arm(case/'b', 'A3b', {'mesh': base, 'state': raw_state}, {'state': R.SMALL_STATE})
    a = R.build_arm(case/'a', 'A3a', {'mesh': swapped, 'state': raw_state}, {'state': R.SMALL_STATE})
    plan.append(('A3_face_owners_swapped', b, a, 'not PASS (owner order, hence orientation, flipped)',
                 {'face_id': face['face_id'], 'owners_before': owners}))
    del base, swapped

    state = json.loads(raw_state)
    canon_state = R.canon(state)
    state['cells'].reverse()
    reversed_state = R.canon(state)
    case = R.case_dirs(out, 'A4_state_cells_reordered')
    arrays = [('exterior-fv:component_mass_kg:0', rows)]
    b = R.build_arm(case/'b', 'A4b', {'state': R.SMALL_STATE}, {'state': canon_state}, arrays1=arrays)
    a = R.build_arm(case/'a', 'A4a', {'state': R.SMALL_STATE}, {'state': reversed_state}, arrays1=arrays)
    plan.append(('A4_state_cells_reordered', b, a,
                 'not PASS if per-cell array rows follow state.cells order (539 cells, 539-row arrays)',
                 {'cells': len(state['cells'])}))

    case = R.case_dirs(out, 'V1_after_only_rss_limit')
    b = R.build_arm(case/'b', 'V1b', {'state': R.SMALL_STATE}, {'state': R.SMALL_STATE})
    a = R.build_arm(case/'a', 'V1a', {'state': R.SMALL_STATE}, {'state': R.SMALL_STATE})
    stage = a[0]/'stage-interval.json'
    record = json.loads(stage.read_bytes())
    record.update(status='FAILED', failed_step='runner', reason='guarded runner did not seal cleanly',
                  width_gate_passed=None, steps=record['steps'][:1])
    stage.write_bytes(R.canon(record))
    (a[0]/'run-interval'/'run.guard-abort.json').write_bytes(b'{"reason": "rss_limit", "phase": "advance"}')
    plan.append(('V1_after_only_rss_limit', b, a, 'FAIL or a distinct class: rss_limit is the arm\'s own memory, '
                 'not the machine', None))
    R.run(plan, out)


if __name__ == '__main__':
    main()
