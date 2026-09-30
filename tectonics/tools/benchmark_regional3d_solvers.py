"""Matched-workload, matched-acceptance benchmark of the 3D regional Stokes methods.

SPDX-License-Identifier: AGPL-3.0-only
Not a planetary run, a calibrated geological simulation or acceptance evidence.

Every (case, cells, method) runs in a fresh Python process so that cold
preparation, first solve, warm solves with changed forcing, and a rebuild for
changed viscosity are timed without state left by a previous run. The child
records the solver's own accounted reservations separately from measured peak
process memory (Windows: peak private commit and peak working set; elsewhere
ru_maxrss). Velocity/pressure from every solve are saved so that methods can
be compared on identical inputs. Every published solution has passed the same
fixed acceptance gates (matched acceptance). The achieved residuals, iteration
counts and refinements differ between methods and are recorded per solve, and the
cross-method output differences are reported, not assumed. Forward error against
the direct oracle is a separate mode (``--forward-error``) for small grids.

Memory: each phase records the process's lifetime peaks (cumulative, so later
phases include earlier peaks) and its current private and working-set bytes.
The solver's own operations run with one BLAS thread under the package's native
lease; the thread configuration at import is recorded, because OpenBLAS commits
per-thread buffers (about 1 GiB of private commit with 16 threads) before any
solver work. Report memory above the post-import level.

Run a source tree explicitly (the baseline and candidate trees use this same
harness):

    python -B tectonics/tools/benchmark_regional3d_solvers.py \
        --source-root tectonics/src --output-dir <new-dir> \
        --cases inclusion:4,6 --methods gmres,multigrid,auto

``auto`` runs the automatic selection and records its choice, reason and
overhead. ``--decisions`` records the
selection for each case without preparing or solving anything. The
``plume``, ``slab``, ``blobs``, ``ramp`` and ``shear`` cases (and the timing
of ``layered1e4``) are held out from the selection calibration, which used
``smooth``, ``lithosphere`` and ``inclusion``, to test whether it generalises.

Declared per-case limits: a case whose forecast peak private memory (import
baseline plus the route's own accounting projection) exceeds ``--max-private-gib``
is skipped before it starts; a running case stops as soon as a phase ends above
that limit, and ``--timeout`` bounds its elapsed seconds. Projected assembled
reservations above ``--max-projected-gib`` are skipped as before.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter

import numpy as np

SIDE_NAMES = ('x0', 'x1', 'y0', 'y1', 'z0', 'z1')


# --------------------------------------------------------------------------
# Measured process memory (not the solver's accounting)
# --------------------------------------------------------------------------

def process_memory():
    """Current and peak process memory in bytes, from the operating system."""
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                        ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                        ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t),
                        ('PrivateUsage', ctypes.c_size_t)]
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        query = kernel.K32GetProcessMemoryInfo
        query.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
        query.restype = wintypes.BOOL
        if not query(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError(ctypes.get_last_error(), 'GetProcessMemoryInfo failed')
        return dict(private_bytes=int(counters.PrivateUsage),
                    peak_private_bytes=int(counters.PeakPagefileUsage),
                    working_set_bytes=int(counters.WorkingSetSize),
                    peak_working_set_bytes=int(counters.PeakWorkingSetSize))
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak *= 1 if sys.platform == 'darwin' else 1024
    return dict(peak_working_set_bytes=int(peak))


# --------------------------------------------------------------------------
# Cases (inputs only; no solver state)
# --------------------------------------------------------------------------

def geometry(cells, lengths):
    cells = np.asarray(cells)
    spacing = np.asarray(lengths, dtype=float)/cells
    index = np.indices(tuple(cells)).reshape(3, -1).T
    points, _ = np.polynomial.legendre.leggauss(3)
    reference = points[np.indices((3, 3, 3)).reshape(3, -1).T]
    quadrature = (index[:, None, :]+(reference[None, :, :]+1)/2)*spacing
    nodes = np.indices(tuple(2*cells+1)).reshape(3, -1).T*(spacing/2)
    return quadrature, nodes


def case_inputs(name, n):
    """Representative same-time regional problems, identical for every method.

    ``base@cX`` rescales a case's log-viscosity about its maximum so the overall
    contrast is 10^X; ``base@aX`` shortens the vertical box length so the brick
    aspect ratio is X, keeping every per-cell and per-node value (the same
    index-space problem in a flatter box). ``random@cX`` is a closed shear box
    with per-point log-uniform viscosity spanning 10^X (fixed seed).
    """
    if '@' in name:
        base, parameter = name.split('@')
        if base == 'random':
            spec = case_inputs('layered1e4', n)
            rng = np.random.default_rng(20260930+n)
            eta = 1e21*10**(float(parameter[1:])*(rng.random((int(np.prod(spec['cells'])), 27))-1))
            return dict(spec, eta=eta, changed_eta=eta*1.5)
        spec = case_inputs(base, n)
        if parameter[0] == 'c':
            def rescale(eta):
                log = np.log10(np.broadcast_to(np.asarray(eta, dtype=float), spec['force'].shape[:2]))
                top, span = np.max(log), np.max(log)-np.min(log)
                return 10**(top+(log-top)*float(parameter[1:])/span)
            return dict(spec, eta=rescale(spec['eta']), changed_eta=rescale(spec['changed_eta']))
        if parameter[0] == 'a':
            cells, lengths = np.asarray(spec['cells']), np.asarray(spec['lengths'], dtype=float)
            horizontal = min(lengths[:2]/cells[:2])
            lengths[2] = cells[2]*horizontal/float(parameter[1:])
            return dict(spec, lengths=tuple(float(x) for x in lengths))
        raise ValueError('unknown case parameter '+parameter)
    if name == 'inclusion':
        # Closed box (pressure gauge), boundary shear, buoyant weak inclusion
        # (contrast 1e4) riding on full rho0*g. Cube, isotropic spacing.
        length, speed = 1e5, 1e-9
        cells, lengths = (n, n, n), (length,)*3
        q, xyz = geometry(cells, lengths)
        inside = np.sum((q/length-[.5, .5, .4])**2, axis=-1) < .06
        eta = np.where(inside, 1e17, 1e21)
        force = np.zeros(q.shape)
        force[..., 2] = -10.*(3300.-30.*inside)
        velocity = np.zeros(xyz.shape)
        velocity[:, 0] = speed*(xyz[:, 2]/length-.5)
        velocity[:, 1] = .3*speed*(xyz[:, 0]/length-.5)
        boundary = {side: ('velocity',)*3 for side in SIDE_NAMES}
        changed = eta*np.exp(.1*np.sin(2*np.pi*q[..., 0]/length))
        return dict(cells=cells, lengths=lengths, eta=eta, changed_eta=changed, force=force,
                    velocity=velocity, boundary=boundary, scales=(length, speed),
                    reference_viscosity=1e21, mean_pressure=None, exact=None)
    if name == 'lithosphere':
        # Open top, free-slip sides/base, convergent side velocities, strong
        # lid (1e23) over a weak mantle (1e20) with a weak fault zone (1e21),
        # dense blob. Flat box: vertical spacing half the horizontal spacing.
        length, depth, speed = 4e5, 2e5, 1e-9
        cells, lengths = (n, n, n), (length, length, depth)
        q, xyz = geometry(cells, lengths)
        z = q[..., 2]/depth
        eta = np.where(z > .8, 1e23, 1e20)
        fault = (z > .8) & (np.abs(q[..., 0]-.5*length-.5*(q[..., 2]-.8*depth)) < .06*length)
        eta = np.where(fault, 1e21, eta)
        blob = np.sum(((q-[.5*length, .5*length, .55*depth])/[.12*length, .2*length, .15*depth])**2, axis=-1) < 1
        force = np.zeros(q.shape)
        force[..., 2] = -10.*(3300.+40.*blob)
        velocity = np.zeros(xyz.shape)
        velocity[xyz[:, 0] == 0., 0] = speed
        velocity[xyz[:, 0] == np.max(xyz[:, 0]), 0] = -speed
        boundary = {'x0': ('velocity', 'traction', 'traction'), 'x1': ('velocity', 'traction', 'traction'),
                    'y0': ('traction', 'velocity', 'traction'), 'y1': ('traction', 'velocity', 'traction'),
                    'z0': ('traction', 'traction', 'velocity'), 'z1': ('traction',)*3}
        changed = eta*np.exp(.1*np.sin(2*np.pi*q[..., 1]/length))
        return dict(cells=cells, lengths=lengths, eta=eta, changed_eta=changed, force=force,
                    velocity=velocity, boundary=boundary, scales=(length, speed),
                    reference_viscosity=1e21, mean_pressure=None, exact=None)
    if name == 'smooth':
        # Manufactured exact polynomial (eta = 1 + x), closed box with datum.
        cells, lengths = (n, n, n), (1., 1., 1.)
        q, xyz = geometry(cells, lengths)
        eta = 1+q[..., 0]
        force = np.stack((np.ones(q.shape[:2]), 2-2*q[..., 2], -3-2*q[..., 1]), axis=-1)
        x, y, zz = xyz.T
        velocity = np.stack((y*zz, zz*x, x*y), axis=-1)
        boundary = {side: ('velocity',)*3 for side in SIDE_NAMES}
        changed = eta*(1+.1*np.sin(2*np.pi*q[..., 1]))
        return dict(cells=cells, lengths=lengths, eta=eta, changed_eta=changed, force=force,
                    velocity=velocity, boundary=boundary, scales=(1., 1.), reference_viscosity=1.,
                    mean_pressure=0., exact='cross-shear velocity; pressure x+2y-3z')
    if name in ('layered1e4', 'layered1e6'):
        # Closed-box shear over a weak layer below z = 2/3 (contrast 1e4 or 1e6),
        # as in the reference suite's weak-layer checks.
        length, speed = 1e5, 1e-9
        cells, lengths = (n, n, n), (length,)*3
        q, xyz = geometry(cells, lengths)
        contrast = 1e4 if name == 'layered1e4' else 1e6
        eta = np.where(q[..., 2]/length > 2/3, 1e21, 1e21/contrast)*np.ones(27)
        velocity = np.zeros(xyz.shape)
        velocity[:, 0] = speed*xyz[:, 2]/length
        velocity[:, 1] = speed*np.sin(np.pi*xyz[:, 0]/length)*xyz[:, 2]/length
        return dict(cells=cells, lengths=lengths, eta=eta, changed_eta=eta*1.5, force=np.zeros(q.shape),
                    velocity=velocity, boundary={side: ('velocity',)*3 for side in SIDE_NAMES},
                    scales=(length, speed), reference_viscosity=1e21, mean_pressure=None, exact=None)
    if name == 'plume':
        # Held out. Open top, free-slip sides and base; viscosity varies smoothly
        # (about 1e2 overall) with height and a warm, buoyant central plume.
        length, speed = 2e5, 1e-9
        cells, lengths = (n, n, n), (length,)*3
        q, xyz = geometry(cells, lengths)
        x, y, z = np.moveaxis(q/length, -1, 0)
        plume = np.exp(-((x-.5)**2+(y-.5)**2)/.02)
        eta = 1e20*10**(1.5*z)/(1+4*plume)
        force = np.zeros(q.shape)
        force[..., 2] = -10.*(3300.-20.*plume)
        boundary = {'x0': ('velocity', 'traction', 'traction'), 'x1': ('velocity', 'traction', 'traction'),
                    'y0': ('traction', 'velocity', 'traction'), 'y1': ('traction', 'velocity', 'traction'),
                    'z0': ('traction', 'traction', 'velocity'), 'z1': ('traction',)*3}
        changed = eta*np.exp(.1*np.sin(2*np.pi*x))
        return dict(cells=cells, lengths=lengths, eta=eta, changed_eta=changed, force=force,
                    velocity=np.zeros(xyz.shape), boundary=boundary, scales=(length, speed),
                    reference_viscosity=1e21, mean_pressure=None, exact=None)
    if name == 'slab':
        # Held out. Non-cubic grid (n, n, n/2) on a flat 4:1 box (2:1 bricks):
        # strong lid (1e23) and a strong, dense slab dipping from it into a weak
        # mantle (1e20); convergent sides, free-slip base, open top.
        length, depth, speed = 8e5, 2e5, 1e-9
        cells, lengths = (n, n, n//2), (length, length, depth)
        q, xyz = geometry(cells, lengths)
        x, z = q[..., 0]/length, q[..., 2]/depth
        slab = (z > .3) & (z <= .8) & (np.abs(x-(.55-.3*(.8-z))) < .06)
        eta = np.where((z > .8) | slab, 1e23, 1e20)
        force = np.zeros(q.shape)
        force[..., 2] = -10.*(3300.+50.*slab)
        velocity = np.zeros(xyz.shape)
        velocity[xyz[:, 0] == 0., 0] = speed
        velocity[xyz[:, 0] == np.max(xyz[:, 0]), 0] = -speed
        boundary = {'x0': ('velocity', 'traction', 'traction'), 'x1': ('velocity', 'traction', 'traction'),
                    'y0': ('traction', 'velocity', 'traction'), 'y1': ('traction', 'velocity', 'traction'),
                    'z0': ('traction', 'traction', 'velocity'), 'z1': ('traction',)*3}
        changed = eta*np.exp(.1*np.sin(2*np.pi*q[..., 1]/length))
        return dict(cells=cells, lengths=lengths, eta=eta, changed_eta=changed, force=force,
                    velocity=velocity, boundary=boundary, scales=(length, speed),
                    reference_viscosity=1e21, mean_pressure=None, exact=None)
    if name == 'blobs':
        # Held out. Closed box (pressure gauge), boundary shear and eight buoyant
        # weak inclusions of contrast 1e3.
        length, speed = 1e5, 1e-9
        cells, lengths = (n, n, n), (length,)*3
        q, xyz = geometry(cells, lengths)
        centres = np.array([[a, b, c] for a in (.27, .73) for b in (.27, .73) for c in (.3, .7)])
        inside = np.any(np.sum((q[..., None, :]/length-centres)**2, axis=-1) < .12**2, axis=-1)
        eta = np.where(inside, 1e18, 1e21)
        force = np.zeros(q.shape)
        force[..., 2] = -10.*(3300.-30.*inside)
        velocity = np.zeros(xyz.shape)
        velocity[:, 0] = speed*(xyz[:, 2]/length-.5)
        velocity[:, 1] = .3*speed*(xyz[:, 0]/length-.5)
        boundary = {side: ('velocity',)*3 for side in SIDE_NAMES}
        changed = eta*np.exp(.1*np.sin(2*np.pi*q[..., 0]/length))
        return dict(cells=cells, lengths=lengths, eta=eta, changed_eta=changed, force=force,
                    velocity=velocity, boundary=boundary, scales=(length, speed),
                    reference_viscosity=1e21, mean_pressure=None, exact=None)
    if name == 'ramp':
        # Held out. Rift: a strong lid (1e23) thinning across the box over a weak
        # mantle (10^19.5); divergent sides, free-slip base, open top, cubic bricks.
        length, speed = 2e5, 1e-9
        cells, lengths = (n, n, n), (length,)*3
        q, xyz = geometry(cells, lengths)
        x, z = q[..., 0]/length, q[..., 2]/length
        eta = np.where(z > .6+.3*x, 1e23, 10**19.5)
        force = np.zeros(q.shape)
        force[..., 2] = -10.*3300.
        velocity = np.zeros(xyz.shape)
        velocity[xyz[:, 0] == 0., 0] = -speed
        velocity[xyz[:, 0] == np.max(xyz[:, 0]), 0] = speed
        boundary = {'x0': ('velocity', 'traction', 'traction'), 'x1': ('velocity', 'traction', 'traction'),
                    'y0': ('traction', 'velocity', 'traction'), 'y1': ('traction', 'velocity', 'traction'),
                    'z0': ('traction', 'traction', 'velocity'), 'z1': ('traction',)*3}
        changed = eta*np.exp(.1*np.sin(2*np.pi*q[..., 1]/length))
        return dict(cells=cells, lengths=lengths, eta=eta, changed_eta=changed, force=force,
                    velocity=velocity, boundary=boundary, scales=(length, speed),
                    reference_viscosity=1e21, mean_pressure=None, exact=None)
    if name == 'shear':
        # Held out. Constant viscosity. A no-slip base moving in x with speed
        # varying across y shears the box under an open top, traction x-faces and
        # free-slip y-faces; a dense anomaly adds buoyancy-driven flow and dynamic
        # pressure (unlike a uniformly moving base, whose exact solution is a
        # rigid translation with zero pressure).
        length, speed = 1e5, 1e-9
        cells, lengths = (n, n, n), (length,)*3
        q, xyz = geometry(cells, lengths)
        velocity = np.zeros(xyz.shape)
        base = xyz[:, 2] == 0.
        velocity[base, 0] = speed*np.cos(np.pi*xyz[base, 1]/length)
        boundary = {'x0': ('traction',)*3, 'x1': ('traction',)*3,
                    'y0': ('traction', 'velocity', 'traction'), 'y1': ('traction', 'velocity', 'traction'),
                    'z0': ('velocity',)*3, 'z1': ('traction',)*3}
        eta = np.full(q.shape[:2], 1e21)
        blob = np.sum((q/length-[.5, .5, .5])**2, axis=-1) < .04
        force = np.zeros(q.shape)
        force[..., 2] = -10.*40.*blob
        changed = eta*(1+.1*np.sin(2*np.pi*q[..., 1]/length))
        return dict(cells=cells, lengths=lengths, eta=eta, changed_eta=changed, force=force,
                    velocity=velocity, boundary=boundary, scales=(length, speed),
                    reference_viscosity=1e21, mean_pressure=None, exact=None)
    raise ValueError('unknown case '+name)


IMPORT_BASELINE_BYTES = int(1.1*1024**3)   # measured post-import private commit (BLAS buffers)


def projected_candidate_bytes(cells, coarse_dofs=3000, restart=60):
    """The multigrid route's admission projection plus its factor allowance bound."""
    cells = np.asarray(cells)
    nc, nv, nq = int(np.prod(cells)), int(np.prod(2*cells+1)), int(np.prod(cells+1))
    structure = 12*1024**2+111*nv+20059*nq+1984*nc
    work = 56*1024**2+8*(3*nv+nq+1)*(2*restart+31)+37592*nc+730*nv
    coarse = min(coarse_dofs, 3*nq)
    factor = 1024**2+12*(min(coarse*coarse, int(288*(coarse/3)**(4/3)))+min(nq*nq, int(48*nq**(4/3))))
    return structure+work+factor


