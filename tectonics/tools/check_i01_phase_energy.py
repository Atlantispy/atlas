"""I01 ideal-mixture phase/energy closure, not calibrated mantle or native magma.

SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "atlas_i01_energy_partition", ROOT/"tools/check_i01_phase_partition.py")
phase = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = phase
_spec.loader.exec_module(phase)
POLICY = dict(max_components=64, max_iterations=64, temperature_tolerance_k=1e-7,
              account_relative_tolerance=2e-11, benchmark_calls=40,
              benchmark_repetitions=3)


@dataclass(frozen=True, slots=True)
class Model:
    component_ids: tuple
    latent_j_kg: tuple
    melting_k: tuple
    solid_volume_m3_kg: tuple
    liquid_volume_m3_kg: tuple
    energy_offset_j_kg: tuple
    cp_j_kg_k: float
    mixing_r_j_kg_k: float
    reference_temperature_k: float
    reference_pressure_pa: float
    temperature_bounds_k: tuple
    pressure_bounds_pa: tuple
    source_id: str

    def __post_init__(self):
        ids = self.component_ids
        if (type(ids) is not tuple or not 1 <= len(ids) <= POLICY['max_components']
                or any(type(x) is not str or not x or len(x) > 128 for x in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError('unique bounded component identities required')
        for key in ('latent_j_kg', 'melting_k', 'solid_volume_m3_kg',
                    'liquid_volume_m3_kg', 'energy_offset_j_kg'):
            values = getattr(self, key)
            if type(values) is not tuple or len(values) != len(ids):
                raise ValueError('one immutable coefficient per component')
            object.__setattr__(self, key, tuple(phase.number(v, key,
                positive=key != 'energy_offset_j_kg') for v in values))
        for key in ('cp_j_kg_k', 'mixing_r_j_kg_k', 'reference_temperature_k',
                    'reference_pressure_pa'):
            object.__setattr__(self, key, phase.number(getattr(self, key), key,
                positive=key != 'reference_pressure_pa'))
        for key in ('temperature_bounds_k', 'pressure_bounds_pa'):
            values = getattr(self, key)
            if type(values) is not tuple or len(values) != 2:
                raise ValueError('two immutable support bounds required')
            bounds = tuple(phase.number(v, key) for v in values)
            if not 0 <= bounds[0] < bounds[1] or (key.startswith('temperature') and bounds[0] == 0):
                raise ValueError('invalid physical support')
            object.__setattr__(self, key, bounds)
        if (self.reference_pressure_pa < 0 or type(self.source_id) is not str
                or not self.source_id or len(self.source_id) > 256):
            raise ValueError('nonnegative reference pressure and source identity required')
        # Positive fusion enthalpy is the declared monotone-H support contract.
        for p in self.pressure_bounds_pa:
            for latent, vs, vl in zip(self.latent_j_kg, self.solid_volume_m3_kg,
                                       self.liquid_volume_m3_kg):
                phase.number(latent+(vl-vs)*(p-self.reference_pressure_pa),
                             'fusion enthalpy over pressure support', positive=True)


@dataclass(frozen=True, slots=True)
class PressureLaw:
    model: Model
    pressure_pa: float

    def __post_init__(self):
        if type(self.model) is not Model:
            raise ValueError('explicit immutable Model required')
        p = phase.number(self.pressure_pa, 'pressure')
        if not self.model.pressure_bounds_pa[0] <= p <= self.model.pressure_bounds_pa[1]:
            raise ValueError('pressure outside declared support')
        object.__setattr__(self, 'pressure_pa', p)

    def terms(self, temperature_k):
        t = phase.number(temperature_k, 'temperature', positive=True)
        m = self.model
        if not m.temperature_bounds_k[0] <= t <= m.temperature_bounds_k[1]:
            raise ValueError('temperature outside declared support')
        dp = self.pressure_pa-m.reference_pressure_pa
        dh = tuple(l+(vl-vs)*dp for l, vs, vl in zip(m.latent_j_kg,
                   m.solid_volume_m3_kg, m.liquid_volume_m3_kg))
        ds = tuple(l/tm for l, tm in zip(m.latent_j_kg, m.melting_k))
        logk = tuple((h/t-s)/m.mixing_r_j_kg_k for h, s in zip(dh, ds))
        bound = math.log(phase.POLICY['coefficient_max'])
        if any(not math.isfinite(k) or abs(k) > bound for k in logk):
            raise ValueError('partition coefficients outside represented support')
        hs = tuple(m.cp_j_kg_k*(t-m.reference_temperature_k)+e+vs*dp
                   for e, vs in zip(m.energy_offset_j_kg, m.solid_volume_m3_kg))
        return t, dh, ds, tuple(math.exp(k) for k in logk), hs


@dataclass(frozen=True, slots=True)
class State:
    law: PressureLaw
    temperature_k: float | None
    solid_mass_kg: tuple
    liquid_mass_kg: tuple
    enthalpy_j: float
    entropy_j_k: float
    volume_m3: float
    heat_capacity_j_k: float | None
    enthalpy_uncertainty_j: float

    @property
    def component_mass_kg(self):
        return tuple(s+l for s, l in zip(self.solid_mass_kg, self.liquid_mass_kg))


def _coexistence(law, mass):
    m = law.model
    dp = law.pressure_pa-m.reference_pressure_pa
    temperatures = tuple((l+(vl-vs)*dp)/(l/tm)
        for l, vl, vs, tm, amount in zip(m.latent_j_kg, m.liquid_volume_m3_kg,
            m.solid_volume_m3_kg, m.melting_k, mass) if amount)
    return temperatures[0] if temperatures and all(t == temperatures[0] for t in temperatures) else None


def _state(law, temperature_k, solid, liquid):
    """Rebuild all accounts and check phase stability; no caller account is trusted."""
    if type(law) is not PressureLaw:
        raise ValueError('prepared pressure law required')
    n = len(law.model.component_ids)
    solid, sm = phase.masses(solid, n)
    liquid, lm = phase.masses(liquid, n)
    total = sm+lm
    if not math.isfinite(total):
        raise ValueError('unrepresentable total mass')
    if not total:
        return State(law, None, solid, liquid, 0., 0., 0., 0., 0.)
    t, dh, ds, k, hs = law.terms(temperature_k)
    m = law.model
    bulk = tuple(s+l for s, l in zip(solid, liquid))
    b = tuple(v/total for v in bulk)
    if any(v > 0 and c == 0 for v, c in zip(bulk, b)):
        raise ValueError('component fraction underflows')
    tol = POLICY['account_relative_tolerance']
    if sm and lm:
        if any(abs(s/sm-ki*l/lm) > tol*max(1., abs(ki*l/lm))
               for s, l, ki in zip(solid, liquid, k)):
            raise ValueError('phase chemical equilibrium does not close')
    elif sm and math.fsum(c/ki for c, ki in zip(b, k)) > 1+tol:
        raise ValueError('unstable all-solid state')
    elif lm and math.fsum(c*ki for c, ki in zip(b, k)) > 1+tol:
        raise ValueError('unstable all-liquid state')
    h = math.fsum([v*x for v, x in zip(bulk, hs)]+
                  [l*x for l, x in zip(liquid, dh)])
    entropy = total*m.cp_j_kg_k*math.log(t/m.reference_temperature_k)
    entropy += math.fsum(l*x for l, x in zip(liquid, ds))
    # Ideal mixing with equal effective component molar masses: one common R.
    for amounts, amount in ((solid, sm), (liquid, lm)):
        if amount:
            entropy -= m.mixing_r_j_kg_k*math.fsum(x*math.log(x/amount)
                                                  for x in amounts if x)
    volume = math.fsum([s*v for s, v in zip(solid, m.solid_volume_m3_kg)]+
                       [l*v for l, v in zip(liquid, m.liquid_volume_m3_kg)])
    capacity = total*m.cp_j_kg_k
    uncertainty = 16*sys.float_info.epsilon*math.fsum(
        [abs(v*x) for v, x in zip(bulk, hs)]+[abs(l*x) for l, x in zip(liquid, dh)])
    if sm and lm:
        f = lm/total
        d = tuple(f+(1-f)*ki for ki in k)
        kt = tuple(-ki*h/(m.mixing_r_j_kg_k*t*t) for ki, h in zip(k, dh))
        rf = -math.fsum(c*((1-ki)/di)**2 for c, ki, di in zip(b, k, d))
        congruent = _coexistence(law, bulk)
        if congruent is not None and abs(t-congruent) <= 8*math.ulp(congruent):
            capacity = None  # Latent plateau: enthalpy, not T, specifies f.
        else:
            if rf == 0:
                raise ValueError('unresolved mixed-phase derivative')
            rt = -math.fsum(c*ki/di**2 for c, ki, di in zip(b, kt, d))
            ft = -rt/rf
            lt = tuple(v*(ki*ft-f*(1-f)*kti)/di**2
                       for v, ki, kti, di in zip(bulk, k, kt, d))
            capacity += math.fsum(h*x for h, x in zip(dh, lt))
            # Propagate the retained partition's f tolerance into the heat solve.
            df = 4*phase.POLICY['fraction_tolerance']
            dmin = tuple(min(max(0., f-df)+(1-max(0., f-df))*ki,
                            min(1., f+df)+(1-min(1., f+df))*ki) for ki in k)
            uncertainty += df*math.fsum(h*v*ki/di**2
                for h, v, ki, di in zip(dh, bulk, k, dmin))
    if not all(math.isfinite(x) for x in (h, entropy, volume)):
        raise ValueError('unrepresentable phase account')
    if capacity is not None and (not math.isfinite(capacity) or capacity < total*m.cp_j_kg_k):
        raise ValueError('invalid equilibrium heat capacity')
    if not math.isfinite(uncertainty):
        raise ValueError('unrepresentable energy uncertainty')
    return State(law, t, solid, liquid, h, entropy, volume, capacity, uncertainty)


def equilibrate(law, component_mass_kg, temperature_k, *, cancel=None, deadline=None):
    phase.check(cancel, deadline)
    if type(law) is not PressureLaw:
        raise ValueError('prepared pressure law required')
    t, _, _, k, _ = law.terms(temperature_k)
    mass, total = phase.masses(component_mass_kg, len(law.model.component_ids))
    tm = _coexistence(law, mass)
    if total and tm is not None and abs(t-tm) <= 8*math.ulp(tm):
        raise ValueError('coexistence needs enthalpy, not temperature alone')
    p = phase.Partition(law.model.component_ids, k, law.pressure_pa, t,
                        law.model.source_id)
    state = phase.equilibrate(p, mass, cancel=cancel, deadline=deadline)
    result = _state(law, t, state.solid_mass_kg, state.liquid_mass_kg)
    phase.check(cancel, deadline)
    return result


def _flash(law, component_mass_kg, enthalpy_j, *, newton, cancel=None, deadline=None):
    """Invert equilibrium H at one P. Never hold H fixed to claim an adiabat."""
    phase.check(cancel, deadline)
    if type(law) is not PressureLaw:
        raise ValueError('prepared pressure law required')
    m = law.model
    mass, total = phase.masses(component_mass_kg, len(m.component_ids))
    target = phase.number(enthalpy_j, 'enthalpy')
    if not total:
        if target != 0:
            raise ValueError('empty inventory cannot carry heat')
        phase.check(cancel, deadline)
        return _state(law, None, mass, mass), 0
    # Pure/congruent melting has a finite H interval at exactly one temperature.
    dp = law.pressure_pa-m.reference_pressure_pa
    dh = tuple(l+(vl-vs)*dp for l, vl, vs in zip(m.latent_j_kg,
                   m.liquid_volume_m3_kg, m.solid_volume_m3_kg))
    tm = _coexistence(law, mass)
    lo, hi = m.temperature_bounds_k
    hbase = math.fsum(v*(e+vs*dp) for v, e, vs in zip(mass,
                         m.energy_offset_j_kg, m.solid_volume_m3_kg))
    sensible = total*m.cp_j_kg_k
    tolerance = sensible*POLICY['temperature_tolerance_k']
    if tm is not None:
        tmel = tm
        hsolid = hbase+sensible*(tmel-m.reference_temperature_k)
        latent = math.fsum(v*h for v, h in zip(mass, dh))
        if hsolid <= target <= hsolid+latent:
            t, f = tmel, (target-hsolid)/latent
        else:
            f = 0. if target < hsolid else 1.
            t = m.reference_temperature_k+(target-hbase-f*latent)/sensible
        liquid = tuple(v*f for v in mass)
        result = _state(law, t, tuple(v-l for v, l in zip(mass, liquid)), liquid)
        if abs(result.enthalpy_j-target)+result.enthalpy_uncertainty_j > tolerance:
            raise ValueError('coexistence energy cannot resolve requested accuracy')
        phase.check(cancel, deadline)
        return result, 0
    low = equilibrate(law, mass, lo, cancel=cancel, deadline=deadline)
    high = equilibrate(law, mass, hi, cancel=cancel, deadline=deadline)
    if not low.enthalpy_j <= target <= high.enthalpy_j:
        raise ValueError('enthalpy outside declared temperature support')
    noise = 16*sys.float_info.epsilon*max(abs(target), abs(low.enthalpy_j), abs(high.enthalpy_j))
    if not math.isfinite(tolerance) or noise > tolerance:
        raise ValueError('energy datum cannot resolve requested temperature accuracy')
    t, previous_residual = (lo+hi)/2, math.inf
    for iterations in range(1, POLICY['max_iterations']+1):
        phase.check(cancel, deadline)
        state = equilibrate(law, mass, t, cancel=cancel, deadline=deadline)
        residual = state.enthalpy_j-target
        # H_T >= M cp proves the error bound on each smooth equilibrium branch.
        if abs(residual)+noise+state.enthalpy_uncertainty_j <= tolerance:
            phase.check(cancel, deadline)
            return state, iterations
        if residual < 0:
            lo = t
        else:
            hi = t
        trial = t-residual/state.heat_capacity_j_k if newton else math.nan
        # A root can legitimately sit very close to a bracket edge. Rejecting
        # that Newton step by a fixed margin needlessly falls back to bisection.
        # Instead require actual residual progress; otherwise bisect next.
        t = trial if lo < trial < hi and abs(residual) < previous_residual*.5 else (lo+hi)/2
        previous_residual = abs(residual)
    raise ValueError('phase energy iteration budget exhausted')


def flash(law, component_mass_kg, enthalpy_j, *, cancel=None, deadline=None):
    return _flash(law, component_mass_kg, enthalpy_j, newton=True,
                  cancel=cancel, deadline=deadline)[0]


def extract(state, fraction, *, cancel=None, deadline=None):
    """Same-P/T finite liquid split with compositional enthalpy; no flux law."""
    phase.check(cancel, deadline)
    if type(state) is not State or state != _state(state.law, state.temperature_k,
            state.solid_mass_kg, state.liquid_mass_kg):
        raise ValueError('state accounts differ from their physical law')
    alpha = phase.number(fraction, 'extraction fraction')
    if not 0 <= alpha <= 1:
        raise ValueError('fraction must be in [0,1]')
    if state.temperature_k is None:
        phase.check(cancel, deadline)
        return state, state
    _, _, _, k, _ = state.law.terms(state.temperature_k)
    p = phase.Partition(state.law.model.component_ids, k, state.law.pressure_pa,
                        state.temperature_k, state.law.model.source_id)
    residual, taken = phase.extract(phase.Phases(p, state.solid_mass_kg,
        state.liquid_mass_kg, 0), alpha, cancel=cancel, deadline=deadline)
    left = _state(state.law, state.temperature_k, residual.solid_mass_kg, residual.liquid_mass_kg)
    payload = _state(state.law, state.temperature_k, tuple(0. for _ in taken), taken)
    for name in ('enthalpy_j', 'entropy_j_k', 'volume_m3'):
        before, after, removed = (getattr(s, name) for s in (state, left, payload))
        scale = max(abs(before), abs(after)+abs(removed), sys.float_info.min)
        if abs(before-after-removed) > POLICY['account_relative_tolerance']*scale:
            raise ValueError('phase extraction account failed: '+name)
    phase.check(cancel, deadline)
    return left, payload


def model_from_json(spec):
    tuple_keys = ('component_ids', 'latent_j_kg', 'melting_k', 'solid_volume_m3_kg',
                  'liquid_volume_m3_kg', 'energy_offset_j_kg',
                  'temperature_bounds_k', 'pressure_bounds_pa')
    return Model(**{k: tuple(v) if k in tuple_keys else v for k, v in spec.items()})


def campaign(spec):
    model = model_from_json(spec['model'])
    law = PressureLaw(model, spec['pressure_pa'])
    mass = spec['component_mass_kg']
    state = equilibrate(law, mass, spec['temperature_k'])
    left, payload = extract(state, spec['extraction_fraction'])
    recovered = flash(law, left.component_mass_kg, left.enthalpy_j)
    cooled = flash(law, payload.component_mass_kg, spec['cooled_enthalpy_j'])
    heat_out = payload.enthalpy_j-cooled.enthalpy_j
    mass_error = max(abs(a-b-c) for a, b, c in zip(mass, left.component_mass_kg, payload.component_mass_kg))
    h_error = state.enthalpy_j-left.enthalpy_j-cooled.enthalpy_j-heat_out
    values = dict(initial_h_j=state.enthalpy_j, removed_h_j=payload.enthalpy_j,
        residual_h_j=left.enthalpy_j, removed_mass_kg=math.fsum(payload.component_mass_kg),
        residual_liquid_kg=math.fsum(recovered.liquid_mass_kg),
        recovered_temperature_k=recovered.temperature_k, cooled_temperature_k=cooled.temperature_k,
        cooled_liquid_kg=math.fsum(cooled.liquid_mass_kg), heat_to_surroundings_j=heat_out,
        component_residual_kg=mass_error, total_energy_residual_j=h_error)
    samples = {'newton': [], 'bisection': []}
    answers = {}
    for repeat in range(POLICY['benchmark_repetitions']):
        names = tuple(samples) if repeat % 2 == 0 else tuple(reversed(samples))
        for name in names:
            start = time.perf_counter()
            for _ in range(POLICY['benchmark_calls']):
                answers[name] = _flash(law, mass, state.enthalpy_j, newton=name == 'newton')
            samples[name].append(time.perf_counter()-start)
    fast, slow = (statistics.median(samples[k]) for k in ('newton', 'bisection'))
    parity = abs(answers['newton'][0].temperature_k-answers['bisection'][0].temperature_k)
    passed = all(abs(values[k]-expected) <= spec['absolute_tolerance'][k]
                 for k, expected in spec['expected'].items()) and parity <= 2*POLICY['temperature_tolerance_k']
    return dict(passed=passed, accounts=values, benchmark=dict(samples_seconds=samples,
        calls=POLICY['benchmark_calls'], newton_seconds=fast, bisection_seconds=slow,
        saved_seconds=slow-fast, saved_percent=100*(slow-fast)/slow,
        temperature_parity_k=parity, iterations={k:v[1] for k,v in answers.items()}),
        native_delivery_authorised=False, calibrated_mantle_model=False)


def bindings():
    names = ('tools/check_i01_phase_energy.py', 'tests/test_i01_phase_energy.py',
             'docs/I01_PHASE_ENERGY.md', 'cases/i01_phase_energy_v1.json',
             'tools/check_i01_phase_partition.py')
    return {'tectonics/'+p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    with args.output.open('x', encoding='utf-8', newline='\n') as out:
        report = dict(schema='atlas.i01-phase-energy-evidence.v1', status='FAIL',
            runtime=dict(python=platform.python_version(), platform=platform.system()))
        start = time.perf_counter()
        try:
            report['source_sha256'] = bindings()
            spec = json.loads((ROOT/'cases/i01_phase_energy_v1.json').read_text(encoding='utf-8'))
            if spec['policy'] != POLICY:
                raise ValueError('case and executable policy differ')
            report.update(campaign(spec))
            report['source_unchanged'] = report['source_sha256'] == bindings()
            if report['passed'] and report['source_unchanged']:
                report['status'] = 'PASS_BOUNDED_PHASE_ENERGY_ONLY'
        except Exception as exc:
            report.update(error_type=type(exc).__name__, error=str(exc))
        report['elapsed_seconds'] = time.perf_counter()-start
        json.dump(report, out, indent=2, allow_nan=False)
        out.write('\n')
    print(json.dumps({k:report[k] for k in ('status', 'elapsed_seconds')}))
    return 0 if report['status'] == 'PASS_BOUNDED_PHASE_ENERGY_ONLY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
