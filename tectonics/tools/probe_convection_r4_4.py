#!/usr/bin/env python3
"""Bounded frozen-temperature resolution study, NOT coupled benchmark acceptance.

SPDX-License-Identifier: AGPL-3.0-only
Reconstruct one smooth temperature field from exact coarse cell integrals,
then solve its mechanics on each requested mesh. The field uses sine modes
vertically and cosine modes horizontally, preserving the specified thermal
walls. This isolates mechanical/support/surface sampling error. It cannot
recover unresolved physical detail or establish full thermochemical convergence.
"""
from __future__ import annotations

import argparse
from concurrent.futures import CancelledError
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np


def temperature_on_grid(temperature, cells):
    """Reintegrate a boundary-compatible spectral interpolant, without clipping."""
    T = np.asarray(temperature, dtype=float)
    if (T.ndim != 2 or T.shape[0] != T.shape[1] or not 2 <= len(T) <= 256
            or not np.isfinite(T).all() or np.any((T < 1) | (T > 2))):
        raise ValueError('finite square Tosi cell averages in [1,2] required')
    if type(cells) is not int or not len(T) <= cells <= 256:
        raise ValueError('target must refine the input, at most 256 cells')
    n = len(T)
    if cells == n:
        return T.copy()
    x = (np.arange(n) + .5) / n
    vertical = np.arange(1, n + 1)
    horizontal = np.arange(n)
    sine = np.sin(np.pi*x[:, None]*vertical) * np.sinc(vertical/(2*n))
    cosine = np.cos(np.pi*x[:, None]*horizontal) * np.sinc(horizontal/(2*n))
    coefficients = np.linalg.solve(sine, T - (2 - x[:, None]))
    coefficients = np.linalg.solve(cosine, coefficients.T).T
    y = (np.arange(cells) + .5) / cells
    fine_sine = np.sin(np.pi*y[:, None]*vertical) * np.sinc(vertical/(2*cells))
    fine_cosine = np.cos(np.pi*y[:, None]*horizontal) * np.sinc(horizontal/(2*cells))
    result = 2 - y[:, None] + fine_sine @ coefficients @ fine_cosine.T
    if not np.isfinite(result).all() or np.any((result < 1) | (result > 2)):
        raise ValueError('interpolant exceeds physical bounds; no clipping or fallback')
    return result


def surface_probes(u):
    """Keep existing nearest-row diagnostic alongside a free-slip wall estimate.

    The quadratic through the two nearest rows with zero wall derivative gives
    (9*u[-1]-u[-2])/8. Exact for quadratic normal profiles; O(h^3) generally.
    This comparison is not substituted into the registered acceptance gates.
    """
    u = np.asarray(u, dtype=float)
    if (u.ndim != 2 or u.shape != (len(u), len(u)+1) or len(u) < 2
            or not np.isfinite(u).all() or np.any(u[:, [0, -1]])):
        raise ValueError('finite square MAC horizontal velocities with closed sides required')
    rows = {'registered_nearest_row': u[-1], 'quadratic_free_slip_wall': (9*u[-1]-u[-2])/8}
    return {name: {'rms': float(np.sqrt(np.sum(row*row)/len(u))),
                   'maximum_signed': float(np.max(row)), 'maximum_speed': float(np.max(abs(row)))}
            for name, row in rows.items()}


def write_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def main(args):
    root = args.source_root.resolve()
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(root/'src'), str(root/'tools')]
    import atlas_tectonics as atlas
    from atlas_tectonics.resources import WorkBudget
    from run_convection_r4_4 import source_record, Cancellation
    from analyse_convection_r4_4 import compare_table

    if not args.input.is_file() or args.input.is_symlink():
        raise ValueError('regular input archive required')
    input_hash = hashlib.sha256(args.input.read_bytes()).hexdigest()
    with np.load(args.input, allow_pickle=False) as fields:
        T = fields['temperature_k'].copy()
        original_u = fields['u_m_s'].copy() if 'u_m_s' in fields else None
    # Validate before output or solver preparation.
    if args.cells != sorted(set(args.cells)):
        raise ValueError('mesh sizes must be unique and increasing')
    for cells in args.cells:
        temperature_on_grid(T, cells)
    if not np.isfinite(args.seconds) or args.seconds <= 0:
        raise ValueError('positive finite per-grid deadline required')
    args.output.mkdir(parents=False, exist_ok=False)
    source = source_record()
    specification = json.loads((root/'cases/convection_r4_4.json').read_bytes())
    policy = atlas.NonlinearStokesPolicy(max_picard_iterations=400, ilu_fill_factor=17.)
    declaration = dict(schema='atlas.r4-4-frozen-field-probe.v1',
        meaning='Diagnostic isolation only; NOT an evolved mesh study or benchmark acceptance',
        input_sha256=input_hash, source=source,
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        case='tosi-1', meshes=args.cells, seconds_per_mesh=args.seconds,
        nonlinear_policy=asdict(policy), python=platform.python_version(), numpy=np.__version__,
        benchmark_accepted=False,
        timing_scope='Includes preparation and compilation as encountered; mesh timings are not a matched performance benchmark',
        reconstructed_field='exact source-cell integrals; sin(z)/cos(x); no extra resolved information')
    if original_u is not None:
        declaration['saved_surface_probes'] = surface_probes(original_u)
    write_new(args.output/'experiment.json', declaration)
    records = []
    for cells in args.cells:
        started = time.perf_counter()
        budget = WorkBudget(1024 << 20)
        record = dict(cells=cells, status='STARTED', benchmark_accepted=False)
        try:
            temperature = temperature_on_grid(T, cells)
            problem = atlas.TosiCase('tosi-1').problem(cells)
            state = atlas.ThermochemicalState(problem, temperature, np.zeros_like(temperature),
                time_s=0., source='NEW frozen-field probe from NPZ sha256:'+input_hash, budget=budget)
            with atlas.PreparedVariableStokes2D(problem.box, problem.scales, policy=policy,
                    budget=budget) as solver:
                flow = atlas.tosi_endpoint_flow(state, solver, budget=budget, cancel=Cancellation(args.seconds))
                diagnostics = atlas.tosi_state_diagnostics(state, flow, budget=budget)
                record.update(status='SOLVED_FROZEN_FIELD_ONLY', diagnostics=diagnostics,
                    surface_probes=surface_probes(flow.array('u_m_s')),
                    reference_screen=compare_table('tosi-1', diagnostics['diagnostics'], specification),
                    mechanical_diagnostics=flow.descriptor()['diagnostics'], solver_identity=solver.identity)
                np.savez_compressed(args.output/f'fields_{cells}.npz', temperature_k=temperature,
                    u_m_s=flow.array('u_m_s'), w_m_s=flow.array('w_m_s'))
        except (ValueError, CancelledError) as exc:
            record.update(status='REFUSED_OR_CANCELLED', error=str(exc))
        record.update(elapsed_s=time.perf_counter()-started, budget=budget.statistics())
        if source_record() != source:
            raise ValueError('source changed during probe; results are not source-bound')
        write_new(args.output/f'result_{cells}.json', record)
        records.append(record)
        print(json.dumps({k: record[k] for k in ('cells', 'status', 'elapsed_s')}), flush=True)
    write_new(args.output/'summary.json', dict(experiment=declaration, results=records, benchmark_accepted=False))
    return int(any(r['status'] != 'SOLVED_FROZEN_FIELD_ONLY' for r in records))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--cells', nargs='+', type=int, default=[32, 64, 128])
    parser.add_argument('--seconds', type=float, default=90.)
    raise SystemExit(main(parser.parse_args()))