def projected_baseline_bytes(cells, method='gmres'):
    """The assembled route's own admission formula (assembly plus factor allowance).

    ``gmres``: the incomplete-factor allowance on the at-most-full velocity block.
    ``direct``: the dense-bound allowance 16 K^2 + 1024 K on the saddle-point size
    K (bounded above by all velocity and pressure unknowns plus the gauge row).
    """
    cells = np.asarray(cells)
    nc, nv, npr = int(np.prod(cells)), int(np.prod(2*cells+1)), int(np.prod(cells+1))
    assembly = 8*1024**2+420000*nc+3000*(3*nv+npr)
    if method == 'direct':
        size = 3*nv+npr+1
        return assembly+16*size*size+1024*size
    nnz = 9*int(np.prod(8*cells+1))
    return assembly+16*10*nnz+1024*3*nv


# --------------------------------------------------------------------------
# Child: one case/size/method in a fresh process
# --------------------------------------------------------------------------

def child(args):
    begin = perf_counter()
    sys.path.insert(0, str(Path(args.source_root).resolve()))
    import scipy
    from atlas_tectonics.regional_execution import RegionalMechanicsScales
    from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D, SIDES
    from atlas_tectonics.resources import WorkBudget
    imported = process_memory()
    try:
        from threadpoolctl import threadpool_info
        threads = [dict(api=i.get('internal_api'), threads=i.get('num_threads')) for i in threadpool_info()]
    except ImportError:
        threads = 'threadpoolctl unavailable'
    spec = case_inputs(args.case, args.cells)
    budget = WorkBudget(int(args.budget_gib*1024**3))
    scales = RegionalMechanicsScales(*spec['scales'])
    tractions = {side: 0. for side in SIDES}
    record = dict(case=args.case, n=args.cells, method=args.method, cells=list(spec['cells']),
                  lengths_m=list(spec['lengths']), runtime=dict(python=platform.python_version(),
                  numpy=np.__version__, scipy=scipy.__version__, system=platform.system(),
                  machine=platform.machine(), native_threads_at_import=threads,
                  thread_environment={k: os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS',
                                                                        'MKL_NUM_THREADS')},
                  solver_threads='one, under the package native lease'), import_seconds=perf_counter()-begin,
                  memory_after_import=imported, phases={})
    arrays = {}

    def prepare(eta, source):
        return PreparedRegionalStokes3D(spec['cells'], spec['lengths'], eta, spec['boundary'],
            scales=scales, reference_viscosity_pa_s=spec['reference_viscosity'],
            frame_id='benchmark-Cartesian', vertical_datum='box-bottom-z-zero',
            material_source=source, physical_mean_pressure_pa=spec['mean_pressure'],
            method=args.method, budget=budget)

    def chosen(plan):
        """Resolved method and selection record (older trees have neither)."""
        return dict(method=getattr(plan, 'method', args.method),
                    selection=plan.solver_selection() if hasattr(plan, 'solver_selection') else None)

    def solve(plan, amplitude, parent):
        start = perf_counter()
        result = plan.solve(amplitude*spec['force'], spec['velocity'], tractions,
            parent_state_id=parent, epoch_id='benchmark-instant', time_s=0.,
            force_source='benchmark-force', boundary_source='benchmark-boundary')
        seconds = perf_counter()-start
        d = result.descriptor()
        gates = {k: d[k] for k in ('linear_relative_residual', 'momentum_backward_error',
                                   'continuity_backward_error', 'work_relative_residual',
                                   'krylov_iterations', 'linear_refinements', 'weak_divergence_max')}
        return result, seconds, gates

    limit = int(args.max_private_gib*1024**3)

    def phase(name, **values):
        values['memory'] = process_memory()
        values['budget'] = budget.statistics()
        record['phases'][name] = values
        peak = values['memory'].get('peak_private_bytes', values['memory']['peak_working_set_bytes'])
        if peak > limit:
            record['status'] = 'stopped: peak private memory above --max-private-gib after '+name
            with open(Path(args.output).with_suffix('.json'), 'x', encoding='utf-8', newline='\n') as out:
                json.dump(record, out, indent=1, allow_nan=False, default=float)
            raise SystemExit(3)

    start = perf_counter()
    plan = prepare(spec['eta'], 'benchmark-original-viscosity')
    phase('cold_prepare', seconds=perf_counter()-start, statistics=plan.statistics(), **chosen(plan))
    result, seconds, gates = solve(plan, 1., 'first')
    arrays['first_velocity'] = result.array('velocity_m_s')
    arrays['first_pressure'] = result.array('relative_pressure_pa')
    record['physical_pressure_defined'] = result.descriptor()['physical_pressure_defined']
    phase('first_solve', seconds=seconds, gates=gates)
    warm = []
    for k in range(1, args.warm+1):
        result, seconds, gates = solve(plan, 1.+.01*k, 'warm-'+str(k))
        warm.append(dict(seconds=seconds, gates=gates))
    arrays['warm_velocity'] = result.array('velocity_m_s')
    phase('warm_solves', solves=warm, statistics=plan.statistics())
    reuse = hasattr(plan, 'with_viscosity')
    if reuse:
        # As the connected evolution does: release the old plan, reuse its geometry.
        start = perf_counter()
        rebuilt = plan.with_viscosity(spec['changed_eta'], material_source='benchmark-changed-viscosity',
                                      release=True)
        prepare_seconds = perf_counter()-start
        result, seconds, gates = solve(rebuilt, 1., 'rebuild-reuse')
        arrays['rebuild_reuse_velocity'] = result.array('velocity_m_s')
        phase('rebuild_with_reuse', prepare_seconds=prepare_seconds, solve_seconds=seconds, gates=gates,
              statistics=rebuilt.statistics(), **chosen(rebuilt))
        rebuilt.close()
    else:
        plan.close()
    # The connected evolution loop closes the old plan before preparing the new.
    start = perf_counter()
    cold = prepare(spec['changed_eta'], 'benchmark-changed-viscosity')
    prepare_seconds = perf_counter()-start
    result, seconds, gates = solve(cold, 1., 'rebuild-cold')
    arrays['rebuild_cold_velocity'] = result.array('velocity_m_s')
    arrays['rebuild_cold_pressure'] = result.array('relative_pressure_pa')
    phase('rebuild_cold', prepare_seconds=prepare_seconds, solve_seconds=seconds, gates=gates,
          statistics=cold.statistics(), **chosen(cold))
    cold.close()
    record['descriptor_method'] = result.descriptor()['plan']['method']
    record['plan_definition'] = {k: v for k, v in result.descriptor()['plan'].items()
                                 if k not in ('scales',)}
    record['total_seconds'] = perf_counter()-begin
    record['final_budget'] = budget.statistics()
    stem = Path(args.output)
    np.savez(stem.with_suffix('.npz'), **arrays)
    with open(stem.with_suffix('.json'), 'x', encoding='utf-8', newline='\n') as out:
        json.dump(record, out, indent=1, allow_nan=False, default=float)
        out.write('\n')


