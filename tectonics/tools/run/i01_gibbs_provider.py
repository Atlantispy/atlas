"""Experimental common-Gibbs melt accounts. SPDX-License-Identifier: AGPL-3.0-only

Backend supplies closed-system equilibrium chemical potentials in SI. Phase
properties follow Gibbs-Duhem, not a derivative of a changing phase composition.
No raw backend H/S/V, empirical tuning, persistent transactions or world run.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import CancelledError
from dataclasses import dataclass
import math
import time


def finite(x, name, *, positive=False):
    if type(x) not in (int, float):
        raise ValueError(name + ' must be a finite number')
    try:
        x = float(x)
    except OverflowError as exc:
        raise ValueError(name + ' is unrepresentable') from exc
    if not math.isfinite(x) or (positive and x <= 0):
        raise ValueError(name + ' outside represented support')
    return x


def dot(a, b):
    # Absent components have no chemical potential contribution.
    return finite(math.fsum(x*y for x, y in zip(a, b) if x), 'contraction')


def check(cancel=None, deadline=None):
    if cancel is not None and cancel.is_set():
        raise CancelledError('melt calculation cancelled; no transfer committed')
    if deadline is not None and time.perf_counter() >= finite(deadline, 'deadline'):
        raise TimeoutError('melt calculation deadline reached')


@dataclass(frozen=True, slots=True)
class PhasePoint:
    key: str
    # Component moles in this phase per ONE mole of total bulk components.
    amounts: tuple[float, ...]
    coordinates: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class Point:
    provider_id: str
    pressure_pa: float
    temperature_k: float
    bulk: tuple[float, ...]
    mu_j_mol: tuple[float, ...]
    gibbs_j_mol: float
    phases: tuple[PhasePoint, ...]


@dataclass(frozen=True, slots=True)
class Controls:
    temperature_step_k: float = 1.0
    pressure_step_pa: float = 1e6
    component_tolerance: float = 1e-7
    relative_derivative_tolerance: float = 1e-3
    entropy_tolerance_j_kg_k: float = 0.1
    volume_tolerance_m3_kg: float = 1e-8
    branch_coordinate_tolerance: float = 0.05
    max_points: int = 1024
    cache_points: int = 256

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            v = getattr(self, name)
            if name in ('max_points', 'cache_points'):
                if type(v) is not int or not 1 <= v <= 4096:
                    raise ValueError('bounded positive point/cache budget required')
            else:
                finite(v, name, positive=True)


@dataclass(frozen=True, slots=True)
class Phase:
    key: str
    component_mass_kg: tuple[float, ...]
    enthalpy_j: float
    entropy_j_k: float
    volume_m3: float
    entropy_discrepancy_j_k: float
    volume_discrepancy_m3: float


@dataclass(frozen=True, slots=True)
class State:
    provider_id: str
    pressure_pa: float
    temperature_k: float | None
    component_mass_kg: tuple[float, ...]
    enthalpy_j: float
    entropy_j_k: float
    volume_m3: float
    phases: tuple[Phase, ...]
    entropy_discrepancy_j_k: float
    volume_discrepancy_m3: float
    component_residual_kg: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class Parcel:
    provider_id: str
    pressure_pa: float
    component_mass_kg: tuple[float, ...]
    enthalpy_j: float


@dataclass(frozen=True, slots=True)
class ThermalBranch:
    """Caller-declared support, not a certificate inferred from sampled states.

    The physical/model basis must cover the entire temperature interval for this
    inventory and pressure. Matching sampled phase IDs is necessary, not proof
    that an unsampled phase or order transition is absent.
    """
    provider_id: str
    controls: Controls
    component_ids: tuple[str, ...]
    component_mass_kg: tuple[float, ...]
    pressure_pa: float
    temperature_bounds_k: tuple[float, float]
    phase_keys: tuple[str, ...]
    support: str


class Provider:
    """Small bounded in-memory reuse, bound to ONE immutable backend instance.

    Backend must expose identity, component_ids, molar_mass_kg, validate(p,t,b)
    and solve(p,t,b,cancel=...,deadline=...) -> Point. Bounds are numerical
    support, not calibration acceptance. No cross-provider cache is shared.
    """
    def __init__(self, backend, controls=Controls()):
        if type(controls) is not Controls:
            raise ValueError('explicit immutable numerical controls required')
        self.backend, self.controls = backend, controls
        self.identity = backend.identity
        self.ids = tuple(backend.component_ids)
        self.molar_mass = tuple(finite(v, 'molar mass', positive=True)
                                for v in backend.molar_mass_kg)
        if (not isinstance(self.identity, str) or not self.identity
                or not 1 <= len(self.ids) <= 64 or len(set(self.ids)) != len(self.ids)
                or len(self.ids) != len(self.molar_mass)):
            raise ValueError('explicit provider and component identities required')
        self.cache = OrderedDict()
        self.calls = self.hits = 0

    def declare_thermal_branch(self, mass, pressure_pa, temperature_bounds_k, *,
                               phase_keys, support):
        """Bind an explicit supported-branch assumption; do not infer admission.

        This does no equilibrium calculation. In particular, endpoints agreeing
        cannot supply the caller's whole-interval physical/model support.
        """
        if self.backend.identity != self.identity:
            raise ValueError('backend identity changed')
        mass, _, total, _ = self.inventory(mass)
        p = finite(pressure_pa, 'pressure', positive=True)
        if not total:
            raise ValueError('a thermal branch needs a nonempty inventory')
        if type(temperature_bounds_k) not in (tuple, list) or len(temperature_bounds_k) != 2:
            raise ValueError('two supported temperature bounds required')
        bounds = tuple(finite(t, 'branch temperature', positive=True) for t in temperature_bounds_k)
        if not bounds[0] < bounds[1]:
            raise ValueError('ordered supported temperature bounds required')
        if (type(phase_keys) is not tuple or not 1 <= len(phase_keys) <= 64
                or any(type(k) is not str or not k for k in phase_keys)
                or len(set(phase_keys)) != len(phase_keys)):
            raise ValueError('explicit unique stable phase identities required')
        if type(support) is not str or not support.strip():
            raise ValueError('whole-interval branch support provenance required')
        return ThermalBranch(self.identity, self.controls, self.ids, mass, p,
                             bounds, tuple(sorted(phase_keys)), support)

    def _thermal_branch(self, branch, mass, pressure_pa, bracket_k):
        if type(branch) is not ThermalBranch:
            raise ValueError('explicit declared thermal branch required')
        # Revalidate even a manually constructed or dataclasses.replace record.
        validated = self.declare_thermal_branch(branch.component_mass_kg,
            branch.pressure_pa, branch.temperature_bounds_k,
            phase_keys=branch.phase_keys, support=branch.support)
        if validated != branch:
            raise ValueError('thermal branch provider, controls or component basis mismatch')
        mass, _, _, _ = self.inventory(mass)
        p = finite(pressure_pa, 'pressure', positive=True)
        if (branch.component_mass_kg != mass or branch.pressure_pa != p
                or not branch.temperature_bounds_k[0] <= bracket_k[0] < bracket_k[1]
                       <= branch.temperature_bounds_k[1]):
            raise ValueError('request outside declared thermal branch inventory, pressure or bounds')

    @staticmethod
    def _branch_state(branch, state):
        if tuple(sorted(s.key for s in state.phases)) != branch.phase_keys:
            raise ValueError('sampled phase identities leave declared thermal branch')
        return state

    def inventory(self, mass):
        if type(mass) not in (tuple, list) or len(mass) != len(self.ids):
            raise ValueError('component masses in provider order required')
        mass = tuple(finite(x, 'mass') for x in mass)
        if any(x < 0 for x in mass):
            raise ValueError('negative inventory')
        n = tuple(finite(x/w, 'component moles') for x, w in zip(mass, self.molar_mass))
        total = finite(math.fsum(n), 'total moles')
        bulk = tuple(x/total if total else 0. for x in n)
        if any(m and (ni == 0 or b == 0) for m, ni, b in zip(mass, n, bulk)):
            raise ValueError('positive inventory underflows')
        return mass, n, total, bulk

    def point(self, p, t, bulk, *, cancel=None, deadline=None):
        check(cancel, deadline)
        p, t = finite(p, 'pressure', positive=True), finite(t, 'temperature', positive=True)
        if (type(bulk) is not tuple or len(bulk) != len(self.ids)
                or any(finite(x, 'bulk') < 0 for x in bulk)
                or abs(math.fsum(bulk)-1) > 1e-12):
            raise ValueError('normalised immutable component-mole bulk required')
        if self.backend.identity != self.identity:
            raise ValueError('backend identity changed')
        self.backend.validate(p, t, bulk)
        key = (p, t, bulk)
        if key in self.cache:
            self.hits += 1
            self.cache.move_to_end(key)
            return self.cache[key]
        if self.calls >= self.controls.max_points:
            raise TimeoutError('prepared provider point budget exhausted')
        self.calls += 1
        r = self.backend.solve(p, t, bulk, cancel=cancel, deadline=deadline)
        check(cancel, deadline)
        c, size = self.controls, len(bulk)
        if (type(r) is not Point or r.provider_id != self.identity
                or r.pressure_pa != p or r.temperature_k != t
                or len(r.bulk) != size or len(r.mu_j_mol) != size
                or not 1 <= len(r.phases) <= 64):
            raise ValueError('backend result identity/shape mismatch')
        if any(abs(finite(x, 'returned bulk')-y) > 1e-12 for x, y in zip(r.bulk, bulk)):
            raise ValueError('backend changed the requested composition')
        for x, mu in zip(bulk, r.mu_j_mol):
            if x:
                finite(mu, 'chemical potential')
        keys = [s.key for s in r.phases]
        if len(set(keys)) != len(keys) or any(not isinstance(k, str) or not k for k in keys):
            raise ValueError('unique stable phase/branch identities required')
        for s in r.phases:
            if len(s.amounts) != size or type(s.amounts) is not tuple or type(s.coordinates) is not tuple:
                raise ValueError('immutable phase arrays required')
            if any(finite(v, 'phase amount') < 0 for v in s.amounts) or not math.fsum(s.amounts):
                raise ValueError('negative or empty stable phase')
            for v in s.coordinates:
                finite(v, 'phase coordinate')
        for i, b in enumerate(bulk):
            a = math.fsum(s.amounts[i] for s in r.phases)
            if (b == 0 and a != 0) or abs(a-b) > c.component_tolerance:
                raise ValueError(f'phase component balance does not close: {self.ids[i]} '
                                 f'residual={a-b:g}, P={p:g}, T={t:g}')
        g = finite(r.gibbs_j_mol, 'Gibbs energy')
        if abs(g-dot(bulk, r.mu_j_mol)) > 1e-9*max(1., abs(g)):
            raise ValueError('Gibbs energy/chemical potential mismatch')
        self.cache[key] = r
        if len(self.cache) > c.cache_points:
            self.cache.popitem(last=False)
        return r

    def _stencil(self, centre, axis, step, cancel, deadline):
        samples = []
        for d in (-step, step, -step/2, step/2):
            p, t = centre.pressure_pa, centre.temperature_k
            r = self.point(p+d if axis == 'p' else p, t+d if axis == 't' else t,
                           centre.bulk, cancel=cancel, deadline=deadline)
            phases = {s.key: s for s in r.phases}
            if set(phases) != {s.key for s in centre.phases}:
                raise ValueError('derivative stencil crosses a phase boundary')
            for s in centre.phases:
                v = phases[s.key]
                a, b = math.fsum(s.amounts), math.fsum(v.amounts)
                ca = tuple(x/a for x in s.amounts)+s.coordinates
                cb = tuple(x/b for x in v.amounts)+v.coordinates
                if (len(ca) != len(cb) or max(abs(x-y) for x, y in zip(ca, cb))
                        > self.controls.branch_coordinate_tolerance):
                    raise ValueError('phase composition/order branch is unresolved')
            samples.append(r)
        lo, hi, lhalf, hhalf = samples
        def derivative(a, b, width):
            return tuple((y-x)/width if active else 0.
                         for x, y, active in zip(a.mu_j_mol, b.mu_j_mol, centre.bulk))
        return derivative(lo, hi, 2*step), derivative(lhalf, hhalf, step)

    def equilibrate(self, mass, pressure_pa, temperature_k, *, cancel=None, deadline=None):
        check(cancel, deadline)
        p = finite(pressure_pa, 'pressure', positive=True)
        t = finite(temperature_k, 'temperature', positive=True)
        mass, n, total, bulk = self.inventory(mass)
        if self.backend.identity != self.identity:
            raise ValueError('backend identity changed')
        if not total:
            return State(self.identity, p, None, mass, 0., 0., 0., (), 0., 0., mass)
        c = self.controls
        centre = self.point(p, t, bulk, cancel=cancel, deadline=deadline)
        dt0, dt = self._stencil(centre, 't', c.temperature_step_k, cancel, deadline)
        dp0, dp = self._stencil(centre, 'p', c.pressure_step_pa, cancel, deadline)
        phases = []
        for s in centre.phases:
            amounts = tuple(total*x for x in s.amounts)
            pmass = tuple(finite(x*w, 'phase mass') for x, w in zip(amounts, self.molar_mass))
            if any(v > 0 and (x == 0 or m == 0) for v, x, m in zip(s.amounts, amounts, pmass)):
                raise ValueError('positive phase inventory underflows')
            smass = finite(math.fsum(pmass), 'phase total mass', positive=True)
            entropy, volume = -dot(amounts, dt), dot(amounts, dp)
            ds = abs(dot(amounts, tuple(a-b for a, b in zip(dt, dt0))))
            dv = abs(dot(amounts, tuple(a-b for a, b in zip(dp, dp0))))
            if (ds > smass*c.entropy_tolerance_j_kg_k+c.relative_derivative_tolerance*abs(entropy)
                    or dv > smass*c.volume_tolerance_m3_kg+c.relative_derivative_tolerance*abs(volume)
                    or volume <= 0):
                raise ValueError('phase thermodynamic derivative unresolved')
            h = finite(dot(amounts, centre.mu_j_mol)+t*entropy, 'phase enthalpy')
            phases.append(Phase(s.key, pmass, h, entropy, volume, ds, dv))
        entropy, volume = -dot(n, dt), dot(n, dp)
        h = finite(dot(n, centre.mu_j_mol)+t*entropy, 'enthalpy')
        if volume <= 0:
            raise ValueError('nonpositive volume')
        residual = tuple(math.fsum(s.component_mass_kg[i] for s in phases)-m
                         for i, m in enumerate(mass))
        check(cancel, deadline)
        return State(self.identity, p, t, mass, h, entropy, volume, tuple(phases),
                     math.fsum(s.entropy_discrepancy_j_k for s in phases),
                     math.fsum(s.volume_discrepancy_m3 for s in phases), residual)

    def flash(self, mass, pressure_pa, target, bracket_k, *, branch, constraint,
              tolerance, cancel=None, deadline=None):
        """Bracketed H or S inversion; phase-boundary/latent stencils refuse.

        Caller declares whole-interval support independently of these samples.
        Every sampled state must retain its declared phase identities; unsampled
        crossings are not excluded by this guard or by endpoint agreement.
        """
        if constraint not in ('enthalpy_j', 'entropy_j_k'):
            raise ValueError('choose enthalpy_j or entropy_j_k explicitly')
        target, tol = finite(target, 'target'), finite(tolerance, 'tolerance', positive=True)
        lo, hi = map(lambda v: finite(v, 'bracket temperature', positive=True), bracket_k)
        if not lo < hi:
            raise ValueError('ordered temperature bracket required')
        self._thermal_branch(branch, mass, pressure_pa, (lo, hi))
        a = self._branch_state(branch, self.equilibrate(mass, pressure_pa, lo,
                              cancel=cancel, deadline=deadline))
        b = self._branch_state(branch, self.equilibrate(mass, pressure_pa, hi,
                              cancel=cancel, deadline=deadline))
        va, vb = getattr(a, constraint), getattr(b, constraint)
        if not va <= target <= vb or not va < vb:
            raise ValueError('target not bracketed on a monotone branch')
        for _ in range(64):
            for r in (a, b):
                err = r.entropy_discrepancy_j_k
                if constraint == 'enthalpy_j':
                    err *= r.temperature_k
                if abs(getattr(r, constraint)-target)+err <= tol:
                    return r
            mid = (lo+hi)/2
            if not lo < mid < hi:
                break
            r = self._branch_state(branch, self.equilibrate(mass, pressure_pa, mid,
                                  cancel=cancel, deadline=deadline))
            value = getattr(r, constraint)
            if not va <= value <= vb:
                raise ValueError('non-monotone or unresolved thermal branch')
            if value < target:
                lo, a, va = mid, r, value
            else:
                hi, b, vb = mid, r, value
        raise ValueError('thermal inversion unresolved within numerical budget')

    def extract(self, state, fraction, *, liquid_key='liq'):
        """Finite source/parcel account proposal; no transport or commit."""
        if type(state) is not State or state.provider_id != self.identity:
            raise ValueError('matching common-provider state required')
        f = finite(fraction, 'extraction fraction')
        if not 0 <= f <= 1:
            raise ValueError('extraction fraction outside [0,1]')
        liquid = [s for s in state.phases if s.key == liquid_key]
        self.inventory(state.component_mass_kg)
        finite(state.enthalpy_j, 'source enthalpy')
        taken = tuple(f*math.fsum(s.component_mass_kg[i] for s in liquid)
                      for i in range(len(self.ids)))
        if f and any(any(s.component_mass_kg[i] > 0 for s in liquid) and x == 0
                     for i, x in enumerate(taken)):
            raise ValueError('positive transfer underflows')
        left = tuple(m-x for m, x in zip(state.component_mass_kg, taken))
        if any(x < 0 for x in left):
            raise ValueError('extraction exceeds represented source inventory')
        h = finite(f*math.fsum(s.enthalpy_j for s in liquid), 'carried enthalpy')
        return (Parcel(self.identity, state.pressure_pa, left,
                       finite(state.enthalpy_j-h, 'residue enthalpy')),
                Parcel(self.identity, state.pressure_pa, taken, h))

    def receive(self, receiver, parcel, bracket_k, *, branch, tolerance_j, cancel=None, deadline=None):
        if (type(receiver) is not State or type(parcel) is not Parcel
                or receiver.provider_id != self.identity or parcel.provider_id != self.identity
                or receiver.pressure_pa != parcel.pressure_pa):
            raise ValueError('matching provider and explicit common pressure required')
        m, _, _, _ = self.inventory(parcel.component_mass_kg)
        self.inventory(receiver.component_mass_kg)
        finite(parcel.enthalpy_j, 'incoming enthalpy')
        if not any(m):
            if parcel.enthalpy_j != 0:
                raise ValueError('empty parcel carries nonzero enthalpy')
            check(cancel, deadline)
            return receiver
        mass = tuple(finite(a+b, 'mixed mass') for a, b in zip(receiver.component_mass_kg, m))
        h = finite(receiver.enthalpy_j+parcel.enthalpy_j, 'mixed enthalpy')
        return self.flash(mass, receiver.pressure_pa, h, bracket_k,
                          branch=branch, constraint='enthalpy_j', tolerance=tolerance_j,
                          cancel=cancel, deadline=deadline)
