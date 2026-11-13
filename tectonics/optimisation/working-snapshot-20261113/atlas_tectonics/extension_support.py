"""W05.3 dry listric loads and one continuous uniform elastic response.

Motion remains in its unflexed material frame. Surface, base and fault are
derived total-reference views, never fed back into transported inventory.
"""
from __future__ import annotations
from contextlib import ExitStack
from dataclasses import dataclass, asdict
import hashlib
import json
import math
import numpy as np
from ._validation import TectonicsError, scalar, text, frozen, read_array, input_shape
from .extension import PreparedListricExtension, _within_budget
from .materials import _json
from .regional import RegionalGrid1D, _cancelled
from .parameters import FlexureParameters
from .finite_flexure import FiniteRegionFlexure, FlexureBoundary1D
from .column_loads import LoadSupport, LoadPhase, ColumnLoadState, column_load_change
from .resources import select_budget


def _cell_mean_weights(cells, spacing_m, alpha_m, restoring):
    """Double-integrated Green weights / target width, offsets -(N-1)..N-1.

    G(t)=Re((1-i)*exp((-1+i)*abs(t)))/2, t=x/alpha. Off-diagonal
    second primitive differences factor into expm1(z*h)**2; the central weight
    uses a small-h series. No centre sampling or approximate quadrature.
    """
    h = scalar(spacing_m/alpha_m, 'dimensionless mean cell width', positive=True)
    z = complex(-1., 1.)
    with np.errstate(over='raise', invalid='raise', divide='raise', under='ignore'):
        step = np.expm1(z*h)
        if h <= .01:
            term = z*h/2
            series = term
            for power in range(2, 12):
                term *= z*h/(power+1)
                series += term
            centre = -series.real
        else:
            centre = 1-(step/z/h).real
        offsets = np.abs(np.arange(-cells+1, cells))
        values = np.empty(2*cells-1)
        far = offsets > 0
        distance = (offsets[far]-1)*h
        factor = -.5*(step/h)*(step/z)
        values[far] = (np.exp(z*np.minimum(distance, 745.))*factor).real
        values[~far] = centre
        values /= restoring
        if not np.isfinite(values).all() or values[cells-1] <= 0:
            raise TectonicsError('cell-mean response outside numerical range')
        return frozen(values)