# --------------------------------------------------------------------------
# Parent: schedule children, compare outputs, summarise
# --------------------------------------------------------------------------

def _pressure_forward_error(reference, actual, *, physical_pressure_defined):
    """Compare the datum too, unless pressure is genuinely free up to a constant."""
    p0, p1 = np.asarray(reference), np.asarray(actual)
    if not physical_pressure_defined:
        p0, p1 = p0-np.mean(p0), p1-np.mean(p1)
    error = float(np.max(np.abs(p1-p0)))
    scale = float(np.max(np.abs(p0)))
    if scale == 0.:
        if error == 0.:
            return 0.
        raise ValueError('relative pressure error is undefined for a zero reference')
    return error/scale


def forward_error(args):
    """Forward error of gmres and multigrid against the direct oracle (small grids)."""
    sys.path.insert(0, str(Path(args.source_root).resolve()))
    from atlas_tectonics.regional_execution import RegionalMechanicsScales
    from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D, SIDES
    from atlas_tectonics.resources import WorkBudget
    rows = []
    for case, n in parse_cases(args.cases):
        spec = case_inputs(case, n)
        outputs = {}
        for method in ('direct', 'gmres', 'multigrid'):
            try:
                with PreparedRegionalStokes3D(spec['cells'], spec['lengths'], spec['eta'], spec['boundary'],
                        scales=RegionalMechanicsScales(*spec['scales']),
                        reference_viscosity_pa_s=spec['reference_viscosity'], frame_id='benchmark-Cartesian',
                        vertical_datum='box-bottom-z-zero', material_source='benchmark-original-viscosity',
                        physical_mean_pressure_pa=spec['mean_pressure'], method=method,
                        budget=WorkBudget(int(args.budget_gib*1024**3))) as plan:
                    start = perf_counter()
                    result = plan.solve(spec['force'], spec['velocity'], {side: 0. for side in SIDES},
                        parent_state_id='first', epoch_id='benchmark-instant', time_s=0.,
                        force_source='benchmark-force', boundary_source='benchmark-boundary')
                    d = result.descriptor()
                    outputs[method] = dict(u=result.array('velocity_m_s'), p=result.array('relative_pressure_pa'),
                        physical_pressure_defined=d['physical_pressure_defined'],
                        seconds=perf_counter()-start, iterations=d['krylov_iterations'],
                        refinements=d['linear_refinements'])
            except Exception as exc:
                outputs[method] = dict(refused=f'{type(exc).__name__}: {exc}')
        row = dict(case=case, n=n)
        oracle = outputs['direct']
        for method in ('gmres', 'multigrid'):
            out = outputs[method]
            if 'refused' in out or 'refused' in oracle:
                row[method] = dict(refused=out.get('refused', 'no direct oracle'))
                continue
            if out['physical_pressure_defined'] != oracle['physical_pressure_defined']:
                raise ValueError('candidate and oracle disagree on pressure datum')
            row[method] = dict(velocity_error=float(np.max(np.abs(out['u']-oracle['u']))/np.max(np.abs(oracle['u']))),
                               pressure_error=_pressure_forward_error(oracle['p'], out['p'],
                                   physical_pressure_defined=oracle['physical_pressure_defined']),
                               pressure_comparison=('datum_preserved' if oracle['physical_pressure_defined']
                                                    else 'constant_removed'),
                               iterations=out['iterations'], refinements=out['refinements'],
                               seconds=out['seconds'])
        rows.append(row)
        print(json.dumps(row), flush=True)
    with open(args.forward_error, 'x', encoding='utf-8', newline='\n') as out:
        json.dump(dict(schema='atlas.regional3d-forward-error.v2', scientific_acceptance=False,
                       note='pressure datum preserved when physically defined by traction or a supplied mean; '
                            'otherwise compared up to a constant; errors relative to the direct oracle',
                       harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       rows=rows), out, indent=1, allow_nan=False)
        out.write('\n')
    return 0


