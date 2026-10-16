"""W02: conservative open/closed-boundary crustal transport on a fixed 1D grid.

H is cell-mean thickness (m); u is prescribed face velocity (m/s). Constant
crustal density cancels: the inventory is volume per width (m²), NOT kilograms.
The physical law is dH/dt + d(uH)/dx = 0. No material production, plate topology,
force prediction, geological calibration or automatic time advancement is implied.
The compiled backend is normal; the independent NumPy/Python reference remains
explicit. The regional API does not alter the historical periodic API.
"""
from __future__ import annotations
from dataclasses import dataclass
from concurrent.futures import CancelledError
import math
from typing import Any
import numpy as np
from ._validation import TectonicsError, FloatArray, input_shape, read_array, frozen, scalar
from .resources import select_budget


@dataclass(frozen=True, slots=True)
class RegionalGrid1D:
    """Uniform fixed cells. N cells have N+1 faces, including external faces."""
    cells: int
    length_m: float
    origin_m: float = 0.0

    def __post_init__(self):
        if type(self.cells) is not int or not 1 <= self.cells <= np.iinfo(np.intp).max-1:
            raise TectonicsError("regional cells must be a positive addressable integer")
        object.__setattr__(self, "length_m", scalar(self.length_m, "length_m", positive=True))
        object.__setattr__(self, "origin_m", scalar(self.origin_m, "origin_m"))
        scalar(self.spacing_m, "spacing_m", positive=True)
        scalar(self.origin_m + self.length_m, "domain end")

    @property
    def spacing_m(self) -> float:
        return self.length_m/self.cells


@dataclass(frozen=True, slots=True)
class TransportBoundary:
    """Constant external face state during ONE interval, not a padded ghost grid.

    open: inflow needs exterior_thickness_m; outflow uses the interior donor.
    closed: the supplied boundary velocity must be zero; never overwrite it.
    Optional material_id identifies an external reservoir for provenance only;
    this single-field increment does not transport mixtures or geological ages.
    """
    mode: str
    exterior_thickness_m: float | None = None
    material_id: str | None = None

    def __post_init__(self):
        if self.mode not in ("open", "closed"):
            raise TectonicsError("boundary mode must be open or closed")
        if self.exterior_thickness_m is not None:
            object.__setattr__(self, "exterior_thickness_m", scalar(
                self.exterior_thickness_m, "exterior thickness", nonnegative=True))
        if self.material_id is not None and (type(self.material_id) is not str or not self.material_id.strip()):
            raise TectonicsError("material_id must be nonblank text when supplied")
        if self.mode == "closed" and (self.exterior_thickness_m is not None or self.material_id is not None):
            raise TectonicsError("closed boundary cannot declare incoming material")


@dataclass(frozen=True, slots=True)
class TransportStepLimit:
    maximum_duration_s: float | None
    limiting_cell: int | None
    outgoing_fraction_limit: float
    scheme: str


_SCHEMES = ("upwind", "muscl")
_METRICS = ("solid_volume_per_width_before_m2", "solid_volume_per_width_after_m2",
            "inflow_m2", "outflow_m2", "balance_residual_m2", "maximum_outflow_fraction",
            "left_exchange_m2", "right_exchange_m2")


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError("regional transport cancelled; no candidate published")


def _validate_definition(grid, left, right, scheme, backend):
    if not isinstance(grid, RegionalGrid1D):
        raise TectonicsError("explicit RegionalGrid1D required")
    if not isinstance(left, TransportBoundary) or not isinstance(right, TransportBoundary):
        raise TectonicsError("explicit left and right TransportBoundary required")
    if scheme not in _SCHEMES or backend not in ("numba", "reference"):
        raise TectonicsError("supported scheme: upwind/muscl; backend: numba/reference; no fallback")


def _boundaries(u, left, right):
    values = []
    for face, boundary, inward in ((u[0], left, u[0]>0), (u[-1], right, u[-1]<0)):
        if boundary.mode == "closed" and face != 0:
            raise TectonicsError("closed boundary requires zero supplied face velocity")
        if inward and boundary.exterior_thickness_m is None:
            raise TectonicsError("incoming flow requires explicit exterior thickness")
        # This zero is a never-consumed placeholder for an outflow-only boundary,
        # not an inferred zero-thickness inflow. Reversal is validated afresh.
        values.append(0.0 if boundary.exterior_thickness_m is None else boundary.exterior_thickness_m)
    return tuple(values)


