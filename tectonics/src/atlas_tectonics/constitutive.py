"""R3 local constitutive laws, not a convection or mechanical solver.

SPDX-License-Identifier: AGPL-3.0-only

Tosi et al. (2015), doi:10.1002/2015GC005807, equations 6--10/Table 1:
its plastic denominator uses the Frobenius norm sqrt(e:e), NOT our second
invariant sqrt(e:e/2); its harmonic mean includes a factor TWO. These choices
are preserved rather than silently replaced by a conventional plastic cap.

Becker & Fuchs (2023), doi:10.1029/2023GC011179, equations 6--8/Table 1:
only the local temperature/yield/damage laws are reproduced. The source's
asthenosphere masks, viscosity clipping, empirical time rescaling, spherical
solver and continental rafts are NOT implicit defaults. Damage is an unbounded
strain-like memory: saturation applies to its strength effect, not its history.

All registered laws use explicit dimensionless temperature/depth in [0,1]. SI
conversion requires a named scale set. None extrapolates the room-temperature
material catalogue to a mantle law. Native binary64 array arithmetic is the
normal path; reference scalar formulae are retained in independent tests.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import asdict, dataclass
import hashlib
import json
import math

import numpy as np

from ._validation import TectonicsError, scalar, text, input_shape, read_array, frozen
from .resources import select_budget, elements

_METHOD = 'atlas.constitutive-r3.v1'
_TOSI_DOI = '10.1002/2015GC005807'
_MEMORY_DOI = '10.1029/2023GC011179'


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError('constitutive work cancelled')


@dataclass(frozen=True, slots=True)
class ConstitutiveLimits:
    """Finite computational and input envelopes, not geological uncertainties."""
    max_points: int = 2_097_152
    batch_points: int = 32_768
    max_rate: float = 1e16
    max_damage: float = 1e12
    max_elapsed: float = 1e12

    def __post_init__(self):
        for key in ('max_points', 'batch_points'):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise TectonicsError(key+' must be a positive integer')
        for key in ('max_rate', 'max_damage', 'max_elapsed'):
            object.__setattr__(self, key, scalar(getattr(self, key), key, positive=True))


@dataclass(frozen=True, slots=True)
class DiffusiveScales:
    """Explicit SI nondimensionalisation; no hidden conversion to Earth time.

    t0=L^2/kappa, u0=kappa/L, stress0=eta0/t0, rate0=1/t0.
    T=(T_K-T_surface)/delta_T; z=z_m/depth_scale_m. Depth normalisation is
    separate from the diffusive length (e.g. layer thickness versus radius).
    kappa, eta0 and both lengths are scenario
    inputs; these conversion factors are not measured mantle properties.
    """
    name: str
    length_m: float
    diffusivity_m2_s: float
    viscosity_pa_s: float
    surface_temperature_k: float
    temperature_scale_k: float
    depth_scale_m: float

    def __post_init__(self):
        text(self.name, 'scale identity')
        for key in ('length_m','diffusivity_m2_s','viscosity_pa_s',
                    'surface_temperature_k','temperature_scale_k','depth_scale_m'):
            object.__setattr__(self, key, scalar(getattr(self, key), key, positive=True))
        try:
            derived=(self.time_s,self.velocity_m_s,self.stress_pa)
        except (OverflowError,ZeroDivisionError) as exc:
            raise TectonicsError('scale conversion outside finite binary64 range') from exc
        if any(not math.isfinite(v) or v<=0 for v in derived):
            raise TectonicsError('scale conversion outside finite binary64 range')

    @property
    def time_s(self):
        return self.length_m * (self.length_m/self.diffusivity_m2_s)

    @property
    def velocity_m_s(self):
        return self.diffusivity_m2_s/self.length_m

    @property
    def stress_pa(self):
        return self.viscosity_pa_s/self.time_s

    def rayleigh(self, density_kg_m3, gravity_m_s2, expansion_per_k):
        rho = scalar(density_kg_m3, 'reference density', positive=True)
        g = scalar(gravity_m_s2, 'gravity magnitude', nonnegative=True)
        a = scalar(expansion_per_k, 'expansion', nonnegative=True)
        return scalar(rho*g*a*self.temperature_scale_k*self.length_m/self.stress_pa,
                      'Rayleigh number', nonnegative=True)


@dataclass(frozen=True, slots=True)
class RheologyProfile:
    """Versioned local law. Named presets below freeze the published values.

    A user-defined variant must carry its own name and provenance. A numerical
    viscosity interval is optional, explicit and reported at every clipped point;
    it is never labelled a measured strength or a localisation length.
    """
    name: str
    family: str
    source: str
    parameters: tuple[tuple[str, float], ...]
    viscosity_bounds: tuple[float, float] | None = None

    def __post_init__(self):
        text(self.name, 'profile name'); text(self.source, 'profile source')
        if self.family not in ('constant', 'tosi-linear', 'tosi-plastic', 'bf23-memory'):
            raise TectonicsError('unknown constitutive family')
        required = {
            'constant': ('eta',),
            'tosi-linear': ('contrast_T', 'contrast_z'),
            'tosi-plastic': ('contrast_T', 'contrast_z', 'eta_star', 'sigma_y'),
            'bf23-memory': ('E', 'eta0', 'a', 'b', 'dcrit', 'weakening', 'B', 'Ed'),
        }[self.family]
        if (type(self.parameters) is not tuple or
            any(type(p) is not tuple or len(p)!=2 for p in self.parameters) or
            tuple(k for k,_ in self.parameters) != required):
            raise TectonicsError('explicit ordered constitutive parameters required')
        checked = tuple((k, scalar(v, k, nonnegative=True)) for k,v in self.parameters)
        p = dict(checked)
        for key in ('eta','eta0','eta_star','dcrit'):
            if key in p and p[key] < 1e-100:
                raise TectonicsError(key+' must be positive within the arithmetic envelope (>=1e-100)')
        for key in ('contrast_T','contrast_z'):
            if key in p and not 1 <= p[key] <= 1e30:
                raise TectonicsError('viscosity contrast must lie in [1,1e30]')
        if self.family=='bf23-memory':
            if p['a'] <= 0 or p['weakening'] >= 1 or p['E'] > 100 or p['Ed'] > 100:
                raise TectonicsError('positive cohesion, weakening <1 and finite exponent envelope required')
        if any(v > 1e30 for _,v in checked):
            raise TectonicsError('parameter exceeds registered arithmetic envelope')
        object.__setattr__(self, 'parameters', checked)
        if self.viscosity_bounds is not None:
            if type(self.viscosity_bounds) is not tuple or len(self.viscosity_bounds)!=2:
                raise TectonicsError('viscosity bounds must be an explicit pair')
            lo,hi = (scalar(v,'numerical viscosity bound',positive=True) for v in self.viscosity_bounds)
            if not lo <= hi or hi > 1e100 or lo < 1e-100:
                raise TectonicsError('invalid numerical viscosity interval')
            object.__setattr__(self, 'viscosity_bounds',(lo,hi))

    @property
    def profile_id(self):
        return hashlib.sha256(_json({'method':_METHOD, **asdict(self)})).hexdigest()

    def descriptor(self):
        return {'method':_METHOD, **asdict(self), 'profile_id':self.profile_id}


def reference_rheology(name: str) -> RheologyProfile:
    """One benchmark family and one explicit memory-law subset, with controls."""
    if name=='constant':
        return RheologyProfile('constant-unit-viscosity-v1','constant',
                               'Atlas analytical verification control',(('eta',1.),))
    if name in ('tosi-1','tosi-2','tosi-3','tosi-4','tosi-5a'):
        i=name[5:]; plastic=i in ('2','4','5a')
        pars=(('contrast_T',1e5),('contrast_z',10. if i in ('3','4','5a') else 1.))
        if plastic:
            pars += (('eta_star',1e-3),('sigma_y',4. if i=='5a' else 1.))
        return RheologyProfile(name+'-constitutive-v1','tosi-plastic' if plastic else 'tosi-linear',_TOSI_DOI,pars)
    if name in ('bf23-memory','bf23-no-damage'):
        pars=(('E',40.),('eta0',1.),('a',1e6),('b',1.51e7),('dcrit',10.),
              ('weakening',.9 if name=='bf23-memory' else 0.),('B',2.44e9),('Ed',46.1))
        return RheologyProfile(name+'-model19-local-v1','bf23-memory',_MEMORY_DOI,pars)
    raise TectonicsError('unknown registered rheology profile')


def _inputs(values, names, limits):
    shapes=tuple(input_shape(v,n) for v,n in zip(values,names))
    try: shape=np.broadcast_shapes(*shapes)
    except ValueError as exc: raise TectonicsError('constitutive input shapes do not broadcast') from exc
    count=elements(shape)
    if not 0 < count <= limits.max_points:
        raise TectonicsError('constitutive request outside point envelope')
    return shape, count, sum(elements(s) for s in shapes)


def _check_fields(T,z,e,d,limits):
    if np.any((T<0)|(T>1)) or np.any((z<0)|(z>1)):
        raise TectonicsError('reference temperature/depth must lie in [0,1]; no extrapolation')
    if np.any((e<0)|(e>limits.max_rate)) or np.any((d<0)|(d>limits.max_damage)):
        raise TectonicsError('strain-rate or damage outside finite input envelope')


def _native_law(profile, T, z, e, d):
    """Native local arrays; callers have captured/admitted/validated inputs.

    Algebra avoids division by zero without inventing a small strain rate.
    Zero-rate plastic branches are evaluated by their analytical limits.
    """
    p=dict(profile.parameters)
    weakening=np.ones_like(T); healing=np.zeros_like(T); strength=np.zeros_like(T)
    if profile.family=='constant':
        eta=np.full_like(T,p['eta'])
    elif profile.family.startswith('tosi'):
        linear=np.exp(-math.log(p['contrast_T'])*T+math.log(p['contrast_z'])*z)
        eta=linear
        if profile.family=='tosi-plastic':
            q=np.sqrt(2.)*e  # Tosi: Frobenius norm, not second invariant.
            strength[:]=p['sigma_y']
            if p['sigma_y']==0:
                inverse=np.full_like(q,1./p['eta_star'])
            else:
                inverse=q/(p['eta_star']*q+p['sigma_y'])
            eta=2.*linear/(1.+linear*inverse)
    else:
        weakening=1.-p['weakening']*np.minimum(d,p['dcrit'])/p['dcrit']
        strength=(p['a']+p['b']*z)*weakening
        linear=p['eta0']*np.exp(p['E']/(T+1.)-p['E']/2.)
        # Compare stresses first so division is used only where it can lower eta.
        active=2.*linear*e > strength
        eta=linear.copy()
        np.divide(strength,2.*e,out=eta,where=active)
        healing=p['B']*np.exp(-p['Ed']/(T+1.)+p['Ed']/2.)
    if np.any(eta<=0) or not np.isfinite(eta).all():
        raise TectonicsError('positive finite viscosity required; numerical underflow is not a physical zero')
    limited=np.zeros_like(T)
    if profile.viscosity_bounds is not None:
        lo,hi=profile.viscosity_bounds
        limited=(eta<lo).astype(float)+2.*(eta>hi)
        eta=np.clip(eta,lo,hi)
    return eta,2.*eta*e,strength,weakening,healing,limited


def evaluate_rheology(profile, temperature, depth, strain_rate_ii, damage=None, *, limits=None, budget=None, cancel=None):
    """Return immutable named response arrays on a shared broadcast shape.

    Inputs are dimensionless; output viscosity, stress and healing rate use the
    same nominated scales. 'yield_parameter' is Tosi's sigma_Y in its *own*
    norm convention, or BF's second-invariant yield stress; not interchangeable.
    Constants/linear controls have no yield parameter (key absent, not zero).
    """
    if type(profile) is not RheologyProfile:
        raise TectonicsError('typed rheology profile required')
    limits=ConstitutiveLimits() if limits is None else limits
    if type(limits) is not ConstitutiveLimits:
        raise TectonicsError('typed constitutive limits required')
    if damage is None:
        if profile.family=='bf23-memory':
            raise TectonicsError('initial damage must be explicit; zero memory is not an unknown-value default')
        damage=0.
    args=(temperature,depth,strain_rate_ii,damage); names=('temperature','depth','strain rate','damage')
    shape,n,inputs=_inputs(args,names,limits); batch=min(n,limits.batch_points)
    _cancel(cancel)
    # Capture, outputs, immutable publication and a fixed-size ufunc scratch.
    with select_budget(budget).reserve(24*inputs+144*n+256*batch+65536,category='constitutive-evaluate'):
        values=tuple(read_array(v,k) for v,k in zip(args,names))
        if np.broadcast_shapes(*(v.shape for v in values))!=shape:
            raise TectonicsError('input shape changed during capture')
        arrays=np.broadcast_arrays(*values)
        _check_fields(*arrays,limits)
        if profile.family!='bf23-memory' and np.any(arrays[3]!=0):
            raise TectonicsError('this reference has no damage law; do not silently ignore nonzero memory')
        out=[np.empty(n) for _ in range(6)]; offset=0
        # Buffered iteration handles strided and broadcast inputs without dense
        # point-by-parameter objects or extra broadcast input copies.
        it=np.nditer(arrays, flags=['external_loop','buffered','zerosize_ok'],
                     op_flags=[['readonly']]*4,order='C',buffersize=batch)
        with np.errstate(over='raise',invalid='raise',divide='raise'):
            try:
                for chunk in it:
                    _cancel(cancel)
                    results=_native_law(profile,*chunk)
                    m=chunk[0].size
                    for dst,src in zip(out,results): dst[offset:offset+m]=src
                    offset+=m
            except FloatingPointError as exc:
                raise TectonicsError('constitutive result outside numerical range') from exc
        _cancel(cancel)
        keys=('viscosity','stress_ii','yield_parameter','weakening_factor','healing_rate','viscosity_bound_code')
        result={k:frozen(v.reshape(shape)) for k,v in zip(keys,out)}
        if profile.family in ('constant','tosi-linear'):
            del result['yield_parameter']
        return result


def advance_memory(profile, damage, strain_rate_ii, temperature, elapsed, *, limits=None,budget=None,cancel=None):
    """Exact material-point update for coefficients held fixed over one interval.

    d'=e-h*d, d_new=d*exp(-h*dt)+(e/h)*(1-exp(-h*dt)). This is NOT a
    spatial advection scheme or exact integration for varying T/e. Split an
    imposed history explicitly; later coupled solvers own their time accuracy.
    No clipping at dcrit: persistent stored strain beyond saturation can heal.
    """
    if type(profile) is not RheologyProfile or profile.family!='bf23-memory':
        raise TectonicsError('memory update requires the selected BF local law')
    limits=ConstitutiveLimits() if limits is None else limits
    if type(limits) is not ConstitutiveLimits: raise TectonicsError('typed limits required')
    dt=scalar(elapsed,'elapsed dimensionless time',nonnegative=True)
    if dt>limits.max_elapsed: raise TectonicsError('elapsed time exceeds envelope')
    shape,n,inputs=_inputs((damage,strain_rate_ii,temperature),('damage','rate','temperature'),limits)
    batch=min(n,limits.batch_points); _cancel(cancel)
    with select_budget(budget).reserve(24*inputs+32*n+128*batch+65536,category='constitutive-memory'):
        vals=tuple(read_array(v,k) for v,k in zip((damage,strain_rate_ii,temperature),('damage','rate','temperature')))
        d,e,T=np.broadcast_arrays(*vals)
        _check_fields(T,np.zeros((),dtype=float),e,d,limits)
        p=dict(profile.parameters); out=np.empty(n); pos=0
        it=np.nditer((d,e,T),flags=['external_loop','buffered'],op_flags=[['readonly']]*3,
                     order='C',buffersize=batch)
        with np.errstate(over='raise',invalid='raise',divide='raise'):
            try:
                for a,r,t in it:
                    _cancel(cancel)
                    h=p['B']*np.exp(-p['Ed']/(t+1.)+p['Ed']/2.)
                    x=h*dt
                    # expm1 preserves tiny healing; evaluate via dt*phi for x<1
                    # to avoid overflow in e/h when h approaches zero.
                    gain=np.empty_like(x); small=x<1.
                    phi=np.ones_like(x)
                    np.divide(-np.expm1(-x),x,out=phi,where=x!=0)
                    gain[small]=r[small]*(dt*phi[small])
                    np.divide(r,h,out=gain,where=~small)
                    gain[~small]*=-np.expm1(-x[~small])
                    value=a*np.exp(-x)+gain
                    if np.any(value>limits.max_damage):
                        raise TectonicsError('memory exceeds declared envelope, not clipped')
                    out[pos:pos+a.size]=value; pos+=a.size
            except FloatingPointError as exc:
                raise TectonicsError('memory update outside numerical range') from exc
        _cancel(cancel)
        return frozen(out.reshape(shape))


def strain_rate_invariant(tensor, *,budget=None):
    """sqrt(e:e/2) for a supplied symmetric 2D or 3D *strain-rate* tensor.

    Supply e=(grad u+grad u.T)/2, NOT the velocity gradient. No hidden
    symmetrisation removes vorticity; no plane-strain-to-3D strain is invented.
    """
    shape=input_shape(tensor,'strain tensor')
    if len(shape)<2 or shape[-2:] not in ((2,2),(3,3)):
        raise TectonicsError('symmetric 2x2 or 3x3 tensors required')
    with select_budget(budget).reserve(40*elements(shape)+65536,category='constitutive-invariant'):
        a=read_array(tensor,'strain tensor')
        scale=np.max(np.abs(a),axis=(-2,-1))
        skew=np.max(np.abs(a-np.swapaxes(a,-1,-2)),axis=(-2,-1))
        if np.any(skew>64*np.finfo(float).eps*scale):
            raise TectonicsError('strain tensor is not symmetric')
        # Scale first: finite large/small strain entries need not overflow their squares.
        norm=np.zeros_like(a)
        np.divide(a,scale[...,None,None],out=norm,where=scale[...,None,None]!=0)
        return frozen(scale*np.sqrt(.5*np.sum(norm*norm,axis=(-2,-1))))


@dataclass(frozen=True, slots=True)
class BoussinesqMaterial:
    """Explicit constant-property reference for force, flux and heat accounting.

    rho'=-rho0*alpha*(T-Tref)+delta_rho*C; gravity is an explicitly supplied
    Cartesian acceleration vector. rho0 remains the mass/heat capacity reference.
    Dynamic pressure is excluded from this EOS and from BF's depth-only yield.
    This is a selected approximation, not a hot/high-P mineral property library.
    """
    name: str
    source: str
    density_kg_m3: float
    heat_capacity_j_kg_k: float
    conductivity_w_m_k: float
    expansion_per_k: float
    reference_temperature_k: float
    composition_density_contrast_kg_m3: float
    internal_heating_w_m3: float
    temperature_range_k: tuple[float,float]
    max_relative_density_anomaly: float = .1

    def __post_init__(self):
        text(self.name,'material name'); text(self.source,'material source')
        for key in ('density_kg_m3','heat_capacity_j_kg_k','conductivity_w_m_k','reference_temperature_k'):
            object.__setattr__(self,key,scalar(getattr(self,key),key,positive=True))
        for key in ('expansion_per_k','internal_heating_w_m3'):
            object.__setattr__(self,key,scalar(getattr(self,key),key,nonnegative=True))
        object.__setattr__(self,'composition_density_contrast_kg_m3',scalar(self.composition_density_contrast_kg_m3,'density contrast'))
        if type(self.temperature_range_k) is not tuple or len(self.temperature_range_k)!=2:
            raise TectonicsError('explicit temperature interval required')
        a,b=(scalar(v,'temperature bound',positive=True) for v in self.temperature_range_k)
        if a>b: raise TectonicsError('reversed temperature interval')
        object.__setattr__(self,'temperature_range_k',(a,b))
        f=scalar(self.max_relative_density_anomaly,'Boussinesq anomaly envelope',positive=True)
        if f>=1: raise TectonicsError('Boussinesq envelope must be below reference density')
        object.__setattr__(self,'max_relative_density_anomaly',f)


def boussinesq_response(material,temperature_k,composition,gravity_m_s2,temperature_gradient_k_m,*,
                        viscous_dissipation_w_m3=None,budget=None,cancel=None):
    """Local SI body force, conductive flux and heating; no traction is added.

    Passing dissipation explicitly adds it exactly once. Omitting it selects the
    benchmark's internally heated/conductive approximation, not unknown-as-zero.
    No adiabatic/latent heating, compressibility, diffusion of C or pressure work.
    """
    if type(material) is not BoussinesqMaterial: raise TectonicsError('typed Boussinesq material required')
    ts=input_shape(temperature_k); cs=input_shape(composition)
    gs=input_shape(gravity_m_s2); qs=input_shape(temperature_gradient_k_m)
    if not gs or gs[-1] not in (2,3) or not qs or qs[-1]!=gs[-1]:
        raise TectonicsError('gravity/temperature gradient need matching 2D or 3D vector axes')
    try: shape=np.broadcast_shapes(ts,cs,gs[:-1],qs[:-1],() if viscous_dissipation_w_m3 is None else input_shape(viscous_dissipation_w_m3))
    except ValueError as exc: raise TectonicsError('incompatible material-field shapes') from exc
    n=elements(shape)
    if n>ConstitutiveLimits().max_points: raise TectonicsError('body-force request too large')
    _cancel(cancel)
    with select_budget(budget).reserve(256*n+24*(elements(gs)+elements(qs)+elements(ts)+elements(cs))+65536,category='constitutive-thermochemical'):
        T,C=np.broadcast_arrays(read_array(temperature_k,'temperature'),read_array(composition,'composition'))
        if np.any((T<material.temperature_range_k[0])|(T>material.temperature_range_k[1])) or np.any((C<0)|(C>1)):
            raise TectonicsError('material temperature/composition outside declared envelope')
        gravity=read_array(gravity_m_s2,'gravity'); gradient=read_array(temperature_gradient_k_m,'temperature gradient')
        density=-material.density_kg_m3*material.expansion_per_k*(T-material.reference_temperature_k)+material.composition_density_contrast_kg_m3*C
        density=np.broadcast_to(density,shape)
        if np.any(np.abs(density)>material.density_kg_m3*material.max_relative_density_anomaly):
            raise TectonicsError('density anomaly exceeds selected Boussinesq approximation envelope')
        heat=np.full(shape,material.internal_heating_w_m3)
        if viscous_dissipation_w_m3 is not None:
            heat+=np.broadcast_to(read_array(viscous_dissipation_w_m3,'dissipation',nonnegative=True),shape)
        _cancel(cancel)
        return {'density_anomaly_kg_m3':frozen(density),
                'body_force_n_m3':frozen(density[...,None]*np.broadcast_to(gravity,shape+(gs[-1],))),
                'conductive_flux_w_m2':frozen(-material.conductivity_w_m_k*np.broadcast_to(gradient,shape+(gs[-1],))),
                'heating_w_m3':frozen(heat),
                'heat_capacity_j_m3_k':frozen(np.full(shape,material.density_kg_m3*material.heat_capacity_j_kg_k))}


def stress_and_dissipation(viscosity, strain_tensor, *, budget=None):
    """tau=2*eta*e and tau:e, with the caller's consistent SI or scaled units.

    Supply the traceless deviatoric strain tensor; incompressibility enforcement
    belongs to the later solver. No implicit trace removal hides a divergence
    error. No pressure, elastic stress or bulk dissipation is invented. For SI
    inputs (Pa s and s^-1) outputs are Pa and W/m^3. The energy equation decides
    whether this term is included and must not add it twice.

    Mantissa/exponent arithmetic postpones range conversion until the final
    products. In particular, neither e**2 nor 2*eta is formed at physical scale.
    Binary64 subnormal results are allowed; a mathematically non-zero output
    which rounds to zero, or an overflowing output, is explicitly refused.
    Exact zero strain remains an exact zero response. Normalised terms too small
    to affect their non-negative sum may round away; no cancellation can amplify
    them. This is a bounded floating-point calculation, not arbitrary precision.
    """
    shape = input_shape(strain_tensor, 'strain tensor')
    vs = input_shape(viscosity, 'viscosity')
    if len(shape) < 2 or shape[-2:] not in ((2, 2), (3, 3)):
        raise TectonicsError('2D or 3D strain tensors required')
    try:
        outshape = np.broadcast_shapes(shape[:-2], vs)
    except ValueError as exc:
        raise TectonicsError('viscosity/tensor shapes differ') from exc
    n = elements(outshape)
    if n > ConstitutiveLimits().max_points:
        raise TectonicsError('stress request exceeds envelope')
    # Admit capture, normalised input/mantissas, integer exponents, native scratch,
    # full broadcast output and its immutable publication. Broadcast views do not
    # allocate full inputs. No secondary invariant computation/copy is needed.
    required = 320*n + 64*(elements(shape) + elements(vs)) + 65536
    with select_budget(budget).reserve(required, category='constitutive-stress'):
        a = read_array(strain_tensor, 'strain tensor')
        eta = read_array(viscosity, 'viscosity')
        if np.any(eta <= 0):
            raise TectonicsError('positive viscosity required')
        with np.errstate(over='raise', invalid='raise', divide='raise', under='ignore'):
            try:
                scale = np.max(np.abs(a), axis=(-2, -1))
                scale_m, scale_e = np.frexp(scale)
                # A power-of-two scaling preserves normal significands exactly.
                # Very small normalised components may underflow, but then cannot
                # affect symmetry/trace tests or the non-negative square sum at
                # binary64 accuracy. Component stress uses unnormalised a below.
                scaled = np.ldexp(a, -scale_e[..., None, None])
                tolerance = 64*np.finfo(float).eps*scale_m
                skew = np.max(np.abs(scaled - np.swapaxes(scaled, -1, -2)), axis=(-2, -1))
                if np.any(skew > tolerance):
                    raise TectonicsError('strain tensor is not symmetric')
                if np.any(np.abs(np.trace(scaled, axis1=-2, axis2=-1)) > tolerance):
                    raise TectonicsError('deviatoric stress needs a traceless strain tensor; no bulk law is selected')

                eta_m, eta_e = np.frexp(eta)
                a_m, a_e = np.frexp(a)
                fullshape = outshape + shape[-2:]
                em = np.broadcast_to(eta_m, outshape)
                ee = np.broadcast_to(eta_e, outshape)
                stress = np.empty(fullshape, dtype=np.float64)
                np.multiply(a_m, em[..., None, None], out=stress)
                exponents = a_e + ee[..., None, None]
                exponents += 1  # the factor 2 belongs here, not in physical eta
                np.ldexp(stress, exponents, out=stress)
                if np.any((stress == 0) & (np.broadcast_to(a, fullshape) != 0)):
                    raise TectonicsError('non-zero stress underflows binary64 output')

                # tau:e = 2*eta*sum(e_ij**2), with both off-diagonal entries.
                # Sum while scaled before final ldexp: individually subnormal
                # physical terms can together give a representable heat rate.
                square_sum = np.sum(scaled*scaled, axis=(-2, -1))
                heat_m = (2*em) * square_sum
                heat_e = ee + 2*scale_e
                dissipation = np.ldexp(heat_m, heat_e)
                if np.any((dissipation == 0) & (np.broadcast_to(scale, outshape) != 0)):
                    raise TectonicsError('non-zero dissipation underflows binary64 output')
            except FloatingPointError as exc:
                raise TectonicsError('stress/heat outside numerical range') from exc
        return {'deviatoric_stress': frozen(stress),
                'viscous_dissipation': frozen(dissipation)}
