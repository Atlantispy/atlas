"""Focused bulk-flux and W=0 analytical checks; no empirical terrain claim."""
from __future__ import annotations

import json
import math
import sys
import time
import unittest

from work.native_terrain_r1.hillslope import Grid, face_requests
from work.terrain_model_r7.hillslope_kernel import State, hillslope_step


ORACLE_RESULTS = []


def toe_faces(grid, elevation=0.0):
    return [{"id": f"toe-{row}", "cell": row * grid.cols + grid.cols - 1,
             "elevation_m": elevation, "distance_m": grid.dx_m / 2,
             "width_m": grid.dy_m, "axis": "x+",
             "evidence": "SYNTHETIC W=0 numerical fixed toe at x=L"}
            for row in range(grid.rows)]


def allocated_updates(requests, available):
    """Independent binary64 fixture application, not a native layer adapter."""
    terms = [[value] for value in available]
    exports = []
    for face in requests["faces"]:
        amount = face["requested_bulk_m3"] * requests["source_scale_factors"][face["donor"]]
        terms[face["donor"]].append(-amount)
        if face["receiver"] is None:
            exports.append(amount)
        else:
            terms[face["receiver"]].append(amount)
    return [math.fsum(values) for values in terms], math.fsum(exports)


def decay_oracle():
    """Freeze actual scheme/bands before each trajectory, then score.

    Cell-centred x_i=(i+.5)h; reflected ghost z_-1=z_0 and fixed-toe
    ghost z_N=-z_(N-1) give eigenvalue lambda_h=4K sin²(pi h/4L)/h².
    The two identical rows have zero y transport. Forward Euler multiplies
    amplitude by (1-lambda_h dt) each step; variable endpoint segment steps
    therefore add steps*log1p(-lambda_h dt). The actual total relative
    discretisation band is |expm1(log_amplitude+t/tau)|, not the spatial-only
    expm1((1-lambda_h*tau)*t/tau).

    Both are calculated BEFORE the numerical trajectory. A separate absolute
    roundoff envelope is 64 eps (B+A) (steps+1) metres with B=1m cover base,
    plus atol=1e-13m and rtol=1e-12 at initial amplitude A. The explicit
    stencil is monotone under our CFL, so errors accumulate without an
    unstable amplification factor. This generous per-step binary64 envelope
    includes stock/surface subtraction and geometry arithmetic. No native
    rational conversion or quantisation occurs in this kernel-only oracle.
    The omitted divide face and declared half-cell toe match the ghost stencil;
    the analytical boundary modelling error for this chosen problem is zero.
    """
    results = []
    length, amplitude, kappa, base = 1.0, .01, .003, 1.0
    tau = 4 * length ** 2 / (math.pi ** 2 * kappa)
    eps = sys.float_info.epsilon
    for cells in (16, 32, 64):
        h = length / cells
        grid = Grid(2, cells, h, length)
        shape = [math.cos(math.pi * (col + .5) * h / (2 * length))
                 for row in range(2) for col in range(cells)]
        stock = [(base + amplitude * value) * grid.area_m2 for value in shape]
        initial_inventory = math.fsum(stock)
        coefficients = [kappa] * grid.size
        eigenvalue = 4 * kappa * math.sin(math.pi * h / (4 * length)) ** 2 / h ** 2
        # Toe diagonal is 3K/h² (one internal face plus a half-cell boundary).
        # Its half-row CFL is 1.5K dt/h²; .125 gives .1875 < inherited .20.
        dt_max = .125 * h ** 2 / kappa
        frozen = []
        previous_t = log_decay = 0.0
        total_steps = 0
        for fraction in (.25, 1., 3.):
            target = fraction * tau
            steps = math.ceil((target - previous_t) / dt_max)
            dt = (target - previous_t) / steps
            total_steps += steps
            log_decay += steps * math.log1p(-eigenvalue * dt)
            exact_amplitude = amplitude * math.exp(-fraction)
            fe_amplitude = amplitude * math.exp(log_decay)
            roundoff = 64 * eps * (base + amplitude) * (total_steps + 1)
            rounding_band = 1e-13 + 1e-12 * amplitude + roundoff
            frozen.append({"t_over_tau": fraction, "segment_steps": steps,
                           "dt_years": dt, "total_steps": total_steps,
                           "analytic_amplitude_m": exact_amplitude,
                           "forward_euler_amplitude_m": fe_amplitude,
                           "semidiscrete_amplitude_m": amplitude * math.exp(-eigenvalue * target),
                           "spatial_only_relative_error": math.expm1(fraction - eigenvalue * target),
                           "actual_scheme_relative_discretisation_error": abs(math.expm1(log_decay + fraction)),
                           "scheme_check_absolute_band_m": rounding_band,
                           "total_absolute_band_m": abs(fe_amplitude - exact_amplitude) + rounding_band})
            previous_t = target
        exported = []
        boundaries = toe_faces(grid)
        for expected in frozen:
            for _ in range(expected["segment_steps"]):
                surface = [value / grid.area_m2 - base for value in stock]
                requests = face_requests(grid, surface, stock, coefficients,
                                         expected["dt_years"], external_faces=boundaries)
                if requests["limited_source_cells"]:
                    raise AssertionError("analytical trajectory exhausted finite cover")
                stock, outward = allocated_updates(requests, stock)
                exported.append(outward)
            numerical = [value / grid.area_m2 - base for value in stock]
            scheme_error = max(abs(value - expected["forward_euler_amplitude_m"] * basis)
                               for value, basis in zip(numerical, shape, strict=True))
            continuous_error = max(abs(value - expected["analytic_amplitude_m"] * basis)
                                   for value, basis in zip(numerical, shape, strict=True))
            inventory_residual = math.fsum([math.fsum(stock), math.fsum(exported), -initial_inventory])
            inventory_band = expected["scheme_check_absolute_band_m"] * grid.area_m2 * grid.size
            if scheme_error > expected["scheme_check_absolute_band_m"]:
                raise AssertionError(("actual scheme", cells, expected, scheme_error))
            if continuous_error > expected["total_absolute_band_m"]:
                raise AssertionError(("total numerical band", cells, expected, continuous_error))
            if abs(inventory_residual) > inventory_band:
                raise AssertionError(("boundary inventory", cells, inventory_residual, inventory_band))
            if min(stock) <= 0:
                raise AssertionError("finite cover became nonpositive")
            results.append({"cells_per_length": cells, "h_over_L": 1 / cells,
                            "grid_cells": grid.size, "expected": expected,
                            "scheme_error_max_m": scheme_error,
                            "continuous_error_max_m": continuous_error,
                            "exported_bulk_m3": math.fsum(exported),
                            "inventory_residual_m3": inventory_residual,
                            "inventory_band_m3": inventory_band,
                            "coverage": "KERNEL_ONLY_BINARY64_SYNTHETIC_NUMERICAL"})
    # Refinement is observed against the continuous solution; it is not assumed
    # by the per-grid band. Euler dt scales with h², giving second-order space
    # and first-order time errors that jointly refine at approximately 4x.
    for offset in range(3):
        sequence = [results[offset + 3 * level]["continuous_error_max_m"] for level in range(3)]
        if any(coarse / fine < 3.5 for coarse, fine in zip(sequence, sequence[1:])):
            raise AssertionError(("joint space/time refinement", sequence))
    return results


