"""Bounded fixed-case shape evidence, not a geological acceptance test.

Run with python -I -B and one native-library thread. JSON goes to stdout.
Uses the existing pinned PB2002 reader, shape metrics and source inventory.
Does not tune, retry, increase resolution or modify any acceptance threshold.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import asdict
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import numpy as np

from atlas_tectonics import (SphericalFrame, PlateLayoutSettings,
    generate_plate_layout, layout_metrics, plate_outline_cycles)
from atlas_tectonics.geometry import GeometryError
from atlas_tectonics.plate_reference import AREA_ROWS
from atlas_tectonics.plate_reference_acceptance import (
    OBSERVATION_SCALES_M, evaluation_record, record_role)
from atlas_tectonics.plate_reference_dataset import (
    EARTH_REFERENCE_RADIUS_M, load_pb2002, lonlat_vectors,
    multiscale_ring_measures)
from atlas_tectonics.resources import WorkBudget


class Deadline:
    """Existing cooperative cancellation API; no extra scheduler/thread."""
    def __init__(self, seconds):
        self.ends = time.perf_counter() + seconds

    def is_set(self):
        return time.perf_counter() >= self.ends


def differences(candidate, reference):
    rows = []
    for a, b in zip(candidate['scales'], reference['scales'], strict=True):
        if a['scale_m'] != b['scale_m']:
            raise ValueError('observation scale mismatch')
        for x, y in zip(a['phases'], b['phases'], strict=True):
            if x['phase'] != y['phase']:
                raise ValueError('sampling phase mismatch')
            row = dict(scale_m=a['scale_m'], phase=x['phase'],
                       candidate_status=x['status'], reference_status=y['status'])
            if x['status'] == y['status'] == 'MEASURED':
                row['metrics'] = {}
                for key in ('sampled_compactness', 'reflex_turning_radians',
                            'sampled_perimeter_radians'):
                    row['metrics'][key] = dict(candidate=x[key], reference=y[key],
                                               difference=x[key]-y[key])
                row['boundary_second_moment_eigenvalues'] = dict(
                    candidate=x['boundary_second_moment_eigenvalues'],
                    reference=y['boundary_second_moment_eigenvalues'])
            rows.append(row)
    return rows


def main():
    started = time.perf_counter()
    spec = importlib.util.spec_from_file_location('atlas_verify', ROOT/'verify.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    before = verifier.source_inventory(ROOT)
    case = json.loads((ROOT/'cases/w01_plate_layout_revision.json').read_text())
    area_bound = case['acceptance']['geometry_area_closure_sr']
    budget = WorkBudget(256*1024**2)
    deadline = Deadline(120.)
    dataset = load_pb2002(ROOT/'reference_data/pb2002', budget=budget, cancel=deadline)
    # Select by already-exposed calibration ranks, never by candidate fit.
    ranked = sorted(AREA_ROWS, key=lambda item: (-item[1], item[0]))[:12]
    curves = {c.name: c for c in dataset.plates}
    reference = {name: multiscale_ring_measures(
        lonlat_vectors(curves[name].measurement_coordinates()), EARTH_REFERENCE_RADIUS_M,
        OBSERVATION_SCALES_M, budget=budget, cancel=deadline) for name, _ in ranked}
    reference_seconds = time.perf_counter()-started
    rows = []
    sphere = SphericalFrame(EARTH_REFERENCE_RADIUS_M, 'bounded-shape-comparison')
    # Same three seeds/resolution as the original comparison; one explicit
    # microplate-coverage case, with no retry at a more favourable resolution.
    settings = [PlateLayoutSettings(12, seed, 512) for seed in (41, 42, 43)]
    settings.append(PlateLayoutSettings(52, 41, 1024))
    for setting in settings:
        begin = time.perf_counter()
        deadline = Deadline(120.)
        row = dict(settings=asdict(setting), candidate_id=None, plates=[])
        try:
            world = generate_plate_layout(sphere, setting, budget=budget, cancel=deadline)
            row.update(generation_seconds=time.perf_counter()-begin,
                       candidate_id=world.atlas_id, status='GENERATED_NOT_GEOLOGICALLY_ACCEPTED',
                       layout_metrics=layout_metrics(world, budget=budget, cancel=deadline),
                       generation_provenance=world.descriptor()['source_bindings'])
            if setting.plate_count == 12:
                # Rank association is only an area-conditioned diagnostic. It
                # does not claim that an invented plate reconstructs the Earth.
                for rank, (name, table_area) in enumerate(ranked):
                    plate_id = f'plate-{rank:06d}'
                    role = record_role(observable='outline', plate_id=name)
                    split = 'withheld' if role == 'WITHHELD_WITHIN_MODEL' else 'development'
                    item = dict(plate_id=plate_id, reference_plate=name,
                                area_rank=rank+1, reference_shape_role=role,
                                reference_table_area_sr=table_area,
                                evaluation=evaluation_record(dataset.dataset_id, world.atlas_id,
                                    split=split, purpose='validation',
                                    run_id=f'W01-short-20260922-seed-{setting.seed}-rank-{rank+1}'))
                    rings = plate_outline_cycles(world, plate_id, budget=budget, cancel=deadline)
                    if len(rings) != 1:
                        item.update(status='UNSUPPORTED_MULTIRING_COMPARISON', ring_count=len(rings))
                    else:
                        measured = multiscale_ring_measures(rings[0], sphere.radius_m,
                            OBSERVATION_SCALES_M, budget=budget, cancel=deadline)
                        item.update(status='MEASURED', candidate=measured,
                                    differences=differences(measured, reference[name]))
                    row['plates'].append(item)
                measured = [p for p in row['plates'] if p['status'] == 'MEASURED']
                areas = dict(zip(row['layout_metrics']['plate_ids'],
                                 row['layout_metrics']['area_steradians'], strict=True))
                closure = abs(math.fsum(areas.values())-4*math.pi)
                formula_error = max((p['candidate']['native']['area_formula_disagreement_sr']
                                     for p in measured), default=None)
                atlas_error = max((abs(p['candidate']['native']['area_steradians']-areas[p['plate_id']])
                                   for p in measured), default=None)
                complete = len(measured) == setting.plate_count
                passed = complete and max(closure, formula_error, atlas_error) <= area_bound
                row['numerical_geometry'] = dict(
                    status='PASS' if passed else 'FAIL_OR_INCOMPLETE', plates_checked=len(measured),
                    area_bound_sr=area_bound, closure_error_sr=closure,
                    maximum_formula_disagreement_sr=formula_error,
                    maximum_ring_vs_atlas_area_error_sr=atlas_error)
                if complete and not passed:
                    raise ArithmeticError('independent spherical area check exceeded original case tolerance')
        except CancelledError as exc:
            row.update(status='BOUNDED_CHECK_TIMEOUT', error=str(exc))
        except GeometryError as exc:
            row.update(status='EXPLICIT_CAPABILITY_REFUSAL', error=str(exc))
        row['elapsed_seconds'] = time.perf_counter()-begin
        rows.append(row)
        print(f"{setting.plate_count} plates seed {setting.seed}: {row['status']} "
              f"({row['elapsed_seconds']:.3f} s)", file=sys.stderr, flush=True)
    after = verifier.source_inventory(ROOT)
    result = dict(schema='atlas.w01.bounded-shape-evidence.v1',
        status='MEASURED_NOT_GEOLOGICALLY_ACCEPTED',
        source_unchanged=before == after, source_sha256=before,
        runtime=dict(python=platform.python_version(), numpy=np.__version__, platform=platform.system()),
        dataset=dataset.provenance(), scales_m=list(OBSERVATION_SCALES_M), phases=[0., .5],
        reference=reference, reference_rank_order=[name for name, _ in ranked],
        calibration_area_renormalisation=4*math.pi/math.fsum(a for _, a in ranked),
        reference_elapsed_seconds=reference_seconds, candidates=rows,
        elapsed_seconds=time.perf_counter()-started, peak_accounted_bytes=budget.peak_reserved_bytes,
        budget_reservations_remaining=budget.reserved_bytes,
        scientific_acceptance=False,
        limitations=[
            'Largest 12 area-conditioned comparisons, not the full 52-plate morphology population.',
            'Equal observation spacing cannot recover boundary detail absent from the generating support.',
            'Area ranks are not geological correspondences; renormalised candidate areas are larger.',
            'Single present-day PB2002 model; held-out PS shape is not independent external evidence.',
            'No fitted score, new pass threshold, force inference, historical evolution or R4.4 campaign.',
            'Cooperative 120-second per-case cancellation, not an operating-system hard timeout.',
        ])
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if before == after and budget.reserved_bytes == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