def regional_work_bytes(cells: int, *, scheme: str = "muscl") -> int:
    """Conservative array/capture/publication allowance, not an RSS or JIT heap cap."""
    if type(cells) is not int or cells < 1 or scheme not in _SCHEMES:
        raise TectonicsError("invalid regional workspace description")
    return (96 if scheme == "upwind" else 160)*cells + 8192


def transport_timestep_limit(face_velocity_m_s: Any, grid: RegionalGrid1D, *,
                             left: TransportBoundary, right: TransportBoundary,
                             scheme: str = "muscl", backend: str = "numba", budget=None) -> TransportStepLimit:
    """Advise, never change a requested timestep. None means no finite cap.

    MC reconstruction with SSP-RK2 uses a sufficient outgoing-fraction bound 1/2;
    first-order donor transport uses 1. Return the next smaller float so normal
    rounding of the subsequent admission pass does not turn the advice unsafe.
    """
    _validate_definition(grid, left, right, scheme, backend)
    if input_shape(face_velocity_m_s, "face velocities") != (grid.cells+1,):
        raise TectonicsError("regional grid needs N+1 face velocities")
    cap = 0.5 if scheme == "muscl" else 1.0
    with select_budget(budget).reserve(24*(grid.cells+1)+4096, category="regional-limit"):
        u = read_array(face_velocity_m_s, "face velocities", ndim=1)
        _boundaries(u, left, right)
        if backend == "numba":
            from ._regional_native import duration_limit
            limit, cell = duration_limit(u, grid.spacing_m, cap)
        else:
            limit, cell = math.inf, -1
            for i in range(grid.cells):
                a,b = max(float(u[i+1]),0.0), max(-float(u[i]),0.0)
                s=max(a,b)
                if s:
                    dm,de=math.frexp(grid.spacing_m);sm,se=math.frexp(s)
                    mm,ee=math.frexp((dm/sm)*(cap/(a/s+b/s)))
                    try: candidate=math.ldexp(mm,ee+de-se)
                    except OverflowError: candidate=math.inf
                    if candidate<limit:limit,cell=candidate,i
        if math.isinf(limit):return TransportStepLimit(None, None if cell<0 else cell, cap, scheme)
        if limit <= 0:
            raise TectonicsError("no positive representable timestep for supplied velocities")
        advised = math.nextafter(float(limit), 0.0)
        if advised == 0:
            raise TectonicsError("no safely rounded positive timestep in supported range")
        return TransportStepLimit(advised, int(cell), cap, scheme)


@dataclass(frozen=True, slots=True)
class RegionalTransportResult:
    """Immutable candidate and interval-MEAN flux; RK2 flux is not endpoint flux.

    left/right_exchange_m2 are signed INTO the domain. inflow/outflow are
    nonnegative totals. All fields describe one fixed-forcing interval.
    """
    thickness_m: FloatArray
    face_flux_m2_s: FloatArray
    solid_volume_per_width_before_m2: float
    solid_volume_per_width_after_m2: float
    inflow_m2: float
    outflow_m2: float
    balance_residual_m2: float
    maximum_outflow_fraction: float
    left_exchange_m2: float
    right_exchange_m2: float
    scheme: str
    backend: str

    @property
    def numerical_method(self):
        return f"regional-{self.scheme}-binary64-{'exact-positive' if self.backend=='numba' else 'fsum'}-v1"

    def __reduce__(self):
        return (unpack_regional_result, (pack_regional_result(self), self.thickness_m.size, self.scheme, self.backend))


def pack_regional_result(result: RegionalTransportResult) -> FloatArray:
    """Versioned transfer/cache layout: H[N], mean-flux[N+1], eight named metrics.

    This extra contiguous representation is used ONLY at persistence/process
    boundaries; the stencil itself has no packed-object or per-cell overhead.
    The invocation record carries grid, boundary, units, interval and method.
    """
    n = result.thickness_m.size
    payload=np.empty(2*n+9, dtype=np.float64)
    payload[:n]=result.thickness_m;payload[n:2*n+1]=result.face_flux_m2_s
    payload[2*n+1:]=[getattr(result,k) for k in _METRICS]
    return frozen(payload)


