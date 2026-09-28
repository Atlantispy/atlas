"""Focused MC-03 melt-segregation tests. They cover the instantaneous one-dimensional two-phase compaction closure
against:
- an independent constant-coefficient closed form, itself checked against a hand solution, and a manufactured
  variable-coefficient solution;
- second-order refinement;
- exact buoyancy antisymmetry and a pressure-driven reversal;
- per-cell phase and mixture volume balances and the fluid pressure reproducing the Darcy flux;
- explicit dry and disconnected states without floors;
- incompatible and malformed boundary refusals;
- the volume/mass fraction distinction and exact operator reuse.
Synthetic values only. The bounded controls are called directly, no receipt is written, and the CLI is exercised only
for exclusive creation.
SPDX-License-Identifier: AGPL-3.0-only
"""
import copy
import dataclasses
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_melt_segregation as s

SPEC = s.load_case()
PROVENANCE = {"status": "SYNTHETIC test values", "densities": "SYNTHETIC test value", "gravity": "SYNTHETIC test value",
              "viscosities": "SYNTHETIC test values", "permeability": "SYNTHETIC test values"}
MATERIAL = {"solid_density_kg_m3": 3300.0, "liquid_density_kg_m3": 2800.0, "gravity_m_s2": 9.81,
            "liquid_viscosity_pa_s": 1.0, "shear_viscosity_pa_s": 3e18, "bulk_viscosity_pa_s": 6e18,
            "bulk_viscosity_reference_porosity": 0.01, "bulk_viscosity_exponent": 1.0, "permeability_m2": 1e-13,
            "permeability_reference_porosity": 0.01, "permeability_exponent": 3.0, "provenance": PROVENANCE}
K, XI = 1e-13, 1e19                      # K/mu and zeta + 4 eta/3 at the 1% reference fraction
DELTA = math.sqrt(K*XI)                  # 1000 m
BETA = 0.99*500.0*9.81                   # (1 - phi)(rho_s - rho_f) g, Pa/m


def column(cells=128, length=4000.0, phi=0.01, gamma=1e-9, **override):
    declared = {"face_heights_m": np.linspace(0.0, length, cells+1), "liquid_volume_fraction": np.full(cells, phi),
                "melting_rate_kg_m3_s": np.full(cells, gamma), "provenance": "SYNTHETIC test column"}
    declared.update(override)
    return declared


def boundary(bottom=("flux", 0.0), top=("rigid",), **velocity):
    declared = {"bottom": bottom[0], "top": top[0], "provenance": "SYNTHETIC test boundary"}
    for end, condition in (("bottom", bottom), ("top", top)):
        if condition[0] == "flux":
            declared[end+"_flux_m_s"] = condition[1]
    declared.update(velocity or {"bottom_matrix_velocity_m_s": 1e-9})
    return declared


