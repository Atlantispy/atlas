"""Declared invariant volume supports for the W01-to-W02 regional workflow.

Planar strips have fixed transverse width and no transverse/vertical relative
flow. Spherical supports are complete northern/southern hemisphere longitude
wedges about the section pole, bounded by actual minor great-circle arcs. Axial
Euler motion preserves their transverse support. Their area is R*ds, and their
S5 shell volume is normalised by ds*reference_width_m by the workflow, never by
raw radial thickness. North/south refer to the declared pole, not world axes.

These are initial query supports, not evolved geological geometry. Geometry
conditioning failures are refusals; no clipping, snapping or owner averaging.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import numpy as np

from atlas_tectonics._validation import scalar
from atlas_tectonics.history.geological_case import _check_geometry_frame
from atlas_tectonics.history.geological_records import GeologySource
from atlas_tectonics.planet.geometry import GeometryLimits, PlanarGeometry, _check_cancel
from atlas_tectonics.kinematics import _unit
from atlas_tectonics.crust.precursor import InitialConditionState
from atlas_tectonics.crust.precursor_sampling import InitialSamplingCell, PrecursorSamplingLimits, _provably_disjoint
from atlas_tectonics.regional.forcing import (MotionReductionError, RegionalFaceForcing, SphericalRegionalSection)
from atlas_tectonics.integration.resources import select_budget
from atlas_tectonics.planet.spherical_atlas import SphericalAtlas
from atlas_tectonics.planet.spherical_geometry import SphericalChart, SphericalGeometry


@dataclass(frozen=True, slots=True)
class RegionalColumnSupport:
    """Authored common depth band and invariant transverse support.

    Depth is the initial case's named inward depth reference. The caller supplies
    the source and both depths; neither geology nor physical values come from IDs.
    The spherical reference width is a fixed metric normalisation, not the
    hemisphere's meridional arc length or an invented finite latitude strip.
    """
    kind: str
    top_depth_m: float
    bottom_depth_m: float
    source: GeologySource

    def __post_init__(self):
        top = scalar(self.top_depth_m, 'support top depth', nonnegative=True)
        bottom = scalar(self.bottom_depth_m, 'support bottom depth', positive=True)
        object.__setattr__(self, 'top_depth_m', top)
        object.__setattr__(self, 'bottom_depth_m', bottom)

    def descriptor(self):
        return asdict(self)


def _relative_motion(motion, section):
    """Use S6's affine coefficients, without inventing a new tolerance/law."""
    omega = np.asarray(motion.angular_velocity_rad_s)
    delta = omega - np.asarray(section.frame_angular_velocity_rad_s)
    if type(section) is SphericalRegionalSection:
        return tuple(delta)
    shift = np.asarray(section.origin_m) - np.asarray(motion.pivot_m)
    cross = np.cross(omega, shift)
    base = tuple(math.fsum((motion.translation_m_s[j], float(cross[j]),
                           -section.frame_velocity_m_s[j])) for j in range(3))
    return (*base, *delta)


def _incompatible_regions(forcing):
    topology = forcing.definition.topology
    samples = forcing.samples
    first = int(samples.selected_rows[0])
    if first < 0:
        first = 0  # S6 certified exactly equal sided face speeds in this case.
    region_id = samples.region_ids[int(samples.owner_pairs[first, 1])]
    owners = ({p.region_id: p.plate_id for p in topology.patches}
              if type(topology) is SphericalAtlas else
              {r.region_id: r.plate_id for r in topology.regions})
    motions = {m.plate_id: _relative_motion(m, forcing.section)
               for m in forcing.definition.motions}
    reference = motions[owners[region_id]]
    # Full coefficient equality is intentionally stronger than equality at one
    # point. A distinct small residual cannot silently become a common field.
    return tuple(r for r in topology.regions if motions[r.plate_id] != reference)


def build_workflow_cells(initial: InitialConditionState, forcing: RegionalFaceForcing,
                         support: RegionalColumnSupport, *, budget=None,
                         cancel=None) -> tuple[InitialSamplingCell, ...]:
    """Build exactly one whole-volume S5 query for each uniform S6 column.

    Requires an already accepted S6 forcing object; no face-only shortcut is
    available here. All footprint material must share its section's complete
    reduced relative motion. For a regional topology, the entire footprint must
    be covered. A validated spherical atlas already covers the whole sphere.
    Work and native allocation admission use existing finite geometry/sampling
    envelopes. Returned immutable supports become caller-owned retained data.
    """
    _check_cancel(cancel)
    case = initial.case
    section = forcing.section
    definition = forcing.definition
    grid = forcing.grid
    spherical = type(section) is SphericalRegionalSection
    if spherical and support.bottom_depth_m >= section.sphere.radius_m:
        raise MotionReductionError('spherical support must remain outside the centre')
    limits = GeometryLimits()
    PrecursorSamplingLimits()
    policy = select_budget(budget)
    # Includes retained output geometry, coefficient maps and loop scratch. Each
    # native construction/overlay additionally admits its own transient workspace.
    allowance = (16384 * grid.cells + 4096 * len(definition.motions)
                 + 256 * len(definition.topology.regions) + 65536)
    with policy.reserve(allowance, category='workflow-cell-geometry'):
        incompatible = _incompatible_regions(forcing)
        offsets = forcing.samples.offsets_m
        if spherical:
            radial = _unit(np.asarray(section.start_direction))
            pole = _unit(np.asarray(section.pole_direction))
            tangent = _unit(np.cross(pole, radial))
            angles = offsets / section.sphere.radius_m
            vertices = np.cos(angles)[:, None] * radial + np.sin(angles)[:, None] * tangent
            cap = pole if support.kind == 'north-hemisphere' else -pole
        else:
            direction = _unit(np.asarray(section.direction_xy))
            transverse = np.array((-direction[1], direction[0]))
            vertices = np.asarray(section.origin_m[:2]) + offsets[:, None] * direction
            half_width = forcing.reduction.reference_width_m / 2
        cells = []
        for i in range(grid.cells):
            _check_cancel(cancel)
            a, b = vertices[i], vertices[i + 1]
            if spherical:
                chart = SphericalChart(section.sphere, tuple(a + b + cap))
                footprint = SphericalGeometry.polygon((a, b, cap), chart=chart,
                                                       limits=limits, budget=policy)
            else:
                width = half_width * transverse
                footprint = PlanarGeometry.polygon((a-width, b-width, b+width, a+width),
                    frame_id=section.frame_id, limits=limits, budget=policy)
            _check_geometry_frame(case.topology, footprint, limits, policy)
            for region in incompatible:
                _check_cancel(cancel)
                if _provably_disjoint(footprint, region.geometry):
                    continue
                common = footprint.overlay(region.geometry, 'intersection', limits=limits,
                                           budget=policy, cancel=cancel)
                if common.area_m2 > 0:
                    raise MotionReductionError('whole column footprint has incompatible owner motion')
            cells.append(InitialSamplingCell('workflow-column-'+str(i), footprint,
                support.top_depth_m, support.bottom_depth_m))
        _check_cancel(cancel)
        return tuple(cells)