def unpack_regional_result(payload, cells, scheme, backend) -> RegionalTransportResult:
    if type(cells) is not int or cells<1 or scheme not in _SCHEMES or backend not in ("reference","numba"):
        raise TectonicsError("invalid regional result descriptor")
    raw=frozen(payload)
    if raw.shape != (2*cells+9,) or np.any(raw[:cells]<0):
        raise TectonicsError("invalid regional result payload")
    values=tuple(float(x) for x in raw[2*cells+1:])
    if any(values[i]<0 for i in (0,1,2,3,5)) or values[5]>(0.5 if scheme=="muscl" else 1.0):
        raise TectonicsError("invalid regional accounting")
    expected_in=math.fsum((max(values[6],0.),max(values[7],0.)))
    expected_out=math.fsum((max(-values[6],0.),max(-values[7],0.)))
    expected_residual=math.fsum((values[1],-values[0],-values[6],-values[7]))
    if values[2] != expected_in or values[3] != expected_out or values[4] != expected_residual:
        raise TectonicsError("inconsistent regional exchange accounting")
    # Shared immutable bytes, distinct array descriptors. Do not rely on pickle
    # preserving NumPy's read-only flag, nor duplicate both fields on restoration.
    return RegionalTransportResult(raw[:cells].view(),raw[cells:2*cells+1].view(),*values,scheme,backend)


def _reference(h,u,ratio,left,right,high):
    """Independent whole-field reference: NumPy slopes/fluxes, math.fsum totals."""
    out=np.maximum(u[1:],0)*ratio+np.maximum(-u[:-1],0)*ratio
    cap=0.5 if high else 1.0
    if not np.isfinite(out).all() or np.any(out>cap):
        raise TectonicsError("outgoing Courant sum exceeds scheme limit or numerical range")
    def faces(state):
        slope=np.zeros_like(state)
        if high and state.size>2:
            dl=np.diff(state)[:-1];dr=np.diff(state)[1:]
            m=np.minimum(np.minimum(2*np.abs(dl),2*np.abs(dr)), np.abs(0.5*dl+0.5*dr))
            slope[1:-1]=np.where((dl>0)&(dr>0),m,np.where((dl<0)&(dr<0),-m,0.0))
        if high and state.size>1:
            for i in (0, state.size-1):
                if state.size==2:
                    v=float(state[1]-state[0])
                else:
                    d1=float(state[1]-state[0] if i==0 else state[-1]-state[-2])
                    d2=float(state[2]-state[1] if i==0 else state[-2]-state[-3])
                    candidates=(2*d1,1.5*d1-.5*d2,2*d2)
                    v=min(candidates) if min(candidates)>0 else max(candidates) if max(candidates)<0 else 0.
                slope[i]=math.copysign(min(abs(v),2*float(state[i])),v)
        f=np.empty(state.size+1)
        f[0]=u[0]*(left if u[0]>0 else state[0]-.5*slope[0])
        f[-1]=u[-1]*(right if u[-1]<0 else state[-1]+.5*slope[-1])
        f[1:-1]=u[1:-1]*np.where(u[1:-1]>=0,state[:-1]+0.5*slope[:-1],state[1:]-0.5*slope[1:])
        if not np.isfinite(f).all():raise TectonicsError("nonfinite face flux")
        return f
    flux=faces(h)
    if ratio == 0 or not np.any(u):
        total=math.fsum(h)
        return h.copy(),flux,total,total,float(out.max())
    if high:
        stage=h+ratio*flux[:-1]-ratio*flux[1:]
        if np.any(stage<0) or not np.isfinite(stage).all():raise TectonicsError("invalid MUSCL stage")
        f2=faces(stage)
        second=stage+ratio*f2[:-1]-ratio*f2[1:]
        if np.any(second<0) or not np.isfinite(second).all():raise TectonicsError("invalid MUSCL stage")
        updated=h+0.5*(second-h)
        flux=flux+0.5*(f2-flux)
    else:
        hl=np.r_[left,h[:-1]];hr=np.r_[h[1:],right]
        updated=(1-out)*h
        updated=updated+(np.maximum(u[:-1],0)*ratio)*hl
        updated=updated+(np.maximum(-u[1:],0)*ratio)*hr
    return updated,flux,math.fsum(h),math.fsum(updated),float(out.max())


