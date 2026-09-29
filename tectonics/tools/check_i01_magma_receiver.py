"""I01 finite isobaric ideal-mixture receiver; WORKING NON-CANON.

No flow-rate law, pressure transport, native emplacement or persisted transaction.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
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
POLICY = dict(max_parcels=64, maximum_seconds=30., benchmark_calls=20,
              benchmark_batches=3, benchmark_parcels=8)


@dataclass(frozen=True, slots=True)
class Receipt:
    state: energy.State
    incoming_mass_kg: float
    incoming_enthalpy_j: float
    component_residual_kg: tuple
    enthalpy_residual_j: float
    energy_allowance_j: float
    entropy_production_j_k: float
    entropy_allowance_j_k: float
    boundary_work_j: float
    internal_energy_residual_j: float
    net_crystallised_kg: float


@dataclass(frozen=True, slots=True)
class Transfer:
    donor: energy.State
    receiver: Receipt
    parcel: energy.State


def checked(state, *, cancel=None, deadline=None):
    # Public zero extraction reconstructs all stored accounts and phase stability.
    energy.extract(state, 0., cancel=cancel, deadline=deadline)
    return state


def receive_many(receiver, parcels, *, cancel=None, deadline=None):
    """Co-add bounded liquid parcels at one P/law, then equilibrate once.

    Adiabatic, well-mixed final state, only P dV external work. No temporal ordering
    or intervening losses/reactions with outside material is represented.
    """
    energy.phase.check(cancel, deadline)
    if type(parcels) is not tuple or len(parcels) > POLICY['max_parcels']:
        raise ValueError('bounded immutable parcel tuple required')
    checked(receiver, cancel=cancel, deadline=deadline)
    for parcel in parcels:
        checked(parcel, cancel=cancel, deadline=deadline)
        if parcel.law != receiver.law:
            raise ValueError('same pressure, component order and complete material/energy law required')
        if any(parcel.solid_mass_kg):
            raise ValueError('only existing liquid parcels are admitted')
    parts = (receiver,)+parcels
    count = len(receiver.component_mass_kg)
    added = tuple(math.fsum(p.component_mass_kg[i] for p in parcels) for i in range(count))
    mass = tuple(math.fsum(p.component_mass_kg[i] for p in parts) for i in range(count))
    if any(a > 0 and c == b for a,b,c in zip(added,receiver.component_mass_kg,mass)):
        raise ValueError('receiver credit below numerical resolution')
    target = math.fsum(p.enthalpy_j for p in parts)
    if not all(math.isfinite(x) for x in (*mass,target)):
        raise ValueError('unrepresentable receiver inventory')
    if not any(added):
        result = receiver
    elif not any(receiver.component_mass_kg) and len(parcels) == 1:
        result = parcels[0]  # Already validated equilibrium; no inversion needed.
    else:
        result = energy.flash(receiver.law, mass, target, cancel=cancel, deadline=deadline)
    errors = tuple(a-b for a,b in zip(result.component_mass_kg,mass))
    total = math.fsum(mass)
    hres = result.enthalpy_j-target
    scale = math.fsum(abs(p.enthalpy_j) for p in parts)+abs(result.enthalpy_j)
    allowance = total*receiver.law.model.cp_j_kg_k*energy.POLICY['temperature_tolerance_k']
    allowance += 64*sys.float_info.epsilon*scale
    if (any(abs(x) > energy.POLICY['account_relative_tolerance']*total for x in errors)
            or abs(hres) > allowance):
        raise ValueError('receiver component or enthalpy account failed')
    sbefore = math.fsum(p.entropy_j_k for p in parts)
    entropy = result.entropy_j_k-sbefore
    slower = receiver.law.model.temperature_bounds_k[0]
    sallow = (abs(hres)+result.enthalpy_uncertainty_j)/slower
    sallow += 64*sys.float_info.epsilon*math.fsum(abs(p.entropy_j_k) for p in (*parts,result))
    if entropy < -sallow:
        raise ValueError('receiver entropy decrease exceeds numerical allowance')
    p = receiver.law.pressure_pa
    work = p*(result.volume_m3-math.fsum(x.volume_m3 for x in parts))
    internal_before = math.fsum(x.enthalpy_j-p*x.volume_m3 for x in parts)
    ures = result.enthalpy_j-p*result.volume_m3-internal_before+work
    # U arithmetic additionally subtracts P V, which may exceed the chosen H datum.
    uallow = allowance+64*sys.float_info.epsilon*math.fsum(
        abs(p*x.volume_m3) for x in (*parts,result))
    if not all(math.isfinite(x) for x in (hres,allowance,entropy,sallow,work,ures,uallow)):
        raise ValueError('unrepresentable receiver energy/work account')
    if abs(ures) > uallow:
        raise ValueError('receiver internal energy and boundary work do not close')
    receipt = Receipt(result, math.fsum(added), math.fsum(x.enthalpy_j for x in parcels), errors,
        hres, allowance, entropy, sallow, work, ures,
        math.fsum(v for x in parts for v in x.liquid_mass_kg)-math.fsum(result.liquid_mass_kg))
    energy.phase.check(cancel, deadline)
    return receipt


def transfer(donor, receiver, fraction, *, cancel=None, deadline=None):
    """Return both candidate states only after every check succeeds; input states never mutate."""
    energy.phase.check(cancel, deadline)
    if donor is receiver:
        raise ValueError('donor and receiver must be distinct inventories')
    left, parcel = energy.extract(donor, fraction, cancel=cancel, deadline=deadline)
    received = receive_many(receiver, (parcel,), cancel=cancel, deadline=deadline)
    energy.phase.check(cancel, deadline)
    return Transfer(left, received, parcel)


def setup():
    spec = json.loads((ROOT/'cases/i01_phase_energy_v1.json').read_text(encoding='utf-8'))
    model = energy.model_from_json(spec['model'])
    return model, energy.PressureLaw(model,spec['pressure_pa'])


def campaign(case, deadline):
    model, law = setup()
    pure = energy.PressureLaw(replace(model,melting_k=(1500.,1500.)),law.pressure_pa)
    donor = energy.equilibrate(pure,(1000.,0.),1800.,deadline=deadline)
    cold = energy.equilibrate(pure,(1000.,0.),1000.,deadline=deadline)
    analytic = transfer(donor,cold,1.,deadline=deadline)
    expected_entropy = (2000000*math.log(1.5)+(1000/3)*200
                        -1000000*math.log(1.8)-200000)
    source = energy.equilibrate(law,(4000.,6000.),1500.,deadline=deadline)
    receiver = energy.equilibrate(law,(2000.,3000.),1000.,deadline=deadline)
    connected = transfer(source,receiver,.5,deadline=deadline)
    refractory = energy.equilibrate(law,(0.,8000.),1000.,deadline=deadline)
    binary = transfer(source,refractory,.5,deadline=deadline)
    second = transfer(connected.donor,connected.receiver.state,.5,deadline=deadline)
    total_mass = tuple(a+b for a,b in zip(source.component_mass_kg,receiver.component_mass_kg))
    remainder = tuple(a+b for a,b in zip(second.donor.component_mass_kg,
                                         second.receiver.state.component_mass_kg))
    total_h = source.enthalpy_j+receiver.enthalpy_j
    closed_h = second.donor.enthalpy_j+second.receiver.state.enthalpy_j
    # Same co-added parcels with no intermediate external exchanges. Sequential
    # mixing is a diagnostic comparator, not the physical timing of emplacement.
    parcels = tuple(energy.equilibrate(law,(50.+5*i,50.),2100.+10*i,deadline=deadline)
                    for i in range(POLICY['benchmark_parcels']))
    samples = dict(batch=[],sequential=[])
    answers = {}
    for repetition in range(POLICY['benchmark_batches']):
        names = ('batch','sequential') if repetition%2 == 0 else ('sequential','batch')
        for name in names:
            started = time.perf_counter()
            for _ in range(POLICY['benchmark_calls']):
                if name == 'batch':
                    final = receive_many(receiver,parcels,deadline=deadline)
                else:
                    state = receiver
                    for parcel in parcels:
                        final = receive_many(state,(parcel,),deadline=deadline)
                        state = final.state
                answers[name] = final.state
            samples[name].append(time.perf_counter()-started)
    fast,slow = (statistics.median(samples[n]) for n in ('batch','sequential'))
    parity = abs(answers['batch'].temperature_k-answers['sequential'].temperature_k)
    checks = dict(analytic_temperature=abs(analytic.receiver.state.temperature_k-1500.)<=1e-7,
        analytic_liquid=abs(math.fsum(analytic.receiver.state.liquid_mass_kg)-1000/3)<=1e-6,
        analytic_energy=abs(analytic.receiver.state.enthalpy_j-1.1e9)<=.01,
        analytic_entropy=abs(analytic.receiver.entropy_production_j_k-expected_entropy)<=1e-6,
        binary_analytic=abs(binary.receiver.state.temperature_k-1100.)<=1e-7
            and math.fsum(binary.receiver.state.liquid_mass_kg)==0.
            and abs(binary.receiver.entropy_production_j_k-336550.367259013)<=.01,
        component_conservation=max(abs(a-b) for a,b in zip(total_mass,remainder))<=1e-8,
        repeated_energy=abs(closed_h-total_h)<=3.,
        batch_temperature=parity<=POLICY['benchmark_parcels']*energy.POLICY['temperature_tolerance_k'],
        batch_components=max(abs(a-b) for a,b in zip(answers['batch'].component_mass_kg,
            answers['sequential'].component_mass_kg))<=1e-8,
        batch_energy=abs(answers['batch'].enthalpy_j-answers['sequential'].enthalpy_j)<=5.)
    values = dict(temperature_k=analytic.receiver.state.temperature_k,
        liquid_kg=math.fsum(analytic.receiver.state.liquid_mass_kg),
        crystallised_kg=analytic.receiver.net_crystallised_kg,
        entropy_production_j_k=analytic.receiver.entropy_production_j_k,
        boundary_work_j=analytic.receiver.boundary_work_j,
        internal_energy_residual_j=analytic.receiver.internal_energy_residual_j,
        repeated_energy_residual_j=closed_h-total_h,
        connected_receiver_temperature_k=connected.receiver.state.temperature_k,
        binary_temperature_k=binary.receiver.state.temperature_k,
        binary_entropy_production_j_k=binary.receiver.entropy_production_j_k,
        binary_boundary_work_j=binary.receiver.boundary_work_j)
    energy.phase.check(None,deadline)
    return dict(passed=all(checks.values()),checks=checks,accounts=values,
        benchmark=dict(samples_seconds=samples,calls=POLICY['benchmark_calls'],
            parcels_per_call=len(parcels),batch_seconds=fast,sequential_seconds=slow,
            saved_seconds=slow-fast,saved_percent=100*(slow-fast)/slow,temperature_parity_k=parity),
        native_delivery_authorised=False,calibrated_mantle_model=False)


def bindings():
    names=('tools/check_i01_magma_receiver.py','tests/test_i01_magma_receiver.py',
        'docs/I01_MAGMA_RECEIVER.md','cases/i01_magma_receiver_v1.json',
        'tools/check_i01_phase_energy.py','tools/check_i01_phase_partition.py','cases/i01_phase_energy_v1.json')
    return {'tectonics/'+p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in names}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    with args.output.open('x',encoding='utf-8',newline='\n') as output:
        report=dict(schema='atlas.i01-magma-receiver-evidence.v1',status='FAIL',
                    runtime=dict(python=platform.python_version(),platform=platform.system()))
        started=time.perf_counter()
        try:
            report['source_sha256']=bindings()
            case=json.loads((ROOT/'cases/i01_magma_receiver_v1.json').read_text(encoding='utf-8'))
            if case['policy'] != POLICY:
                raise ValueError('case/executable policy differs')
            report.update(campaign(case,started+POLICY['maximum_seconds']))
            report['source_unchanged']=report['source_sha256']==bindings()
            if report['passed'] and report['source_unchanged']:
                report['status']='PASS_BOUNDED_MAGMA_RECEIVER_ONLY'
        except Exception as error:
            report.update(error_type=type(error).__name__,error=str(error))
        report['elapsed_seconds']=time.perf_counter()-started
        json.dump(report,output,indent=2,allow_nan=False)
        output.write('\n')
    print(json.dumps({k:report[k] for k in ('status','elapsed_seconds')}))
    return 0 if report['status']=='PASS_BOUNDED_MAGMA_RECEIVER_ONLY' else 1


if __name__=='__main__':
    raise SystemExit(main())