def decisions(args):
    """The automatic selection for each case and reuse, without preparing or solving.

    Selection time is the best of three complete ``_selection`` calls (features,
    both admission predictions and the rule) against a fresh ``--budget-gib``.
    """
    sys.path.insert(0, str(Path(args.source_root).resolve()))
    from atlas_tectonics import regional_execution3d as execution3d
    from atlas_tectonics.regional_execution import RegionalMechanicsScales
    rows = []
    available = int(args.budget_gib*1024**3)
    for case, n in parse_cases(args.cases):
        spec = case_inputs(case, n)
        cells = tuple(spec['cells'])
        eta = np.broadcast_to(np.asarray(spec['eta'], dtype=float), (int(np.prod(cells)), 27))
        pattern = {k: tuple(v) for k, v in spec['boundary'].items()}
        times = []
        for _ in range(3):
            start = perf_counter()
            record = execution3d._selection(cells, tuple(float(x) for x in spec['lengths']),
                RegionalMechanicsScales(*spec['scales']), pattern, eta, available)
            times.append(perf_counter()-start)
        rows.append(dict(case=case, n=n, seconds=min(times), selection=record))
        print(json.dumps(dict(case=case, n=n, method=record['method'], reason=record['reason'],
                              seconds=round(min(times), 5))), flush=True)
    with open(args.decisions, 'x', encoding='utf-8', newline='\n') as out:
        json.dump(dict(schema='atlas.regional3d-solver-decisions.v1', scientific_acceptance=False,
                       budget_bytes=available, rows=rows,
                       harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),
                  out, indent=1, allow_nan=False)
        out.write('\n')
    return 0