def advect_regional(thickness_m: Any, face_velocity_m_s: Any, grid: RegionalGrid1D,
                    duration_s: float, *, left: TransportBoundary, right: TransportBoundary,
                    scheme: str = "muscl", backend: str = "numba", budget=None,
                    cancel=None) -> RegionalTransportResult:
    """One conservative interval, never automatic substeps or cached I/O.

    Forcing and exterior face thickness stay constant through this interval.
    Caller must split at forcing changes; MUSCL does not promise second-order
    accuracy for time-varying boundary data that were supplied as one constant.
    Cancellation is checked before work and before publication. A running native
    call is drained, not killed. Caller owns the returned arrays' later lifetime.
    """
    _cancelled(cancel)
    _validate_definition(grid,left,right,scheme,backend)
    dt=scalar(duration_s,"duration_s",nonnegative=True)
    if input_shape(thickness_m,"thickness")!=(grid.cells,) or input_shape(face_velocity_m_s,"velocity")!=(grid.cells+1,):
        raise TectonicsError("expected N cell thicknesses and N+1 face velocities")
    with select_budget(budget).reserve(regional_work_bytes(grid.cells,scheme=scheme),category="regional-transport"):
        h=read_array(thickness_m,"thickness",ndim=1,nonnegative=True)
        u=read_array(face_velocity_m_s,"face velocities",ndim=1)
        exterior=_boundaries(u,left,right)
        ratio=dt/grid.spacing_m
        if not math.isfinite(ratio) or (dt>0 and ratio==0):
            raise TectonicsError("interval/spacing outside supported numerical range")
        try:
            if backend=="numba":
                from ._regional_native import advance_regional
                data=advance_regional(h,u,ratio,*exterior,scheme=="muscl")
            else:
                with np.errstate(over="raise", invalid="raise", divide="raise"):
                    data=_reference(h,u,ratio,*exterior,scheme=="muscl")
            updated,flux,sumb,sumafter,maximum=data
            if not np.isfinite(updated).all() or np.any(updated<0):
                raise TectonicsError("invalid candidate thickness")
            before=scalar(sumb*grid.spacing_m,"before inventory",nonnegative=True)
            after=scalar(sumafter*grid.spacing_m,"after inventory",nonnegative=True)
            lx=scalar(dt*float(flux[0]),"left exchange")
            rx=scalar(-dt*float(flux[-1]),"right exchange")
            incoming=scalar(math.fsum((max(lx,0),max(rx,0))),"inflow",nonnegative=True)
            outgoing=scalar(math.fsum((max(-lx,0),max(-rx,0))),"outflow",nonnegative=True)
            residual=math.fsum((after,-before,-lx,-rx))
            # New-method roundoff budget, not a changed historical tolerance.
            # Exact sum reduces accounting error; it cannot remove cell-update
            # rounding. Refuse instead of adjusting the final cell to hide drift.
            tolerance=128*np.finfo(float).eps*max(before,after,incoming,outgoing,np.finfo(float).tiny)
            if not math.isfinite(residual) or abs(residual)>tolerance:
                raise TectonicsError("regional conservation residual exceeds roundoff budget")
        except (ValueError,OverflowError,FloatingPointError) as exc:
            raise TectonicsError(str(exc)) from exc
        except ImportError as exc:
            raise TectonicsError("declared Numba backend unavailable; no fallback") from exc
        _cancelled(cancel)
        return RegionalTransportResult(frozen(updated),frozen(flux),before,after,incoming,outgoing,
                                       residual,maximum,lx,rx,scheme,backend)


def regional_native_build_info():
    """Observed compiled-code digest for the new method, not a security seal."""
    from . import _regional_native as native
    import numba, llvmlite, hashlib
    functions=(native.admission,native.duration_limit,native.advance_regional,native.fluxes,native.upwind_span)
    assembly="\n".join(f.inspect_asm(sig) for f in functions for sig in f.signatures)
    return {"schemes":list(_SCHEMES),"default_scheme":"muscl","numba":numba.__version__,
            "llvmlite":llvmlite.__version__,"fastmath":False,"nogil":True,
            "disk_jit_cache":False,"compiled_assembly_sha256":hashlib.sha256(assembly.encode()).hexdigest()}
