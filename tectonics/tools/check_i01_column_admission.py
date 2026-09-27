"""Conservative motion admission from the actual column; not physical rupture.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time

import numpy as np
from threadpoolctl import threadpool_limits

import check_i01_decoupling as d
import check_i01_motion_coupling as m

w = m.w
ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases/i01_column_admission_v1.json"
PRIOR = ROOT / "evidence/i01-motion-coupling-r1.json"
POLICY = dict(maximum_seconds=30., repetitions=10, batches=3,
              oracle_relative=1e-8, inequality_relative=1e-9)


def check_stop(cancel, deadline):
    w.column.check_cancel(cancel)
    w.check_deadline(deadline)


def fraction(value):
    return d.rational(float(value), "represented point value")


def factor_at(kappa, law, name):
    """Exact linear weakening factor for the represented input numbers."""
    start, end = fraction(law.start), fraction(law.end)
    u = min(Fraction(1), max(Fraction(0), (kappa-start)/(end-start)))
    return 1-(1-fraction(getattr(law, name)))*u


@dataclass(frozen=True, slots=True)
class ColumnEnvelope:
    column: w.PreparedColumn
    law: w.WeakeningLaw
    drive: m.Drive
    history_floor: tuple
    balance: d.Balance


def prepare(prep, law, kappa, drive, *, cancel=None, deadline=None):
    """Bound the represented quadrature model, not an uncomputed continuum.

    Every point needs a plastic branch. This upper bound discards nonnegative
    creep resistance contributions to rate, never changes the actual rheology.
    Borrow only the retained preparation's immutable arrays and copy history.
    """
    check_stop(cancel, deadline)
    if type(prep) is not w.PreparedColumn or type(law) is not w.WeakeningLaw or type(drive) is not m.Drive:
        raise ValueError("retained typed column, weakening law and drive required")
    if prep.closure not in (w.LITHOSTATIC, w.SUPPLIED) or drive.force_n_m <= 0:
        raise ValueError("positive extension and supported pressure closure required")
    if not np.all(prep.plastic) or not np.all(np.isfinite(prep.eta) & (prep.eta > 0)):
        raise ValueError("every point needs finite positive plastic regularisation")
    law.certify(prep)
    history = w.history_array(prep, kappa)
    floor = tuple(fraction(k) for k in history)
    yield_bound, viscosity = Fraction(0), Fraction(0)
    for j, k in enumerate(floor):
        check_stop(cancel, deadline)
        weight = fraction(prep.weight[j])
        if weight <= 0:
            raise ValueError("positive quadrature weights required")
        c = fraction(prep.cohesion_pa[j])*factor_at(k, law, "cohesion_factor")
        phi = fraction(prep.friction_rad[j])*factor_at(k, law, "friction_factor")
        effective = max(fraction(prep.reference_pa[j])-fraction(prep.pore_pa[j]), 0)
        # cos(phi)<=1 and sin(phi)<=min(1,phi), with phi>=0. These rational
        # bounds avoid claiming that a converged floating root is an enclosure.
        yield_bound += 2*weight*(c+effective*min(Fraction(1), phi))
        viscosity += 4*weight*fraction(prep.eta[j])
    balance = d.Balance(drive.force_n_m, drive.drag_pa_s, yield_bound,
                        viscosity/fraction(drive.width_m), 1)
    check_stop(cancel, deadline)
    return ColumnEnvelope(prep, law, drive, floor, balance)


def admit(envelope, prep, law, kappa, drive, *, duration_s, used_strain,
          relative_tolerance, displacement_limit_m, cancel=None, deadline=None):
    """Sufficient whole-window bound for fixed preparation/drive, growing history.

    Caller supplies already-used strain: a new call is not a strain-budget reset.
    Failure of the upper bound is NOT evidence that actual motion error is large.
    """
    check_stop(cancel, deadline)
    if type(envelope) is not ColumnEnvelope:
        raise ValueError("prepared column envelope required")
    if prep is not envelope.column or law != envelope.law or drive != envelope.drive:
        raise ValueError("changed preparation, law or drive requires a new envelope")
    history = w.history_array(prep, kappa)
    for k, lower in zip(history, envelope.history_floor):
        if fraction(k) < lower:
            raise ValueError("history has fallen outside the whole-window envelope")
    used = d.rational(used_strain, "already-used strain")
    duration = d.rational(duration_s, "duration", positive=True)
    v0 = envelope.balance.force/envelope.balance.drag
    total = used+duration*v0/fraction(drive.width_m)
    if total > d.rational(.05, "retained small-strain ceiling"):
        raise ValueError("window exceeds remaining small-strain allowance")
    result = d.window_admission(envelope.balance, envelope.balance,
        duration_s=duration, relative_tolerance=relative_tolerance,
        displacement_limit_m=displacement_limit_m)
    result.pop("snapshot_passed")  # the surrogate is an upper bound, not the actual snapshot
    result["status"] = "CERTIFIED_COLUMN_WINDOW" if result["numerical_admissible"] else "NOT_CERTIFIED_BY_BOUND"
    result["strain_upper_bound"] = d.upper_float(total)
    result["scope"] = "represented fixed column, drive and temperature; nondecreasing raw history; extension"
    check_stop(cancel, deadline)
    return result


def analytic_layer():
    return dict(name="analytical-linear", thickness_m=1000., temperature_k=[600., 600.],
        mean_pressure_pa=[0., 0.], pore_pressure_pa=[0., 0.], grain_m=.001,
        cohesion_pa=0., friction_rad=0., plastic_viscosity_pa_s=1e19,
        creep=[dict(a=1e-20, n=1., energy_j_mol=0.)])


def bounds(envelope):
    return dict(yield_bound_n_m=d.upper_float(envelope.balance.yield_force),
                linear_bound_pa_s=d.upper_float(envelope.balance.coefficient))


def campaign(spec, deadline):
    prior = w.load_case()
    law = w.law_of(prior)
    drive = m.Drive(**spec["drive"])
    rows = []
    for order in spec["orders"]:
        prep, _ = w.base_prepare(prior, order=order)
        history = w.initial_history(prep, prior)
        envelope = prepare(prep, law, history, drive, deadline=deadline)
        judgement = admit(envelope, prep, law, history, drive, duration_s=spec["duration_s"],
            used_strain=0., relative_tolerance=spec["relative_tolerance"],
            displacement_limit_m=spec["displacement_limit_m"], deadline=deadline)
        ratios = []
        for extra in (0., .08):
            actual = m.solve(prep, law, history+extra, drive, deadline=deadline)
            upper = envelope.balance.yield_force+envelope.balance.coefficient*fraction(actual["velocity_m_s"])
            ratios.append(abs(actual["force"])/float(upper))
        rows.append(dict(order=order, actual_force_to_bound=ratios,
                         judgment=judgement, **bounds(envelope)))

    # Independent exact homogeneous solution, with a nonzero creep contribution.
    layer = analytic_layer()
    simple = w.prepare([layer], 4, closure=w.SUPPLIED)
    zero = np.zeros(simple.size)
    env = prepare(simple, w.OFF, zero, drive, deadline=deadline)
    exact_k = 2*layer["thickness_m"]/(drive.width_m*(1e-20+1/(2e19)))
    exact_v = drive.force_n_m/(drive.drag_pa_s+exact_k)
    actual = m.solve(simple, w.OFF, zero, drive, deadline=deadline)
    analytical = admit(env, simple, w.OFF, zero, drive, duration_s=spec["duration_s"],
        used_strain=0., relative_tolerance=spec["analytical_tolerance"],
        displacement_limit_m=spec["displacement_limit_m"], deadline=deadline)
    relative = abs(actual["velocity_m_s"]-exact_v)/exact_v

    # Threshold is rational; equality and its stricter neighbour are decisive.
    edge = env.balance.coefficient/(env.balance.drag+env.balance.coefficient)
    prepared = d.PreparedBalance(env.balance)
    equality, tighter = prepared.admits(edge), prepared.admits(edge/2)

    # Actual mixed exponents within the same local constitutive response.
    mixed_layer = dict(layer, creep=layer["creep"]+[dict(a=1e-45, n=3.5, energy_j_mol=0.)])
    mixed = w.prepare([mixed_layer], 4, closure=w.SUPPLIED)
    mixed_env = prepare(mixed, w.OFF, zero, drive, deadline=deadline)
    mixed_actual = m.solve(mixed, w.OFF, zero, drive, deadline=deadline)
    mixed_upper = mixed_env.balance.yield_force+mixed_env.balance.coefficient*fraction(mixed_actual["velocity_m_s"])

    # Short genuine evolving history: it must stay above the prepared floors.
    prep, _ = w.base_prepare(prior, order=spec["orders"][0])
    history = w.initial_history(prep, prior)
    envelope = prepare(prep, law, history, drive, deadline=deadline)
    evolved = m.evolve(prep, law, history, drive, duration_s=spec["duration_s"], steps=8, deadline=deadline)
    end_admission = admit(envelope, prep, law, evolved["kappa"], drive,
        duration_s=spec["duration_s"], used_strain=abs(evolved["strain"]),
        relative_tolerance=spec["relative_tolerance"], displacement_limit_m=spec["displacement_limit_m"],
        deadline=deadline)

    # Same actual public call, recomputing versus reusing the immutable envelope.
    # Mechanical preparation is held fixed in both; guard/history checks remain.
    samples = dict(rebuilt=[], reused=[])
    parity = True
    for batch in range(POLICY["batches"]):
        for mode in (("rebuilt", "reused") if batch % 2 == 0 else ("reused", "rebuilt")):
            check_stop(None, deadline)
            start = time.perf_counter()
            for _ in range(POLICY["repetitions"]):
                candidate = prepare(prep, law, history, drive, deadline=deadline) if mode == "rebuilt" else envelope
                answer = admit(candidate, prep, law, evolved["kappa"], drive,
                    duration_s=spec["duration_s"], used_strain=abs(evolved["strain"]),
                    relative_tolerance=spec["relative_tolerance"],
                    displacement_limit_m=spec["displacement_limit_m"], deadline=deadline)
                parity &= answer == end_admission
            samples[mode].append(time.perf_counter()-start)
    slow, fast = (statistics.median(samples[k]) for k in ("rebuilt", "reused"))
    checks = dict(layer_bounds=max(max(r["actual_force_to_bound"]) for r in rows) <= 1+POLICY["inequality_relative"],
        honest_nonadmission=all(not r["judgment"]["numerical_admissible"] for r in rows),
        analytical=relative <= POLICY["oracle_relative"] and analytical["numerical_admissible"],
        exact_threshold=equality and not tighter,
        mixed_creep=abs(mixed_actual["force"]) <= float(mixed_upper)*(1+POLICY["inequality_relative"]),
        evolving=evolved["status"] == "COMPLETE" and np.all(evolved["kappa"] >= history),
        no_rupture=not end_admission["generated_separation_authorised"],
        same_decisions=parity)
    return w.verdict(checks, layered=rows, analytical=dict(relative_error=relative, judgment=analytical),
        mixed=dict(exponents=[1., 3.5], actual_force_n_m=mixed_actual["force"], bound_n_m=float(mixed_upper)),
        evolving=dict(strain=evolved["strain"], window_after_evolution=end_admission),
        benchmark=dict(count=POLICY["repetitions"], batches=POLICY["batches"], samples_seconds=samples,
            rebuilt_median_seconds=slow, reused_median_seconds=fast,
            saved_seconds=slow-fast, saved_percent=100*(1-fast/slow), decisions_equal=bool(parity),
            scope="same public admission calls, rebuilt versus reused envelope, including guards; retained mechanical preparation excluded in both; not simulation/world speedup"))


def bindings():
    paths = [Path(__file__), CASE, ROOT/"docs/I01_COLUMN_ADMISSION.md",
        ROOT/"tests/test_i01_column_admission.py", Path(d.__file__), Path(m.__file__),
        Path(w.__file__), Path(w.column.__file__), w.CASE, w.COLUMN_CASE, PRIOR,
        ROOT/"evidence/i01-decoupling-r1.json"]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream, threadpool_limits(limits=1, user_api="blas"):
        start = time.perf_counter()
        result = dict(schema="atlas.i01-column-admission-evidence.v1", status="INCOMPLETE",
            scientific_acceptance=False, runtime=dict(python=platform.python_version(), system=platform.system(),
            numpy=np.__version__, blas_threads=1))
        try:
            before = bindings()
            result["source_sha256"] = before
            spec = json.loads(CASE.read_text(encoding="utf-8"))
            if spec["schema"] != "atlas.i01-column-admission-case.v1" or spec["policy"] != POLICY:
                raise ValueError("case schema/policy mismatch")
            for source in (PRIOR, ROOT/"evidence/i01-decoupling-r1.json"):
                prior = json.loads(source.read_text(encoding="utf-8"))
                for name, digest in prior["source_sha256"].items():
                    if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest:
                        raise ValueError("retained reviewed prerequisite changed")
            result.update(case=spec, controls=campaign(spec, start+POLICY["maximum_seconds"]))
            result["source_unchanged"] = before == bindings()
            result["status"] = "PASS_BOUNDED_COLUMN_ADMISSION_ONLY" if result["controls"]["passed"] and result["source_unchanged"] else "FAIL"
        except Exception as exc:
            result.update(status="FAIL", error_type=type(exc).__name__, error=str(exc).replace(str(ROOT), "TECTONICS_ROOT"))
        result["elapsed_seconds"] = time.perf_counter()-start
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: result.get(k) for k in ("status", "elapsed_seconds", "error_type", "error")}))
    return 0 if result["status"] == "PASS_BOUNDED_COLUMN_ADMISSION_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