class ClosedFormOracleTests(unittest.TestCase):
    def test_oracle_matches_the_hand_solution_for_a_sealed_base(self):
        # Sealed base, rigid top, no reaction: a = beta delta E/(1+E^2), c = -beta delta/(1+E^2), W = -q.
        exact = s.constant_coefficient(K, XI, BETA, 0.0, 0.0, 4000.0, ("flux", 0.0), ("rigid",), w_bottom=0.0)
        z = np.linspace(0.0, 4000.0, 17)
        e = math.exp(-4.0)
        up, down = np.exp(-(4000.0-z)/DELTA), np.exp(-z/DELTA)
        sigma, q, w = exact(z)
        np.testing.assert_allclose(sigma, BETA*DELTA*(e*up-down)/(1+e*e), rtol=0, atol=1e-12*BETA*DELTA)
        np.testing.assert_allclose(q, K*BETA*(1-(e*up+down)/(1+e*e)), rtol=0, atol=1e-12*K*BETA)
        np.testing.assert_allclose(w, -q, rtol=0, atol=1e-12*K*BETA)
        self.assertLess(abs(q[0]), 1e-12*K*BETA)                        # the sealed base
        self.assertLess(abs(sigma[-1]), 1e-12*BETA*DELTA)               # the rigid top

    def test_oracle_satisfies_its_conditions_and_the_mixture_balance(self):
        reaction = 1e-9*(1/2800-1/3300)
        conditions = {"flux": ("flux", 2e-10), "rigid": ("rigid",), "free_flux": ("free_flux",)}
        for bottom in conditions.values():
            for top in conditions.values():
                with self.subTest(bottom=bottom, top=top):
                    exact = s.constant_coefficient(K, XI, BETA, reaction, 0.0, 4000.0, bottom, top, w_bottom=1e-9)
                    z = np.linspace(0.0, 4000.0, 41)
                    sigma, q, w = exact(z)
                    scale = K*BETA+reaction*4000.0+1e-9
                    # d(W + q)/dz = R exactly: W + q is linear with slope R.
                    np.testing.assert_allclose(w+q-(w[0]+q[0]), reaction*z, rtol=0, atol=1e-12*scale)
                    for end, condition, index in (("bottom", bottom, 0), ("top", top, -1)):
                        if condition[0] == "flux":
                            self.assertAlmostEqual(q[index], condition[1], delta=1e-12*scale, msg=end)
                        elif condition[0] == "rigid":
                            self.assertAlmostEqual(sigma[index], 0.0, delta=1e-12*XI*scale/DELTA, msg=end)
                        else:                                      # dSigma/dz = 0 means q = k beta
                            self.assertAlmostEqual(q[index], K*BETA, delta=1e-12*scale, msg=end)


class ControlTests(unittest.TestCase):
    """The frozen campaign controls, each with its independent reference."""

    def check(self, control):
        result = control(SPEC)
        self.assertTrue(result["passed"], {name: ok for name, ok in result["checks"].items() if not ok})
        return result

    def test_derivation(self):
        result = self.check(s.derivation_control)
        self.assertEqual(len(result["pairs"]), len(SPEC["controls"]["boundary_pairs"]))

    def test_refinement(self):
        result = self.check(s.refinement_control)
        for table in (result["constant_orders"], result["manufactured_orders"]):
            for orders in table.values():
                self.assertEqual(len(orders), len(SPEC["controls"]["grids"])-1)

    def test_reversal(self):
        self.check(s.reversal_control)

    def test_balances(self):
        self.check(s.balance_control)

    def test_dry_limits(self):
        self.check(s.dry_limits_control)

    def test_boundaries(self):
        self.check(s.boundaries_control)

    def test_porosity_basis(self):
        self.check(s.porosity_basis_control)

    def test_reuse(self):
        self.check(s.reuse_control)

    def test_small_matched_timing(self):
        spec = copy.deepcopy(SPEC)
        spec["controls"]["timing"] = {"cells": [64], "loads": 3}
        rows = s.timing_rows(spec)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["bitwise_identical"])
        for samples in rows[0]["samples_seconds"].values():
            self.assertEqual(len(samples), s.POLICY["timing_repetitions"])
            self.assertTrue(all(math.isfinite(t) and t >= 0 for t in samples))