class ContinuousCellMeanFlexure:
    """Prepared exact mean response, uniform cells, zero exterior load change.

    Complements FiniteRegionFlexure point diagnostics, not a second physical
    response. The caller owns the explicit exterior approximation/error.
    """
    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise AttributeError('prepared cell-mean operator is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, operator, *, budget=None):
        if type(operator) is not FiniteRegionFlexure or not operator.boundary.continuous:
            raise TectonicsError('uniform continuous-plate operator required')
        self.cells = n = operator.grid.cells
        self.operator_id = hashlib.sha256(_json(dict(method='mean-cell-green-v1',
                                                     point_operator=operator.operator_id))).hexdigest()
        self._nfft = 1 << (3*n-2).bit_length()
        with select_budget(budget).reserve(1024*n+8192, category='mean-flexure-setup'):
            weights = _cell_mean_weights(n, operator.grid.spacing_m, operator.alpha_m,
                                         operator.parameters.restoring_pa_per_m)
            self._spectrum = np.fft.rfft(weights, n=self._nfft).tobytes()
        self._sealed = True

    @property
    def setup_bytes(self):
        return len(self._spectrum)

    def solve(self, load_pa, *, budget=None):
        if input_shape(load_pa) != (self.cells,):
            raise TectonicsError('one cell pressure per source cell required')
        with select_budget(budget).reserve(1024*self.cells+8192, category='mean-flexure-solve'):
            load = read_array(load_pa, 'cell load')
            values = np.fft.irfft(np.fft.rfft(load, n=self._nfft)*
                np.frombuffer(self._spectrum, dtype=np.complex128), n=self._nfft)
            result = values[self.cells-1:2*self.cells-1]
            if not np.isfinite(result).all():
                raise TectonicsError('cell-mean flexure outside numerical range')
            return frozen(result)


@dataclass(frozen=True, slots=True)
class ExtensionSupportPolicy:
    elastic: FlexureParameters
    max_abs_displacement_m: float
    max_abs_slope: float
    max_bending_strain: float
    max_omitted_displacement_m: float
    source_id: str

    def __post_init__(self):
        if type(self.elastic) is not FlexureParameters:
            raise TectonicsError('explicit elastic parameters required')
        text(self.source_id, 'support policy source')
        for key in ('max_abs_displacement_m', 'max_abs_slope', 'max_bending_strain',
                    'max_omitted_displacement_m'):
            object.__setattr__(self, key, scalar(getattr(self, key), key, positive=True))
        if self.max_abs_slope >= 1 or self.max_bending_strain >= 1:
            raise TectonicsError('small-slope and strain limits must be below one')


@dataclass(frozen=True, slots=True, init=False)
class ExtensionSupportResult:
    """Immutable mean fields and separately labelled face/centre diagnostics.

    Mean columns: downward q (Pa), downward w (m), unflexed surface change,
    surface, base, fault elevations (m), Hc, H, F (m), mantle volume into the
    column (m3). Datum is the initial flat surface. No material is updated.
    """
    result_id: str
    _metadata: bytes
    _fields: bytes
    _points: bytes

    def descriptor(self):
        return json.loads(self._metadata)

    @property
    def cell_means(self):
        return np.frombuffer(self._fields, dtype=np.float64).reshape(-1, 10)

    @property
    def face_centre_response(self):
        """Rows face, centre, face...; columns w, w', w'', w''' (point values)."""
        return np.frombuffer(self._points, dtype=np.float64).reshape(-1, 4)


def _upper_exp(exponent):
    try:
        value = math.exp(exponent)
    except OverflowError as exc:
        raise TectonicsError('exterior uncertainty exceeds numerical range') from exc
    return scalar(max(np.nextafter(0., 1.), value)*(1+16*np.finfo(float).eps),
                  'rounded-up uncertainty', positive=True)


class PreparedExtensionSupport:
    """One source-bound motion reference and reused load/support geometry.

    Borrowed motion preparation must stay open; closing this object does not
    close it. Initial reference is fixed, never the preceding requested output.
    """
    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise AttributeError('prepared extension support is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, motion, policy, *, budget=None, cancel=None):
        _cancelled(cancel)
        if type(motion) is not PreparedListricExtension or type(policy) is not ExtensionSupportPolicy:
            raise TectonicsError('typed prepared extension and support policy required')
        motion._check(motion.initial); motion._context.verify()
        if motion.transport != 'characteristic':
            raise TectonicsError('W05 coupled support requires the accuracy-accepted characteristic route')
        if policy.elastic.density_contrast_kg_m3 <= motion.density_kg_m3:
            raise TectonicsError('dry restoring density is mantle density, strictly greater than crust density')
        edges = motion.grid.edges_m
        n = motion.grid.cells
        grid = RegionalGrid1D(n, float(edges[-1]-edges[0]), float(edges[0]))
        expected = np.linspace(edges[0], edges[-1], n+1)
        if (np.any(np.abs(edges-expected) > 1e-12*grid.spacing_m) or
                np.any(np.abs(motion.grid.widths_m-grid.spacing_m) > 1e-12*grid.spacing_m)):
            raise TectonicsError('uniform shared load/motion grid required; no implicit remapping')
        self.motion = motion; self.policy = policy
        self._budget = motion._budget if budget is None else select_budget(budget)
        _within_budget(self._budget, motion._budget)
        self._stack = ExitStack(); self._closed = False
        try:
            self._stack.enter_context(self._budget.reserve(2048*n+32768, category='extension-support-retained'))
            self.operator = FiniteRegionFlexure(grid, policy.elastic,
                FlexureBoundary1D('continuous', 'continuous', policy.source_id), budget=self._budget)
            self.mean_operator = ContinuousCellMeanFlexure(self.operator, budget=self._budget)
            with self._budget.reserve(512*n+16384, category='extension-load-setup'):
                area = motion.grid.widths_m*motion.width_m
                self.support = LoadSupport(tuple(str(i) for i in range(n)), area,
                    np.full(n, motion.geometry.crust_thickness_m), geometry_source=motion.plan_id,
                    frame_id=motion.grid.frame_id, datum_id=motion.datum_id, budget=self._budget)
                self.phase = tuple(LoadPhase(name, 'rock', motion.density_kg_m3, motion.plan_id)
                                   for name in ('fixed-footwall', 'moving-hangingwall'))
                self._zero = np.zeros(n).tobytes()
                initial_h = motion.initial.material.total_thickness(backend=motion.backend, budget=self._budget)
                initial_volume = area*initial_h
                if np.any((initial_h > 0) & (initial_volume == 0)):
                    raise TectonicsError('initial hanging-wall volume underflows')
                # Partition the declared initial support IN VOLUME coordinates.
                # F = capacity-H0 avoids an artificial over-capacity ulp from
                # separately rounded area*F and area*H0. Moving H is not altered.
                footwall_volume = area*motion.geometry.crust_thickness_m-initial_volume
                if (np.any(footwall_volume <= 0) or np.any(np.abs(footwall_volume-
                        area*motion.footwall_thickness_m) > 1e-12*footwall_volume)):
                    raise TectonicsError('stationary footwall volume does not resolve declared geometry')
                self._initial_h = initial_h.tobytes()
                self._initial_h_volume = initial_volume.tobytes()
                self._footwall_volume = footwall_volume.tobytes()
                self._reference_load = self._load(motion.initial, initial_h, cancel)
                self.plan_id = hashlib.sha256(_json(dict(method='w05-dry-support-v1',
                    motion=motion.plan_id, policy=asdict(policy), reference_load=self._reference_load.state_id,
                    operator=self.operator.operator_id, mean_operator=self.mean_operator.operator_id,
                    execution=motion.execution_id))).hexdigest()
            _cancelled(cancel); motion._context.verify()
            self._sealed = True
        except BaseException:
            self._stack.close()
            raise

    def _load(self, state, hangingwall, cancel):
        with np.errstate(over='raise', invalid='raise', under='ignore'):
            moving_volume = hangingwall*self.support.area_m2
        initial_h = np.frombuffer(self._initial_h, dtype=np.float64)
        initial_volume = np.frombuffer(self._initial_h_volume, dtype=np.float64)
        if (np.any((hangingwall > 0) & (moving_volume == 0)) or
                np.any((hangingwall != initial_h) & (moving_volume == initial_volume))):
            raise TectonicsError('hanging-wall volume or nonzero change is unresolvable')
        volumes = np.column_stack((np.frombuffer(self._footwall_volume, dtype=np.float64), moving_volume))
        return ColumnLoadState(self.support, self.phase, volumes,
            np.frombuffer(self._zero, dtype=np.float64), source_id=state.state_id,
            epoch_id=hashlib.sha256(_json(dict(epoch=state.material.epoch_id,
                                             time_s=state.material.time_s))).hexdigest(),
            budget=self._budget, cancel=cancel)

    def _tail(self, state):
        motion, params = self.motion, self.policy.elastic
        elapsed = state.material.time_s-motion.initial.material.time_s
        a = scalar(motion.velocity_m_s*elapsed, 'displacement', nonnegative=True)
        distance = self.operator.grid.origin_m+self.operator.grid.length_m-motion.geometry.trace_m-a
        if distance <= 0:
            raise TectonicsError('moving front must remain inside the represented load domain')
        if a == 0:
            return 0., (0., 0., 0.)
        fraction = scalar(-math.expm1(-a/motion.geometry.decay_length_m), 'tail amplitude', positive=True)
        logq = (math.log(motion.density_kg_m3)+math.log(params.gravity_m_s2)+
            math.log(motion.geometry.detachment_depth_m)+math.log(fraction)-
            distance/motion.geometry.decay_length_m)
        qright = _upper_exp(logq)
        logw = math.log(qright)-math.log(params.restoring_pa_per_m)-.5*math.log(2.)
        bounds = tuple(_upper_exp(logw+d*(.5*math.log(2.)-math.log(self.operator.alpha_m)))
                       for d in range(3))
        return qright, bounds

    def solve(self, state, *, cancel=None):
        if self._closed:
            raise TectonicsError('extension support preparation is closed')
        self.motion._check(state); _cancelled(cancel); self.motion._context.verify()
        n = self.motion.grid.cells
        with self._budget.reserve(1024*n+32768, category='extension-support-output'):
            fields = self.motion.geometry_fields(state, budget=self._budget)
            kinematic = fields[:, 3]
            current = self._load(state, fields[:, 0], cancel)
            loads = column_load_change(self._reference_load, current,
                self.policy.elastic.gravity_m_s2, budget=self._budget, cancel=cancel)
            q = loads[:, 3]
            qright, tail = self._tail(state)
            if tail[0] > self.policy.max_omitted_displacement_m:
                raise TectonicsError('exterior-load uncertainty exceeds the declared displacement tolerance')
            points = self.operator.solve(np.r_[q, 0., 0.], budget=self._budget)
            means = self.mean_operator.solve(q, budget=self._budget)
            # Global Green derivative L1 bounds cover unsampled extrema between
            # each face/centre pair. Include omitted exterior loads too.
            scale = float(np.max(np.abs(q)))/self.policy.elastic.restoring_pa_per_m
            derivatives = []
            bound = math.sqrt(2.)*scale
            for _ in range(3):
                bound = bound/self.operator.alpha_m*math.sqrt(2.)
                derivatives.append(scalar(bound, 'derivative envelope', nonnegative=True))
            valid = tuple(scalar(float(np.max(np.abs(points[:, d])))+
                self.operator.grid.spacing_m/4*derivatives[d]+tail[d],
                'continuous response envelope', nonnegative=True) for d in range(3))
            strain = scalar(self.policy.elastic.elastic_thickness_m/2*valid[2], 'bending strain', nonnegative=True)
            if (valid[0] > self.policy.max_abs_displacement_m or valid[1] > self.policy.max_abs_slope or
                    strain > self.policy.max_bending_strain):
                raise TectonicsError('dry support displacement/slope/bending-strain envelope exceeded')
            crust = self.motion.geometry.crust_thickness_m+kinematic
            surface = kinematic-means
            base = -self.motion.geometry.crust_thickness_m-means
            fault = self.motion.footwall_thickness_m-self.motion.geometry.crust_thickness_m-means
            mantle_volume = -self.support.area_m2*means
            values = np.column_stack((q, means, kinematic, surface, base, fault,
                                      crust, fields[:, 0], fields[:, 1], mantle_volume))
            if not np.isfinite(values).all() or not np.isfinite(points).all():
                raise TectonicsError('derived support fields exceed numerical range')
            record = dict(schema='atlas.w05-support-result.v1', plan=self.plan_id,
                initial=self.motion.initial.state_id, current=state.state_id,
                load_reference=self._reference_load.state_id, load_current=current.state_id,
                frame_id=self.motion.grid.frame_id, datum_id=self.motion.datum_id,
                epoch_id=state.material.epoch_id, time_s=state.material.time_s,
                execution=self.motion.execution_id, exterior_right_bound_pa=qright,
                omitted_response_bounds=tail, continuous_validity_bounds=valid,
                max_bending_strain_bound=strain, mean_output='exact-cell-load-and-output-integrals',
                mantle='hydrostatic reservoir; -A*w, not transported crust',
                reference='total change from initial; never accumulated onto earlier output')
            metadata, payload, point_payload = _json(record), values.tobytes(), points.tobytes()
            result = object.__new__(ExtensionSupportResult)
            for name, value in (('_metadata', metadata), ('_fields', payload), ('_points', point_payload),
                    ('result_id', hashlib.sha256(metadata+payload+point_payload).hexdigest())):
                object.__setattr__(result, name, value)
            _cancelled(cancel); self.motion._context.verify()
            return result

    def close(self):
        if not self._closed:
            object.__setattr__(self, '_closed', True)
            self._stack.close()

    def __enter__(self):
        if self._closed:
            raise TectonicsError('extension support preparation is closed')
        return self

    def __exit__(self, *args):
        self.close()
