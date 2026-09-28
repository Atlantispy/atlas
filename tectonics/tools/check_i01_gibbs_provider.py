"""Opt-in small G25 connection campaign, never a planet run or installer.

SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import asdict, replace
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import time

from i01_gibbs_provider import Provider, Controls
from magemin_g25 import MAGEMinG25

ROOT = Path(__file__).resolve().parents[1]
# Native predefined KLB1, test 0, from pinned MAGEMin; SOFTWARE comparison input,
# not reconstructed experimental chemistry or independently withheld calibration.
BULK = (0.38451319035870185, 0.017740308257833806, 0.028208688355924924,
        0.5050993397328966, 0.0587947378409965, 9.988912307338855e-5,
        0.0024972280768347137, 0.0009988912307338856,
        0.0009589355815045301, 0.0010887914414999351, 0.0)


def campaign(julia, project, depot):
    began = time.perf_counter()
    settings = dict(temperature_bounds_k=(1000., 2000.), pressure_bounds_pa=(1e8, 2e9))
    with MAGEMinG25(julia, project, depot, **settings) as backend:
        startup = time.perf_counter()-began
        provider = Provider(backend)
        mass = tuple(n*w for n, w in zip(BULK, backend.molar_mass_kg))
        mass = tuple(x/math.fsum(mass) for x in mass)
        p, t = 8e8, 1673.15
        solid = provider.equilibrate(mass, p, 1073.15)
        hot = provider.equilibrate(mass, p, t)
        assert all(s.key != 'liq' for s in solid.phases)
        liquid = next(s for s in hot.phases if s.key == 'liq')
        assert 0 < math.fsum(liquid.component_mass_kg) < math.fsum(mass)
        scaled = provider.equilibrate(tuple(4*x for x in mass), p, t)
        assert scaled.enthalpy_j == 4*hot.enthalpy_j
        # Halving the stencil is a numerical discrepancy check, not a formal
        # convergence order or proof of an unsampled smooth branch.
        fine_provider = Provider(backend, replace(Controls(), temperature_step_k=.5,
                                                  pressure_step_pa=5e5))
        fine = fine_provider.equilibrate(mass, p, t)

        def compare_phases(a, b):
            by_name = {s.key: s for s in b.phases}
            rows = []
            assert set(by_name) == {s.key for s in a.phases}
            for s in a.phases:
                other = by_name[s.key]
                ma, mb = math.fsum(s.component_mass_kg), math.fsum(other.component_mass_kg)
                sa, sb = s.entropy_j_k/ma, other.entropy_j_k/mb
                va, vb = s.volume_m3/ma, other.volume_m3/mb
                ds, dv = abs(sa-sb), abs(va-vb)
                assert ds <= .1+1e-3*max(abs(sa),abs(sb))
                assert dv <= 1e-8+1e-3*max(abs(va),abs(vb))
                rows.append(dict(phase=s.key, entropy_difference_j_kg_k=ds,
                                 volume_difference_m3_kg=dv))
            return rows
        refinement = compare_phases(hot, fine)
        # Change phase proportions, retaining the same equilibrium phase states:
        # a distinct bulk path must recover their specific thermodynamics.
        alternate_mass = tuple(math.fsum(s.component_mass_kg[i]*(1.3 if s.key == 'liq' else .9)
                               for s in hot.phases) for i in range(len(mass)))
        alternate = provider.equilibrate(alternate_mass, p, t)
        tie_line = compare_phases(hot, alternate)
        left, parcel = provider.extract(hot, .1)
        residue = provider.equilibrate(left.component_mass_kg, p, t)
        # Reference entropy discrepancies propagated as a comparison allowance;
        # not a certified error bound and not a law/coefficient fit.
        delta_h = residue.enthalpy_j+parcel.enthalpy_j-hot.enthalpy_j
        allowance_h = t*(hot.entropy_discrepancy_j_k+residue.entropy_discrepancy_j_k)+1.
        assert abs(delta_h) <= allowance_h
        for a, b, c in zip(left.component_mass_kg, parcel.component_mass_kg, mass):
            assert abs(a+b-c) <= 1e-15
        # Recombine the extracted liquid at the same P without inventing a new
        # caloric law. This small bracket stays within the tested thermal branch.
        joined_mass = tuple(a+b for a, b in zip(residue.component_mass_kg, parcel.component_mass_kg))
        branch_support = ('Declared continuous pre-existing-phase KLB1 branch within T_reference +/- 2 K; '
                          'conditional software control, not a proof excluding unsampled transitions')
        phase_keys = tuple(s.key for s in hot.phases)
        receiver_branch = provider.declare_thermal_branch(joined_mass, p, (t-2., t+2.),
            phase_keys=phase_keys, support=branch_support)
        entropy_branch = provider.declare_thermal_branch(mass, p, (t-2., t+2.),
            phase_keys=phase_keys, support=branch_support)
        joined = provider.receive(residue, parcel, (t-2., t+2.),
                                  branch=receiver_branch, tolerance_j=100.)
        assert abs(joined.temperature_k-t) < .1
        assert abs(joined.enthalpy_j-residue.enthalpy_j-parcel.enthalpy_j) < 100.
        entropy_recovery = provider.flash(mass, p, hot.entropy_j_k, (t-2.,t+2.),
                                          branch=entropy_branch, constraint='entropy_j_k', tolerance=.1)
        assert abs(entropy_recovery.temperature_k-t) < .01
        # Deliberate coarse stencil crosses phase appearance: must refuse.
        refused = False
        try:
            Provider(backend, replace(Controls(), temperature_step_k=500.)).equilibrate(mass,p,1500.)
        except ValueError as exc:
            refused = 'phase boundary' in str(exc)
        assert refused
        cold, warm = [], []
        for _ in range(3):
            provider.cache.clear()
            a = time.perf_counter()
            fresh = provider.equilibrate(mass,p,t)
            cold.append(time.perf_counter()-a)
            a = time.perf_counter()
            reused = provider.equilibrate(mass,p,t)
            warm.append(time.perf_counter()-a)
            assert fresh == reused
        result = dict(scientific_acceptance=False,
            status='PASS_BOUNDED_G25_COMMON_GIBBS_CONNECTION_ONLY',
            python=platform.python_version(), system=platform.system(),
            input_kind='pinned native KLB1 software reference; not withheld experiment',
            metadata=backend.metadata, native=backend.last_metadata,
            controls=asdict(provider.controls), input_mass_kg=mass,
            solid=asdict(solid), melting=asdict(hot),
            refinement=refinement, changed_bulk_phase_comparison=tie_line,
            extraction=dict(enthalpy_residual_j=delta_h, comparison_allowance_j=allowance_h,
                            parcel=asdict(parcel)),
            receiver_temperature_k=joined.temperature_k,
            entropy_recovery_temperature_k=entropy_recovery.temperature_k,
            declared_thermal_branches={'receiver': asdict(receiver_branch),
                                       'entropy_recovery': asdict(entropy_branch)},
            phase_boundary_refused=refused, startup_seconds=startup,
            timing=dict(uncached_samples_s=cold, cached_samples_s=warm,
                        uncached_median_s=statistics.median(cold),
                        cached_median_s=statistics.median(warm), cached_bit_identical=True),
            elapsed_seconds=time.perf_counter()-began,
            limitations=['not withheld geological calibration', 'no latent-plateau inversion',
                         'declared branch support; sampled phase agreement is not an interval certificate',
                         'no extraction rate, focusing or axial lid',
                         'no spatial transport or persistent transaction',
                         'Windows run; Linux not executed'])
    result['timing']['saved_seconds'] = statistics.median(cold)-statistics.median(warm)
    result['timing']['saved_percent'] = 100*(1-statistics.median(warm)/statistics.median(cold))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('julia','project','depot','output'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    paths = ['tools/i01_gibbs_provider.py','tools/magemin_g25.py','tools/magemin_g25.jl',
             'tools/check_i01_gibbs_provider.py','tests/test_i01_gibbs_provider.py',
             'docs/I01_THERMO_PROVIDER_CONTRACT.md']
    # Prove destination permission/no-overwrite BEFORE any native work. A failed
    # run leaves an explicitly incomplete record, never a false success receipt.
    with Path(args.output).open('x', encoding='utf-8') as stream:
        json.dump({'status':'INCOMPLETE','scientific_acceptance':False},stream)
        stream.flush()
        before = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
        result = campaign(args.julia,args.project,args.depot)
        assert before == {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
        result['source_bindings'] = before
        stream.seek(0)
        json.dump(result,stream,indent=2,allow_nan=False)
        stream.write('\n')
        stream.truncate()
    print(json.dumps({k:result[k] for k in ('status','elapsed_seconds','timing')},indent=2))


if __name__ == '__main__':
    main()
