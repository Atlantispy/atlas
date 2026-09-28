"""I01 bounded multidirectional mechanics using the retained real 3D producer.

SPDX-License-Identifier: AGPL-3.0-only
Synthetic same-time feasibility, not physical junction birth or world evolution.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "src")]

import numpy as np
import scipy

from atlas_tectonics.regional_execution import RegionalMechanicsScales
from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D, SIDES
from atlas_tectonics.resources import WorkBudget
from regional_plate_coupling import PreparedPlateBoundary3D
from check_i01_ridge_junction import PreparedCandidate, fixture as ridge_fixture


CASE = ROOT / "cases/i01_junction_feasibility_v1.json"
ROTATION = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
FRAME_ROTATION = np.array([[0., 0., 1.], [1., 0., 0.], [0., 1., 0.]])
EXPECTED = {
    "schema": "atlas.i01-junction-feasibility-case.v1",
    "status": "WORKING_NON_CANON",
    "purpose": "same-time multidirectional mechanical feasibility; no topology birth",
    "cells": [2, 2, 2], "lengths_m": [2., 2., 2.], "origin_m": [-1., -1., 4.],
    "reference_viscosity_pa_s": 4., "corridor_width_m": .5,
    "symmetric_reductions_pa_s": [1.5, 1.5],
    "directional_reductions_pa_s": [2.5, .5],
    "external_resistance_nm_s": .5, "torque_magnitude_nm": 1.,
    "relative_tolerance": 2e-8, "absolute_tolerance": 2e-10,
    "minimum_material_response_difference": 1e-5,
    "native_budget_bytes": 64*1024**2, "adapter_budget_bytes": 4*1024**2,
    "maximum_seconds": 60., "method": "direct",
    "generated_reorganisation_enabled": False,
}


def validate_case(spec):
    # Exact prospective control contract; no user-supplied relaxed acceptance.
    if (type(spec) is not dict or set(spec) != set(EXPECTED)
            or json.dumps(spec, sort_keys=True, allow_nan=False)
            != json.dumps(EXPECTED, sort_keys=True, allow_nan=False)):
        raise ValueError("case differs from predeclared junction feasibility controls")


def quadrature(spec):
    cells = np.asarray(spec["cells"])
    indices = np.indices(tuple(cells)).reshape(3, -1).T
    g, _ = np.polynomial.legendre.leggauss(3)
    points = g[np.indices((3, 3, 3)).reshape(3, -1).T]
    return (indices[:, None, :] + (points[None, :, :] + 1)/2) * (
        np.asarray(spec["lengths_m"])/cells)


def viscosity(spec, reductions):
    """Declared scalar spatial heterogeneity, not anisotropic rock rheology."""
    xy = quadrature(spec)[..., :2] - np.asarray(spec["lengths_m"][:2])/2
    return spec["reference_viscosity_pa_s"] - np.sum(
        np.asarray(reductions)*np.exp(-(xy/spec["corridor_width_m"])**2), axis=-1)


@contextmanager
def region(spec, reductions):
    bc = {side: ("traction",)*3 for side in SIDES}
    bc["z0"] = bc["z1"] = ("velocity",)*3
    budget = WorkBudget(spec["native_budget_bytes"])
    with PreparedRegionalStokes3D(spec["cells"], spec["lengths_m"], viscosity(spec, reductions), bc,
            scales=RegionalMechanicsScales(1., 1.),
            reference_viscosity_pa_s=spec["reference_viscosity_pa_s"],
            frame_id="synthetic-local-box", vertical_datum="stationary-box-bottom",
            material_source="declared-crossing-viscosity-corridors:"+repr(list(reductions)),
            method=spec["method"], budget=budget) as plan:
        yield plan, budget


def mapping(plan, spec, axes=None, reverse_ids=False):
    axes = np.eye(3) if axes is None else axes
    xyz = plan.coordinates("velocity")
    owners = np.full(len(xyz), -1, dtype=int)
    owners[xyz[:, 2] == 0.] = 0
    owners[xyz[:, 2] == spec["lengths_m"][2]] = 1
    if reverse_ids:
        owners[owners >= 0] = 1-owners[owners >= 0]
    return PreparedPlateBoundary3D(plan, global_frame_id="synthetic-planet-centred",
        origin_m=axes@np.asarray(spec["origin_m"]), local_axes_global=axes,
        plate_ids=("upper", "lower") if reverse_ids else ("lower", "upper"),
        node_plate_index=owners, geometry_source="explicit-two-face-synthetic-control",
        max_work_bytes=spec["adapter_budget_bytes"])


def solve(plan, mapped, torque):
    return mapped.solve_torque_coupled(0., np.zeros_like(plan.coordinates("velocity")),
        {side: 0. for side in SIDES}, torque,
        EXPECTED["external_resistance_nm_s"]*np.eye(6),
        coupling_source="declared-exterior-resistance-excludes-regional-material",
        parent_state_id="synthetic-crossing-corridors-at-one-instant",
        epoch_id="synthetic-instant", time_s=0., force_source="explicit-zero-body-force",
        boundary_source="plate-owned-z-faces-and-zero-lateral-tractions")


def balances(result, spec):
    """Independent nodal sums and physical products, not copied pass flags."""
    m, e = result.mechanical, result.exchange
    rate = e.array("angular_velocity_rad_s")
    torque = e.array("torque_on_region_nm")
    force = m.array("velocity_constraint_reaction_n")
    velocity = m.array("velocity_m_s")
    mapping_record = e.descriptor()["mapping"]
    shape = 2*np.asarray(spec["cells"])+1
    xyz = np.indices(tuple(shape)).reshape(3, -1).T * (np.asarray(spec["lengths_m"])/(shape-1))
    axes = np.asarray(mapping_record["local_axes_global"])
    positions = np.asarray(mapping_record["origin_m"]) + xyz@axes.T
    force_global = force@axes.T
    independent_torque = []
    for name in mapping_record["plate_ids"]:
        at = xyz[:, 2] == (0. if name == "lower" else spec["lengths_m"][2])
        independent_torque.append(np.cross(positions[at], force_global[at]).sum(axis=0))
    independent_torque = np.asarray(independent_torque)
    drive = np.asarray(e.descriptor()["request"]["external_torque_nm"])
    exterior = spec["external_resistance_nm_s"]*rate
    p = m.descriptor()["power_w"]
    regional_power = float(np.sum(rate*torque))
    return {
        "net_force_n": float(np.linalg.norm(force_global.sum(axis=0))),
        "net_regional_torque_nm": float(np.linalg.norm(independent_torque.sum(axis=0))),
        "torque_return_error_nm": float(np.max(np.abs(independent_torque-torque))),
        "coupled_torque_error_nm": float(np.max(np.abs(torque+exterior-drive))),
        "nodal_to_plate_power_error_w": abs(float(np.sum(force*velocity))-regional_power),
        "opposite_port_power_error_w": abs(regional_power+float(np.sum(rate*e.array("torque_on_plates_nm")))),
        "full_power_error_w": abs(float(np.sum(drive*rate))-float(np.sum(exterior*rate))
            -p["viscous_dissipation"]-p["pressure_work"]),
        "viscous_dissipation_w": p["viscous_dissipation"],
        "native_linear_relative_residual": m.descriptor()["linear_relative_residual"],
        "native_work_relative_residual": m.descriptor()["work_relative_residual"],
    }


def controls(spec):
    validate_case(spec)
    start = perf_counter()
    close = lambda a, b: bool(np.allclose(a, b, rtol=spec["relative_tolerance"], atol=spec["absolute_tolerance"]))
    checks, measurements, results = {}, {}, {}
    tx = spec["torque_magnitude_nm"]*np.array([[1., 0., 0.], [-1., 0., 0.]])
    ty = tx@ROTATION.T
    with region(spec, spec["symmetric_reductions_pa_s"]) as (p, budget):
        mapped = mapping(p, spec)
        for name, force in (("x", tx), ("y", ty), ("both", tx+ty)):
            results[name] = solve(p, mapped, force)
        results["reordered"] = solve(p, mapping(p, spec, reverse_ids=True), (tx+ty)[::-1])
        results["frame_rotated"] = solve(p, mapping(p, spec, axes=FRAME_ROTATION), (tx+ty)@FRAME_ROTATION.T)
        xyz = p.coordinates("velocity")
        rotated_xyz = (xyz-np.array([1., 1., 1.]))@ROTATION.T + np.array([1., 1., 1.])
        node_lookup = {tuple(point): i for i, point in enumerate(xyz)}
        rotation_permutation = [node_lookup[tuple(point)] for point in rotated_xyz]
        checks["symmetric_rotated_velocity"] = close(results["y"].mechanical.array("velocity_m_s")[rotation_permutation],
            results["x"].mechanical.array("velocity_m_s")@ROTATION.T)
        checks["symmetric_rotated_rates"] = close(results["y"].exchange.array("angular_velocity_rad_s"),
            results["x"].exchange.array("angular_velocity_rad_s")@ROTATION.T)
        both = results["both"]
        checks["both_forcing_directions_consumed"] = close(both.mechanical.array("velocity_m_s"),
            results["x"].mechanical.array("velocity_m_s")+results["y"].mechanical.array("velocity_m_s"))
        rates = both.exchange.array("angular_velocity_rad_s")
        checks["symmetric_no_direction_winner"] = close(rates[:, 0], rates[:, 1]) and close(rates[:, 2], 0.)
        checks["plate_id_order_invariance"] = close(both.mechanical.array("velocity_m_s"),
            results["reordered"].mechanical.array("velocity_m_s")) and close(rates,
            results["reordered"].exchange.array("angular_velocity_rad_s")[::-1])
        checks["global_frame_velocity_invariance"] = close(both.mechanical.array("velocity_m_s"),
            results["frame_rotated"].mechanical.array("velocity_m_s"))
        checks["global_frame_torque_covariance"] = close(both.exchange.array("torque_on_region_nm")@FRAME_ROTATION.T,
            results["frame_rotated"].exchange.array("torque_on_region_nm"))
        checks["one_factor_for_symmetric_controls"] = p.statistics()["factorizations"] == 1
        checks["changed_forcing_reuses_response"] = p.statistics()["coupling_response_hits"] == 2
        measurements["symmetric_plan_statistics"] = p.statistics()
        measurements["peak_native_reserved_bytes"] = budget.peak_reserved_bytes
    reductions = spec["directional_reductions_pa_s"]
    for name, material, force in (("material_x", reductions, tx),
                                   ("material_y", reductions[::-1], ty),
                                   ("material_y_same_force", reductions[::-1], tx)):
        with region(spec, material) as (p, budget):
            results[name] = solve(p, mapping(p, spec), force)
            measurements["peak_native_reserved_bytes"] = max(measurements["peak_native_reserved_bytes"], budget.peak_reserved_bytes)
    mx, my = results["material_x"], results["material_y"]
    checks["rotated_material_velocity_covariance"] = close(my.mechanical.array("velocity_m_s")[rotation_permutation],
        mx.mechanical.array("velocity_m_s")@ROTATION.T)
    checks["rotated_material_torque_covariance"] = close(my.exchange.array("torque_on_region_nm"),
        mx.exchange.array("torque_on_region_nm")@ROTATION.T)
    material_delta = float(np.linalg.norm(mx.exchange.array("angular_velocity_rad_s")-
        results["material_y_same_force"].exchange.array("angular_velocity_rad_s")))
    checks["material_direction_changes_solved_motion"] = material_delta > spec["minimum_material_response_difference"]
    measurements["material_direction_rate_difference_rad_s"] = material_delta
    residuals = {name: balances(result, spec) for name, result in results.items()}
    for field in ("net_force_n", "net_regional_torque_nm", "torque_return_error_nm", "coupled_torque_error_nm",
                  "nodal_to_plate_power_error_w", "opposite_port_power_error_w", "full_power_error_w"):
        checks[field] = all(row[field] <= spec["absolute_tolerance"] for row in residuals.values())
    checks["nonnegative_viscous_dissipation"] = all(row["viscous_dissipation_w"] > 0 for row in residuals.values())
    # Consume the retained negative physical boundary. Do not add an event proxy,
    # caller-issued interface token or a fabricated physical acceptance gate.
    kinematic = PreparedCandidate(**ridge_fixture()).record()
    checks["feasible_kinematics_refuses_physical_birth"] = (
        kinematic["status"] == "LOCALLY_FEASIBLE_NOT_GENERATED"
        and kinematic["physical_birth_verified"] is False
        and kinematic["topology_change_authorised"] is False)
    checks["mechanical_outputs_do_not_issue_topology"] = all(
        result.mechanical.descriptor()["scientific_acceptance"] is False
        and result.mechanical.descriptor()["scope"] ==
        "same-time regional mechanical solve; no material/history advancement or boundary birth"
        for result in results.values())
    checks["bounded_duration"] = perf_counter()-start <= spec["maximum_seconds"]
    measurements["residuals"] = residuals
    measurements["angular_velocity_rad_s"] = {name: r.exchange.array("angular_velocity_rad_s").tolist() for name, r in results.items()}
    return dict(passed=all(checks.values()), checks=checks, measurements=measurements,
        kinematic_candidate=kinematic, generated_reorganisation=False, physical_topology_issued=False,
        scope="same-time synthetic multidirectional 3D mechanical feasibility only",
        missing_physical_conditions=[
            "admitted MC-01 separation/contact and MC-02 initiation outputs for the case",
            "compatible MC-03 finite melt supply wherever the actual mechanism requires it",
            "objective stress/history evolution, moving boundaries and accepted parent transfer",
            "material-derived interface extraction, joint event timing and conservative transaction",
            "physical spatial/time/domain refinement and whole-window plate handoff"],
        execution_identity=results["both"].mechanical.descriptor()["plan"]["execution"])


def bindings():
    names = ["tools/check_i01_junction_feasibility.py", "tests/test_i01_junction_feasibility.py",
             "docs/I01_JUNCTION_FEASIBILITY.md", "cases/i01_junction_feasibility_v1.json",
             "tools/regional_plate_coupling.py", "tools/check_i01_ridge_junction.py",
             "tools/check_i01_junction_events.py"]
    names += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT/"src/atlas_tectonics").glob("*.py"))]
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def report():
    start = perf_counter()
    result = dict(schema="atlas.i01-junction-feasibility-control.v1", status="INCOMPLETE",
        scientific_acceptance=False, generated_reorganisation=False, physical_topology_issued=False,
        runtime=dict(python=platform.python_version(), system=platform.system(),
                     numpy=np.__version__, scipy=scipy.__version__))
    try:
        result["source_sha256"] = bindings()
        result.update(controls(json.loads(CASE.read_text(encoding="utf-8"))))
        result["source_unchanged"] = result["source_sha256"] == bindings()
        result["status"] = "PASS_BOUNDED_CONTROLS_ONLY" if result["passed"] and result["source_unchanged"] else "FAIL"
    except Exception as exc:
        result.update(status="FAIL", error_type=type(exc).__name__, error=str(exc))
    result["elapsed_seconds"] = perf_counter()-start
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output is None:
        result = report()
        print(json.dumps(result, indent=2, allow_nan=False))
    else:
        # Exclusive creation happens before the bounded computation.
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            result = report()
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({key: result[key] for key in ("status", "elapsed_seconds")}))
    return 0 if result["status"] == "PASS_BOUNDED_CONTROLS_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