def parse_cases(text):
    cases = []
    for item in text.split(';'):
        name, sizes = item.split(':')
        cases += [(name, int(n)) for n in sizes.split(',')]
    return cases


def compare(directory, runs):
    """Cross-method differences on identical inputs, relative to the velocity scale."""
    by_key = {}
    for run in runs:
        if run.get('status') == 'completed':
            by_key.setdefault((run['case'], run['n']), {})[run['method']] = run
    comparisons = []
    for (case, n), methods in sorted(by_key.items()):
        names = sorted(methods)
        loaded = {m: np.load(directory/(methods[m]['stem']+'.npz')) for m in names}
        for i, a in enumerate(names):
            for b in names[i+1:]:
                entry = dict(case=case, n=n, methods=[a, b])
                for key in ('first_velocity', 'warm_velocity', 'rebuild_cold_velocity'):
                    ua, ub = loaded[a][key], loaded[b][key]
                    scale = max(float(np.max(np.abs(ua))), float(np.max(np.abs(ub))))
                    entry[key+'_relative_difference'] = float(np.max(np.abs(ua-ub))/scale)
                pa, pb = loaded[a]['first_pressure'], loaded[b]['first_pressure']
                defined = {methods[m]['record'].get('physical_pressure_defined') for m in (a, b)}
                if len(defined) != 1:
                    raise ValueError('methods disagree on the pressure datum')
                defined = defined.pop()
                if defined is None:                 # records without the flag: the closed, datum-free cases
                    defined = case not in ('inclusion', 'blobs')
                # Only a genuinely undetermined gauge is compared up to a constant.
                key = ('first_pressure_relative_difference' if defined
                       else 'first_pressure_minus_mean_relative_difference')
                entry[key] = _pressure_forward_error(pa, pb, physical_pressure_defined=defined)
                comparisons.append(entry)
        for m in names:
            if 'rebuild_reuse_velocity' in loaded[m].files:
                ua, ub = loaded[m]['rebuild_reuse_velocity'], loaded[m]['rebuild_cold_velocity']
                comparisons.append(dict(case=case, n=n, methods=[m+':reuse', m+':cold'],
                    rebuild_relative_difference=float(np.max(np.abs(ua-ub))/np.max(np.abs(ub)))))
    return comparisons


