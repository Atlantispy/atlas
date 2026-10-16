"""W08 dry fixed-base shortening loads and one continuous elastic response.

Conservative moving parcels are projected onto an explicit fixed uniform grid.
This is a derived total-reference view, not a W03 workflow or a buckling law.
Transported enthalpy does not silently become a temperature/density anomaly.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import numpy as np

from ._validation import TectonicsError, input_shape, read_array, scalar, text
from .column_loads import LoadPhase, LoadSupport, ColumnLoadState, column_load_change
from .extension import _within_budget
from .extension_support import ContinuousCellMeanFlexure
from .finite_flexure import FiniteRegionFlexure, FlexureBoundary1D
from .materials import _json
from .mesh import ColumnGrid1D
from .parameters import FlexureParameters
from .regional import RegionalGrid1D, _cancelled
from .resources import select_budget
from .shortening import PreparedShortening, _overlaps
from .stokes_execution import _factored_scale


@dataclass(frozen=True, slots=True)
class ShorteningSupportPolicy:
    """Caller-supplied dry mantle restoring density and response validity caps.

    Density contrast in the elastic parameters is exactly mantle density for
    this dry branch. Water/fill feedback needs a separately identified closure.
    """
    elastic: FlexureParameters
    mantle_density_kg_m3: float
    max_abs_displacement_m: float
    max_abs_slope: float
    max_bending_strain: float
    source_id: str

    def __post_init__(self):
        if type(self.elastic) is not FlexureParameters:
            raise TectonicsError('explicit elastic parameters required')
        text(self.source_id, 'shortening support policy source')
        for name in ('mantle_density_kg_m3', 'max_abs_displacement_m',
                     'max_abs_slope', 'max_bending_strain'):
            object.__setattr__(self, name, scalar(getattr(self, name), name, positive=True))
        if self.elastic.density_contrast_kg_m3 != self.mantle_density_kg_m3:
            raise TectonicsError('dry restoring density must equal the explicit mantle density')
        if self.max_abs_slope >= 1 or self.max_bending_strain >= 1:
            raise TectonicsError('small-slope and bending-strain limits must be below one')


@dataclass(frozen=True, slots=True, init=False)
class ShorteningSupportResult:
    """Immutable load/response means; elevations are changes from the reference.

    cell_means columns: q (Pa), w downward (m), unflexed thickness change (m),
    surface change (m), base change (m), reference/current total thickness (m).
    phase_load_pa is (cohorts, target cells), in the original cohort order.
    Output retained beyond a call belongs to the caller's memory allowance.
    """
    result_id: str
    _metadata: bytes
    _fields: bytes
    _points: bytes
    _phase_loads: bytes

    def descriptor(self):
        return json.loads(self._metadata)

    @property
    def cell_means(self):
        return np.frombuffer(self._fields, dtype=np.float64).reshape(-1, 7)

    @property
    def face_centre_response(self):
        """Rows face, centre, face...; columns w, w', w'', w''' (point values)."""
        return np.frombuffer(self._points, dtype=np.float64).reshape(-1, 4)

    @property
    def phase_load_pa(self):
        return np.frombuffer(self._phase_loads, dtype=np.float64).reshape(-1, len(self._fields)//56)


def _continuous_envelopes(operator, pressure, points):
    """Cover unsampled response extrema between every face/centre pair.

    Whole-line Green derivative L1 bounds applied to max|q| bound the next
    derivative. The nearest sample is at most one quarter cell width away.
    Omitted exterior load is exactly zero, guarded before this calculation.
    """
    scale = scalar(float(np.max(np.abs(pressure)))/operator.parameters.restoring_pa_per_m,
                   'hydrostatic displacement scale', nonnegative=True)
    bound = math.sqrt(2.)*scale
    result = []
    for d in range(3):
        bound = scalar(bound/operator.alpha_m*math.sqrt(2.),
                       'response derivative envelope', nonnegative=True)
        result.append(scalar(float(np.max(np.abs(points[:, d])))+
            operator.grid.spacing_m/4*bound, 'continuous response envelope', nonnegative=True))
    return tuple(result)


class PreparedShorteningSupport:
    """Borrowed motion and reusable fixed-reference load/elastic preparation.

    Both reference and requested occupied material must fit the target grid and
    the explicitly finite vertical support. Exterior parcels remain owned by
    motion; this first support branch refuses nonzero omitted exterior volume.
    Replacement density must be an explicit per-column zero vector (dry air).
    Motion stays in its unflexed fixed-base frame. No Airy term is added to w.
    """
    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise AttributeError('prepared shortening support is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, motion, target_grid, policy, *, support_height_m,
                 replacement_density_kg_m3, geometry_source, budget=None, cancel=None):
        _cancelled(cancel)
        if type(motion) is not PreparedShortening or type(policy) is not ShorteningSupportPolicy:
            raise TectonicsError('typed prepared shortening and support policy required')
        motion._check(motion.initial)
        if type(target_grid) is not ColumnGrid1D:
            raise TectonicsError('explicit fixed ColumnGrid1D load target required')
        if target_grid.frame_id != motion.initial.material.grid.frame_id:
            raise TectonicsError('load and material coordinate frame must agree')
        text(geometry_source, 'finite load support geometry source')
        n, c = target_grid.cells, len(motion.initial.material.cohorts)
        if input_shape(support_height_m) != (n,) or input_shape(replacement_density_kg_m3) != (n,):
            raise TectonicsError('explicit per-column finite height and replacement density required')
        self.motion, self.grid, self.policy = motion, target_grid, policy
        self._budget = motion._budget if budget is None else select_budget(budget)
        _within_budget(self._budget, motion._budget)
        self._stack = ExitStack()
        self._closed = False
        try:
            # Retains the reference projection/load and FFT operators. Transient
            # project work is additionally charged to the shared motion ancestor.
            self._stack.enter_context(self._budget.reserve(4096*n+128*c*n+32768,
                                                          category='shortening-support-retained'))
            edges = target_grid.edges_m
            regional = RegionalGrid1D(n, float(edges[-1]-edges[0]), float(edges[0]))
            expected = np.linspace(edges[0], edges[-1], n+1)
            if (np.any(np.abs(edges-expected) > 1e-12*regional.spacing_m) or
                    np.any(np.abs(target_grid.widths_m-regional.spacing_m) > 1e-12*regional.spacing_m)):
                raise TectonicsError('uniform fixed load grid required')
            fill = read_array(replacement_density_kg_m3, 'dry replacement density', nonnegative=True)
            if fill.shape != (n,) or np.any(fill != 0):
                raise TectonicsError('dry support requires explicit zero replacement density')
            self._fill = fill.tobytes()
            with np.errstate(over='raise', invalid='raise', under='ignore'):
                area = target_grid.widths_m*motion.width_m
            self.support = LoadSupport(tuple(str(i) for i in range(n)), area, support_height_m,
                geometry_source=geometry_source, frame_id=target_grid.frame_id,
                datum_id=motion.datum_id, budget=self._budget)
            self.phases = tuple(LoadPhase(cohort.cohort_id, 'rock', float(density), motion.plan_id)
                for cohort, density in zip(motion.initial.material.cohorts, motion.density_kg_m3))
            self._projection_source = hashlib.sha256(_json(dict(method='w08-support-projection-v1',
                motion=motion.plan_id, grid=target_grid.grid_id, support=self.support.support_id))).hexdigest()
            self._reference_projection = self._project(motion.initial, cancel)
            self._reference_load = self._load(self._reference_projection, motion.initial, cancel)
            self._reference_h = self._reference_projection.material.total_thickness(
                backend='reference', budget=self._budget).tobytes()
            self.operator = FiniteRegionFlexure(regional, policy.elastic,
                FlexureBoundary1D('continuous', 'continuous', policy.source_id), budget=self._budget)
            self.mean_operator = ContinuousCellMeanFlexure(self.operator, budget=self._budget)
            self.plan_id = hashlib.sha256(_json(dict(method='w08-dry-fixed-base-support-v1',
                motion=motion.plan_id, policy=asdict(policy), reference=self._reference_load.state_id,
                projection=self._reference_projection.projection_id, operator=self.operator.operator_id,
                mean_operator=self.mean_operator.operator_id, execution=motion.execution_id))).hexdigest()
            _cancelled(cancel)
            motion._context.verify()
            self._sealed = True
        except (FloatingPointError, OverflowError) as exc:
            self._stack.close()
            raise TectonicsError('shortening support preparation outside numerical range') from exc
        except BaseException:
            self._stack.close()
            raise

    def _project(self, state, cancel):
        projection = self.motion.project(state, self.grid,
            exterior_ids=('shortening-support-left', 'shortening-support-right'),
            source_id=self._projection_source, cancel=cancel)
        if np.any(projection.outside_volume_m3 != 0):
            raise TectonicsError('occupied footprint extends into omitted exterior; enlarge fixed load grid')
        # A finite vertical support contains each physical parcel interior,
        # not just its diluted target-cell mean volume. Sparse intersections
        # cover every positive-width source/target overlap, including parcels
        # narrower than a cell and portions which miss the target centre.
        ns, nt = state.material.grid.cells, self.grid.cells
        with self._budget.reserve(160*(ns+nt)+8192, category='shortening-support-coverage'):
            heights = state.material.total_thickness(backend='reference', budget=self._budget)
            donor, target, _ = _overlaps(state.material.grid.edges_m, self.grid.edges_m)
            if np.any(heights[donor] > self.support.height_m[target]):
                raise TectonicsError('parcel interior exceeds the finite support height')
            _cancelled(cancel)
        return projection

    def _load(self, projection, state, cancel):
        return ColumnLoadState(self.support, self.phases, projection.volume_m3.T,
            np.frombuffer(self._fill, dtype=np.float64), source_id=projection.projection_id,
            epoch_id=hashlib.sha256(_json(dict(epoch=state.material.epoch_id,
                                              time_s=state.material.time_s))).hexdigest(),
            budget=self._budget, cancel=cancel)

    def solve(self, state, *, cancel=None):
        if self._closed:
            raise TectonicsError('shortening support preparation is closed')
        _cancelled(cancel)
        n, c = self.grid.cells, len(self.phases)
        with self._budget.reserve(1536*n+128*c*n+32768, category='shortening-support-output'):
            # project authenticates state and live source on entry/publication.
            projection = self._project(state, cancel)
            current = self._load(projection, state, cancel)
            loads = column_load_change(self._reference_load, current,
                self.policy.elastic.gravity_m_s2, budget=self._budget, cancel=cancel)
            pressure = loads[:, 3]
            try:
                with np.errstate(over='raise', invalid='raise', divide='raise', under='ignore'):
                    delta_volume = projection.volume_m3-self._reference_projection.volume_m3
                    dh = delta_volume/self.support.area_m2
                    if np.any((delta_volume != 0) & (dh == 0)):
                        raise TectonicsError('cohort thickness change underflows')
                    kinematic = np.array([math.fsum(column) for column in dh.T])
                    phase_loads = np.empty_like(dh)
                    for j, phase in enumerate(self.phases):
                        phase_loads[j] = _factored_scale(dh[j], (phase.density_kg_m3,
                            self.policy.elastic.gravity_m_s2), (), 'cohort downward load')
                    points = self.operator.solve(np.r_[pressure, 0., 0.], budget=self._budget)
                    _cancelled(cancel)
                    means = self.mean_operator.solve(pressure, budget=self._budget)
                    valid = _continuous_envelopes(self.operator, pressure, points)
                    strain = scalar(self.policy.elastic.elastic_thickness_m/2*valid[2],
                                    'bending strain', nonnegative=True)
                    if (valid[0] > self.policy.max_abs_displacement_m or
                            valid[1] > self.policy.max_abs_slope or strain > self.policy.max_bending_strain):
                        raise TectonicsError('dry support displacement/slope/bending-strain envelope exceeded')
                    current_h = projection.material.total_thickness(backend='reference', budget=self._budget)
                    values = np.column_stack((pressure, means, kinematic, kinematic-means, -means,
                        np.frombuffer(self._reference_h, dtype=np.float64), current_h))
            except (FloatingPointError, OverflowError) as exc:
                raise TectonicsError('shortening load/support arithmetic outside numerical range') from exc
            if not all(np.isfinite(a).all() for a in (values, points, phase_loads)):
                raise TectonicsError('derived shortening support fields exceed numerical range')
            record = dict(schema='atlas.w08-shortening-support-result.v1', plan=self.plan_id,
                initial=self.motion.initial.state_id, current=state.state_id,
                load_reference=self._reference_load.state_id, load_current=current.state_id,
                projection_reference=self._reference_projection.projection_id,
                projection_current=projection.projection_id, support=self.support.support_id,
                frame_id=self.grid.frame_id, datum_id=self.motion.datum_id,
                epoch_id=state.material.epoch_id, time_s=state.material.time_s,
                cohort_ids=tuple(p.phase_id for p in self.phases), execution=self.motion.execution_id,
                omitted_response_bounds=(0., 0., 0.), continuous_validity_bounds=valid,
                max_bending_strain_bound=strain, validity_domain='entire target grid',
                mean_output='exact-cell-load-and-output-integrals',
                cell_mean_columns=('load_pa', 'downward_displacement_m', 'unflexed_thickness_change_m',
                    'surface_change_m', 'base_change_m', 'reference_thickness_m', 'current_thickness_m'),
                mantle='single hydrostatic restoring owner; not transported crust',
                thermal='transported enthalpy retained by motion; no thermal buoyancy inferred',
                reference='total change from initial fixed base; never accumulated onto earlier output')
            metadata = _json(record)
            payload, point_payload, phase_payload = values.tobytes(), points.tobytes(), phase_loads.tobytes()
            identity = hashlib.sha256(metadata)
            for data in (payload, point_payload, phase_payload):
                identity.update(data)
            result = object.__new__(ShorteningSupportResult)
            for name, value in (('_metadata', metadata), ('_fields', payload), ('_points', point_payload),
                    ('_phase_loads', phase_payload), ('result_id', identity.hexdigest())):
                object.__setattr__(result, name, value)
            _cancelled(cancel)
            self.motion._context.verify()
            return result

    def close(self):
        if not self._closed:
            object.__setattr__(self, '_closed', True)
            self._stack.close()

    def __enter__(self):
        if self._closed:
            raise TectonicsError('shortening support preparation is closed')
        return self

    def __exit__(self, *args):
        self.close()
