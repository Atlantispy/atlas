"""Fixed small step-2 assessment; no fitting, seed retries or simulation.

SPDX-License-Identifier: AGPL-3.0-only
Run with the scientific Python, -B, and --output NEW.json. Failure evidence is
retained in that claimed output. The caller chooses its trusted local path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))


class Deadline:
    def __init__(self, seconds):
        self.end = time.perf_counter() + seconds

    def is_set(self):
        return time.perf_counter() >= self.end


def summarise_series(series):
    """Do not turn unattempted, failed or missing diagnostic rows into a pass."""
    rows = series['cases']
    complete = (series['requested_cases'] == series['attempted_cases'] == len(rows)
                and not series['unattempted_case_indices'])
    generated = [row for row in rows if (row.get('generation') or {}).get('atlas_id') is not None]
    numerical = complete and bool(generated) and all(
        row.get('generation') is not None and 'assessment_error' not in row for row in rows)
    for row in generated:
        assessment = row.get('assessment') or {}
        numerical = numerical and all(assessment.get(key, {}).get('status') == 'PASS'
            for key in ('geometry', 'global_rotation', 'outline_geometry'))
        numerical = numerical and assessment.get('global_rotation', {}).get('cut_rotation', {}).get('status') == 'PASS'
    vectors = [row['assessment']['layout_metrics']['ranked_area_fractions']
               for row in rows[:3] if row.get('assessment') is not None]
    gaps = [sum(abs(a-b) for a,b in zip(first,second, strict=True))
            for i,first in enumerate(vectors) for second in vectors[i+1:]]
    return dict(numerical_geometry_pass=bool(numerical),
                three_seed_ranked_area_pairwise_l1=gaps,
                three_seed_rotation_invariant_diversity=len(vectors) == 3 and min(gaps) > .001)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    paths = [Path(__file__), ROOT/'tools/new_world_layout.py',
             ROOT/'tools/new_world_contract.py', ROOT/'tools/assess_plate_layout_morphology.py']
    def source():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    # Claim before scientific work; no overwrite or retry into a conflicting file.
    with args.output.open('x', encoding='utf-8') as output:
        before = source()
        result = dict(schema='atlas.new-world.step2-evidence.v1', source_sha256=before,
                      runtime=dict(python=platform.python_version(), platform=platform.system()),
                      status='INCOMPLETE', scientific_acceptance=False)
        start = time.perf_counter()
        try:
            from atlas_tectonics.resources import WorkBudget
            from atlas_tectonics.plate_reference_use import prepare_reference_use
            from new_world_contract import new_request, resolve_request
            from new_world_layout import generate_layout_candidate
            from assess_plate_layout_morphology import prepare_reference, assess_cases
            budget = WorkBudget(128 << 20)
            deadline = Deadline(240.)
            reference_start = time.perf_counter()
            reference_plan = prepare_reference_use(ROOT/'reference_data/pb2002',
                budget=budget, cancel=deadline)
            reference = prepare_reference(reference_plan, include_withheld=True,
                run_id='new-world-s2-reference-20260924', budget=budget, cancel=deadline)
            result['reference_seconds'] = time.perf_counter()-reference_start
            result['reference'] = reference
            cases = [(0,12,512), (1,12,512), (2,12,512), (0,12,1024), (0,52,1024)]
            plans = []
            for seed, count, support in cases:
                request = new_request(f'{seed:032x}', support_cells=support)
                request['settings']['plate_count'] = dict(mode='fixed', value=count)
                plans.append(resolve_request(request))
            def generate(plan):
                candidate = generate_layout_candidate(plan, cancel=deadline)
                print(f"{plan['resolved_settings']['plate_count']} plates / "
                      f"{plan['request']['resolution']['support_cells']} support: "
                      f"{candidate.report['status']} in {candidate.report['elapsed_seconds']:.3f}s",
                      flush=True)
                return candidate
            series = assess_cases(plans, generate=generate, run_id='new-world-s2-20260924',
                reference=reference, resolution_pairs=((0,3),), budget=budget, cancel=deadline)
            result['assessment'] = series
            result['assessment_resources'] = budget.statistics()
            result['source_unchanged'] = source() == before
            result.update(summarise_series(series))
            result['status'] = 'MEASURED_NOT_GEOLOGICALLY_ACCEPTED'
        except Exception as exc:
            result['failure'] = dict(type=type(exc).__name__, message=str(exc))
        result['elapsed_seconds'] = time.perf_counter()-start
        json.dump(result, output, indent=2, allow_nan=False)
        output.write('\n')
    print(json.dumps({key:value for key,value in result.items()
                     if key not in ('reference','assessment','source_sha256')}, sort_keys=True))
    return 0 if (result['status'] != 'INCOMPLETE' and result['source_unchanged']
                 and result['numerical_geometry_pass']
                 and result['three_seed_rotation_invariant_diversity']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
