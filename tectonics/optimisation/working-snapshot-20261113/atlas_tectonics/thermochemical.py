"""R4.2 constant-property heat/composition operators on the R4.1 MAC rectangle.

SPDX-License-Identifier: AGPL-3.0-only
rho0*cp*(T_t + div(u*T)) = k*lap(T) + H ; C_t + div(u*C) = 0.
T and C are cell averages, x right and z upward. C is ONE named constituent's
volume fraction, not a plate/cohort ID; its complement represents the other
constituent. The constant-density Boussinesq reference sets heat capacity, not
in-situ compressible mass. All budgets are per ONE metre out-of-plane thickness.

Normal time stepping uses Strang D(dt/2)-A(dt)-D(dt/2). D is the exact flow of
the discrete constant-coefficient diffusion/source operator (DCT-II in x,
DST-II for fixed top/bottom temperatures or DCT-II for insulation in z).
A uses multidimensional MC reconstruction and SSP-RK2, resolving the R4.1
mechanical response at BOTH RK stages when buoyancy coupling is selected.
This is second-order time splitting, NOT an exact coupled PDE solution.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib
import json
import math
import numpy as np
try:
    from scipy.fft import dct, idct, dst, idst
except ImportError:
    dct=idct=dst=idst=None
from ._validation import TectonicsError, scalar, text, frozen, input_shape, read_array
from .resources import select_budget
from .stokes import StokesBox2D
from .constitutive import BoussinesqMaterial, DiffusiveScales, RheologyProfile, _cancel, _json

_METHOD='atlas.thermochemical-strang-mc-ssprk2-2d.v1'
# Python float also participates in the existing loaded-constant identity check.
_BOUND_TOL=float(64*np.finfo(np.float64).eps)
# A numerical publication guard, not a physical time-resolution ceiling.
# Source identity includes these Python constants.
_TIME_RTOL=2e-11
_PUBLICATION_CONTRACT='atlas.thermochemical-conditioned-diffusion-and-clock.v1'


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class ThermalBoundary2D:
    """Sides are insulating. Top/bottom are either BOTH fixed or BOTH insulating.

    Fixed values are physical face temperatures, not boundary-cell averages.
    Geometry is not periodic; closed mechanical walls have zero advective flux.
    """
    kind: str
    bottom_temperature_k: float | None = None
    top_temperature_k: float | None = None

    def __post_init__(self):
        if self.kind not in ('fixed-top-bottom', 'insulated'):
            raise TectonicsError('supported thermal boundary: fixed-top-bottom or insulated')
        for key in ('bottom_temperature_k','top_temperature_k'):
            value=getattr(self,key)
            if self.kind=='insulated':
                if value is not None: raise TectonicsError('insulated walls have no temperature value')
            else:
                object.__setattr__(self,key,scalar(value,key,positive=True))


@dataclass(frozen=True, slots=True)
class ThermochemicalPolicy:
    """Work/accuracy envelope, never an implicit change of mesh/model or timestep."""
    max_cells: int = 131072
    outgoing_courant: float = 0.45
    inventory_rtol: float = 2e-11
    velocity_divergence_rtol: float = 1e-10
    max_steps: int = 4096

    def __post_init__(self):
        for k in ('max_cells','max_steps'):
            if type(getattr(self,k)) is not int or getattr(self,k)<1:
                raise TectonicsError(k+' must be a positive integer')
        c=scalar(self.outgoing_courant,'outgoing Courant',positive=True)
        if c>0.5: raise TectonicsError('MC Euler positivity requires outgoing Courant <= 1/2')
        object.__setattr__(self,'outgoing_courant',c)
        for k in ('inventory_rtol','velocity_divergence_rtol'):
            v=scalar(getattr(self,k),k,positive=True)
            if not 8*np.finfo(float).eps<=v<=1e-8:
                raise TectonicsError(k+' outside supported accuracy envelope')
            object.__setattr__(self,k,v)


@dataclass(frozen=True, slots=True)
class ThermochemicalProblem:
    box: StokesBox2D
    material: BoussinesqMaterial
    boundary: ThermalBoundary2D
    rheology: RheologyProfile
    scales: DiffusiveScales
    gravity_m_s2: tuple[float,float]
    epoch_id: str
    composition_id: str
    source: str
    mechanical_mode: str = 'constant-r4.2'

    def __post_init__(self):
        from .stokes import _scaling
        if self.mechanical_mode not in ('constant-r4.2','variable-r4.3'):
            raise TectonicsError('unknown mechanical mode')
        if self.mechanical_mode == 'variable-r4.3':
            from .variable_stokes import check_coupled_rheology
            check_coupled_rheology(self.box,self.scales,self.rheology)
        else:
            _scaling(self.box,self.scales,self.rheology)
        if type(self.material) is not BoussinesqMaterial or type(self.boundary) is not ThermalBoundary2D:
            raise TectonicsError('typed material and thermal boundary required')
        for key in ('epoch_id','composition_id','source'):
            text(getattr(self,key),key)
            if len(getattr(self,key))>4096: raise TectonicsError('metadata string too long')
        if type(self.gravity_m_s2) is not tuple or len(self.gravity_m_s2)!=2:
            raise TectonicsError('explicit Cartesian gravity tuple required')
        object.__setattr__(self,'gravity_m_s2',tuple(scalar(v,'gravity') for v in self.gravity_m_s2))
        if self.boundary.kind=='fixed-top-bottom':
            lo,hi=self.material.temperature_range_k
            if not all(lo<=v<=hi for v in (self.boundary.bottom_temperature_k,self.boundary.top_temperature_k)):
                raise TectonicsError('thermal walls outside material temperature interval')
        capacity=scalar(self.material.density_kg_m3*self.material.heat_capacity_j_kg_k,'volumetric heat capacity',positive=True)
        scalar(self.material.conductivity_w_m_k/capacity,'thermal diffusivity',positive=True)
        scalar((self.box.width_m/self.box.nx)*(self.box.height_m/self.box.nz),'cell area',positive=True)
        scalar(self.box.width_m*self.box.height_m,'domain area',positive=True)

    @property
    def heat_capacity_j_m3_k(self):
        return self.material.density_kg_m3*self.material.heat_capacity_j_kg_k

    @property
    def diffusivity_m2_s(self):
        return self.material.conductivity_w_m_k/self.heat_capacity_j_m3_k

    @property
    def problem_id(self):
        return _digest(self.descriptor())

    def descriptor(self):
        result=asdict(self)
        result['rheology']=self.rheology.descriptor()
        if self.mechanical_mode=='constant-r4.2':
            del result['mechanical_mode']  # Preserve exact historical problem bytes.
        return result

    @classmethod
    def from_descriptor(cls,d):
        try:
            m=dict(d['material']);m['temperature_range_k']=tuple(m['temperature_range_k'])
            r=d['rheology']
            rp=RheologyProfile(r['name'],r['family'],r['source'],tuple(tuple(v) for v in r['parameters']),
                              None if r['viscosity_bounds'] is None else tuple(r['viscosity_bounds']))
            out=cls(StokesBox2D(**d['box']),BoussinesqMaterial(**m),ThermalBoundary2D(**d['boundary']),rp,
                DiffusiveScales(**d['scales']),tuple(d['gravity_m_s2']),d['epoch_id'],d['composition_id'],d['source'],
                d.get('mechanical_mode','constant-r4.2'))
            if _json(out.descriptor())!=_json(d): raise TectonicsError('noncanonical problem description')
            return out
        except (KeyError,TypeError,ValueError) as exc:
            raise TectonicsError('invalid thermochemical problem description') from exc


def _check_fields(problem,T,C):
    shape=(problem.box.nz,problem.box.nx)
    if T.shape!=shape or C.shape!=shape or not np.isfinite(T).all() or not np.isfinite(C).all():
        raise TectonicsError('finite cell-average temperature/composition fields required')
    lo,hi=problem.material.temperature_range_k
    if np.any((T<lo)|(T>hi)):
        raise TectonicsError('temperature outside the selected material validity interval')
    if problem.rheology.family != 'constant':
        t=(T-problem.scales.surface_temperature_k)/problem.scales.temperature_scale_k
        if not np.isfinite(t).all() or np.any((t<0)|(t>1)):
            raise TectonicsError('temperature outside selected R3 dimensionless law interval')
    # This is a disclosed binary64 round-off envelope, not clipping or a source.
    # Raw excursions are retained, reported, and included in every material account.
    excursion=max(0.,float(-C.min()),float(C.max()-1.))
    if excursion>_BOUND_TOL:
        raise TectonicsError('composition outside [0,1] beyond 64-epsilon round-off envelope')
    m=problem.material
    with np.errstate(over='raise',invalid='raise'):
        try:
            rho=-m.density_kg_m3*m.expansion_per_k*(T-m.reference_temperature_k)+m.composition_density_contrast_kg_m3*C
        except FloatingPointError as exc: raise TectonicsError('density anomaly outside finite range') from exc
    if not np.isfinite(rho).all() or np.any(np.abs(rho)>m.density_kg_m3*m.max_relative_density_anomaly):
        raise TectonicsError('density anomaly exceeds R3 Boussinesq validity envelope')
    return rho,excursion


def _decay_coefficients(x):
    """exp(-x), phi1(-x), and integral-source phi2(-x), stable including x=0.

    phi1=(1-exp(-x))/x; phi2=(1-phi1)/x.  These multiply dt and
    dt**2 respectively in integrals. Callers form time averages to avoid dt**2.
    The series near zero prevents losing a finite source or its boundary flux.
    """
    if np.any(x<0) or not np.isfinite(x).all():
        raise TectonicsError('diffusion interval/eigenvalue outside finite envelope')
    e=np.exp(-x)
    p=np.empty_like(x);s=np.empty_like(x)
    tiny=x<1e-3
    z=x[tiny]
    p[tiny]=1+z*(-.5+z*(1/6+z*(-1/24+z*(1/120-z/720))))
    s[tiny]=.5+z*(-1/6+z*(1/24+z*(-1/120+z*(1/720-z/5040))))
    z=x[~tiny]
    p[~tiny]=-np.expm1(-z)/z
    s[~tiny]=(1-p[~tiny])/z
    return e,p,s


def _source_weight(weight,dt):
    """Prepare interval-only source products once, with a rare unsafe-factor mask.

    The normal caller holds one cache entry, so masks and weights never grow with
    trajectory length. Only the mode multiplication depends on the source field.
    This retains the same exponent-safe arithmetic as the uncached helper route.
    """
    with np.errstate(over='ignore',under='ignore',invalid='ignore'):
        factor=weight*dt
    unsafe=(~np.isfinite(factor))|((np.abs(factor)<np.finfo(float).tiny)&(weight!=0))
    return factor,unsafe if np.any(unsafe) else None


def _weighted_source(modes,weight,dt,*,prepared=None,source_exponent=0):
    """Form weight*dt BEFORE multiplying forcing; scale extreme products safely.

    dt*phi1 is bounded by 1/rate away from the zero mode. Multiplying an
    enormous source impulse before its attenuation is both wasteful and unsafe.
    The rare subnormal/overflow path combines exponents before final rounding.
    """
    if source_exponent:
        # The transform was normalised BEFORE its internal sums. Restore its
        # scale only in the complete response, not as an overflowing raw mode.
        a,ea=np.frexp(modes);b,eb=np.frexp(weight);c,ec=math.frexp(dt)
        with np.errstate(over='ignore',under='ignore',invalid='ignore'):
            out=np.ldexp((a*b)*c,ea+eb+ec+source_exponent)
        if not np.isfinite(out).all(): raise TectonicsError('diffusive forcing response outside finite range')
        return out
    factor,unsafe=_source_weight(weight,dt) if prepared is None else prepared
    with np.errstate(over='ignore',under='ignore',invalid='ignore'):
        out=modes*factor
    # A NONZERO subnormal factor may already have lost most of its relative
    # precision. Combining exponents only after it rounds to zero is too late.
    if unsafe is not None:
        a,ea=np.frexp(modes[unsafe]);b,eb=np.frexp(weight[unsafe]);c,ec=math.frexp(dt)
        with np.errstate(over='ignore',under='ignore',invalid='ignore'):
            out[unsafe]=np.ldexp((a*b)*c,ea+eb+ec)
    if not np.isfinite(out).all(): raise TectonicsError('diffusive forcing response outside finite range')
    return out


def _attenuated_modes(modes,x,exponential):
    """Preserve representable modal tails even when exp(-x) alone underflows."""
    out=modes*exponential
    extreme=(x>500)&(modes!=0)
    if np.any(extreme):
        with np.errstate(under='ignore'):
            out[extreme]=np.sign(modes[extreme])*np.exp(np.log(np.abs(modes[extreme]))-x[extreme])
    return out


def _normalise_extreme(values):
    """Rare power-of-two normalisation, refusing even nonzero rounding loss."""
    maximum=float(np.max(np.abs(values)))
    if not math.isfinite(maximum): raise TectonicsError('thermal source outside finite range')
    exponent=math.frexp(maximum)[1]
    with np.errstate(under='ignore'):
        scaled=np.ldexp(values,-exponent)
        restored=np.ldexp(scaled,exponent)
    if not np.array_equal(restored,values):
        raise TectonicsError('thermal normalisation loses represented values')
    return scaled,exponent


def _scaled_thermal_sum(values,numerator,denominator=()):
    """Rare scaled reduction: never materialise an overflowing sum or factor."""
    scaled,exponent=_normalise_extreme(values)
    total=math.fsum(scaled.flat)
    if total==0:return 0.
    mantissa,power=math.frexp(total);power+=exponent
    for factor in numerator:
        m,e=math.frexp(factor);mantissa*=m;power+=e
    for factor in denominator:
        m,e=math.frexp(factor);mantissa/=m;power-=e
    try: result=math.ldexp(mantissa,power)
    except OverflowError as exc: raise TectonicsError('thermal account outside finite range') from exc
    if not math.isfinite(result) or (result==0 and mantissa!=0):
        raise TectonicsError('thermal account outside representable range')
    return result


def _wall_heat(gradient,k,dx,dz,dt):
    if dt==0:return 0.
    # Keep ordinary operation order; detect unsafe intermediate coefficients
    # as well as an unsafe reduction before using the exponent-safe route.
    a=2*k;b=a*dx;c=b/dz;factor=c*dt
    safe=all(math.isfinite(v) and v>=np.finfo(float).tiny for v in (a,b,c,factor))
    try: total=math.fsum(gradient.tolist()) if safe else None
    except OverflowError: total=None
    if total is not None:return factor*total
    return _scaled_thermal_sum(gradient,(2.,k,dx,dt),(dz,))


class _Diffusion2D:
    """Private constant-property spectral exponential; prepared O(N) eigenvalues.

    It diagonalises the SAME second-order finite-volume Laplacian, not a higher
    resolution continuum Fourier model. Spatial discretisation error remains.
    No dense matrix/exponential or Crank-Nicolson large-step oscillation is used.
    One dt entry is retained; parameter/source changes require another parent plan.
    """
    def __init__(self,problem):
        if dct is None: raise TectonicsError('SciPy transforms required; no fallback')
        self.problem=problem
        b=problem.box
        dx=b.width_m/b.nx; dz=b.height_m/b.nz
        self.fixed=problem.boundary.kind=='fixed-top-bottom'
        from .stokes_execution import _factored_scale
        self.lx=_factored_scale((2*np.sin(np.pi*np.arange(b.nx)/(2*b.nx)))**2,
            (problem.diffusivity_m2_s,),(dx,dx),'horizontal diffusion rates')
        modes=np.arange(1,b.nz+1) if self.fixed else np.arange(b.nz)
        self.lz=_factored_scale((2*np.sin(np.pi*modes/(2*b.nz)))**2,
            (problem.diffusivity_m2_s,),(dz,dz),'vertical diffusion rates')
        with np.errstate(over='ignore'): self.rates=self.lz[:,None]+self.lx[None,:]
        if not np.isfinite(self.rates).all(): raise TectonicsError('diffusion operator outside finite range')
        if self.fixed:
            fraction=(np.arange(b.nz)+.5)/b.nz
            self.lift=((1-fraction)*problem.boundary.bottom_temperature_k+fraction*problem.boundary.top_temperature_k)[:,None]
        else:
            # A constant reference offset limits cancellation during FFT round trips.
            # The material's buoyancy reference is not a thermal boundary value.
            # An observed offset is selected per call below; otherwise an arbitrary
            # distant reference can erase resolved temperature contrasts in T-lift.
            self.lift=None
        self._dt=None;self._coeff=None

    def transform(self,a):
        t=dct(a,type=2,axis=1,norm='ortho',workers=1)
        return (dst if self.fixed else dct)(t,type=2,axis=0,norm='ortho',workers=1,overwrite_x=True)

    def inverse(self,a):
        t=(idst if self.fixed else idct)(a,type=2,axis=0,norm='ortho',workers=1)
        return idct(t,type=2,axis=1,norm='ortho',workers=1,overwrite_x=True)

    def prepare_source(self,Q):
        # Headroom for FFT internal sums, not just the final orthonormal mode.
        # The ordinary source transform is unchanged; no trajectory cache grows.
        if float(np.max(np.abs(Q)))>np.finfo(float).max/(8*Q.size):
            scaled,exponent=_normalise_extreme(Q)
            return self.transform(scaled),exponent
        return self.transform(Q),0

    def advance(self,T,source_modes,dt,cancel,*,source_exponent=0):
        _cancel(cancel)
        if self._dt!=dt:
            with np.errstate(over='raise',invalid='raise'):
                try: x=self.rates*dt
                except FloatingPointError as exc: raise TectonicsError('diffusion timestep overflows') from exc
            coeff=_decay_coefficients(x)
            self._coeff=coeff;self._dt=dt;self._attenuation=x
            # Increment form avoids a damaging forward/inverse round trip when
            # the actual short-interval change is far smaller than the field.
            # For large attenuation the absolute form avoids subtracting nearly
            # all of T and is better conditioned. Equations/order are identical.
            self._incremental=bool(np.max(x)<=0.5)
            self._decay_increment=np.expm1(-x) if self._incremental else None
            self._mean_increment=(-x*coeff[2]) if self._incremental and self.fixed else None
            self._source_weight=_source_weight(coeff[1],dt)
            self._source_average_weight=_source_weight(coeff[2],dt) if self.fixed else None
        e,p,s=self._coeff
        if self.fixed:
            lift=self.lift
        else:
            lo=float(np.min(T));hi=float(np.max(T))
            lift=lo+0.5*(hi-lo)
        modes=self.transform(T-lift)
        with np.errstate(over='raise',invalid='raise'):
            try:
                source_response=_weighted_source(source_modes,p,dt,prepared=self._source_weight,source_exponent=source_exponent)
                if self._incremental:
                    updated=T+self.inverse(self._decay_increment*modes+source_response)
                else:
                    updated=lift+self.inverse(_attenuated_modes(modes,self._attenuation,e)+source_response)
                # With insulation there is no boundary-heat contraction and this
                # time-average field is unused: do not perform its inverse FFT.
                if self.fixed:
                    source_average=_weighted_source(source_modes,s,dt,prepared=self._source_average_weight,source_exponent=source_exponent)
                    if self._incremental:
                        # phi1-1=-x*phi2, evaluated without subtracting near-ones.
                        average=T+self.inverse(self._mean_increment*modes+source_average)
                    else:
                        average=lift+self.inverse(p*modes+source_average)
            except FloatingPointError as exc: raise TectonicsError('diffusion/source response overflows') from exc
        if not np.isfinite(updated).all() or (self.fixed and not np.isfinite(average).all()):
            raise TectonicsError('diffusion/source field outside finite range')
        _cancel(cancel)
        # Integrated heat flux, outward positive. Face temperature BCs are applied
        # at a HALF-cell separation, not a full-cell distance. Side flux is zero.
        b=self.problem.box;k=self.problem.material.conductivity_w_m_k
        if self.fixed:
            dx=b.width_m/b.nx;dz=b.height_m/b.nz
            lower=_wall_heat(average[0]-self.problem.boundary.bottom_temperature_k,k,dx,dz,dt)
            upper=_wall_heat(average[-1]-self.problem.boundary.top_temperature_k,k,dx,dz,dt)
        else: lower=upper=0.
        if not all(math.isfinite(v) for v in (lower,upper)):
            raise TectonicsError('boundary heat account outside finite range')
        return updated,(lower,upper)


def _reference_transfers(q,cx,cz,fx,fz,temperature_walls=None):
    """Independent NumPy formulation for a focused same-equation timing/reference.

    Not the default and not a second numerical-order option. It constructs slope
    arrays; the default fused kernel computes only needed donor slopes.
    """
    sx=np.zeros_like(q);sz=np.zeros_like(q)
    def limiter(a,b):
        return np.where(((a>0)&(b>0))|((a<0)&(b<0)),np.sign(a)*np.minimum(np.minimum(2*np.abs(a),2*np.abs(b)),np.abs(.5*a+.5*b)),0.)
    sx[:,:,1:-1]=limiter(q[:,:,1:-1]-q[:,:,:-2],q[:,:,2:]-q[:,:,1:-1])
    sz[:,1:-1,:]=limiter(q[:,1:-1,:]-q[:,:-2,:],q[:,2:,:]-q[:,1:-1,:])
    if temperature_walls is not None:
        lower=2.*(q[0,0]-temperature_walls[0])
        upper=2.*(temperature_walls[1]-q[0,-1])
        low_slope=limiter(lower,q[0,1]-q[0,0])
        high_slope=limiter(q[0,-1]-q[0,-2],upper)
        # Keep reconstructed wall states inside the cell/wall interval. The
        # reflected ghosts themselves need not lie in the admissible range.
        sz[0,0]=np.sign(low_slope)*np.minimum(np.abs(low_slope),np.abs(lower))
        sz[0,-1]=np.sign(high_slope)*np.minimum(np.abs(high_slope),np.abs(upper))
    fx.fill(0.);fz.fill(0.)
    fx[:,:,1:-1]=cx[None,:,1:-1]*np.where(cx[None,:,1:-1]>=0,q[:,:,:-1]+.5*sx[:,:,:-1],q[:,:,1:]-.5*sx[:,:,1:])
    fz[:,1:-1,:]=cz[None,1:-1,:]*np.where(cz[None,1:-1,:]>=0,q[:,:-1,:]+.5*sz[:,:-1,:],q[:,1:,:]-.5*sz[:,1:,:])
