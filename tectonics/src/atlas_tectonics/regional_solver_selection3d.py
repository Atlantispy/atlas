"""Multigrid-first choice between the matrix-free and assembled 3D Stokes solvers.

SPDX-License-Identifier: AGPL-3.0-only

``method='auto'`` of ``regional_execution3d.PreparedRegionalStokes3D`` calls
``select`` once for each prepared operator. Nothing here solves, times or
caches: the choice is a deterministic function of the workload and the admitted
memory. It only decides which existing method prepares the plan; that method's
equations, tolerances, gates, cancellation and resource safeguards are unchanged.

Rule (policy v2), in order:

1. Admission. Each method's complete reservation is predicted with the formulas
   the method itself reserves with, and compared with the budget's available
   bytes. If neither fits, the plan is refused. If only one fits, it is chosen.
2. Multigrid whenever the workload lies inside the range where the matrix-free
   method has been shown to meet every gate at least as reliably as the
   assembled route: at least ``MIN_AXIS_CELLS`` cells along every axis, and
   either brick aspect at most ``MAX_ELEMENT_ASPECT`` with viscosity contrast at
   most ``10**MAX_LOG10_CONTRAST``, or aspect at most ``FLAT_ELEMENT_ASPECT``
   with contrast at most ``10**FLAT_LOG10_CONTRAST``.
3. Otherwise the assembled ``gmres`` route.

Why multigrid first: on the 29 measured workloads (4^3-16x16x8, contrasts 1 to
1e4, closed and open boxes, held-out structures included) multigrid was faster
or within 3% in 27 and always met the gates; always choosing it took 177.8 s
against 177.5 s for the faster method of each workload and 752.8 s for gmres.
A probe of the range's edges set the limits: at contrast 1e5 multigrid never
failed where gmres succeeded (a layered case only multigrid solved), and 4:1
bricks with contrast up to 1e3 ran 1.8-7 times faster; at 1e6 each method fails
cases the other solves, and at 8:1 and 20:1 multigrid slows. The assembled route
stays outside that range, for boxes too thin to coarsen, and as the explicit
reference.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from . import regional_multigrid3d as multigrid3d

_LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SIDES = ('x0', 'x1', 'y0', 'y1', 'z0', 'z1')
POLICY = 'atlas.regional3d-solver-selection.v2'
MAX_LOG10_CONTRAST = 5.
MAX_ELEMENT_ASPECT = 2.
FLAT_ELEMENT_ASPECT = 4.
FLAT_LOG10_CONTRAST = 3.
MIN_AXIS_CELLS = 4
_TOLERANCE = 1e-9


def _round(x):
    return float(round(float(x), 6))


def workload_features(cells, spacing, viscosity, pattern):
    """Deterministic workload features (rounded as recorded).

    ``viscosity`` is the validated positive (cells, 27) quadrature field.
    """
    cells = tuple(int(n) for n in cells)
    log = np.log10(viscosity)
    spacing = np.asarray(spacing, dtype=float)
    return dict(cells=list(cells), cell_count=int(np.prod(cells)), min_axis_cells=min(cells),
                element_aspect=_round(np.max(spacing)/np.min(spacing)),
                log10_viscosity_contrast=_round(np.max(log)-np.min(log)),
                closed_box=all(pattern[side]['xyz'.index(side[0])] == 'velocity' for side in SIDES),
                traction_components=sum(kind == 'traction' for side in SIDES for kind in pattern[side]))


def _free_masks(shape, pattern):
    masks = [np.ones(shape, dtype=bool) for _ in range(3)]
    for side in SIDES:
        axis = 'xyz'.index(side[0])
        index = [slice(None)]*3
        index[axis] = 0 if side[1] == '0' else shape[axis]-1
        for component, kind in enumerate(pattern[side]):
            if kind == 'velocity':
                masks[component][tuple(index)] = False
    return masks


def assembled_free_nonzeros(cells, pattern):
    """Stored entries and order of the assembled free-free Q2 velocity block.

    The assembled pattern couples two nodes when they share a brick: along each
    axis a vertex node reaches two nodes either side, a mid-edge node one. The
    count therefore factorises by axis, with every component pair coupled, and
    includes the explicitly stored zeros the assembly keeps.
    """
    shape = tuple(2*int(n)+1 for n in cells)
    free = sum(m.astype(np.int64) for m in _free_masks(shape, pattern))
    reach = free.astype(float)
    for axis, n in enumerate(shape):
        index = np.arange(n)
        width = np.where(index % 2 == 0, 2, 1)
        coupling = (np.abs(index[:, None]-index[None, :]) <= width[:, None]).astype(float)
        reach = np.moveaxis(np.tensordot(coupling, np.moveaxis(reach, axis, 0), axes=1), 0, axis)
    return int(round(float(np.sum(free*reach)))), int(np.sum(free))


def multigrid_bytes(cells, spacing, pattern):
    """The multigrid plan's complete reservation (structure, work and factor allowance).

    ``spacing`` must be the scaled brick spacing the mesh uses; the nested levels
    follow ``regional_multigrid3d.StructuredGeometry`` without building transfers.
    """
    cells = tuple(int(n) for n in cells)
    projected = multigrid3d.projected_bytes(cells)
    coords = [np.arange(n+1)*h for n, h in zip(cells, np.asarray(spacing, dtype=float))]
    shape = tuple(n+1 for n in cells)
    free = int(np.count_nonzero(~multigrid3d._node_mask(shape, pattern)))
    fine = free
    levels = 0
    while free > multigrid3d.SETTINGS['coarse_dofs']:
        widths = [float(np.max(np.diff(c))) if len(c) > 1 else np.inf for c in coords]
        smallest = min(widths)
        keeps = []
        for axis in range(3):
            n = len(coords[axis])-1
            if n >= 2 and widths[axis] < 2*smallest*(1-1e-12):
                keeps.append(multigrid3d._coarse_line(coords[axis])[0])
            else:
                keeps.append(np.arange(n+1))
        coarse_shape = tuple(len(k) for k in keeps)
        if coarse_shape == shape:
            break
        coarse = int(np.count_nonzero(~multigrid3d._node_mask(coarse_shape, pattern)))
        if coarse == 0:
            break
        levels += 1
        shape, free = coarse_shape, coarse
        coords = [c[k] for c, k in zip(coords, keeps)]
    geometry = SimpleNamespace(levels=[dict(free=range(free))] if levels else [], free1=range(fine),
                               np=int(np.prod(np.asarray(cells)+1)))
    return projected['structure']+projected['work']+multigrid3d.factor_allowance(geometry)


def unsupported(features):
    """Reasons the workload lies outside multigrid's shown range (empty inside it)."""
    reasons = []
    contrast, aspect = features['log10_viscosity_contrast'], features['element_aspect']
    if contrast > MAX_LOG10_CONTRAST+_TOLERANCE:
        reasons.append('viscosity contrast above 1e%g' % MAX_LOG10_CONTRAST)
    if aspect > FLAT_ELEMENT_ASPECT+_TOLERANCE:
        reasons.append('element aspect ratio above %g' % FLAT_ELEMENT_ASPECT)
    elif aspect > MAX_ELEMENT_ASPECT+_TOLERANCE and contrast > FLAT_LOG10_CONTRAST+_TOLERANCE:
        reasons.append('element aspect ratio above %g with viscosity contrast above 1e%g'
                       % (MAX_ELEMENT_ASPECT, FLAT_LOG10_CONTRAST))
    if features['min_axis_cells'] < MIN_AXIS_CELLS:
        reasons.append('fewer than %d cells along an axis' % MIN_AXIS_CELLS)
    return reasons


def select(features, needs, available_bytes):
    """Resolve ``auto`` to ``multigrid`` or ``gmres``; ``method`` is None when neither is admitted.

    ``needs`` maps each method to its complete predicted reservation in bytes.
    The returned record is deterministic in its arguments and is stored in the
    plan definition; the available byte count itself is not recorded there.
    """
    admitted = {m: int(needs[m]) <= available_bytes for m in ('gmres', 'multigrid')}
    outside = unsupported(features)
    record = dict(policy=POLICY, requested='auto', features=dict(features),
                  admission={m: dict(bytes=int(needs[m]), admitted=admitted[m]) for m in admitted},
                  multigrid_supported=not outside, unsupported=outside)
    if not any(admitted.values()):
        record.update(method=None, reason='neither method is admitted by the budget')
    elif not admitted['multigrid']:
        record.update(method='gmres', reason='only gmres is admitted by the budget')
    elif not admitted['gmres']:
        record.update(method='multigrid', reason='only multigrid is admitted by the budget'
                      + ('' if not outside else '; outside its shown range'))
    elif outside:
        record.update(method='gmres', reason='outside the range where multigrid has been shown to converge')
    else:
        record.update(method='multigrid', reason='inside the range where multigrid has been shown to converge')
    return record