class FaceRequestsTests(unittest.TestCase):
    def setUp(self):
        self.grid = Grid(2, 3, 2., 3.)
        self.z = [2., 1., 0., 2.2, 1.2, .2]
        self.stock = [20.] * 6
        self.k = [.01] * 6

    def request(self, **changes):
        arguments = dict(grid=self.grid, surface_m=self.z, available_bulk_m3=self.stock,
                         diffusivity_m2_year=self.k, dt_years=.01)
        arguments.update(changes)
        return face_requests(**arguments)

    def test_bulk_requests_match_r7_before_supply_limits(self):
        porosity = (.1, .3, .2, .4, .15, .25)
        solid = tuple(bulk * (1 - p) for bulk, p in zip(self.stock, porosity))
        state = State(self.grid, tuple(z - bulk / self.grid.area_m2 for z, bulk in zip(self.z, self.stock)),
                      solid, porosity, 2700., 2600.)
        expected, _ = hillslope_step(state, self.k, .01, [2.] * 6)
        requests = self.request(critical_gradient=[2.] * 6,
                                receiving_expansion_max=max(1 - p for p in porosity) / min(1 - p for p in porosity))
        terms = [[value] for value in solid]
        for face in requests["faces"]:
            actual = face["requested_bulk_m3"] * (1 - porosity[face["donor"]])
            terms[face["donor"]].append(-actual)
            terms[face["receiver"]].append(actual)
        self.assertEqual(len(requests["faces"]), 7)
        for wanted, values in zip(expected.mobile_solid_m3, terms):
            self.assertAlmostEqual(wanted, math.fsum(values), places=12)
        self.assertFalse(requests["state_applied"])

    def test_linear_face_amount_and_units(self):
        result = self.request()
        face = next(item for item in result["faces"] if item["id"] == "internal:x:0:1")
        self.assertEqual(face["requested_bulk_m3"], .01 * .5 * 3 * .01)
        self.assertEqual((face["donor"], face["receiver"]), (0, 1))
        self.assertEqual(result["transfer_basis"], "donor_bulk_m3")

    def test_finite_supply_reports_shared_proportional_limit(self):
        stock = [1e-6] + self.stock[1:]
        result = self.request(surface_m=[3., 0., 0., 0., 0., 0.], available_bulk_m3=stock)
        self.assertEqual(result["limited_source_cells"], 1)
        demand = result["requested_bulk_m3_by_source"][0]
        self.assertEqual(result["source_scale_factors"][0], stock[0] / demand)
        updated, export = allocated_updates(result, stock)
        self.assertAlmostEqual(updated[0], 0., places=20)
        self.assertEqual(export, 0.)
        self.assertAlmostEqual(math.fsum(updated), math.fsum(stock), places=12)

    def test_steep_bare_donor_skips_soil_law(self):
        result = self.request(surface_m=[1000.] + [0.] * 5,
                              available_bulk_m3=[0.] + self.stock[1:], critical_gradient=[.01] * 6)
        self.assertEqual(result["faces"], [])
        self.assertEqual(result["explicit_cfl"], 0.)

    def test_zero_k_and_flat_zero_transport(self):
        self.assertEqual(self.request(diffusivity_m2_year=[0.] * 6, critical_gradient=[0.] * 6)["faces"], [])
        self.assertEqual(self.request(surface_m=[1.] * 6, critical_gradient=[0.] * 6)["faces"], [])

    def test_full_transverse_gradient_controls_nonlinear_applicability(self):
        with self.assertRaisesRegex(ValueError, "critical-gradient"):
            self.request(surface_m=[0., .1, .2, 3., 3.1, 3.2], critical_gradient=[.8] * 6)

    def test_critical_and_cfl_reject_without_clipping(self):
        with self.assertRaisesRegex(ValueError, "critical-gradient"):
            self.request(critical_gradient=[.1] * 6)
        with self.assertRaisesRegex(ValueError, "stability"):
            self.request(dt_years=1000.)

    def test_receiving_expansion_strengthens_cfl(self):
        plain = self.request()
        expanded = self.request(receiving_expansion_max=3.)
        self.assertAlmostEqual(expanded["explicit_cfl"], 3 * plain["explicit_cfl"])
        self.assertEqual([f["requested_bulk_m3"] for f in plain["faces"]],
                         [f["requested_bulk_m3"] for f in expanded["faces"]])
        with self.assertRaises(ValueError):
            self.request(receiving_expansion_max=.9)

    def test_boundary_ledger_and_permutation_identity(self):
        boundaries = toe_faces(self.grid, -.2)
        result = self.request(external_faces=boundaries)
        self.assertEqual(result, self.request(external_faces=list(reversed(boundaries))))
        updated, export = allocated_updates(result, self.stock)
        self.assertEqual(export, math.fsum(row["requested_outward_bulk_m3"] for row in result["boundary_requests"]))
        self.assertAlmostEqual(math.fsum(updated) + export, math.fsum(self.stock), places=12)
        self.assertTrue(all(row["evidence"] for row in result["boundary_requests"]))
        # Reversing application order gives identical per-cell fsum reductions.
        permuted = dict(result, faces=list(reversed(result["faces"])))
        self.assertEqual(allocated_updates(permuted, self.stock), (updated, export))

    def test_short_boundary_distance_strengthens_cfl(self):
        boundaries = toe_faces(self.grid, -.2)
        boundaries[0]["distance_m"] = .001
        with self.assertRaisesRegex(ValueError, "stability"):
            self.request(dt_years=.1, external_faces=boundaries)

    def test_undeclared_boundary_import_rejected(self):
        with self.assertRaisesRegex(ValueError, "import"):
            self.request(external_faces=toe_faces(self.grid, 10.))

    def test_boundary_validation(self):
        examples = []
        face = toe_faces(self.grid)[0]
        for key, value in (("cell", 1), ("evidence", ""), ("distance_m", 0),
                           ("axis", "z+"), ("width_m", 4)):
            examples.append([dict(face, **{key: value})])
        examples += [[face, face], [dict(face, extra=True)]]
        for boundaries in examples:
            with self.subTest(boundaries=boundaries), self.assertRaises(ValueError):
                self.request(external_faces=boundaries)

    def test_input_validation(self):
        for changes in ({"surface_m": [0.]}, {"available_bulk_m3": [-1.] * 6},
                        {"diffusivity_m2_year": [math.nan] * 6}, {"dt_years": 0},
                        {"dt_years": True}, {"periodic_x": 1},
                        {"critical_gradient": [-1.] * 6}, {"receiving_expansion_max": math.inf}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.request(**changes)

    def test_periodic_faces_are_distinct_physical_seams(self):
        result = self.request(periodic_x=True)
        self.assertEqual(len({face["id"] for face in result["faces"]}), len(result["faces"]))
        self.assertIn("internal:x:2:0", [face["id"] for face in result["faces"]])
        with self.assertRaises(ValueError):
            self.request(periodic_x=True, external_faces=toe_faces(self.grid))


class AnalyticalDecayTests(unittest.TestCase):
    def test_reflecting_divide_fixed_toe_actual_scheme_and_total_bands(self):
        ORACLE_RESULTS.extend(decay_oracle())
        self.assertEqual(len(ORACLE_RESULTS), 9)


if __name__ == "__main__":
    started = time.perf_counter()
    outcome = unittest.main(exit=False, verbosity=2)
    print(json.dumps({"runtime_seconds": time.perf_counter() - started,
                      "tests_run": outcome.result.testsRun,
                      "passed": outcome.result.wasSuccessful(),
                      "oracle_results": ORACLE_RESULTS}, sort_keys=True))
    raise SystemExit(0 if outcome.result.wasSuccessful() else 1)