def parent(args):
    directory = Path(args.output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    source = Path(args.source_root).resolve()
    digest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted((source/'atlas_tectonics').glob('regional_*3d.py'))}
    runs = []
    for case, n in parse_cases(args.cases):
        for method in args.methods.split(','):
            stem = f'{case}-{n}-{method}'
            entry = dict(case=case, n=n, method=method, stem=stem)
            cells = case_inputs(case, n)['cells']
            projected = projected_baseline_bytes(cells, method)
            entry['projected_assembled_reservation_bytes'] = projected
            own = dict(gmres=projected, direct=projected, multigrid=projected_candidate_bytes(cells),
                       auto=max(projected, projected_candidate_bytes(cells)))
            forecast = IMPORT_BASELINE_BYTES+own[method]
            entry['forecast_peak_private_bytes'] = forecast
            entry['limits'] = dict(max_private_gib=args.max_private_gib, timeout_seconds=args.timeout, warm=args.warm)
            # auto may resolve to the assembled route (e.g. for a changed viscosity).
            if method in ('gmres', 'direct', 'auto') and projected > args.max_projected_gib*1024**3:
                entry['status'] = 'skipped: projected assembled reservation above --max-projected-gib'
            elif forecast > args.max_private_gib*1024**3:
                entry['status'] = 'skipped: forecast peak private memory above --max-private-gib'
            if 'status' in entry:
                runs.append(entry)
                print(json.dumps(entry), flush=True)
                continue
            command = [sys.executable, '-B', str(Path(__file__).resolve()), '--child',
                       '--source-root', str(source), '--case', case, '--cells', str(n),
                       '--method', method, '--warm', str(args.warm), '--budget-gib', str(args.budget_gib),
                       '--max-private-gib', str(args.max_private_gib),
                       '--output', str(directory/stem)]
            start = perf_counter()
            try:
                done = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout)
            except subprocess.TimeoutExpired:
                entry['status'] = 'timeout'
            else:
                entry['returncode'] = done.returncode
                entry['status'] = 'completed' if done.returncode == 0 else 'failed'
                if done.returncode != 0:
                    entry['stderr_tail'] = done.stderr[-4000:]
            entry['wall_seconds'] = perf_counter()-start
            if entry['status'] == 'completed':
                with open(directory/(stem+'.json'), encoding='utf-8') as handle:
                    entry['record'] = json.load(handle)
            elif (directory/(stem+'.json')).exists():
                # A declared-limit stop writes its partial record and reason.
                with open(directory/(stem+'.json'), encoding='utf-8') as handle:
                    entry['record'] = json.load(handle)
                entry['status'] = entry['record'].get('status', entry['status'])
            runs.append(entry)
            print(json.dumps({k: entry[k] for k in ('case', 'n', 'method', 'status', 'wall_seconds')}), flush=True)
    summary = dict(schema='atlas.regional3d-solver-benchmark.v1', scientific_acceptance=False,
                   source_root=str(source), regional3d_source_sha256=digest,
                   harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   host=dict(system=platform.system(), machine=platform.machine(),
                             processor=platform.processor(), cpu_count=os.cpu_count()),
                   runs=runs, comparisons=compare(directory, runs))
    with open(directory/'summary.json', 'x', encoding='utf-8', newline='\n') as out:
        json.dump(summary, out, indent=1, allow_nan=False, default=float)
        out.write('\n')
    return 0 if all(r['status'] == 'completed' or r['status'].startswith(('skipped', 'stopped')) for r in runs) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source-root', required=True, help='directory containing atlas_tectonics')
    parser.add_argument('--output-dir', help='new directory for the parent run')
    parser.add_argument('--cases', default='inclusion:4;lithosphere:4;smooth:4')
    parser.add_argument('--methods', default='gmres,multigrid')
    parser.add_argument('--warm', type=int, default=3)
    parser.add_argument('--budget-gib', type=float, default=64.)
    parser.add_argument('--max-projected-gib', type=float, default=8.)
    parser.add_argument('--timeout', type=float, default=900., help='elapsed-seconds limit per case')
    parser.add_argument('--max-private-gib', type=float, default=4., help='peak private memory limit per case')
    parser.add_argument('--forward-error', help='new JSON path: compare gmres and multigrid with direct')
    parser.add_argument('--decisions', help='new JSON path: automatic selections only (nothing prepared or solved)')
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--case')
    parser.add_argument('--cells', type=int)
    parser.add_argument('--method')
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.child:
        child(args)
        return 0
    if args.forward_error:
        return forward_error(args)
    if args.decisions:
        return decisions(args)
    if not args.output_dir:
        parser.error('--output-dir is required')
    return parent(args)


if __name__ == '__main__':
    raise SystemExit(main())
