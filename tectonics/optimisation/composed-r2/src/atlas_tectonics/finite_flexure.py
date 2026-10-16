"""W04.3: finite windows and physical ends of a uniform elastic plate.

Cell-constant pressures are integrated analytically, not replaced by point loads.
Linear (zero-padded) convolution evaluates the continuous Green solution. A
four-coefficient homogeneous correction supplies actual free/clamped ends.
No physical boundary is inferred from a computational window. No variable D.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import numpy as np

from ._validation import TectonicsError, scalar, text, input_shape, read_array, frozen
from .parameters import FlexureParameters, identity
from .regional import RegionalGrid1D
from .resources import select_budget


@dataclass(frozen=True, slots=True)
class FlexureBoundary1D:
    left: str
    right: str
    source_id: str

    def __post_init__(self):
        text(self.source_id, 'boundary source')
        if ((self.left, self.right) != ('continuous', 'continuous') and
                not (self.left in ('free', 'clamped') and self.right in ('free', 'clamped'))):
            raise TectonicsError('declare a continuous plate or two physical free/clamped ends')

    @property
    def continuous(self):
        return self.left == 'continuous'


def _integrated_kernel(offset, cell_width, alpha):
    """alpha**d times response derivatives, before division by K, d=0..3.

For t>=0 the dimensionless Green antiderivative is -exp((-1+i)t)/2.
expm1 preserves narrow cells; parity handles cells straddling the source.
"""
    u = np.asarray(offset, dtype=float)/alpha
    h = cell_width/(2*alpha)
    if not math.isfinite(h) or h <= 0 or not np.isfinite(u).all():
        raise TectonicsError('flexural spacing outside numerical range')
    lo, hi = u-h, u+h
    if np.any(hi <= lo):
        raise TectonicsError('cell edges collapse in flexural coordinates')
    z = complex(-1., 1.)
    out = np.empty(u.shape+(4,))
    positive, negative = lo >= 0, hi <= 0
    crossing = ~(positive | negative)
    # Beyond 700 decay lengths all derivatives are below binary64 normal range;
    # avoid unsafe complex phases. The omitted-load bound is rounded upward.
    def integral(a, width, d):
        a = np.minimum(a, 745.)
        width = np.minimum(width, 745.)
        return (-.5*z**d*np.exp(z*a)*np.expm1(z*width)).real
    for d in range(4):
        out[positive, d] = integral(lo[positive], hi[positive]-lo[positive], d)
        out[negative, d] = (-1)**d*integral(-hi[negative], hi[negative]-lo[negative], d)
        out[crossing, d] = (integral(np.zeros(np.sum(crossing)), hi[crossing], d)
                            +(-1)**d*integral(np.zeros(np.sum(crossing)), -lo[crossing], d))
    return out


def _basis(x, length, alpha):
    """Bounded end-localised homogeneous basis and alpha-scaled derivatives."""
    z = complex(-1., 1.)
    out = np.empty((len(x), 4, 4))
    for side, t in enumerate((x/alpha, (length-x)/alpha)):
        e = np.exp(z*np.minimum(t, 745.))
        for d in range(4):
            v = ((-1)**(side*d)*z**d)*e
            out[:, d, side*2] = v.real
            out[:, d, side*2+1] = v.imag
    return out


@dataclass(frozen=True, slots=True)
class _Definition:
    method: str
    grid: RegionalGrid1D
    parameters: FlexureParameters
    boundary: FlexureBoundary1D


@dataclass(frozen=True, slots=True)
class FiniteRegionFlexure:
    """Exact cell-load response on uniform 1D support, at all faces and centres.

