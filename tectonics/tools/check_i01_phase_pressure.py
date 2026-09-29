"""I01 reversible pressure changes for the retained ideal-mixture energy law.

SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import time

import check_i01_phase_energy as energy

ROOT = Path(__file__).resolve().parents[1]
POLICY = dict(max_iterations=64, temperature_tolerance_k=1e-7,
              benchmark_calls=40, benchmark_repetitions=3, maximum_seconds=30.)


def entropy_uncertainty(state):
    """Finite partition/roundoff safeguard, not an interval-arithmetic proof."""
    if state.temperature_k is None:
        return 0.
    m = state.law.model
    mass = state.component_mass_kg
    total = math.fsum(mass)
    t, dh, ds, k, _ = state.law.terms(state.temperature_k)
    sensible = total*m.cp_j_kg_k
    terms = [abs(sensible*math.log(t/m.reference_temperature_k)), sensible]
    terms.extend(abs(l*s) for l, s in zip(state.liquid_mass_kg, ds))
    for amounts in (state.solid_mass_kg, state.liquid_mass_kg):
        amount = math.fsum(amounts)
        if amount:
            terms.extend(-m.mixing_r_j_kg_k*x*math.log(x/amount) for x in amounts if x)
    error = 64*sys.float_info.epsilon*math.fsum(terms)
    liquid, solid = math.fsum(state.liquid_mass_kg), math.fsum(state.solid_mass_kg)
    if liquid and solid and energy._coexistence(state.law, mass) is None:
        # Phase-normalisation error is included in the retained 4*tolerance.
        f = liquid/total
        df = 4*energy.phase.POLICY['fraction_tolerance']
        low, high = max(0., f-df), min(1., f+df)
        logbound = max(abs(math.log(ki)) for ki, mi in zip(k, mass) if mi)
        error += df*math.fsum(mi*ki/min(low+(1-low)*ki, high+(1-high)*ki)**2
            * (hi/t+m.mixing_r_j_kg_k*logbound) for mi, ki, hi in zip(mass, k, dh) if mi)
    if not math.isfinite(error):
        raise ValueError('unrepresentable entropy uncertainty')
    return error


def _flash_s(law, component_mass_kg, entropy_j_k, *, newton, cancel=None, deadline=None):
    """Solve equilibrium at (S,P); no pressure time-stepping or stored history."""
    energy.phase.check(cancel, deadline)
    if type(law) is not energy.PressureLaw:
        raise ValueError('prepared pressure law required')
    m = law.model
    mass, total = energy.phase.masses(component_mass_kg, len(m.component_ids))
    target = energy.phase.number(entropy_j_k, 'entropy')
    if not total:
        if target != 0:
            raise ValueError('empty inventory cannot carry entropy')
        return energy._state(law, None, mass, mass), 0
    lo, hi = m.temperature_bounds_k
    sensible = total*m.cp_j_kg_k
    tolerance = sensible/hi*POLICY['temperature_tolerance_k']
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError('entropy accuracy is unrepresentable')

    def accepted(state):
        return abs(state.entropy_j_k-target)+entropy_uncertainty(state) <= tolerance

    tm = energy._coexistence(law, mass)
    if tm is not None:
        mix = -m.mixing_r_j_kg_k*math.fsum(v*math.log(v/total) for v in mass if v)
        latent = math.fsum(v*l/t for v, l, t in zip(mass, m.latent_j_kg, m.melting_k))
        ssolid = sensible*math.log(tm/m.reference_temperature_k)+mix
        if ssolid <= target <= ssolid+latent:
            t, f = tm, (target-ssolid)/latent
        else:
            f = 0. if target < ssolid else 1.
            t = m.reference_temperature_k*math.exp((target-mix-f*latent)/sensible)
        liquid = tuple(v*f for v in mass)
        state = energy._state(law, t, tuple(v-l for v, l in zip(mass, liquid)), liquid)
        if not accepted(state):
            raise ValueError('coexistence entropy cannot resolve requested accuracy')
        energy.phase.check(cancel, deadline)
        return state, 0
    low = energy.equilibrate(law, mass, lo, cancel=cancel, deadline=deadline)
    high = energy.equilibrate(law, mass, hi, cancel=cancel, deadline=deadline)
    if not low.entropy_j_k <= target <= high.entropy_j_k:
        raise ValueError('entropy outside declared temperature support')
    for endpoint in (low, high):
        if accepted(endpoint):
            energy.phase.check(cancel, deadline)
            return endpoint, 0
    t, previous = (lo+hi)/2, math.inf
    for iterations in range(1, POLICY['max_iterations']+1):
        energy.phase.check(cancel, deadline)
        state = energy.equilibrate(law, mass, t, cancel=cancel, deadline=deadline)
        residual = state.entropy_j_k-target
        # Along smooth equilibrium branches S_T = H_T/T >= M cp/Tmax.
        if accepted(state):
            energy.phase.check(cancel, deadline)
            return state, iterations
        if residual < 0:
            lo = t
        else:
            hi = t
        trial = t-residual*t/state.heat_capacity_j_k if newton else math.nan
        t = trial if lo < trial < hi and abs(residual) < previous*.5 else (lo+hi)/2
        previous = abs(residual)
    raise ValueError('phase entropy iteration budget exhausted')


def flash_s(law, component_mass_kg, entropy_j_k, *, cancel=None, deadline=None):
    return _flash_s(law, component_mass_kg, entropy_j_k, newton=True,
                    cancel=cancel, deadline=deadline)[0]


@dataclass(frozen=True, slots=True)
class Movement:
    state: energy.State
    entropy_residual_j_k: float
    entropy_uncertainty_j_k: float
    component_residual_kg: tuple
    enthalpy_pressure_change_j: float
    compression_work_j: float
    work_uncertainty_j: float


def adiabatic_move(source, target_pressure_pa, *, cancel=None, deadline=None):
    """Closed reversible move, work positive into material. For a sampled path,
    always reuse the original source so rounding does not reset conserved S.
    """
    energy.phase.check(cancel, deadline)
    energy.extract(source, 0., cancel=cancel, deadline=deadline)  # Validate all accounts.
    law = energy.PressureLaw(source.law.model, target_pressure_pa)
    if law == source.law:
        return Movement(source, 0., entropy_uncertainty(source),
                        tuple(0. for _ in source.component_mass_kg), 0., 0., 0.)
    state = flash_s(law, source.component_mass_kg, source.entropy_j_k,
                    cancel=cancel, deadline=deadline)
    residual = tuple(a-b for a, b in zip(state.component_mass_kg, source.component_mass_kg))
    for delta, amount in zip(residual, source.component_mass_kg):
        if abs(delta) > energy.POLICY['account_relative_tolerance']*amount:
            raise ValueError('component mass changed along pressure path')
    sres = state.entropy_j_k-source.entropy_j_k
    serror = entropy_uncertainty(source)+entropy_uncertainty(state)
    dh = state.enthalpy_j-source.enthalpy_j
    # dH=V dP at dS=0, but external work is dU=-P dV, NOT dH.
    pv1, pv2 = source.law.pressure_pa*source.volume_m3, law.pressure_pa*state.volume_m3
    work = math.fsum((state.enthalpy_j, -source.enthalpy_j, -pv2, pv1))
    noise = 32*sys.float_info.epsilon*math.fsum((abs(source.enthalpy_j),
        abs(state.enthalpy_j), abs(pv1), abs(pv2)))
    error = source.enthalpy_uncertainty_j+state.enthalpy_uncertainty_j+noise
    error += source.law.model.temperature_bounds_k[1]*(serror+abs(sres))
    tolerance = 4*math.fsum(source.component_mass_kg)*law.model.cp_j_kg_k*POLICY['temperature_tolerance_k']
    if not all(math.isfinite(v) for v in (dh, work, error, tolerance)) or error > tolerance:
        raise ValueError('energy reference cannot resolve pressure-work accounts')
    energy.phase.check(cancel, deadline)
    return Movement(state, sres, serror, residual, dh, work, error)


def setup():
    spec = json.loads((ROOT/'cases/i01_phase_energy_v1.json').read_text(encoding='utf-8'))
    model = energy.model_from_json(spec['model'])
    law = energy.PressureLaw(model, spec['pressure_pa'])
    return energy.equilibrate(law, spec['component_mass_kg'], spec['temperature_k'])


def pure_fixture(spec):
    model = energy.model_from_json(spec['model'])
    law = energy.PressureLaw(model, spec['start_pressure_pa'])
    mass = spec['component_mass_kg']
    f = spec['start_liquid_fraction']
    liquid = tuple(v*f for v in mass)
    return energy._state(law, spec['start_temperature_k'],
                         tuple(v-l for v, l in zip(mass, liquid)), liquid)


def pressure_integral(source, target_pressure_pa, panels, *, deadline=None):
    """Independent composite Simpson control; not used by the endpoint solver."""
    dp = (target_pressure_pa-source.law.pressure_pa)/panels
    terms = []
    for j in range(panels+1):
        state = flash_s(energy.PressureLaw(source.law.model, source.law.pressure_pa+j*dp),
                        source.component_mass_kg, source.entropy_j_k, deadline=deadline)
        terms.append(state.volume_m3*(1 if j in (0, panels) else 4 if j % 2 else 2))
    return dp/3*math.fsum(terms)


def campaign(spec, deadline):
    source = setup()
    moved = adiabatic_move(source, spec['target_pressure_pa'], deadline=deadline)
    back = adiabatic_move(moved.state, source.law.pressure_pa, deadline=deadline)
    pure = adiabatic_move(pure_fixture(spec['pure']), spec['pure']['target_pressure_pa'], deadline=deadline)
    values = dict(temperature_k=pure.state.temperature_k,
        liquid_fraction=math.fsum(pure.state.liquid_mass_kg)/math.fsum(pure.state.component_mass_kg),
        enthalpy_pressure_change_j=pure.enthalpy_pressure_change_j,
        compression_work_j=pure.compression_work_j)
    integrals = {str(n): pressure_integral(source, spec['target_pressure_pa'], n, deadline=deadline)
                 for n in spec['simpson_panels']}
    errors = {n: abs(v-moved.enthalpy_pressure_change_j) for n, v in integrals.items()}
    checks = {k: abs(values[k]-v) <= spec['pure']['absolute_tolerance'][k]
              for k, v in spec['pure']['expected'].items()}
    checks.update(pressure_work_quadrature=errors[str(spec['simpson_panels'][-1])] <= spec['integral_tolerance_j'],
        quadrature_refines=all(a > b for a,b in zip(list(errors.values()), list(errors.values())[1:])),
        entropy=abs(moved.entropy_residual_j_k) <= math.fsum(source.component_mass_kg)*source.law.model.cp_j_kg_k
            /source.law.model.temperature_bounds_k[1]*POLICY['temperature_tolerance_k'],
        decompression_melts=math.fsum(moved.state.liquid_mass_kg) > math.fsum(source.liquid_mass_kg),
        melting_cools=moved.state.temperature_k < source.temperature_k,
        reverse_temperature=abs(back.state.temperature_k-source.temperature_k) <= 3*POLICY['temperature_tolerance_k'])
    samples, answers = {'newton': [], 'bisection': []}, {}
    law = moved.state.law
    for repeat in range(POLICY['benchmark_repetitions']):
        for name in (tuple(samples) if repeat % 2 == 0 else tuple(reversed(samples))):
            started = time.perf_counter()
            for _ in range(POLICY['benchmark_calls']):
                answers[name] = _flash_s(law, source.component_mass_kg, source.entropy_j_k,
                                         newton=name == 'newton', deadline=deadline)
            samples[name].append(time.perf_counter()-started)
    fast, slow = (statistics.median(samples[k]) for k in ('newton','bisection'))
    parity = abs(answers['newton'][0].temperature_k-answers['bisection'][0].temperature_k)
    checks['solver_parity'] = parity <= 2*POLICY['temperature_tolerance_k']
    energy.phase.check(None, deadline)
    return dict(passed=all(checks.values()), checks=checks, pure_accounts=values,
        binary_accounts=dict(temperature_k=moved.state.temperature_k, liquid_kg=math.fsum(moved.state.liquid_mass_kg),
            entropy_residual_j_k=moved.entropy_residual_j_k, entropy_uncertainty_j_k=moved.entropy_uncertainty_j_k,
            enthalpy_pressure_change_j=moved.enthalpy_pressure_change_j, compression_work_j=moved.compression_work_j,
            work_uncertainty_j=moved.work_uncertainty_j, integral_errors_j=errors),
        benchmark=dict(calls=POLICY['benchmark_calls'], samples_seconds=samples, newton_seconds=fast,
            bisection_seconds=slow, saved_seconds=slow-fast, saved_percent=100*(slow-fast)/slow,
            temperature_parity_k=parity, iterations={k:v[1] for k,v in answers.items()}),
        native_delivery_authorised=False, calibrated_mantle_model=False)


def bindings():
    names = ('tools/check_i01_phase_pressure.py','tests/test_i01_phase_pressure.py',
        'docs/I01_PHASE_PRESSURE.md','cases/i01_phase_pressure_v1.json',
        'tools/check_i01_phase_energy.py','tools/check_i01_phase_partition.py',
        'cases/i01_phase_energy_v1.json','tools/check_i01_magma_receiver.py')
    return {'tectonics/'+p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    with args.output.open('x', encoding='utf-8', newline='\n') as output:
        report = dict(schema='atlas.i01-phase-pressure-evidence.v1',status='FAIL',
            runtime=dict(python=platform.python_version(),platform=platform.system()))
        started = time.perf_counter()
        try:
            report['source_sha256'] = bindings()
            spec = json.loads((ROOT/'cases/i01_phase_pressure_v1.json').read_text(encoding='utf-8'))
            if spec['policy'] != POLICY:
                raise ValueError('case/executable policy differs')
            report.update(campaign(spec, started+POLICY['maximum_seconds']))
            report['source_unchanged'] = report['source_sha256'] == bindings()
            if report['passed'] and report['source_unchanged']:
                report['status'] = 'PASS_BOUNDED_PHASE_PRESSURE_ONLY'
        except Exception as error:
            report.update(error_type=type(error).__name__,error=str(error))
        report['elapsed_seconds'] = time.perf_counter()-started
        json.dump(report,output,indent=2,allow_nan=False)
        output.write('\n')
    print(json.dumps({k:report[k] for k in ('status','elapsed_seconds')}))
    return 0 if report['status'] == 'PASS_BOUNDED_PHASE_PRESSURE_ONLY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