class FocusedTests(unittest.TestCase):
    def test_receiver_flux_uses_declared_frame_and_phase_trace(self):
        result = s.solve(MATERIAL, column(), boundary())
        phi = np.full(result.matrix_velocity_m_s.size, 0.01)
        zero = np.zeros(phi.size)
        fixed = result.liquid_mass_flux_at_faces(phi, zero)
        moving = result.liquid_mass_flux_at_faces(phi, result.matrix_velocity_m_s)
        np.testing.assert_array_equal(moving, result.relative_liquid_mass_flux_kg_m2_s)
        np.testing.assert_allclose(fixed-moving, 2800*phi*result.matrix_velocity_m_s, rtol=1e-12, atol=0)
        self.assertNotEqual(fixed[-1], moving[-1])
        with self.assertRaises(s.Refusal):
            result.liquid_mass_flux_at_faces(phi[:-1], zero)
        with self.assertRaises(s.Refusal):
            result.liquid_mass_flux_at_faces(np.ones(phi.size), zero)

    def test_fraction_conversion_preserves_representable_small_phases(self):
        self.assertEqual(s.porosity_from_phase_volumes(1e308, 1e308), 0.5)
        self.assertEqual(s.porosity_from_liquid_mass_fraction(1e-300, 1e308, 1e308), 1e-300)
        self.assertEqual(s.liquid_mass_fraction_from_porosity(1e-300, 1e-300, 1e-300), 1e-300)
        self.assertEqual(s.porosity_from_phase_volumes(0, 1), 0)
        self.assertEqual(s.porosity_from_phase_volumes(1, 0), 1)
        with self.assertRaises(s.Refusal) as raised:
            s.porosity_from_phase_volumes(1e-300, 1e308)
        self.assertEqual(raised.exception.code, s.RANGE)

    def test_rigid_matrix_darcy_flux_is_not_the_closure(self):
        result = s.solve(MATERIAL, column(gamma=0.0), boundary())
        q, w = result.segregation_flux_m_s, result.matrix_velocity_m_s
        self.assertEqual(q[0], 0.0)                                     # the declared sealed base holds exactly
        self.assertLess(result.compaction_rate_per_s[0], 0.0)           # the matrix compacts to release the liquid
        # A rigid matrix (W constant) with q = k beta everywhere would put k beta into the sealed base: its first
        # cell would violate the mixture balance by k beta, while the coupled solution balances to rounding.
        rigid_residual = (0.0+K*BETA)-(0.0+0.0)
        self.assertGreater(rigid_residual, 1e6*abs(result.mixture_residual_m_s[0]))
        departure = abs(float(q[16])-K*BETA)                            # face 16 is delta/2 above the base
        self.assertGreater(departure, 0.25*K*BETA)                      # compaction holds the flux below k beta
        self.assertLess(departure, 0.75*K*BETA)                         # ... without stopping it (about 0.61 k beta)
        self.assertLess(float(np.min(w[1:]-w[0])), 0.0)                 # the matrix subsides as liquid leaves

    def test_top_flux_is_not_production(self):
        base = s.solve(MATERIAL, column(), boundary())
        doubled = s.solve(MATERIAL, column(gamma=2e-9), boundary())
        production = base.summary()["column_liquid_production_m_s"]
        self.assertAlmostEqual(production, 1e-9*4000.0/2800.0, delta=1e-12*production)
        top, top_doubled = float(base.segregation_flux_m_s[-1]), float(doubled.segregation_flux_m_s[-1])
        self.assertGreater(abs(top-production), 0.25*production)
        # Melting changes the instantaneous flux only through its reaction volume, far less than the production.
        self.assertLess(abs(top_doubled-top), 0.25*production)
        self.assertGreater(top_doubled, top)

    def test_single_cell_column(self):
        result = s.solve(MATERIAL, column(cells=1, length=100.0), boundary())
        self.assertEqual(result.segregation_flux_m_s[0], 0.0)
        self.assertLessEqual(abs(result.mixture_residual_m_s[0]), 1e-12*result.balance_scale_m_s)
        self.assertTrue(np.all(np.isfinite(result.overpressure_pa)))

    def test_refusal_codes_leave_inputs_unchanged(self):
        grid = np.linspace(0.0, 4000.0, 129)
        tiny = np.full(128, 0.01)
        tiny[40] = 1e-200                                               # K underflows: never floored
        thin = np.full(128, 0.01)
        thin[40] = 1e-10                                                # representable, delta far below the cell
        cases = {
            s.INVALID: [(dict(MATERIAL, shear_viscosity_pa_s=-1.0), column(), boundary()),
                        (dict(MATERIAL, permeability_exponent=0.0), column(), boundary()),
                        (dict(MATERIAL, permeability_reference_porosity=1.0), column(), boundary()),
                        (dict(MATERIAL, gravity_m_s2=True), column(), boundary()),
                        (MATERIAL, column(liquid_volume_fraction=np.full(128, 1.0)), boundary()),
                        (MATERIAL, column(liquid_volume_fraction=np.full(128, -0.01)), boundary()),
                        (MATERIAL, column(face_heights_m=grid[::-1]), boundary()),
                        (MATERIAL, column(melting_rate_kg_m3_s=np.full(127, 1e-9)), boundary())],
            s.UNSUPPORTED: [(dict(MATERIAL, liquid_density_kg_m3=[2800.0, 2900.0]), column(), boundary())],
            s.PROVENANCE: [(dict(MATERIAL, provenance={"status": "SYNTHETIC"}), column(), boundary()),
                           (MATERIAL, column(provenance=""), boundary())],
            s.UNRESOLVED: [(MATERIAL, column(cells=8), boundary()),
                           (MATERIAL, column(liquid_volume_fraction=thin), boundary())],
            s.RANGE: [(MATERIAL, column(liquid_volume_fraction=tiny), boundary())],
        }
        for code, calls in cases.items():
            for mat, col, bnd in calls:
                with self.subTest(code=code):
                    record = s.attempt(code, lambda: s.solve(mat, col, bnd), mat, col, bnd)
                    self.assertTrue(record["refused_as_expected"], record)
                    self.assertTrue(record["inputs_unchanged"], record)

    def test_mass_fraction_is_not_a_column_state(self):
        declared = column()
        declared["melt_fraction"] = declared.pop("liquid_volume_fraction")
        with self.assertRaises(s.Refusal) as raised:
            s.solve(MATERIAL, declared, boundary())
        self.assertEqual(raised.exception.code, s.INVALID)
        self.assertAlmostEqual(s.porosity_from_liquid_mass_fraction(0.1, 3300.0, 2800.0), 11/95, delta=1e-15)

    def test_operator_is_immutable_and_rejects_other_operators(self):
        op = s.prepare(MATERIAL, column(), boundary())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            op.factor = None
        for name in ("conductance", "factor", "wet", "compaction_length"):
            array = getattr(op, name)
            with self.assertRaises(ValueError):
                array.setflags(write=True)
            with self.assertRaises(ValueError):
                array.flat[0] = array.flat[0]
        with self.assertRaises(s.Refusal) as raised:
            op.solve(MATERIAL, column(phi=0.011), boundary())
        self.assertEqual(raised.exception.code, s.MISMATCH)
        reused = op.solve(dict(MATERIAL, liquid_density_kg_m3=2900.0), column(gamma=3e-9), boundary())
        fresh = s.solve(dict(MATERIAL, liquid_density_kg_m3=2900.0), column(gamma=3e-9), boundary())
        for name in s.RESULT_ARRAYS:
            self.assertTrue(np.array_equal(getattr(reused, name), getattr(fresh, name), equal_nan=True), name)


class CaseTests(unittest.TestCase):
    def test_case_policy_and_files_are_bound(self):
        self.assertEqual(SPEC["policy"], s.POLICY)
        self.assertEqual(SPEC["contract"], s.CONTRACT)
        for name in s.NEW_FILES:
            self.assertTrue((s.ROOT/name).is_file(), name)
        document = (s.ROOT/"docs/I01_MELT_SEGREGATION.md").read_text(encoding="utf-8")
        self.assertIn("WORKING NON-CANON", document)
        self.assertIn("CURRENT_STATE", document)
        self.assertIn("SYNTHETIC", SPEC["synthetic"]["material"]["provenance"]["status"])

    def test_cli_output_is_exclusive(self):
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder)/"receipt.json"
            existing.write_text("{}", encoding="utf-8")
            argv = ["check_i01_melt_segregation.py", "--output", str(existing)]
            with mock.patch.object(sys, "argv", argv), self.assertRaises(FileExistsError):
                s.main()
            self.assertEqual(existing.read_text(encoding="utf-8"), "{}")


if __name__ == "__main__":
    unittest.main()
