"""R10 saturation-aware nonlinear resolution; unchanged bound R6 physical laws.

The loop bodies below are explicit reviewed successors, not runtime source
rewrites or monkeypatches. R6 constitutive values, analytic Jacobian, temporal
comparison and physical type/serialization APIs are used through the supplied
sealed module. No predecessor is edited.
"""
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
import hashlib
import math
import numpy as np

IMPLEMENTATION = 'R10_SATURATION_BRANCH_RESOLUTION'
RETAINED_SOLVER_SHA256 = '9afea5168380577a53518f9d051948610151202e2110c5934c7a3695a1ceef9f'


def _source(module):
    path = Path(module.__file__).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def original_numerical_binding(solver):
    source = _source(solver)
    if source['sha256'] != RETAINED_SOLVER_SHA256:
        raise ValueError('adapter requires the explicitly reviewed sealed R6 solver')
    return {'implementation': 'R6_RETAINED_NUMERICAL_EXECUTION', 'adapter': None,
            'retained_solver': source, 'retained_hydraulic_kernel': _source(solver.hj)}


class Adapter:
    """Exact R6 physical types with explicit R10 numerical execution."""
    def __init__(self, bound_r6_solver):
        self._r6 = bound_r6_solver
        self._binding = original_numerical_binding(bound_r6_solver)
        path = Path(__file__).resolve()
        self._binding.update(implementation=IMPLEMENTATION,
            adapter={'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})

    def __getattr__(self, name):
        return getattr(self._r6, name)

    def numerical_binding(self):
        current = original_numerical_binding(self._r6)
        path = Path(__file__).resolve()
        current.update(implementation=IMPLEMENTATION,
            adapter={'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        if current != self._binding:
            raise ValueError('numerical source changed after adapter construction')
        return current

    def _stage(self, *args, **kwargs):
        return _stage(self._r6, *args, **kwargs)

    def _step(self, *args, **kwargs):
        return _step(self._r6, *args, **kwargs)

    def advance(self, *args, **kwargs):
        identity = self.numerical_binding()
        result = _advance(self._r6, *args, **kwargs)
        if self.numerical_binding() != identity:
            raise ValueError('numerical source changed during advance')
        return {**result, 'numerical_binding': identity}


def _log_effective_saturation(layer, head):
    if head >= 0:
        return 0.
    loga = math.log(layer.alpha_per_m)+math.log(-float(head))
    return -(1-1/layer.n)*float(np.logaddexp(0., layer.n*loga))


def storage_change_m(column, before, after):
    """Same VG law, with small water differences evaluated before adding theta_r.

    Subtracting two rounded theta values near saturation erases real capacity.
    expm1(log(Se_new)-log(Se_old)) preserves the constitutive difference, not an
    invented saturated compressibility. Positive head still has zero capacity.
    """
    rows = []
    for layer, left, right in zip(column.layers, before, after):
        a = _log_effective_saturation(layer, left)
        b = _log_effective_saturation(layer, right)
        difference = (-math.exp(b)*math.expm1(a-b) if b >= a
                      else math.exp(a)*math.expm1(b-a))
        rows.append((layer.theta_s-layer.theta_r)*layer.thickness_m*difference)
    value = np.asarray(rows)
    if not np.all(np.isfinite(value)):
        raise ValueError('unrepresentable stable retention storage difference')
    return value


def remaining_capacity_m(column, head):
    value = np.asarray([(layer.theta_s-layer.theta_r)*layer.thickness_m
                         *(-math.expm1(_log_effective_saturation(layer, value)))
                         for layer, value in zip(column.layers, head)])
    if not np.all(np.isfinite(value)) or np.any(value < 0):
        raise ValueError('unrepresentable remaining retention capacity')
    return value


def _stage(solver, column, old, dt, forcing, boundary, controls, *, kernel, known_source_m=None, guess=None):
    hj = solver.hj
    least_squares = solver.least_squares
    dz = np.array([x.thickness_m for x in column.layers])
    if kernel is None:
        kernel = hj.prepare(column, forcing, boundary)
    elif kernel.column is not column or kernel.forcing is not forcing or kernel.boundary is not boundary:
        raise ValueError('prepared hydraulic kernel belongs to different inputs')
    theta_old = kernel.properties(old)[0]
    def _fluxes(_column, head, _forcing, _boundary):
        values = kernel.fluxes(head)
        return values.theta, values.q, values.sink
    known_source_m = np.zeros(len(old)) if known_source_m is None else known_source_m
    def residual(head):
        theta, q, sink = _fluxes(column, head, forcing, boundary)
        return storage_change_m(column, old, head)-dt*(q[:-1]-q[1:]-sink)-known_source_m
    scale = max(controls.nonlinear_mass_atol_m, dt*max(forcing.surface_input_m_s, forcing.potential_et_m_s,
                                                     max(p.ksat_m_s for p in column.layers)))
    # The derivative is of the same mixed finite-volume residual. Avoid finite
    # differences between nearly equal water/flux values in very thin cells.
    # Cache only the most recent evaluation inside this solve: scipy commonly
    # asks for f and J at the same head, and no geometry/forcing state is reused.
    last_head, last_pair = None, None
    def evaluate(head):
        nonlocal last_head, last_pair
        if last_head is None or not np.array_equal(head, last_head):
            _, jac = kernel.residual_and_jacobian(head, theta_old, dt)
            last_pair = (residual(head), jac)
            last_head = head.copy()
        return last_pair
    def unresolved_saturation(value, physical):
        # A local-linear correction is not a nonlinear root-error bound when
        # the remaining capacity is smaller than the required storage change.
        remaining = remaining_capacity_m(column, value)
        return bool(np.any((value < 0) & (-physical > remaining)))
    solution = None
    start = np.asarray(old if guess is None else guess).copy()
    newton_evaluations = 0
    if controls.integration_method == 'SDIRK2':
        # Solving J dh=-F directly avoids minimising squared, very differently
        # scaled layer balances. A bounded correction-norm line search checks
        # pressure progress; actual scalar physical residuals remain authority.
        # This is only a nonlinear strategy, not a different time/soil equation.
        limit = min(40, max(0, controls.max_nfev-1))
        last_seeded = False
        def inspected(value):
            nonlocal newton_evaluations, last_seeded
            last_seeded = False
            # Fully saturated, connected no-flow columns cannot balance positive
            # imposed inflow on the inactive (supply-limited) surface branch.
            # Use zero-surface-head hydrostatic heads ONLY as a Newton trial;
            # the mixed residual still determines the final pressure/flux.
            # This does not alter old water content or add saturated storage.
            if (boundary.kind == 'no_flow' and forcing.surface_input_m_s > 0
                    and np.all(value >= 0) and all(p.ksat_m_s > 0 for p in column.layers)):
                required_top_flux = (math.fsum(remaining_capacity_m(column, old))
                                     -math.fsum(known_source_m))/dt
                _, initial_q, _ = _fluxes(column, value, forcing, boundary)
                if required_top_flux < forcing.surface_input_m_s and initial_q[0] == forcing.surface_input_m_s:
                    seed = np.cumsum(dz)-dz/2
                    if np.all(seed > controls.min_head_m) and np.all(seed < controls.max_head_m):
                        value = seed
                        last_seeded = True
            newton_evaluations += 1
            jac = evaluate(value)[1]
            physical = residual(value)
            correction = np.linalg.solve(jac, physical)
            ratio = float(np.max(np.abs(correction)/(controls.head_atol_m+controls.relative_tolerance*np.abs(value))))
            return value, (physical, jac, correction, ratio)
        try:
            if limit:
                start, (physical, jac, correction, ratio) = inspected(start)
                while newton_evaluations < limit:
                    if (ratio <= .01 and np.max(np.abs(physical)) <= controls.nonlinear_mass_atol_m
                            and not unresolved_saturation(start, physical)):
                        # A tolerated residual is not a reason to keep an
                        # easily removable stiff mode. One representable Newton
                        # polish avoids persistent tiny heads driving appreciable
                        # gross flux when conductance is extremely large.
                        candidate = start-correction
                        if (np.any(candidate != start) and np.all(candidate > controls.min_head_m)
                                and np.all(candidate < controls.max_head_m) and newton_evaluations < limit):
                            candidate, trial = inspected(candidate)
                            crosses = bool(np.any((candidate < 0) != (start < 0)))
                            if last_seeded or (crosses and np.max(np.abs(trial[0])) < np.max(np.abs(physical))):
                                start = candidate
                                physical, jac, correction, ratio = trial
                                continue
                            if trial[3] <= ratio and np.max(np.abs(trial[0])) <= np.max(np.abs(physical)):
                                start = candidate
                                physical, jac, correction, ratio = trial
                        solution = SimpleNamespace(x=start, jac=jac/scale, success=True,
                            nfev=newton_evaluations, status=1, message='bounded analytic Newton pressure and mass gates')
                        break
                    factor = 1.
                    improved = False
                    while newton_evaluations < limit and factor >= 2**-16:
                        candidate = start-factor*correction
                        if np.all(candidate > controls.min_head_m) and np.all(candidate < controls.max_head_m):
                            candidate, trial = inspected(candidate)
                            crosses = bool(np.any((candidate < 0) != (start < 0)))
                            branch_progress = last_seeded or (crosses and np.max(np.abs(trial[0])) < np.max(np.abs(physical)))
                            if (trial[3] < ratio or branch_progress
                                    or (trial[3] <= .01 and np.max(np.abs(trial[0])) <= controls.nonlinear_mass_atol_m
                                        and not unresolved_saturation(candidate, trial[0]))):
                                start = candidate
                                physical, jac, correction, ratio = trial
                                improved = True
                                break
                        factor /= 2
                    if not improved:
                        break
        except (np.linalg.LinAlgError, ValueError, FloatingPointError):
            # The unchanged bounded least-squares strategy remains a fallback;
            # all shared physical/rank/head acceptance gates still apply below.
            pass
    if solution is None:
        solution = least_squares(lambda h: evaluate(h)[0]/scale, start,
            jac=lambda h: evaluate(h)[1]/scale,
            bounds=(controls.min_head_m, controls.max_head_m), xtol=1e-13, ftol=1e-13, gtol=1e-13,
            max_nfev=controls.max_nfev-newton_evaluations, x_scale="jac")
        solution.nfev += newton_evaluations
    head = solution.x
    error = residual(head)
    if not solution.success or not np.all(np.isfinite(head)) or np.max(np.abs(error)) > controls.nonlinear_mass_atol_m:
        return None
    if unresolved_saturation(head, error):
        return None
    # Fully saturated isolated compartments have no retention capacity and can
    # leave pressure undetermined. A small mass residual is not a pressure solve.
    if np.linalg.matrix_rank(solution.jac) < len(old):
        return None
    # At very short dt, an unbalanced saturated head can have tiny integrated
    # mass error. Require the local Newton head correction to be small as well.
    try:
        correction = np.linalg.solve(solution.jac, error/scale)
    except np.linalg.LinAlgError:
        return None
    if np.max(np.abs(correction)/(controls.head_atol_m+controls.relative_tolerance*np.abs(head))) > .01:
        return None
    theta, q, sink = _fluxes(column, head, forcing, boundary)
    if np.any(head <= controls.min_head_m) or np.any(head >= controls.max_head_m):
        return None
    return {"head": head, "theta": theta, "q_m": dt*q, "et_m": dt*sink, "residual_m": error, "nfev": solution.nfev}


def _step(solver, column, old, dt, forcing, boundary, controls, *, kernel=None):
    """One bounded mixed-form step; all flux quadrature weights are positive.

    Alexander SDIRK2: gamma=1-1/sqrt(2), stiffly accurate second stage.
    The stage-2 known source is an integrated flux, NOT a fabricated water state.
    Signed transfers suffice for local error control; gross ledgers retain each
    stage separately to avoid cancelling opposing flows within one step.
    """
    hj = solver.hj
    if kernel is None:
        kernel = hj.prepare(column, forcing, boundary)
    initial_q_m = dt*kernel.fluxes(old).q
    if controls.integration_method == "BACKWARD_EULER":
        result = _stage(solver, column, old, dt, forcing, boundary, controls, kernel=kernel)
        if result is not None:
            result['quadrature'] = [(dt, result['q_m'], result['et_m'])]
            result['initial_q_m'] = initial_q_m
        return result
    gamma = 1-1/math.sqrt(2)
    first = _stage(solver, column, old, gamma*dt, forcing, boundary, controls, kernel=kernel)
    if first is None:
        return None
    weight = (1-gamma)/gamma
    first_q, first_et = weight*first['q_m'], weight*first['et_m']
    known_source = first_q[:-1]-first_q[1:]-first_et
    second = _stage(solver, column, old, gamma*dt, forcing, boundary, controls, kernel=kernel,
                    known_source_m=known_source, guess=first['head'])
    if second is None:
        return None
    q_m, et_m = first_q+second['q_m'], first_et+second['et_m']
    error = storage_change_m(column, old, second['head'])-(q_m[:-1]-q_m[1:]-et_m)
    if not np.all(np.isfinite(error)) or np.max(np.abs(error)) > controls.nonlinear_mass_atol_m:
        return None
    return {"head": second['head'], "theta": second['theta'], "q_m": q_m,
            "et_m": et_m, "residual_m": error, "nfev": first['nfev']+second['nfev'],
            "initial_q_m": initial_q_m,
            "quadrature": [((1-gamma)*dt, first_q, first_et),
                           (gamma*dt, second['q_m'], second['et_m'])]}



def _advance(solver, column, state, forcing, boundary, controls, *, water_density_kg_m3, gravity_m_s2):
    """Advance constant event forcing. Failure returns NULL state, never partial PASS.

    Accepted solution is TWO implicit half steps. A full step supplies independent
    local truncation estimates for heads, theta and signed integrated face fluxes.
    """
    Column, State, Forcing, Boundary, Controls = (solver.Column, solver.State, solver.Forcing, solver.Boundary, solver.Controls)
    _num, column_digest, _arrays, hj = solver._num, solver.column_digest, solver._arrays, solver.hj
    _temporal_errors = solver._temporal_errors
    if any(type(v) is not t for v, t in ((column, Column), (state, State), (forcing, Forcing), (boundary, Boundary), (controls, Controls))):
        raise ValueError("typed hydraulic column/state/forcing/boundary/controls required")
    if state.column_sha256 != column_digest(column) or len(state.head_m) != len(column.layers):
        raise ValueError("state belongs to a different hydraulic geometry/parameter binding")
    rho = _num(water_density_kg_m3, "water density")
    gravity = _num(gravity_m_s2, "gravity")
    if rho <= 0 or gravity <= 0:
        raise ValueError("positive fluid density and gravity required")
    if any(not controls.min_head_m < h < controls.max_head_m for h in state.head_m):
        raise ValueError("initial head outside numerical range")
    if forcing.uptake is not None and (len(forcing.uptake.weights) != len(column.layers) or any(w > 0 for w in forcing.uptake.weights[column.root_boundary_index:])):
        raise ValueError("uptake weights must match cells and remain above the root boundary")
    base = {"schema": "diadem.layered-richards.r6", "numerical_implementation": IMPLEMENTATION, "state": None, "layers": None, "ledger": None,
            "column_sha256": column_digest(column), "source_status": "SYNTHETIC TEST" if all(x.source_status == "SYNTHETIC TEST" for x in (*column.layers, column, forcing, boundary, *((forcing.uptake,) if forcing.uptake is not None else ()))) else "WORKING NON-CANON",
            "model": "1D_MIXED_RICHARDS_VG_MUALEM_"+controls.integration_method+"_STEP_DOUBLING",
            "physical_acceptance": False, "pore_pressure_support": "cell centre; not an inferred slip-plane or terrain-cell mean"}
    unknown = (not all(x.known for x in column.layers) or any(x.source_status == "UNKNOWN" for x in (column, forcing, boundary))
               or forcing.surface_input_m_s is None or forcing.potential_et_m_s is None
               or (boundary.kind == "fixed_head" and boundary.head_m is None)
               or (forcing.uptake is not None and forcing.uptake.source_status == "UNKNOWN"))
    if unknown:
        return {**base, "status": "UNKNOWN", "reason": "required hydraulic/forcing/uptake/boundary evidence unresolved"}
    if forcing.duration_seconds == 0:
        return {**base, "status": "NO_ADVANCE", "state": state, "reason": "zero duration does not certify re-equilibrated pressure"}
    kernel = hj.prepare(column, forcing, boundary)
    head = np.asarray(state.head_m)
    theta0 = kernel.properties(head)[0]
    n = len(head)
    dz = np.asarray([x.thickness_m for x in column.layers])
    time, dt, attempts, accepted = 0.0, controls.initial_dt_s, 0, 0
    exact_time = Fraction(0)
    exact_duration = Fraction(forcing.duration_seconds)
    down, up, ets, cell_residual = np.zeros(n+1), np.zeros(n+1), np.zeros(n), np.zeros(n)
    step_rows = []
    max_error = 0.0
    excess_terms = []
    rejected = {"nonlinear_solution": 0, "temporal_accuracy": 0}
    last_trial = None
    minimum_attempted_dt = None
    recovery_count = 0
    recovery_sequences = 0
    recovery_trials = 0
    recovery_floor_trial = None
    while exact_time < exact_duration:
        attempts += 1
        if attempts > controls.max_steps:
            return {**base, "status": "NUMERICAL_FAILURE", "reason": "adaptive work budget exceeded", "attempts": attempts,
                    "diagnostics": {"last_trial": last_trial, "rejected_trials": rejected}}
        remaining = exact_duration-exact_time
        dt = min(dt, float(remaining))
        # Never round a final subinterval beyond its exact remaining support.
        # The next loop advances any positive representable residual interval.
        if Fraction(dt) > remaining:
            dt = math.nextafter(dt, 0.)
        if dt <= 0:
            return {**base, "status": "NUMERICAL_FAILURE", "reason": "time interval unrepresentable"}
        full = _step(solver, column, head, dt, forcing, boundary, controls, kernel=kernel)
        first = _step(solver, column, head, dt/2, forcing, boundary, controls, kernel=kernel)
        second = None if first is None else _step(solver, column, first["head"], dt/2, forcing, boundary, controls, kernel=kernel)
        error = math.inf
        components, worst = None, None
        if full is not None and first is not None and second is not None:
            error, components, worst = _temporal_errors(column, full, first, second, controls)
        minimum_attempted_dt = dt if minimum_attempted_dt is None else min(minimum_attempted_dt, dt)
        nonlinear_pass = all(step is not None for step in (full, first, second))
        last_trial = {"column_id": column.column_id, "start_seconds": time,
                      "start_seconds_exact": str(exact_time), "initial_head_m": head.tolist(),
                      "dt_seconds": dt, "minimum_permitted_dt_seconds": controls.min_dt_s,
                      "minimum_layer_thickness_m": float(np.min(dz)),
                      "nonlinear_solutions_accepted": {"full": full is not None, "first_half": first is not None,
                                                        "second_half": second is not None},
                      "error_components": components, "worst_component": worst,
                      "retry_direction": "ascending_floor_recovery" if recovery_count else "ordinary_adaptive",
                      "recovery_trial": recovery_count,
                      "gate": "temporal_accuracy" if nonlinear_pass else "nonlinear_solution"}
        if recovery_count:
            recovery_trials += 1
        if error > 1:
            rejected[last_trial['gate']] += 1
            if recovery_count or dt/2 < controls.min_dt_s:
                # Near incompressible saturation an endpoint-pressure error is
                # not monotone in dt. Search larger trials only after halving
                # has reached the unchanged floor. Every trial spends the same
                # work budget and runs every original acceptance gate above.
                # No partial state, clock or flux is committed during search.
                candidate = min(dt*4, controls.max_dt_s, float(remaining))
                if Fraction(candidate) > remaining:
                    candidate = math.nextafter(candidate, 0.)
                if candidate > dt:
                    if not recovery_count:
                        recovery_sequences += 1
                        recovery_floor_trial = last_trial.copy()
                    recovery_count += 1
                    dt = candidate
                    continue
                reason = "bounded ascending recovery exhausted after floor failure; final "
                reason += ("temporal accuracy" if nonlinear_pass else "nonlinear solution") + " gate failed"
                # The retained R3 coupling propagates only reason, not this
                # result dictionary. Keep the material support visible there.
                if nonlinear_pass:
                    component = components[worst]
                    reason += (f" (column {column.column_id}; {worst} at {component['support_kind']} "
                               f"{component['support_index']}; error/allowance={component['error_ratio']}; "
                               f"attempted_dt={dt} s; floor={controls.min_dt_s} s)")
                return {**base, "status": "NUMERICAL_FAILURE", "reason": reason, "attempts": attempts,
                        "diagnostics": {"last_trial": last_trial, "rejected_trials": rejected,
                                        "floor_trial": recovery_floor_trial or last_trial,
                                        "interpretation": "No partial state accepted; time-step floor and all accuracy guards remain unchanged"}}
            dt /= 2
            continue
        for step in (first, second):
            for weight_dt, stage_q, stage_et in step['quadrature']:
                down += np.maximum(stage_q, 0)
                up += np.maximum(-stage_q, 0)
                ets += stage_et
                excess_terms.append(max(0.0, forcing.surface_input_m_s*weight_dt-max(float(stage_q[0]), 0.0)))
            cell_residual += step["residual_m"]
        head = second["head"]
        exact_time += Fraction(dt)
        time = float(exact_time)
        accepted += 1
        max_error = max(max_error, error)
        step_rows.append({"end_seconds": time, "end_seconds_exact": str(exact_time),
                          "dt_seconds": dt, "dt_seconds_exact": str(Fraction(dt)), "error_ratio": error,
                          "retry_direction": "ascending_floor_recovery" if recovery_count else "ordinary_adaptive",
                          "recovery_trials": recovery_count})
        recovery_count = 0
        recovery_floor_trial = None
        if error < .125:
            dt = min(2*dt, controls.max_dt_s)
    theta = kernel.properties(head)[0]
    initial_water = theta0*dz
    final_water = theta*dz
    incoming = forcing.surface_input_m_s*forcing.duration_seconds
    infiltration, exfiltration = float(down[0]), float(up[0])
    excess = math.fsum(excess_terms)
    residual = math.fsum([*initial_water, incoming, float(up[-1]), *(-ets), -float(down[-1]), -excess, -exfiltration, *(-final_water)])
    per_cell = final_water-initial_water-(down[:-1]-up[:-1])+(down[1:]-up[1:])+ets
    if excess < 0 or not math.isfinite(residual) or abs(residual) > controls.total_mass_atol_m or np.max(np.abs(per_cell)) > controls.total_mass_atol_m:
        return {**base, "status": "NUMERICAL_FAILURE", "reason": "final finite-volume water conservation gate failed", "water_residual_m": residual}
    root = column.root_boundary_index
    layers = []
    depth = 0.0
    for i, layer in enumerate(column.layers):
        pressure = rho*gravity*float(head[i])
        if not math.isfinite(pressure):
            raise ValueError("pore pressure overflow")
        layers.append({"layer_id": layer.layer_id, "top_depth_m": depth, "centre_depth_m": depth+layer.thickness_m/2,
                       "bottom_depth_m": depth+layer.thickness_m, "head_m": float(head[i]), "theta_m3_m3": float(theta[i]),
                       "effective_saturation": float((theta[i]-layer.theta_r)/(layer.theta_s-layer.theta_r)),
                       "pore_saturation": float(theta[i]/layer.theta_s), "water_m3_m2": float(final_water[i]),
                       "water_m3_m2_exact_represented": str(Fraction(float(theta[i]))*Fraction(layer.thickness_m)),
                       "signed_pore_pressure_pa": pressure, "positive_pore_pressure_pa": max(0.0, pressure),
                       "et_m": float(ets[i]), "water_residual_m": float(per_cell[i])})
        depth += layer.thickness_m
    following = State(tuple(float(h) for h in head), state.elapsed_seconds+forcing.duration_seconds, column_digest(column))
    return {**base, "status": "MODELLED", "state": following, "layers": layers,
            "ledger": {"initial_storage_m": float(math.fsum(initial_water)), "final_storage_m": float(math.fsum(final_water)),
                       "surface_input_m": incoming, "infiltration_m": infiltration, "rain_excess_runoff_m": excess,
                       "surface_exfiltration_m": exfiltration, "surface_runoff_m": excess+exfiltration,
                       "actual_et_m": float(math.fsum(ets)), "potential_et_m": forcing.potential_et_m_s*forcing.duration_seconds,
                       "bottom_downward_m": float(down[-1]), "bottom_upward_m": float(up[-1]),
                       "root_zone_gross_downward_m": float(down[root]), "root_zone_upward_capillary_m": float(up[root]),
                       "face_downward_m": down.tolist(), "face_upward_m": up.tolist(), "water_residual_m": residual},
            "numerics": {"accepted_steps": accepted, "attempts": attempts, "maximum_error_ratio": max_error,
                         "elapsed_seconds_exact": str(exact_time), "forcing_duration_seconds_exact": str(exact_duration),
                         "ascending_recovery_sequences": recovery_sequences, "ascending_recovery_trials": recovery_trials,
                         "rejected_trials": rejected, "minimum_attempted_dt_seconds": minimum_attempted_dt,
                         "controls": asdict(controls), "accepted_steps_detail": step_rows},
            "forcing": asdict(forcing), "lower_boundary": asdict(boundary),
            "fluid": {"water_density_kg_m3": rho, "gravity_m_s2": gravity},
            "scope": "matrix vertical flow, root-uptake ET only, zero pond storage; external fixed-head exchange explicitly counted"}
