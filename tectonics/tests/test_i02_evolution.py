"""Focused I02.2a/I02.2b checks: one package-owned finite-strain solver, now continuable from the common state.

Six package modules own the equations; the six I01 tools re-export those same objects. A separate process prepares,
evolves and continues the real layered route from the package alone, with no campaign tool importable or loaded.
Small order-8 layered and order-4 homogeneous fixtures keep extension, compression, rest, reference matching,
complete signed accounts, input immutability and independent oracles. I02.2b: uneven pieces of the same history match
the uninterrupted run bitwise inside one prepared continuation and at the retained parity after a cold rebuild, with
schedule, refusal, deadline, forgery, reference-rebuild, instrumentation and prepared-runner ownership checks. Nothing
here saves or commits.
SPDX-License-Identifier: AGPL-3.0-only
"""
import ast
import copy
import dataclasses
import hashlib
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np
from threadpoolctl import threadpool_limits

import atlas_tectonics
from atlas_tectonics import (_integration_column as C, _integration_heat as H, _integration_motion as M,
                             _integration_thermomechanical as T, _integration_weakening as W,
                             integration_evolution as E, integration_state as I)
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.materials import MaterialCohort, MaterialState
from atlas_tectonics.mesh import ColumnGrid1D
from atlas_tectonics.w08_inventory import W08Inventory

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT/"tools"
SRC = Path(atlas_tectonics.__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import check_i01_column as tc
import check_i01_breakup_closure as tb
import check_i01_column_admission as tca
import check_i01_column_heat as th
import check_i01_finite_admission as tfa
import check_i01_finite_strain as tfs
import check_i01_motion_coupling as tmo
import check_i01_thermomechanical_motion as ttm
import check_i01_weakening as tw

SPEC, CTX = tfs.load_case()
LAW, DRIVE = CTX["law"], CTX["drive"]
REP, POLICY = SPEC["representation"], SPEC["policy"]
DURATION = SPEC["drive"]["duration_s"]
WINDOW = tfs.declared_window(SPEC)
STILL = M.Drive(0., DRIVE.drag_pa_s, DRIVE.width_m)
SQUEEZE = M.Drive(-DRIVE.force_n_m, DRIVE.drag_pa_s, DRIVE.width_m)
PACKAGE = (C, W, H, M, T, E)
# Each package owner, the retained tool that must re-export it, and exactly the production objects moved.
MOVED = (
    (C, tc, ("R", "POLICY", "number", "check_cancel", "Creep", "LocalLaw", "Column")),
    (W, tw, ("LITHOSTATIC", "SUPPLIED", "COMMON_LAYER_KEYS", "LAYER_KEYS", "CREEP_KEYS", "TOL", "number", "positive",
             "check_deadline", "WeakeningLaw", "validate_creep", "validate_layers", "fingerprint", "frozen",
             "PreparedColumn", "prepare", "history_array", "_evaluate", "stresses", "respond")),
    (H, th, ("R", "TOL", "UNIT_ROUNDOFF", "THERMAL_KEYS", "BOUNDARY_TYPES", "phi_functions", "ThermalColumn",
             "thermal_identity", "valid_thermal", "scalar", "validate_thermal_layers", "validate_boundaries",
             "width_tolerance", "validate_support", "prepare_thermal", "Propagator", "prepare_propagator", "conduct",
             "ArrheniusUpdate", "mechanics", "heat_fractions", "policy_limits", "same_support")),
    (M, tmo, ("FORCE_TOL", "MAX_ITERATIONS", "Drive", "solve")),
    (T, ttm, ("REST", "expired", "ratio", "departure", "stage", "note", "reference_throughput")),
    (E, tfs, ("STRETCH_CEILING", "TEMPERATURE_CEILING_K", "REPRESENTATION", "REPRESENTATION_LIMITS", "REBUILD_KEYS",
              "STAGE_ACCOUNTS", "THERMAL_ACCOUNTS", "Refused", "coefficients", "column_at", "stage", "clock",
              "clock_source", "eigensystem", "clock_propagator", "rebuilt_propagator", "check_rebuild", "advance_map",
              "window_of", "paired", "weighted", "evolve")))
# Comparison, campaign and case code that stays with the tools rather than inflating the production graph.
TOOL_ONLY = ("conduct_history", "stretch_oracle", "stretch_balance", "scalar_balance", "force_oracle",
             "homogeneous_oracle", "CountdownDeadline", "evolve_heat", "respond_force", "force_envelope",
             "rate_envelope", "strain_limit", "execution_policy", "laboratory_prefactor", "campaign", "load_case",
             "validate_case", "bindings", "evidence_match", "main", "OFF", "geometry", "layered", "freshness")
DERIVED = ("surface_loss_j_m", "basal_gain_j_m", "motion_work_relative", "drive_displacement_relative",
           "partition_relative", "column_energy_relative", "work_to_heat_relative", "drag_excluded_relative",
           "energy_relative", "absolute_energy_relative")
# The carried accounts (the carrier's catalogue guards their names) plus the retained derived identities: 24 in all.
ACCOUNTS = frozenset(I.STAGE_ACCOUNTS+I.THERMAL_ACCOUNTS+DERIVED)
EXTENSIVE = I.STAGE_ACCOUNTS+I.THERMAL_ACCOUNTS+DERIVED[:2]
EVOLVE_SIGNATURE = ("(base, thermal, law, kappa0, drive, *, duration_s, steps, window, temperature_step_k, "
                    "fractions, policy, modes=None, conduction=True, geometry_feedback=True, theta0=None, "
                    "warm_start=True, rebuild=None, inputs=None, deadline=None)")
# Runs in a fresh interpreter: only the package, NumPy/threadpoolctl and the case data files are used.
CHILD = r"""
import copy
import importlib.util
import json
from pathlib import Path
import sys

root, tools = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()

import numpy as np
from threadpoolctl import threadpool_limits

from atlas_tectonics import integration_evolution as E, integration_state as I
from atlas_tectonics import _integration_heat as H, _integration_motion as M, _integration_weakening as W
from atlas_tectonics.materials import MaterialCohort, MaterialState
from atlas_tectonics.mesh import ColumnGrid1D


def case(name):
    return json.loads((root/"cases"/name).read_text(encoding="utf-8"))


def from_tools(module):
    try:
        path = getattr(module, "__file__", None)
    except Exception:                     # a lazily populated module entry; it has no file of its own
        return False
    return isinstance(path, str) and Path(path).resolve().parent == tools


weak, heat, motion, finite = (case(name) for name in (
    "i01_weakening_v1.json", "i01_column_heat_v1.json", "i01_motion_coupling_v1.json", "i01_finite_strain_v1.json"))
rep, frep = weak["representation"], finite["representation"]
layers = copy.deepcopy(weak["layers"])
for layer in layers:                      # the retained fixture's zero temperature offset, which yields floats
    layer["temperature_k"] = [t+0. for t in layer["temperature_k"]]
key = (layers, 8, W.LITHOSTATIC, rep["gravity_m_s2"])
inputs = dict(thicknesses=[layer["thickness_m"] for layer in layers], props=heat["thermal_layers"],
              densities=[layer["density_kg_m3"] for layer in layers], boundaries=heat["boundaries"],
              reference_temperature=None)
law = W.WeakeningLaw.from_spec(weak["weakening"])
with threadpool_limits(limits=1, user_api="blas"):
    base = W.prepare(layers, 8, closure=rep["pressure_closure"], gravity=rep["gravity_m_s2"])
    thermal = H.prepare_thermal(base.layer, base.depth_m, base.weight, inputs["thicknesses"], inputs["props"],
                                inputs["densities"], inputs["boundaries"], mechanical_fingerprint=base.fingerprint)
    kappa0 = np.asarray(weak["campaign"]["initial_history_by_layer"], dtype=float)[base.layer]
    out = E.evolve(base, thermal, law, kappa0, M.Drive(motion["drive_n_m"], motion["drag_pa_s"], motion["width_m"]),
                   duration_s=finite["drive"]["duration_s"]/4, steps=4,
                   window=dict(stretch=frep["stretch_window"], temperature_k=frep["temperature_window_k"]),
                   temperature_step_k=frep["max_temperature_step_k"], fractions=(1., 1.), policy=finite["policy"],
                   inputs=key)
    # The same four steps continued in two pieces from a common state, still with no tool importable.
    reference = I.ColumnReference(
        mechanical=dict(key=key, fingerprint=base.fingerprint, layer=base.layer, depth_m=base.depth_m,
                        weight=base.weight, reference_pa=base.reference_pa, density=base.density,
                        thickness_m=base.thickness_m),
        thermal=dict(provider=I.COLUMN_THERMAL_BASIS, inputs=inputs, fingerprint=thermal.fingerprint,
                     mechanical_fingerprint=thermal.mechanical_fingerprint, layer=thermal.layer,
                     depth_m=thermal.depth_m, volume_m=thermal.volume_m,
                     reference_density_kg_m3=thermal.reference_density_kg_m3, capacity=thermal.capacity,
                     radiogenic=thermal.radiogenic, steady_k=thermal.steady_k,
                     boundary_temperature=thermal.boundary_temperature, thickness_m=thermal.thickness_m))
    settings = I.ColumnSettings(
        representation=frep, law=dict(start=law.start, end=law.end, cohesion_factor=law.cohesion_factor,
                                      friction_factor=law.friction_factor),
        drive=dict(force_n_m=motion["drive_n_m"], drag_pa_s=motion["drag_pa_s"], width_m=motion["width_m"]),
        heat_fractions=(1., 1.), policy=finite["policy"],
        schedule=dict(duration_s=finite["drive"]["duration_s"]/4, steps=4))
    ids = tuple("layer-%d" % k for k in range(len(layers)))
    materials = MaterialState(ColumnGrid1D([0., motion["width_m"]], frame_id="strip"),
                              tuple(MaterialCohort(i, layer["name"], "cases/i01_weakening_v1.json", None)
                                    for i, layer in zip(ids, layers)),
                              [[layer["thickness_m"]] for layer in layers], time_s=0., epoch_id="epoch")
    state = I.initial_state(
        identity=I.StateIdentity(world_id="bounded-control", scenario_id="package-only", epoch_id="epoch",
                                 source_id="0"*64, runtime_id="1"*64, unit_system=I.UNIT_SYSTEM),
        start_time_s=0., frame_id="strip", reference=reference, settings=settings, theta0_k=np.zeros(base.size),
        kappa0=kappa0, materials=materials, layer_cohorts=ids, reservoirs=None, reservoir_basis=None)
    run = I.Continuation(state)
    first = run.advance(state, 1)
    last = run.advance(first.state, 3)
    continued = run.report(last.state)
retained = ("check_i01_column", "check_i01_weakening", "check_i01_column_heat", "check_i01_motion_coupling",
            "check_i01_thermomechanical_motion", "check_i01_finite_strain")
print(json.dumps(dict(
    loaded=sorted(name for name, module in list(sys.modules.items()) if name.startswith("check_") or from_tools(module)),
    on_path=[entry for entry in sys.path if entry and Path(entry).resolve() == tools],
    importable=[name for name in retained if importlib.util.find_spec(name) is not None],
    package=str(Path(E.__file__).resolve()), fingerprints=[base.fingerprint, thermal.fingerprint],
    status=out["status"], accepted=out["accepted_steps"], theta=out["theta"].tolist(), kappa=out["kappa"].tolist(),
    scalars={name: out[name] for name in ("stretch", "displacement_m", "velocity_end_m_s", "clock_s")},
    accounts=out["accounts"],
    continued=dict(statuses=[first.status, last.status], accepted=last.state.column.accepted_steps,
                   theta=continued["theta"].tolist(), kappa=continued["kappa"].tolist(),
                   scalars={name: continued[name] for name in ("stretch", "displacement_m", "velocity_end_m_s",
                                                               "clock_s")}))))
"""


def near(value, reference, relative=1e-12):
    """Agreement within a relative allowance of the reference array's own scale."""
    value, reference = np.asarray(value, dtype=float), np.asarray(reference, dtype=float)
    return float(np.abs(value-reference).max()) <= relative*max(float(np.abs(reference).max()), 1e-300)


def arrays(item):
    """Every array field of a prepared dataclass: a preparation, thermal support or eigensystem."""
    return [value for value in (getattr(item, f.name) for f in dataclasses.fields(item))
            if isinstance(value, np.ndarray)]


def deface(*items):
    """Ordinary descriptor edits along each array's .base chain (shape, then dtype); no payload byte is written."""
    for array in items:
        while type(array) is np.ndarray:
            array.shape = (array.size,)
            array.dtype = np.uint8
            array = array.base


class Limited(unittest.TestCase):
    def setUp(self):
        lease = threadpool_limits(limits=1, user_api="blas")
        self.addCleanup(lease.restore_original_limits)


class OwnershipTests(Limited):
    def test_downstream_receipts_bind_the_executed_package_owners(self):
        records = json.loads((ROOT/"evidence/current-evidence.json").read_text(encoding="utf-8"))["records"]
        current = {record["path"]: record["sha256"] for record in records if record["status"] == "current"}
        for tool, owners in ((tfa, PACKAGE), (tb, PACKAGE), (tca, (C, W, M))):
            bound = tool.bindings()
            for owner in owners:
                path = Path(owner.__file__).resolve()
                name = path.relative_to(ROOT).as_posix()
                with self.subTest(tool=tool.__name__, owner=name):
                    self.assertEqual(bound[name], hashlib.sha256(path.read_bytes()).hexdigest())
                    if tool is not tca:
                        self.assertIs(tool.IMPORTED[name], owner)
                        self.assertIn(name, tool.RETAINED)
            if tool is not tca:
                match = tool.evidence_match(bound)
                self.assertTrue(all(match["imported"].values()))
                # The register decides "current": only accepted receipts it lists as current at their pinned digests
                # may vouch for the moved code, and a historical predecessor never can. Nothing is rebound to pass.
                accepted = all(current.get("tectonics/"+name) == digest for name, digest in tool.ACCEPTED_RECEIPTS.items())
                self.assertEqual(all(match["retained"].values()), accepted, tool.__name__)

    def test_package_modules_import_no_campaign_code(self):
        allowed = {"__future__", "concurrent.futures", "dataclasses", "hashlib", "json", "math", "time", "numpy",
                   "scipy.linalg", "scipy.optimize"}
        siblings = {"_integration_column", "_integration_weakening", "_integration_heat", "_integration_motion",
                    "_integration_thermomechanical"}
        for module in PACKAGE:
            path = Path(module.__file__).resolve()
            with self.subTest(module=module.__name__):
                self.assertEqual(path.parent, Path(atlas_tectonics.__file__).resolve().parent)
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if isinstance(node, ast.Import):
                        self.assertLessEqual({alias.name for alias in node.names}, allowed)
                    elif isinstance(node, ast.ImportFrom) and node.level:
                        self.assertEqual((node.level, node.module), (1, None))      # sibling package owners only
                        self.assertLessEqual({alias.name for alias in node.names}, siblings)
                    elif isinstance(node, ast.ImportFrom):
                        self.assertIn(node.module, allowed)
                    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                        self.assertNotIn(node.func.id, {"exec", "eval", "compile", "__import__", "setattr", "globals"})
                    elif isinstance(node, ast.Attribute):
                        self.assertNotIn(node.attr, {"__globals__", "__code__", "__closure__", "meta_path", "path_hooks"})
                    elif isinstance(node, ast.Name):
                        self.assertNotIn(node.id, {"sys", "importlib", "runpy"})
                for name in TOOL_ONLY:
                    self.assertFalse(hasattr(module, name), name)

    def test_retained_tools_reexport_the_package_objects(self):
        package = {module.__name__ for module in PACKAGE}
        for owner, tool, names in MOVED:
            for name in names:
                with self.subTest(tool=tool.__name__, name=name):
                    value = getattr(owner, name)
                    self.assertIs(getattr(tool, name), value)
                    if isinstance(value, (type, types.FunctionType)):      # defined in the package, never a tool
                        self.assertIn(value.__module__, package)
        # One object graph: package owners reference each other, never a tool or a parallel copy.
        for owner, attribute, target in ((E, "tm", T), (E, "heat", H), (E, "motion", M), (E, "weakening", W),
                                         (T, "heat", H), (T, "motion", M), (T, "weakening", W), (M, "w", W),
                                         (H, "weakening", W), (H, "column", C), (W, "column", C)):
            self.assertIs(getattr(owner, attribute), target)
        # Retained callers still see the tool modules they cross-check among themselves.
        self.assertEqual((tfs.tm, tfs.heat, tfs.motion, tfs.weakening, tw.column), (ttm, th, tmo, tw, tc))
        self.assertEqual((tfa.fs, tfa.motion, tfa.w, tmo.w), (tfs, tmo, tw, tw))

    def test_no_second_implementation_remains_in_the_tools(self):
        everything = set().union(*(set(names) for _, _, names in MOVED))
        for owner, tool, names in MOVED:
            defined, assigned, imported = set(), set(), set()
            for node in ast.parse(Path(tool.__file__).read_text(encoding="utf-8")).body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    defined.add(node.name)
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                        assigned |= {leaf.id for leaf in ast.walk(target) if isinstance(leaf, ast.Name)}
                elif isinstance(node, ast.ImportFrom) and node.module == owner.__name__:
                    imported |= {alias.asname or alias.name for alias in node.names}
            own = set() if tool is tfs else {"evolve"}          # the retained small-strain evolutions stay tool methods
            with self.subTest(tool=tool.__name__):
                self.assertEqual(imported, set(names))
                self.assertFalse(set(names) & (defined | assigned))
                self.assertFalse(defined & (everything-own))

    def test_separately_loaded_tool_copy_shares_the_package_classes(self):
        spec = importlib.util.spec_from_file_location("i02_evolution_column_tool_copy", TOOLS/"check_i01_column.py")
        duplicate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(duplicate)
        self.assertIsNot(duplicate, tc)
        for name in ("Creep", "LocalLaw", "Column", "number", "POLICY"):
            self.assertIs(getattr(duplicate, name), getattr(C, name))
        law = duplicate.LocalLaw.prepare((tc.Creep(5e-22, 1., 0.),), 1000., 1e8, grain_m=.001, cohesion_pa=0.,
                                         friction_rad=0., pore_pressure_pa=0., plastic_viscosity_pa_s=None)
        self.assertIs(type(law), C.LocalLaw)

    def test_evolve_signature_defaults_and_carrier_constants_are_unchanged(self):
        signature = inspect.signature(E.evolve)
        self.assertEqual(str(signature), EVOLVE_SIGNATURE)
        defaults = {name: signature.parameters[name].default for name in ("conduction", "geometry_feedback",
                                                                          "warm_start")}
        self.assertEqual(defaults, {name: I.SOLVER[name] for name in defaults})
        # One reused eigensystem is the default; the rebuilt comparator stays opt-in.
        self.assertEqual((signature.parameters["modes"].default, signature.parameters["rebuild"].default), (None, None))
        # I02.2b: the carrier takes these from their package owners (one copy each), and the tool re-exports them.
        shared = ((I.STRETCH_CEILING, E.STRETCH_CEILING), (I.TEMPERATURE_CEILING_K, E.TEMPERATURE_CEILING_K),
                  (I.MAX_TEMPERATURE_STEP_K, E.MAX_TEMPERATURE_STEP_K), (I.THERMAL_ACCOUNTS, E.THERMAL_ACCOUNTS),
                  (I.REPRESENTATION, E.REPRESENTATION), (I._LIMITS, E.REPRESENTATION_LIMITS),
                  (I.LITHOSTATIC, W.LITHOSTATIC), (I.SUPPLIED, W.SUPPLIED), (tfs.REPRESENTATION, E.REPRESENTATION))
        for mine, owner in shared:
            self.assertIs(mine, owner)
        self.assertEqual(I.STAGE_ACCOUNTS, tuple(name for name, _ in E.STAGE_ACCOUNTS))
        self.assertEqual(I.STAGE_ACCOUNTS+I.THERMAL_ACCOUNTS, E.ACCOUNTS)
        self.assertEqual(set(I.COUNTERS+I.EXTREMA[:4]), set(E.DIAGNOSTICS))
        self.assertEqual((I.MAX_LAYERS, I.MAX_ORDER), (C.POLICY["max_layers"], C.POLICY["max_order"]))
        _, _, key, _ = tfs.layered(CTX, 4)
        self.assertEqual(I._preparation_fingerprint(dict(zip(("layers", "order", "closure", "gravity"), key))),
                         W.fingerprint(*key))

    def test_evolve_wraps_the_one_step_loop_and_the_connection_runs_none(self):
        def called(node):
            return {n.func.id for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}

        def loops(node):
            return any(isinstance(n, (ast.For, ast.While)) for n in ast.walk(node))
        tree = ast.parse(Path(E.__file__).read_text(encoding="utf-8"))
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        # Only advance() takes steps (the thermal clock); evolve composes the core without a loop of its own.
        self.assertEqual({name for name, node in functions.items() if "clock" in called(node)}, {"advance"})
        self.assertFalse(loops(functions["evolve"]))
        self.assertLessEqual({"prepare_run", "begin", "advance", "finish"}, called(functions["evolve"]))
        for name in ("prepare_run", "begin", "finish"):
            self.assertFalse(loops(functions[name]), name)
        tree = ast.parse(Path(I.__file__).read_text(encoding="utf-8"))
        connection = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Continuation")
        self.assertFalse(loops(connection))
        self.assertFalse(called(connection) & {"stage", "clock", "advance_map", "evolve", "conduct"})

    def test_strict_type_checks_hold_across_tools_and_package(self):
        base, thermal, key, _ = tfs.layered(CTX, 8)                  # built through the retained tool fixtures
        kappa0 = tw.initial_history(base, CTX["weak"])
        self.assertEqual(tuple(map(type, (base, thermal, LAW, DRIVE))),
                         (W.PreparedColumn, H.ThermalColumn, W.WeakeningLaw, M.Drive))
        # Package-built objects pass a retained caller's own identity checks (finite admission's Evolution).
        law = W.WeakeningLaw.from_spec(CTX["weak"]["weakening"])
        drive = M.Drive(DRIVE.force_n_m, DRIVE.drag_pa_s, DRIVE.width_m)
        evolution = tfa.Evolution(base, thermal, law, drive, key, kappa0, DURATION/16, WINDOW,
                                  REP["max_temperature_step_k"], (1., 1.), POLICY)
        self.assertIs(type(evolution.modes), H.Propagator)
        # Guards stay exact types: look-alikes and subclasses are refused, not duck-typed.
        common = dict(duration_s=DURATION, steps=1, window=WINDOW, temperature_step_k=REP["max_temperature_step_k"],
                      fractions=(1., 1.), policy=POLICY)

        class Imitation(W.WeakeningLaw):
            pass

        class Push(M.Drive):
            pass
        with self.assertRaisesRegex(ValueError, "reviewed mechanical preparation"):
            E.evolve(types.SimpleNamespace(**vars(base)), thermal, LAW, kappa0, DRIVE, **common)
        with self.assertRaisesRegex(ValueError, "typed weakening law"):
            E.evolve(base, thermal, Imitation(LAW.start, LAW.end, LAW.cohesion_factor, LAW.friction_factor), kappa0,
                     DRIVE, **common)
        with self.assertRaisesRegex(ValueError, "typed preparation"):
            M.solve(base, LAW, kappa0, Push(DRIVE.force_n_m, DRIVE.drag_pa_s, DRIVE.width_m))


class ProcessTests(unittest.TestCase):
    def test_package_alone_prepares_and_evolves_the_real_route(self):
        """A fresh interpreter with only the package source on its path: no tool is importable or imported."""
        env = dict(os.environ, PYTHONPATH=str(SRC), PYTHONDONTWRITEBYTECODE="1", OPENBLAS_NUM_THREADS="1",
                   OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
        with tempfile.TemporaryDirectory() as folder:
            done = subprocess.run([sys.executable, "-B", "-c", CHILD, str(ROOT), str(TOOLS)], cwd=folder, env=env,
                                  capture_output=True, text=True, encoding="utf-8", timeout=600, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-4000:])
        child = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual((child["loaded"], child["on_path"], child["importable"]), ([], [], []))
        self.assertEqual(Path(child["package"]), Path(E.__file__).resolve())
        # The retained tool entry point, in this process and on its own fixture, runs the same objects.
        with threadpool_limits(limits=1, user_api="blas"):
            base, thermal, key, _ = tfs.layered(CTX, 8)
            out = tfs.evolve(base, thermal, LAW, tw.initial_history(base, CTX["weak"]), DRIVE, duration_s=DURATION/4,
                             steps=4, window=WINDOW, temperature_step_k=REP["max_temperature_step_k"],
                             fractions=(1., 1.), policy=POLICY, inputs=key)
        self.assertEqual((out["status"], out["accepted_steps"]), ("COMPLETE", 4))
        self.assertEqual((child["status"], child["accepted"]), (out["status"], out["accepted_steps"]))
        self.assertEqual(child["fingerprints"], [base.fingerprint, thermal.fingerprint])
        for name in ("theta", "kappa"):
            self.assertTrue(near(child[name], out[name]), name)
        for name, value in child["scalars"].items():
            self.assertTrue(near(value, out[name]), name)
        self.assertEqual(set(child["accounts"]), ACCOUNTS)
        scale = [out["accounts"][name] for name in EXTENSIVE]
        self.assertTrue(near([child["accounts"][name] for name in EXTENSIVE], scale))
        # The package-only continuation (pieces of one and three steps) reaches the same four-step state.
        continued = child["continued"]
        self.assertEqual((continued["statuses"], continued["accepted"]), ([I.PIECE_COMPLETE, I.HISTORY_COMPLETE], 4))
        for name in ("theta", "kappa"):
            self.assertTrue(near(continued[name], out[name]), name)
        for name, value in continued["scalars"].items():
            self.assertTrue(near(value, out[name]), name)


class RouteTests(Limited):
    def setUp(self):
        super().setUp()
        self.base, self.thermal, self.key, self.rebuild = tfs.layered(CTX, 8)
        self.kappa0 = tw.initial_history(self.base, CTX["weak"])
        self.modes = E.eigensystem(self.thermal)

    def run_package(self, steps=16, **kw):
        kw.setdefault("modes", self.modes)
        for name, value in (("duration_s", DURATION), ("window", WINDOW), ("kappa0", self.kappa0), ("drive", DRIVE),
                            ("inputs", self.key)):
            kw.setdefault(name, value)
        return E.evolve(kw.pop("base", self.base), kw.pop("thermal", self.thermal), LAW, kw.pop("kappa0"),
                        kw.pop("drive"), steps=steps, temperature_step_k=REP["max_temperature_step_k"],
                        fractions=(1., 1.), policy=POLICY, **kw)

    def test_extension_and_compression_keep_signed_complete_accounts_and_references(self):
        names = ("layer", "depth_m", "weight", "reference_pa", "density", "log_c", "volume_rt")
        mechanical = {name: np.array(getattr(self.base, name)) for name in names}
        steady, capacity = np.array(self.thermal.steady_k), np.array(self.thermal.capacity)
        key, window, policy = copy.deepcopy(self.key), copy.deepcopy(WINDOW), copy.deepcopy(POLICY)
        supplied = self.kappa0.copy()
        for drive, sign in ((DRIVE, 1.), (SQUEEZE, -1.)):
            with self.subTest(force=drive.force_n_m):
                out = self.run_package(drive=drive, kappa0=supplied)
                acc = out["accounts"]
                self.assertEqual((out["status"], out["accepted_steps"]), ("COMPLETE", 16))
                self.assertEqual(set(acc), ACCOUNTS)
                self.assertTrue(all(math.isfinite(value) for value in acc.values()))
                self.assertTrue(tfs.closed(out, POLICY))
                # Signed motion: the drive does positive work either way and no dissipation is negative.
                for value in (out["displacement_m"], out["velocity_end_m_s"], out["stretch"]-1.):
                    self.assertEqual(math.copysign(1., value), sign)
                for name in ("drive_work_j_m", "drag_work_j_m", "column_work_j_m", "heat_j_m"):
                    self.assertGreater(acc[name], 0., name)
                self.assertGreaterEqual(min(acc["creep_work_j_m"], acc["plastic_work_j_m"]), 0.)
                self.assertEqual(acc["stored_j_m"], 0.)                  # heat fractions (1, 1) store nothing
                # Thinning speeds the thermal clock (more reference throughput); thickening slows it.
                self.assertEqual(math.copysign(1., acc["reference_outflow_j_m"]-acc["radiogenic_j_m"]), sign)
                # The current geometry is derived from the unchanged original reference, never re-based.
                self.assertEqual((out["width_m"], out["thickness_m"]),
                                 (DRIVE.width_m*out["stretch"], self.base.thickness_m/out["stretch"]))
                self.assertEqual((out["final"]["width_m"], out["final"]["thickness_m"]),
                                 (out["width_m"], out["thickness_m"]))
                self.assertTrue(tfs.conserved(out))
                fresh = tfs.freshness(CTX, self.base, self.thermal, self.key, out, drive=drive)
                self.assertLess(fresh["geometry_relative"], 1e-10)          # independent current-state preparation
                self.assertLess(fresh["stage_relative"], 1e-8)
                self.assertFalse(np.shares_memory(out["kappa0"], supplied))
        np.testing.assert_array_equal(supplied, self.kappa0)
        self.assertEqual((self.key, WINDOW, POLICY), (key, window, policy))
        for name in names:
            np.testing.assert_array_equal(getattr(self.base, name), mechanical[name])
        np.testing.assert_array_equal(self.thermal.steady_k, steady)
        np.testing.assert_array_equal(self.thermal.capacity, capacity)
        self.assertEqual(self.base.fingerprint, W.fingerprint(*self.key))
        self.assertTrue(H.valid_thermal(self.thermal) and H.same_support(self.thermal, self.base))
        self.assertFalse(any(np.asarray(value).flags.writeable for value in (
            self.base.weight, self.base.reference_pa, self.base.log_c, self.thermal.capacity, self.thermal.steady_k,
            self.modes.lam, self.modes.to_modal)))

    def test_rest_moves_nothing_and_conducts_only_the_existing_departure(self):
        bump = 2.*np.sin(math.pi*np.asarray(self.base.depth_m)/self.thermal.thickness_m)
        supplied = bump.copy()
        out = self.run_package(4, drive=STILL, theta0=supplied)
        acc = out["accounts"]
        np.testing.assert_array_equal(supplied, bump)
        self.assertFalse(np.shares_memory(out["theta0"], supplied))
        self.assertEqual((out["status"], out["accepted_steps"]), ("COMPLETE", 4))
        self.assertEqual(set(acc), ACCOUNTS)
        self.assertEqual((out["stretch"], out["displacement_m"], out["velocity_start_m_s"], out["velocity_end_m_s"]),
                         (1., 0., 0., 0.))
        for name in tfs.MECHANICAL:
            self.assertEqual(acc[name], 0., name)
        np.testing.assert_array_equal(out["kappa"], out["kappa0"])
        self.assertEqual(acc["radiogenic_j_m"], acc["reference_outflow_j_m"])
        self.assertLess(acc["thermal_change_j_m"], 0.)
        self.assertLess(acc["energy_relative"], 1e-10)
        self.assertLess(float(np.abs(out["theta"]).max()), float(np.abs(bump).max()))
        self.assertFalse(np.any(self.run_package(4, drive=STILL)["theta"]))

    def test_mismatched_references_refuse(self):
        other, _ = tw.base_prepare(CTX["weak"], order=8, offset_k=1.)
        thick = [layer["thickness_m"] for layer in self.key[0]]
        dens = [layer["density_kg_m3"] for layer in self.key[0]]
        denser = H.prepare_thermal(self.base.layer, self.base.depth_m, self.base.weight, thick,
                                   CTX["heat"]["thermal_layers"], [rho*1.01 for rho in dens], CTX["heat"]["boundaries"],
                                   mechanical_fingerprint=self.base.fingerprint)
        stretched = E.column_at(self.base, E.coefficients(self.base), 1.1, np.array(self.thermal.steady_k))
        stale = copy.deepcopy(self.key[0])
        stale[0]["temperature_k"] = [t+1e-9 for t in stale[0]["temperature_k"]]
        cases = dict(
            thermal_for_another_column=dict(base=other, inputs=None),
            stretched_state_as_reference=dict(base=stretched, inputs=None),
            thermal_density_one_percent=dict(thermal=denser, modes=None),
            stale_pinned_inputs=dict(inputs=(stale, *self.key[1:])),
            eigensystem_of_another_support=dict(modes=E.eigensystem(denser)))
        for name, kw in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.run_package(2, **kw)

    def test_prepared_operators_are_reused_and_the_cold_comparator_stays_opt_in(self):
        refuse = dict(side_effect=AssertionError("production path rebuilt a prepared operator"))
        with mock.patch.object(H, "prepare_propagator", **refuse), mock.patch.object(H, "prepare_thermal", **refuse), \
                mock.patch.object(W, "prepare", **refuse):
            warm = self.run_package(2, duration_s=DURATION/8)
        self.assertEqual((warm["status"], warm["accepted_steps"]), ("COMPLETE", 2))
        cold = self.run_package(2, duration_s=DURATION/8, modes=None, rebuild=self.rebuild, warm_start=False)
        self.assertEqual((cold["status"], cold["accepted_steps"]), ("COMPLETE", 2))
        for name in ("velocity_end_m_s", "log_strain"):
            self.assertLess(tw.relative_change(warm[name], cold[name]), 1e-8, name)
        self.assertTrue(near(warm["theta"], cold["theta"], 1e-8))


# ----------------------------------------------------------------------------- continuation fixtures (I02.2b)

EPOCH, FRAME, START = "i02-continuation-epoch", "i02-continuation-strip", 2.5e6
HALF = DURATION/2                          # eight whole steps of the retained refusal fixtures' dt = 6.25e12 s
PRODUCER = hashlib.sha256(b"declared producer: tectonics/tests/test_i02_evolution.py continuation").hexdigest()
RUNTIME = hashlib.sha256(json.dumps(dict(numpy=np.__version__), sort_keys=True).encode()).hexdigest()
BASIS = "declared-exterior-enthalpy"


def hand_over(base, thermal, key, inputs):
    """The retained preparations' own values, as the I02.1 carrier receives them."""
    density = None if np.all(np.isnan(base.density)) else base.density
    return (dict(key=key, fingerprint=base.fingerprint, layer=base.layer, depth_m=base.depth_m, weight=base.weight,
                 reference_pa=base.reference_pa, density=density, thickness_m=base.thickness_m),
            dict(provider=I.COLUMN_THERMAL_BASIS, inputs=inputs, fingerprint=thermal.fingerprint,
                 mechanical_fingerprint=thermal.mechanical_fingerprint, layer=thermal.layer, depth_m=thermal.depth_m,
                 volume_m=thermal.volume_m, reference_density_kg_m3=thermal.reference_density_kg_m3,
                 capacity=thermal.capacity, radiogenic=thermal.radiogenic, steady_k=thermal.steady_k,
                 boundary_temperature=thermal.boundary_temperature, thickness_m=thermal.thickness_m))


def scheduled(steps, duration=HALF, drive=DRIVE, **representation):
    """Settings of one fixed global schedule, dt = duration/steps, with the retained law, drive and policy."""
    return I.ColumnSettings(representation=dict(REP, **representation), law=dataclasses.asdict(LAW),
                            drive=dataclasses.asdict(drive), heat_fractions=(1., 1.), policy=POLICY,
                            schedule=dict(duration_s=duration, steps=steps))


def declared_root(reference, settings, theta0, kappa0, layers, *, reservoirs=None, basis=None):
    """A declared initial common state with native W02 cohorts (unknown formation times) in one strip cell."""
    ids = tuple("layer-%d-%s" % (k, layer["name"]) for k, layer in enumerate(layers))
    cohorts = {cohort: (MaterialCohort(cohort, layer["name"], "declared-layer-%d" % k, None),
                        float(layer["thickness_m"])) for k, (cohort, layer) in enumerate(zip(ids, layers))}
    ordered = sorted(cohorts)
    materials = MaterialState(ColumnGrid1D([0., settings.drive_parameters[2]], frame_id=FRAME),
                              tuple(cohorts[c][0] for c in ordered), [[cohorts[c][1]] for c in ordered],
                              time_s=START, epoch_id=EPOCH)
    identity = I.StateIdentity(world_id="atlas-bounded-control:not-a-generated-world",
                               scenario_id="tests/test_i02_evolution.py#continuation", epoch_id=EPOCH,
                               source_id=PRODUCER, runtime_id=RUNTIME, unit_system=I.UNIT_SYSTEM)
    return I.initial_state(identity=identity, start_time_s=START, frame_id=FRAME, reference=reference,
                           settings=settings, theta0_k=theta0, kappa0=kappa0, materials=materials, layer_cohorts=ids,
                           reservoirs=reservoirs, reservoir_basis=basis)


class ContinuationTests(Limited):
    """One layered order-8 history of eight whole steps (dt = 6.25e12 s) advanced in pieces from its common state."""

    def setUp(self):
        super().setUp()
        self.base, self.thermal, self.key, self.inputs = tfs.layered(CTX, 8)
        self.kappa0 = tw.initial_history(self.base, CTX["weak"])                  # nonzero inherited history
        self.theta0 = 2.*np.sin(2.*math.pi*np.asarray(self.base.depth_m)/self.base.thickness_m)     # both signs
        self.mechanical, self.thermal_side = hand_over(self.base, self.thermal, self.key, self.inputs)
        self.reference = I.ColumnReference(mechanical=self.mechanical, thermal=self.thermal_side)

    def history(self, steps=8, *, duration=HALF, drive=DRIVE, theta0=None, reference=None, reservoirs=None,
                basis=None, **representation):
        return declared_root(self.reference if reference is None else reference,
                             scheduled(steps, duration, drive, **representation),
                             self.theta0 if theta0 is None else theta0, self.kappa0, self.key[0],
                             reservoirs=reservoirs, basis=basis)

    def uninterrupted(self, run, steps, *, drive=DRIVE, theta0=None, window=WINDOW):
        """The retained evolve entry point on the continuation's own prepared bytes, for steps of the same dt.

        The runner hands out fresh inspection copies of its owned preparation, support and eigensystem.
        """
        r = run.runner
        return E.evolve(r.base, r.thermal, LAW, self.kappa0, drive, duration_s=r.dt*steps, steps=steps, window=window,
                        temperature_step_k=REP["max_temperature_step_k"], fractions=(1., 1.), policy=POLICY,
                        modes=r.modes, theta0=self.theta0 if theta0 is None else theta0, inputs=self.key)

    def assert_same_run(self, report, whole):
        """Bitwise: every retained scalar diagnostic, array, signed account, conservation value and final stage."""
        for name in tfs.SCALARS:
            if name not in ("status", "reason"):
                self.assertEqual(report[name], whole[name], name)
        for name in ("theta", "theta0", "kappa", "kappa0", "yielded"):
            np.testing.assert_array_equal(report[name], whole[name])
        self.assertEqual(set(report["accounts"]), ACCOUNTS)
        for name in ("accounts", "conservation", "reference"):
            self.assertEqual(report[name], whole[name], name)
        for name in ("velocity_m_s", "force", "rate", "msource", "kdot"):
            np.testing.assert_array_equal(report["final"][name], whole["final"][name])

    def test_uneven_pieces_reproduce_the_uninterrupted_route_bitwise(self):
        bump = 2.*np.sin(math.pi*np.asarray(self.base.depth_m)/self.thermal.thickness_m)
        for drive, theta0 in ((DRIVE, None), (SQUEEZE, None), (STILL, bump)):
            with self.subTest(force=drive.force_n_m):
                state = self.history(drive=drive, theta0=theta0)
                run = I.Continuation(state)
                whole = self.uninterrupted(run, 8, drive=drive, theta0=theta0)
                self.assertEqual((whole["status"], whole["accepted_steps"]), ("COMPLETE", 8))
                finals = []
                for pieces in ((3, 5), (1, 2, 4, 1)):
                    current, statuses = state, []
                    for n in pieces:
                        outcome = run.advance(current, n)
                        self.assertEqual((outcome.requested_steps, outcome.accepted_steps), (n, n))
                        statuses.append(outcome.status)
                        current = outcome.state
                    self.assertEqual(statuses, [I.PIECE_COMPLETE]*(len(pieces)-1)+[I.HISTORY_COMPLETE])
                    self.assert_same_run(run.report(current), whole)
                    finals.append(current)
                # Same physics and accounts on a different path: the column identity agrees, the lineage does not.
                self.assertEqual(finals[0].column.column_state_id, finals[1].column.column_state_id)
                self.assertNotEqual(finals[0].parent_state_id, finals[1].parent_state_id)
                if drive is STILL:
                    self.assertEqual((finals[0].column.stretch, finals[0].column.displacement_m), (1., 0.))
                else:
                    self.assertEqual(math.copysign(1., finals[0].column.stretch-1.), math.copysign(1., drive.force_n_m))
                    self.assertTrue(tfs.closed(dict(whole), POLICY))
                # An independently prepared column (tool fixtures and their own eigensystem) agrees at round-off.
                other = E.evolve(self.base, self.thermal, LAW, self.kappa0, drive, duration_s=HALF, steps=8,
                                 window=WINDOW, temperature_step_k=REP["max_temperature_step_k"], fractions=(1., 1.),
                                 policy=POLICY, theta0=self.theta0 if theta0 is None else theta0, inputs=self.key)
                report = run.report(finals[1])
                for name in ("theta", "kappa"):
                    self.assertTrue(near(report[name], other[name]), name)
                self.assertTrue(near([report["accounts"][name] for name in EXTENSIVE],
                                     [other["accounts"][name] for name in EXTENSIVE]))

    def test_cold_reconstruction_agrees_within_the_retained_parity(self):
        state = self.history()
        first = I.Continuation(state)
        three = first.advance(state, 3).state
        later = I.Continuation(three)                      # a new session: operators rebuilt from the pinned inputs
        rest = later.advance(three, 5)
        self.assertEqual((rest.status, rest.accepted_steps, rest.warm), (I.HISTORY_COMPLETE, 5, False))
        self.assertGreater(rest.reconstruction_evaluations, 0)
        cold, whole = later.report(rest.state), self.uninterrupted(first, 8)
        tolerance = POLICY["parity_relative"]              # the retained warm/cold comparator allowance
        for name in ("stretch", "log_strain", "log_path", "clock_s", "displacement_m", "velocity_end_m_s",
                     "mean_history_gain"):
            self.assertLess(tw.relative_change(cold[name], whole[name]), tolerance, name)
        for name in ("theta", "kappa"):
            self.assertTrue(near(cold[name], whole[name], tolerance), name)
        self.assertTrue(near([cold["accounts"][name] for name in EXTENSIVE],
                             [whole["accounts"][name] for name in EXTENSIVE], tolerance))
        self.assertTrue(tfs.closed(dict(cold, status="COMPLETE"), POLICY))
        # The cold endpoint re-solve is operational work: stages, mismatches and yields are booked exactly once.
        self.assertEqual((cold["stages"], cold["restress_mismatches"], cold["yield_switching_points"]),
                         (whole["stages"], whole["restress_mismatches"], whole["yield_switching_points"]))
        self.assertEqual(rest.state.column.counters["stages"], 1+2*8)
        np.testing.assert_array_equal(cold["yielded"], whole["yielded"])
        # The first session still holds its own warm head: branching there reproduces the run bitwise.
        warm = first.advance(three, 5)
        self.assertTrue(warm.warm)
        self.assert_same_run(first.report(warm.state), whole)
        np.testing.assert_array_equal(rest.state.column.yield_stage_counts, warm.state.column.yield_stage_counts)

    def test_pieces_neither_rerun_the_prefix_nor_rebuild_operators(self):
        state = self.history()
        run = I.Continuation(state)                        # the one eigensystem is prepared here
        before, calls, original = run.runner.modes, [], E.stage       # an inspection copy of the owned eigensystem

        def counted(*args, **kwargs):
            calls.append(args[3])                          # the stretch of every balanced stage
            return original(*args, **kwargs)
        refuse = dict(side_effect=AssertionError("a piece rebuilt a prepared operator"))
        with mock.patch.object(E, "stage", side_effect=counted), mock.patch.object(H, "eigh", **refuse), \
                mock.patch.object(H, "prepare_propagator", **refuse), \
                mock.patch.object(H, "prepare_thermal", **refuse), mock.patch.object(W, "prepare", **refuse):
            a = run.advance(state, 3)
            self.assertEqual(len(calls), 1+2*3)            # the reference balance once, then two stages per step
            b = run.advance(a.state, 2)
            self.assertEqual(len(calls), 7+2*2)            # warm: no accepted step re-run, no endpoint re-solve
            run.report(b.state)
            self.assertEqual(len(calls), 11)               # reporting the warm head solves nothing
            c = run.advance(a.state, 1)                    # a branch from an earlier state re-solves one endpoint
            self.assertEqual(len(calls), 11+1+2)
        # The owned eigensystem is neither rebuilt nor copied: every inspection copy shares its unchanged bytes.
        after = run.runner.modes
        self.assertIsNot(after, before)
        for name in ("lam", "to_modal", "source_modal", "from_modal"):
            self.assertTrue(np.shares_memory(getattr(after, name), getattr(before, name)), name)
        self.assertEqual((a.warm, b.warm, c.warm), (False, True, False))
        self.assertEqual((b.reconstruction_evaluations, c.reconstruction_evaluations > 0), (0, True))
        self.assertEqual((b.state.column.counters["stages"], c.state.column.counters["stages"]), (1+2*5, 1+2*4))
        self.assertEqual((c.state.parent_state_id, c.state.root_state_id), (a.state.state_id, state.state_id))

    def test_schedule_is_fixed_whole_and_cumulative(self):
        state = self.history(4, duration=HALF/2)           # four whole steps of the same dt
        run = I.Continuation(state)
        step_s = state.settings.step_s
        self.assertEqual((run.runner.dt, step_s), (HALF/8, HALF/8))
        for bad in (0, -1, 5, True, 2., "2", None):
            with self.subTest(steps=bad), self.assertRaises(TectonicsError):
                run.advance(state, bad)
        first = run.advance(state, 3)
        three = first.state
        self.assertEqual((first.status, first.history_complete, three.remaining_steps), (I.PIECE_COMPLETE, False, 1))
        self.assertEqual((three.column.accepted_steps, three.column.elapsed_s, three.time_s),
                         (3, 3*step_s, START+3*step_s))
        with self.assertRaises(TectonicsError):
            run.advance(three, 2)                          # beyond the fixed schedule: no new duration or budget
        last = run.advance(three, 1)
        self.assertEqual((last.status, last.history_complete, last.state.remaining_steps),
                         (I.HISTORY_COMPLETE, True, 0))
        self.assertEqual(last.state.column.elapsed_s, 4*step_s)
        for continuation in (run, I.Continuation(last.state)):      # a fresh session cannot reset the global index
            with self.assertRaisesRegex(TectonicsError, "complete"):
                continuation.advance(last.state, 1)

    def test_refused_trials_return_the_exact_accepted_prefix(self):
        dt = HALF/8
        third = E.evolve(self.base, self.thermal, LAW, self.kappa0, DRIVE, duration_s=3*dt, steps=3, window=WINDOW,
                         temperature_step_k=REP["max_temperature_step_k"], fractions=(1., 1.), policy=POLICY,
                         theta0=self.theta0, inputs=self.key)
        euler_fourth = third["stretch"]+dt*third["velocity_end_m_s"]/DRIVE.width_m
        window = [WINDOW["stretch"][0], (third["stretch"]+euler_fourth)/2]      # the fourth predictor leaves it
        state = self.history(stretch_window=window)
        run = I.Continuation(state)
        two = run.advance(state, 2)
        cut = run.advance(two.state, 6)
        self.assertEqual((two.status, cut.status, cut.reason),
                         (I.PIECE_COMPLETE, "REFUSED_STRETCH_WINDOW", "predictor stretch leaves the declared window"))
        self.assertEqual((cut.accepted_steps, cut.state.column.accepted_steps, cut.history_complete), (1, 3, False))
        self.assertEqual(cut.state.parent_state_id, two.state.state_id)
        report = run.report(cut.state)
        self.assertTrue(tfs.same_prefix(report, self.uninterrupted(run, 3, window=dict(WINDOW, stretch=window))))
        self.assertTrue(tfs.nothing_lost(report, POLICY))
        again = run.advance(cut.state, 1)                  # the refused trial repeats, books nothing, returns the input
        self.assertIs(again.state, cut.state)
        self.assertEqual((again.status, again.accepted_steps), ("REFUSED_STRETCH_WINDOW", 0))
        hot = self.history(max_temperature_step_k=1e-3)
        refused = I.Continuation(hot).advance(hot, 2)
        self.assertIs(refused.state, hot)
        self.assertEqual((refused.status, refused.accepted_steps), ("REFUSED_TEMPERATURE_STEP", 0))
        self.assertEqual((hot.column.counters["stages"], hot.column.velocity_start_m_s), (0, None))

    def test_expiry_after_the_final_endpoint_solve_books_nothing(self):
        state = self.history()
        run = I.Continuation(state)
        two = run.advance(state, 2).state
        deadline = ttm.CountdownDeadline(10**9)
        calls, original = 0, E.stage

        def finish_then_expire(*args, **kwargs):
            nonlocal calls
            result = original(*args, **kwargs)
            calls += 1
            if calls == 4:                                 # the second trial's endpoint; the check after it expires
                deadline.remaining = 0
            return result
        with mock.patch.object(E, "stage", side_effect=finish_then_expire):
            cut = run.advance(two, 2, deadline=deadline)
        self.assertEqual(calls, 4)
        self.assertEqual((cut.status, cut.accepted_steps, cut.state.column.accepted_steps), ("REFUSED_DEADLINE", 1, 3))
        self.assertTrue(tfs.same_prefix(run.report(cut.state), self.uninterrupted(run, 3)))
        # The expired trial left no trace in the warm head: finishing the schedule matches the uninterrupted run.
        rest = run.advance(cut.state, 5)
        self.assertTrue(rest.warm)
        self.assert_same_run(run.report(rest.state), self.uninterrupted(run, 8))
        # An exhausted budget before a cold endpoint could be balanced refuses without booking anything.
        fresh = I.Continuation(two)
        late = fresh.advance(two, 1, deadline=0.)
        self.assertIs(late.state, two)
        self.assertEqual((late.status, late.accepted_steps), ("REFUSED_DEADLINE", 0))

    def test_prior_states_and_caller_edits_cannot_change_the_history(self):
        state = self.history()
        run = I.Continuation(state)
        first = run.advance(state, 3)

        def snapshot(s):
            return (s.state_id, json.dumps(s.descriptor(), sort_keys=True),
                    *(a.tobytes() for a in (s.column.theta_k, s.column.kappa, s.column.initial_theta_k,
                                            s.column.initial_kappa, s.column.yield_stage_counts)))
        before = [snapshot(s) for s in (state, first.state)]
        report = run.report(first.state)
        final = report["final"]
        for array in (report["theta"], report["kappa"], report["theta0"], report["kappa0"], final["x"],
                      final["source"], final["kdot"], final["msource"]):
            array[...] = 7.                                # the report holds copies, not carried or warm data
        report["accounts"]["heat_j_m"], final["velocity_m_s"] = -1., 0.
        view = first.state.column.theta_k
        view.shape = (1, view.size)                        # a descriptor edit stays local to that view
        view.dtype = np.uint8
        for array in (first.state.column.kappa, first.state.reference.depth_m):
            with self.assertRaises(ValueError):
                array[0] = 1.
        rest = run.advance(first.state, 5)
        self.assertTrue(rest.warm)
        self.assert_same_run(run.report(rest.state), self.uninterrupted(run, 8))
        self.assertEqual([snapshot(s) for s in (state, first.state)], before)
        # Deterministic: a second continuation from the untouched root issues the same successor identity.
        self.assertEqual(I.Continuation(state).advance(state, 3).state.state_id, first.state.state_id)

    def test_inspected_runner_edits_cannot_reach_later_pieces(self):
        """Review's two reproductions, then shape, dtype and .base edits of every inspected array before each piece."""
        state = self.history()
        clean = I.Continuation(state)                      # an untouched session issues the reference successors
        one = clean.advance(state, 1).state
        two = clean.advance(one, 1).state

        def weight_shape(runner):                          # review reproduction: previously a TypeError
            runner.base.weight.shape = (runner.base.weight.size, 1)

        def eigenvalue_shape(runner):                      # review reproduction: previously REFUSED_CONSTITUTIVE
            runner.modes.lam.shape = (runner.modes.lam.size, 1)
        edits = dict(weight_shape=weight_shape, eigenvalue_shape=eigenvalue_shape,
                     preparation=lambda runner: deface(*arrays(runner.base)),
                     thermal_support=lambda runner: deface(*arrays(runner.thermal)),
                     eigensystem=lambda runner: deface(*arrays(runner.modes)),
                     creep_terms=lambda runner: deface(*runner.coeffs))
        for name, edit in edits.items():
            with self.subTest(name):
                run = I.Continuation(state)
                edit(run.runner)
                first = run.advance(state, 1)
                edit(run.runner)
                second = run.advance(first.state, 1)
                self.assertEqual((first.status, second.status), (I.PIECE_COMPLETE, I.PIECE_COMPLETE))
                self.assertTrue(second.warm)
                self.assertEqual((first.state.state_id, second.state.state_id), (one.state_id, two.state_id))
                self.assert_same_run(run.report(second.state), self.uninterrupted(run, 2))
                # Inspection still hands out intact copies that pass the package's own typed checks.
                base, thermal, modes = run.runner.base, run.runner.thermal, run.runner.modes
                self.assertEqual((base.weight.shape, modes.lam.shape), ((base.size,), (base.size,)))
                self.assertTrue(H.same_support(thermal, base))      # includes the thermal preparation digest
                self.assertEqual(modes.fingerprint, thermal.fingerprint)

    def test_caller_objects_edited_after_preparation_cannot_reach_the_core(self):
        """Direct core use: the caller keeps and edits everything it handed to prepare_run and begin."""
        for comparator in (False, True):
            with self.subTest(rebuilt_comparator=comparator):
                base, thermal, key, inputs = tfs.layered(CTX, 8)       # the caller's own objects, edited below
                modes = None if comparator else E.eigensystem(thermal)
                rebuild = copy.deepcopy(inputs) if comparator else None    # never the shared case data
                kappa0, theta0 = self.kappa0.copy(), self.theta0.copy()
                options = dict(duration_s=HALF/4, steps=2, window=WINDOW, fractions=(1., 1.), policy=POLICY,
                               temperature_step_k=REP["max_temperature_step_k"], modes=modes,
                               warm_start=not comparator, rebuild=rebuild, inputs=key)
                expected = E.evolve(base, thermal, LAW, kappa0, DRIVE, theta0=theta0, **options)
                pristine = copy.deepcopy(rebuild)
                run = E.prepare_run(base, thermal, LAW, DRIVE, **options)
                prefix = E.begin(run, kappa0, theta0)
                deface(*arrays(base), *arrays(thermal), *(arrays(modes) if modes is not None else ()), *run.coeffs)
                kappa0[...], theta0[...] = 0., 1.
                if comparator:
                    rebuild["props"][0]["conductivity_w_m_k"] *= 3.         # the caller's original nested mapping
                    rebuild["densities"][0] *= 2.
                    inspected = run.rebuild                                 # a fresh nested inspection copy
                    inspected["props"][1]["heat_capacity_j_kg_k"] *= 5.
                    inspected["thicknesses"][0] *= 2.
                self.assertEqual(run.rebuild, pristine)
                self.assertIsNot(run.coeffs[0], run.coeffs[0])
                out = E.finish(run, *E.advance(run, prefix, 2))
                if comparator:          # factorised again every step by design: agreement at round-off, not bitwise
                    self.assertEqual((out["status"], out["accepted_steps"], out["stages"]), ("COMPLETE", 2, 5))
                    for name in ("theta", "kappa", "stretch", "displacement_m", "clock_s", "velocity_end_m_s"):
                        self.assertTrue(near(out[name], expected[name]), name)
                    self.assertTrue(near([out["accounts"][name] for name in EXTENSIVE],
                                         [expected["accounts"][name] for name in EXTENSIVE]))
                else:
                    self.assert_same_run(out, expected)

    def test_forged_incompatible_and_unreproducible_inputs_refuse(self):
        state = self.history()
        run = I.Continuation(state)
        one = run.advance(state, 1).state
        two = run.advance(one, 1).state
        lookalike = types.SimpleNamespace(**{name: getattr(one, name) for name in I.CommonState.__slots__})
        swapped = object.__new__(I.CommonState)
        for name in I.CommonState.__slots__:
            object.__setattr__(swapped, name, getattr(one, name))
        object.__setattr__(swapped, "column", two.column)      # another state's column under this identity
        cases = dict(lookalike=lookalike, swapped_column=swapped, another_history=self.history(theta0=-self.theta0),
                     another_schedule=self.history(16, duration=DURATION))
        for name, candidate in cases.items():
            with self.subTest(name), self.assertRaises(TectonicsError):
                run.advance(candidate, 1)
        with self.assertRaises(TectonicsError):
            run.report(swapped)
        edited = run.advance(two, 1).state
        object.__setattr__(edited.column, "stretch", edited.column.stretch+1e-3)   # an edit behind the identity
        for attempt in (lambda: run.advance(edited, 1), lambda: I.Continuation(edited)):
            with self.assertRaises(TectonicsError):
                attempt()
        # The carrier accepts declared overburden and geotherm values; a rebuild must reproduce their bytes.
        bumped = np.array(self.base.reference_pa)
        bumped[5] = np.nextafter(bumped[5], np.inf)
        warmer = np.array(self.thermal.steady_k)
        warmer[3] = np.nextafter(warmer[3], np.inf)
        declared = (("overburden", dict(self.mechanical, reference_pa=bumped), self.thermal_side),
                    ("steady geotherm", self.mechanical, dict(self.thermal_side, steady_k=warmer)))
        for name, mechanical, thermal_side in declared:
            forged = self.history(reference=I.ColumnReference(mechanical=mechanical, thermal=thermal_side))
            with self.subTest(name), self.assertRaisesRegex(TectonicsError, name):
                I.Continuation(forged)

    def test_native_payloads_stay_unchanged_and_current_geometry_is_derived(self):
        stock = W08Inventory(node_ids=("exterior-store",), node_kinds=("reservoir",), component_ids=("A",),
                             component_mass_kg=[[5.]], enthalpy_j=[-3.], source_id="declared-exterior-stock",
                             enthalpy_source=BASIS, time_s=START, formation_time_s=[START-10.],
                             origin_ids=("declared-exterior-origin",))
        state = self.history(reservoirs=stock, basis=BASIS)
        run = I.Continuation(state)
        middle = run.advance(state, 2).state
        later = run.advance(middle, 1).state
        self.assertEqual((middle.parent_state_id, middle.initial_state_id, middle.root_state_id),
                         (state.state_id, state.state_id, state.state_id))
        self.assertEqual((later.parent_state_id, later.root_state_id), (middle.state_id, state.state_id))
        for part in ("reference", "settings", "materials", "reservoirs"):
            self.assertIs(getattr(later, part), getattr(state, part))
        self.assertEqual((later.materials.time_s, later.reservoirs.time_s, later.time_s),
                         (START, START, START+3*later.settings.step_s))
        record = later.descriptor()
        materials, reservoirs = record["materials"], record["reservoirs"]
        self.assertEqual((materials["dated_time_s"], materials["role"]), (START, I.MATERIAL_ROLE))
        self.assertEqual((reservoirs["dated_time_s"], reservoirs["role"]), (START, I.RESERVOIR_ROLE))
        self.assertEqual(reservoirs["descriptor"], stock.descriptor())
        # Current geometry is derived from the unchanged reference and the accepted stretch; h_k stays at lam = 1.
        lam = later.column.stretch
        self.assertEqual(later.current_layer_thickness_m.tobytes(),
                         (later.reference.layer_thickness_m/lam).tobytes())
        self.assertEqual((later.current_width_m, later.current_thickness_m),
                         (DRIVE.width_m*lam, self.base.thickness_m/lam))
        self.assertEqual(later.cohort_reference_volume_m2(), state.cohort_reference_volume_m2())
        self.assertEqual(later.materials.thickness_m.tobytes(), state.materials.thickness_m.tobytes())
        # Accepted-state diagnostics become known; physics this route lacks stays unknown; nothing is admitted.
        known = {entry["name"]: entry["known"] for entry in later.declaration()}
        self.assertTrue(all(known[name] for name in ("velocity_start_m_s", "column_force_start_n_m",
                                                     *("extrema."+name for name in I.EXTREMA))))
        self.assertFalse(any(known[name] for name in ("elastic_stress_pa", "melt_fraction", "absolute_elevation_m",
                                                      "global_position", "lateral_structure", "external_loads_pa")))
        self.assertEqual(later.column.counters["stages"], 1+2*3)
        self.assertEqual((later.admission, record["admission"]), (I.NOT_CONFERRED, I.NOT_CONFERRED))
        scope = dict(window=tfs.declared_window(SPEC), horizon_s=SPEC["drive"]["duration_s"])
        with self.assertRaisesRegex(ValueError, "committed finite-strain state"):
            tfa.prepare(self.base, self.thermal, LAW, DRIVE, self.key, later, **scope)


class OracleTests(Limited):
    def test_homogeneous_package_evolution_matches_independent_oracles(self):
        """DOP853 with the scalar column kernel and SciPy Brent roots; neither shares the vectorised solver."""
        base, thermal, h = ttm.homogeneous_setup(CTX, 4)
        layer, k0, duration = h["layer"], float(h["initial_history"]), 2.5e13
        oracle = tfs.stretch_oracle(layer, h["thermal"], LAW, DRIVE, k0, duration, (1., 1.))
        self.assertTrue(oracle["always_yielding"])
        errors = []
        for n in (16, 32, 64):
            out = E.evolve(base, thermal, LAW, np.full(base.size, k0), DRIVE, duration_s=duration, steps=n,
                           window=WINDOW, temperature_step_k=5., fractions=(1., 1.), policy=POLICY)
            self.assertTrue(tfs.closed(out, POLICY))
            errors.append((tw.relative_change(float(out["theta"][0]), oracle["temperature_rise"]),
                           tw.relative_change(float(out["kappa"][0])-k0, oracle["history_gain"])))
        for series in zip(*errors):
            for order in tw.order(list(series)):
                self.assertTrue(1.8 <= order <= 2.2, order)
        # The same 64 steps continued from a common state in two uneven pieces, judged by the same oracle.
        inputs = dict(thicknesses=[layer["thickness_m"]],
                      props=[dict(name=layer["name"], conductivity_w_m_k=h["thermal"]["conductivity_w_m_k"],
                                  heat_capacity_j_kg_k=h["thermal"]["heat_capacity_j_kg_k"], radiogenic_w_m3=0.)],
                      densities=[h["thermal"]["density_kg_m3"]],
                      boundaries=dict(top=dict(type="insulated"), bottom=dict(type="insulated")),
                      reference_temperature=layer["temperature_k"][0])
        mechanical, thermal_side = hand_over(base, thermal, ([layer], 4, W.SUPPLIED, None), inputs)
        state = declared_root(I.ColumnReference(mechanical=mechanical, thermal=thermal_side), scheduled(64, duration),
                              np.zeros(base.size), np.full(base.size, k0), [layer])
        run = I.Continuation(state)
        piece = run.advance(state, 23)
        chunked = run.report(run.advance(piece.state, 41).state)
        chunk_errors = (tw.relative_change(float(chunked["theta"][0]), oracle["temperature_rise"]),
                        tw.relative_change(float(chunked["kappa"][0])-k0, oracle["history_gain"]))
        for mine, coarser in zip(chunk_errors, errors[-2]):
            self.assertLess(mine, coarser/3.)              # continues the verified second-order convergence
        self.assertTrue(near(chunked["theta"], out["theta"]) and near(chunked["kappa"], out["kappa"]))
        self.assertGreater(chunked["stretch"], 1.)
        start = tfs.stretch_balance(layer, LAW, DRIVE, layer["temperature_k"][0], k0, 1.)
        end = tfs.stretch_balance(layer, LAW, DRIVE, float(thermal.steady_k[0]+out["theta"][0]), float(out["kappa"][0]),
                                  out["stretch"])
        self.assertLess(tw.relative_change(out["velocity_start_m_s"], start["velocity_m_s"]),
                        POLICY["root_parity_relative"])
        self.assertLess(tw.relative_change(out["velocity_end_m_s"], end["velocity_m_s"]), POLICY["root_parity_relative"])
        self.assertGreater(out["stretch"], 1.)


if __name__ == "__main__":
    unittest.main()