response rows alternate face, centre, face, ...; columns are w,w',w'',w'''.
The spatial array is one coupled domain, not independent computational tiles.
Physical ends have zero prescribed motion/slope or zero moment/shear. Arbitrary
end tractions, mixed continuous/physical ends and poorly conditioned very short
physical plates are explicitly unsupported, not silently approximated.
"""
    grid: RegionalGrid1D
    parameters: FlexureParameters
    boundary: FlexureBoundary1D
    budget: object = field(default=None, repr=False, compare=False)
    alpha_m: float = field(init=False)
    operator_id: str = field(init=False)
    _fft_payload: bytes = field(init=False, repr=False, compare=False)
    _basis_payload: bytes = field(init=False, repr=False, compare=False)
    _inverse_payload: bytes = field(init=False, repr=False, compare=False)
    _nfft: int = field(init=False, repr=False)

    @staticmethod
    def setup_work_bytes(grid):
        return 4096*grid.cells+32768

    def __post_init__(self):
        if (type(self.grid) is not RegionalGrid1D or type(self.parameters) is not FlexureParameters
                or type(self.boundary) is not FlexureBoundary1D):
            raise TectonicsError('typed regional grid, elastic parameters and boundary required')
        n = self.grid.cells
        alpha = math.exp((math.log(4.)+math.log(self.parameters.rigidity_n_m)
                          -math.log(self.parameters.restoring_pa_per_m))/4)
        scalar(alpha, 'flexural length', positive=True)
        scalar(self.grid.length_m/alpha, 'dimensionless region length', positive=True)
        nfft = 1 << (6*n).bit_length()  # >= (2n+1)+(4n+1)-1; no cyclic aliases.
        with select_budget(self.budget).reserve(self.setup_work_bytes(self.grid)):
            offsets = np.arange(-2*n, 2*n+1, dtype=float)*(self.grid.spacing_m/2)
            kernel = _integrated_kernel(offsets, self.grid.spacing_m, alpha)
            kernel /= self.parameters.restoring_pa_per_m
            if not np.isfinite(kernel).all() or kernel[2*n, 0] <= 0:
                raise TectonicsError('finite-region transfer outside numerical range')
            fft = np.fft.rfft(kernel, n=nfft, axis=0)
            basis, inverse = b'', b''
            if not self.boundary.continuous:
                x = np.arange(2*n+1, dtype=float)*(self.grid.spacing_m/2)
                basis_values = _basis(x, self.grid.length_m, alpha)
                matrix = np.vstack([basis_values[i, list(self._orders(side))]
                                    for i, side in ((0, self.boundary.left), (-1, self.boundary.right))])
                if not np.isfinite(matrix).all() or np.linalg.cond(matrix) > 1e8:
                    raise TectonicsError('physical-end basis ill-conditioned; unsupported region/flexural length ratio')
                inverse = np.linalg.inv(matrix).tobytes()
                basis = basis_values.tobytes()
            object.__setattr__(self, '_fft_payload', fft.tobytes())
            object.__setattr__(self, '_basis_payload', basis)
            object.__setattr__(self, '_inverse_payload', inverse)
        object.__setattr__(self, '_nfft', nfft)
        object.__setattr__(self, 'alpha_m', alpha)
        object.__setattr__(self, 'operator_id', identity(_Definition(
            'cell-integrated-continuous-green-linear-fft-physical-end-correction-v1',
            self.grid, self.parameters, self.boundary)))

    @staticmethod
    def _orders(side):
        return (0, 1) if side == 'clamped' else (2, 3)

    @property
    def setup_bytes(self):
        return len(self._fft_payload)+len(self._basis_payload)+len(self._inverse_payload)

    def work_bytes(self, shape):
        if shape != (self.grid.cells+2,):
            raise TectonicsError('packed regional load needs N cell pressures and two far-field pressures')
        return 4096*self.grid.cells+32768

    def solve(self, packed_load_pa, *, budget=None):
        """N cell-constant pressures, then explicit left/right half-line pressures.

Physical ends require both last entries exactly zero; they do not acquire an
exterior plate. Continuous support includes both infinite half-lines analytically.
"""
        shape = input_shape(packed_load_pa, 'regional load')
        with select_budget(budget).reserve(self.work_bytes(shape)):
            load = read_array(packed_load_pa, 'regional load', ndim=1)
            if load.shape != shape:
                raise TectonicsError('regional load changed shape during capture')
            n = self.grid.cells
            if not self.boundary.continuous and np.any(load[-2:] != 0):
                raise TectonicsError('physical plate ends cannot include exterior loads')
            sparse_load = np.zeros(2*n+1)
            sparse_load[1::2] = load[:-2]
            spectrum = np.fft.rfft(sparse_load, n=self._nfft)
            gain = np.frombuffer(self._fft_payload, dtype=np.complex128).reshape(-1, 4)
            response = np.fft.irfft(spectrum[:, None]*gain, n=self._nfft, axis=0)[2*n:4*n+1].copy()
            x = np.arange(2*n+1, dtype=float)*(self.grid.spacing_m/2)
            if self.boundary.continuous:
                basis = _basis(x, self.grid.length_m, self.alpha_m)
                k = self.parameters.restoring_pa_per_m
                # Form q/K before halving; 2*K can overflow for valid finite K.
                with np.errstate(over='ignore', under='ignore'):
                    amplitudes = (load[-2:]/k)*.5
                if (not np.isfinite(amplitudes).all() or
                        np.any((load[-2:] != 0) & (amplitudes == 0))):
                    raise TectonicsError('far-field response outside numerical range')
                response += basis[:, :, 0]*amplitudes[0] + basis[:, :, 2]*amplitudes[1]
            else:
                rhs = -np.concatenate([response[i, list(self._orders(side))]
                    for i, side in ((0, self.boundary.left), (-1, self.boundary.right))])
                coefficients = np.frombuffer(self._inverse_payload).reshape(4, 4)@rhs
                response += np.frombuffer(self._basis_payload).reshape(2*n+1, 4, 4)@coefficients
                residual = np.concatenate([response[i, list(self._orders(side))]
                    for i, side in ((0, self.boundary.left), (-1, self.boundary.right))])
                scale = max(float(np.max(np.abs(load)))/self.parameters.restoring_pa_per_m,
                            float(np.max(np.abs(response))))
                if np.max(np.abs(residual)) > 512*np.finfo(float).eps*scale:
                    raise TectonicsError('physical-end correction failed residual check')
            for d in range(1, 4):
                # Division in stages avoids forming alpha**3 outside float range.
                for _ in range(d):
                    response[:, d] /= self.alpha_m
            return frozen(response)

    def omitted_load_bound_m(self, left_bound_pa, right_bound_pa, left_distance_m, right_distance_m):
        """Conservative displacement error from unrepresented residual half-lines.

Bounds are absolute pressure departures from the declared far-field constants,
valid everywhere beyond the represented load interval. Distances are from that
interval to the nearest requested output. This is conditional on supplied bounds,
not a claim that unknown geology has been measured.
"""
        if not self.boundary.continuous:
            raise TectonicsError('omitted exterior-load bound applies only to continuous plates')
        bounds = [scalar(v, 'omitted pressure bound', nonnegative=True) for v in (left_bound_pa, right_bound_pa)]
        distances = [scalar(v, 'exterior distance', nonnegative=True) for v in (left_distance_m, right_distance_m)]
        terms = []
        for bound, distance in zip(bounds, distances):
            if bound == 0:
                terms.append(0.)
            else:
                exponent = (math.log(bound)-math.log(self.parameters.restoring_pa_per_m)
                            -.5*math.log(2.)-distance/self.alpha_m)
                try:
                    term = math.exp(exponent)
                except OverflowError as exc:
                    raise TectonicsError('omitted-load uncertainty outside numerical range') from exc
                terms.append(max(np.nextafter(0., 1.), term)*(1+8*np.finfo(float).eps))
        return scalar(math.fsum(terms), 'omitted displacement bound', nonnegative=True)

    def omitted_response_bounds(self, left_bound_pa, right_bound_pa, left_distance_m, right_distance_m):
        """Conservative w, slope and curvature bounds over the requested crop."""
        w = self.omitted_load_bound_m(left_bound_pa, right_bound_pa, left_distance_m, right_distance_m)
        slope = scalar((w/self.alpha_m)*math.sqrt(2.), 'omitted slope bound', nonnegative=True)
        curvature = scalar((slope/self.alpha_m)*math.sqrt(2.), 'omitted curvature bound', nonnegative=True)
        return (w, slope, curvature)
