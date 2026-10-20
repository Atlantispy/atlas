"""Native writer-to-verifier boundary controls; no solve or scientific CONTROL.

Each arm runs in a fresh process with its selected native module paths. Physical
inputs/results are declared synthetic. CompactMesh authentication, exact native
row/support/accessor APIs, writer operations and release receipts are real.
All generated files and failure logs are retained in a unique workspace folder.
"""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE / "writer-verifier-test-artifacts"


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = load_file("writer_boundary_verifier", HERE / "verify_d02_r13.py")


def hx(value):
    return [hex(value), "0x1"]


def xyz(x, y=0, z=0):
    return [hx(x), hx(y), hx(z)]


def save_json(path, value):
    with path.open("xb") as stream:
        stream.write(V.canonical(value))


def native_record(native, arm):
    """Three uniquely identified cells, eight faces, both native support kinds."""
    H = native.digest
    funding, support_id = H(["synthetic-funding", arm]), H(["synthetic-support", arm])
    grid_id, trajectory = H("synthetic-grid"), H([])
    supports = dict(voxels={}, radial_layers={}, cones={})
    cells = []
    for i in range(3):
        voxel = dict(lower_m=xyz(i), upper_m=xyz(i + 1, 1, 1))
        vid = H(voxel)
        supports["voxels"][vid] = voxel
        refs = dict(voxel_id=vid)
        if i < 2:
            logical = H(dict(kind="collar", funding_id=funding, cell_id=vid))
            row = dict(kind="collar", index=[i, 0, 0], cell_id=logical,
                       logical_cell_id=logical, physical_cell_id=vid)
        else:
            layer, cone = dict(radius_m=hx(10)), [xyz(1), xyz(1, 1), xyz(1, 0, 1)]
            lid, cone_id = H(layer), H(cone)
            supports["radial_layers"][lid], supports["cones"][cone_id] = layer, cone
            refs.update(radial_layer_id=lid, cone_id=cone_id)
            row = dict(kind="exterior", source_key=[H("synthetic-material"), "layer"],
                       voxel_index=[i, 0, 0], radial_band=0, chart=0)
            logical = H({k: row[k] for k in ("source_key", "voxel_index", "radial_band", "chart")}
                        | dict(grid_id=grid_id))
            row.update(logical_cell_id=logical,
                       cell_id=H(dict(logical_cell_id=logical, support_id=support_id)))
        row.update(volume_m3=hx(1), centroid_m=[[hex(2 * i + 1), "0x2"], ["0x1", "0x2"], ["0x1", "0x2"]],
                   physical_volume_bounds_m3=[hx(1), hx(1)],
                   geometry_volume_max_deviation_m3=hx(0), physical_support=refs, faces=[])
        cells.append(row)
    faces = []
    orientation = -1 if arm else 1
    for i in range(8):
        fid = H(["synthetic-face", arm, i])
        linked = []
        if i < 4:
            if i > 0:
                linked.append((i - 1, orientation))
            if i < 3:
                linked.append((i, -orientation))
        else:
            linked.append(((i - 4) % 3, orientation))
        for ci, sign in linked:
            cells[ci]["faces"].append([fid, sign])
        ring = [xyz(i, 0, 0), xyz(i, 1, 0), xyz(i, 1, 1), xyz(i, 0, 1)]
        if arm:
            ring.reverse()
        faces.append(dict(face_id=fid, kind="interior" if len(linked) == 2 else "boundary",
                          geometry_kind="cartesian", centroid_m=xyz(i),
                          area_vector_m2=xyz(orientation), vertices_m=ring,
                          owners=[cells[ci]["cell_id"] for ci, _ in linked],
                          relative_advection="actual certified Cartesian face-time material measure"))
    order = [1, 2, 0] if arm else [0, 1, 2]
    face_order = [7, 3, 1, 6, 0, 4, 2, 5] if arm else list(range(8))
    record = dict(schema=native.LEGACY, method=native.METHOD, funding_id=funding,
                  source={}, support_id=support_id, trajectory_id=trajectory,
                  trajectory_segments=[], endpoint="end", time_s=hx(1), grid_id=grid_id,
                  cells=[cells[i] for i in order], faces=[faces[i] for i in face_order],
                  support_tables=supports,
                  grid_lines=[[hx(i) for i in range(4)], [hx(0), hx(1)], [hx(0), hx(1)]])
    return record, order, face_order


def semantic_result(record, geometry_id, order, face_order, arm, layout):
    """Full synthetic result contract with independently stated exact accounts."""
    H = V.object_hash
    source_policy = "already-booked-transport; zero added heat source"
    boundary = {f["face_id"]: ["power", 0.0] for f in record["faces"] if len(f["owners"]) == 1}
    target = 10**24
    plan = dict(schema="atlas.private.composed-heat-plan.r1",
                method_id="synthetic-exact-transfer-fixture", geometry_id=geometry_id,
                conductivity_w_m_k=[1.0] * 3, boundary=boundary,
                absolute_residual_target=["1", str(target)], absolute_residual_target_decimal="1e-24",
                original_target="1e-24", endpoint_face_trace_status="TEST_FIXTURE_NO_FACE_TRACE")
    sources = {str(layout / "helpers" / name): digest for name, digest in V.CORE_PINS.items()}
    execution = dict(execution_mode="strict", execution_identity=H(["synthetic-execution", arm]))
    loaded = dict(schema="synthetic-native-api-boundary", identity=H(["loaded", arm]),
                  source_and_loaded_semantics_bound=False, source_matches_loaded_not_asserted=True)
    caller = dict(schema="atlas.private.composed-owner-call.r1", fixture_only=True,
                  cell_ids=[c["cell_id"] for c in record["cells"]], duration_s=1.0,
                  geometry_id=geometry_id, thermal_mesh_id=geometry_id, heat_capacity_j_kg_k=1.0,
                  plan_id=H(plan), private_sources=sources, execution=execution, loaded_dependencies=loaded,
                  graph_id=H(["synthetic-graph", arm]), state_id=H(["synthetic-transport", arm]),
                  source_stage_id=H(["synthetic-source", arm]), owner_id=H(["synthetic-owner", arm]),
                  owner_definition_id=H(["synthetic-definition", arm]),
                  native_origin_signature=dict(synthetic=True, forward_origin_certified=False,
                                               parent_state_id=H(["synthetic-parent", arm])),
                  source_policy=source_policy)
    meta = dict(schema="atlas.private.composed-heat-advance.r12", caller_snapshot=caller,
                call_id=H(["synthetic-call", arm]), cell_ids=caller["cell_ids"],
                face_ids=[f["face_id"] for f in record["faces"]], geometry_id=geometry_id,
                duration_s=1.0, plan_id=H(plan), state_id=caller["state_id"],
                private_result_id=H(["synthetic-private-result", arm]), loaded_dependencies=loaded,
                accounting="Native storage residual is TOTAL public residual; signed exact face amounts are not projected to binary64.",
                endpoint_face_trace_status=plan["endpoint_face_trace_status"],
                method_id=plan["method_id"], private_correction_method_id="synthetic-exact-transfer-no-solve",
                fixed_forward_producer="TEST_FIXTURE_NO_FORWARD_PRODUCER",
                genuine_forward_origin=False, origin_binding_status="TEST_FIXTURE_NOT_NATIVE_OWNER",
                native_issue_performed=False, native_resource_admitted=False, production_acceptance=False,
                native_heat_dispatch_enabled=False, private_loaded_source_identity_certified=False,
                loaded_instructions_match_disk_source_not_asserted=True,
                whole_method_memory_inventory_certified=False, source_policy=source_policy,
                resource_scope="Synthetic fixture; actual native API allocations and observer reservations only",
                projection_resource_policy=dict(synthetic_no_projection=True,
                                                allocator_or_rss_bound=False, native_admission=False))
    new = [9, 23, 28]
    for name in V.CELL_ACCOUNTS:
        meta[name] = [hx(new[i] if name == "exact_corrected_enthalpy_j" else 0) for i in order]
    orientation = -1 if arm else 1
    meta[V.FACE_ACCOUNT] = [hx(orientation * [0, 1, -2, 0, 0, 0, 0, 0][i]) for i in face_order]
    meta.update(exact_source_energy_j=hx(0), exact_outward_boundary_energy_j=hx(0),
                independently_supplied_absolute_residual_target=["0x1", hex(target)])
    values = dict(enthalpy_j=new, input_enthalpy_j=[10, 20, 30], input_capacity_j_k=[1, 2, 3],
                  input_source_w=[0, 0, 0], temperature_k=[9, 11.5, 28 / 3])
    fields = {name: np.array([values[name][i] for i in order], dtype=np.float64) for name in V.ARRAY_NAMES}
    meta["call_id"] = H(dict(metadata=caller, arrays={
        native: dict(shape=list(fields[saved].shape), sha256=V.digest(fields[saved].tobytes()))
        for native, saved in (("enthalpy_j", "input_enthalpy_j"),
                              ("capacity_j_k", "input_capacity_j_k"),
                              ("source_w", "input_source_w"))}))
    assert set(caller) == V.CALL_METADATA and set(meta) == V.TOP_METADATA
    return caller, plan, meta, fields


def emit_arm(directory, arm):
    """Actual writer pipeline on actual native mesh/accessors, never a solver."""
    ownership = load_file("writer_boundary_ownership_helpers", HERE / "test_ownership_r13.py")
    layout = V.TASK_ROOT / "hs" / ("lf3", "lh")[arm]
    m, runtime = ownership.load_candidate(layout)
    import mesh_tables as native
    import exterior_mesh_patch
    import heat_ledger_issuer_patch
    import live_spatial_patch
    from content_cache import create_retained_scope
    budget = runtime.WorkBudget(256 << 20)
    record, order, face_order = native_record(native, arm)
    blobs = {}
    compact, columns = native.pack_mesh(record, support_writer=blobs.__setitem__, budget=budget)
    view = native.CompactMesh(compact, columns, support_reader=lambda key, size: blobs[key],
                             expected_geometry_id=compact["geometry_id"], budget=budget)

    class SyntheticMesh:
        def physical_support(self, index):
            return exterior_mesh_patch.physical_support(self, index)

    mesh = SyntheticMesh()
    mesh._compact, mesh._resource = view, budget
    caller, plan, metadata, fields = semantic_result(record, view.geometry_id, order, face_order, arm, layout)
    scope = create_retained_scope(budget, process_epoch="plan05-r13-writer-verifier-synthetic")
    owner = SimpleNamespace(_budget=budget, _component_count=1, _record_scope=scope)

    class SyntheticHolder:
        def __init__(self, value):
            self._resource = self._budget = budget
            self._json = m._canon_bytes(value)
            self._snapshot = SimpleNamespace(_metadata=self._json)

        def record(self):
            return json.loads(self._json)

    logical = [row["logical_cell_id"] for row in record["cells"]]
    graph = SyntheticHolder(dict(cells=[dict(cell_id=cid, end_volume_m3=["1", "1"]) for cid in logical]))
    transport = SyntheticHolder(dict(cell_ids=logical, exact_stocks=dict(
        enthalpy_j=[[str([10, 20, 30][i]), "1"] for i in order],
        **{"component_mass_kg:0": [[str(i + 1), "1"] for i in order]})))
    graph.geometry_id, transport.result_id = caller["graph_id"], caller["state_id"]
    step = SimpleNamespace(graph=graph, result=transport,
                           source=SimpleNamespace(result_id=caller["source_stage_id"]),
                           parent=SimpleNamespace(state_id=V.object_hash(["synthetic-parent", arm])))

    class SyntheticCall:
        pass

    call = SyntheticCall()
    call._budget, call._origin_objects = budget, (owner, step, mesh, transport._snapshot)
    call._snapshot, call._plan = SimpleNamespace(_metadata=m._canon_bytes(caller)), m._canon_bytes(plan)
    call._execution = SimpleNamespace(provenance=caller["execution"])
    call._bindings, call.call_id = caller["private_sources"], metadata["call_id"]

    class SyntheticResult:
        def __init__(self, meta, arrays):
            self._snapshot = SimpleNamespace(_metadata=m._canon_bytes(meta))
            self._arrays = {name: arrays[name].copy() for name in V.ARRAY_NAMES}
            self.array_names = V.ARRAY_NAMES
            self.result_id = V.object_hash(dict(metadata=meta, arrays={name: dict(
                shape=list(self._arrays[name].shape), sha256=V.digest(self._arrays[name].tobytes()))
                for name in self.array_names}))

        def array(self, name):
            return self._arrays[name]

    legacy, advance = SyntheticResult(metadata, fields), SyntheticResult(copy.deepcopy(metadata), fields)
    state, refs = dict(call_weakref=None, legacy_result_id=None, legacy_sha=None), {}
    report = dict(schema="atlas.private.observer-disposition.r13", path="not-started",
                  control_failure=None, operations=[], secondary_failures=[], observer_stopped=False,
                  callback_releases={}, callback_slots={})
    directory.mkdir()
    issuer = SimpleNamespace(HEAT_LEDGER=heat_ledger_issuer_patch, LIVE_SPATIAL=live_spatial_patch)

    def callback(phase, operation, arguments):
        probe = {"arena": None}
        try:
            m._run_observer_operation(runtime, budget, operation, arguments, report, phase, callback_probe=probe)
        finally:
            arguments = operation = None
            report["callback_releases"][phase] = m._observe_callback_release(probe)
            report["callback_slots"][phase] = True

    def invoke():
        callback("bind_owner_call", m._bind_operation, (state, refs, call))
        callback("advance_legacy_packaging", m._legacy_operation, (state, directory, legacy))
        with patch.dict(sys.modules, {"private_heat_native_issuer_r13": issuer}):
            callback("advance", m._capture_operation, (state, refs, directory, call, advance,
                     arm, layout, layout / "helpers/private_heat_native_issuer_r13.py"))

    def stop():
        state.clear()
        report["observer_stopped"] = True

    # Exercise the writer's real finalisation/disposition boundary too.
    m._control_boundary(invoke, stop, report, directory)
    raw = (directory / "legacy_metadata.json").read_bytes()
    checks = dict(
        result_id=legacy.result_id == advance.result_id,
        plan_descriptor=m._canon_bytes(plan) == call._plan,
        metadata_sha256=V.digest(legacy._snapshot._metadata) == V.digest(advance._snapshot._metadata),
        metadata_length=len(legacy._snapshot._metadata) == len(advance._snapshot._metadata),
        metadata_bytes=legacy._snapshot._metadata == advance._snapshot._metadata == raw,
        array_names=legacy.array_names == advance.array_names == V.ARRAY_NAMES,
        arrays=all(legacy.array(n).tobytes() == advance.array(n).tobytes() for n in V.ARRAY_NAMES),
        exact_accounts=all(json.loads(raw)[n] == metadata[n] for n in (*V.CELL_ACCOUNTS, V.FACE_ACCOUNT)),
        snapshot_identity=legacy.result_id == advance.result_id)
    snapshot = dict(result_id=legacy.result_id, metadata_sha256=V.digest(raw), metadata_bytes=len(raw))
    summary = dict(status="PASS" if all(checks.values()) else "FAIL",
                   synthetic_fixture=True, scientific_control_executed=False, cell_count=3, face_count=8,
                   checks=checks, arrays_equal={n: legacy.array(n).tobytes() == advance.array(n).tobytes()
                                               for n in V.ARRAY_NAMES},
                   arrays={n: V.digest(advance.array(n).tobytes()) for n in V.ARRAY_NAMES},
                   legacy=snapshot, compact=snapshot.copy(),
                   ab=dict(observer_disposition=report,
                           leaks=[phase for phase, released in report["callback_releases"].items()
                                  if released["native_owners_retained"]
                                  or released["observer_reserved_bytes"] != released["observer_before_bytes"]],
                           parent_peak_working_set=m.psutil.Process().memory_info().peak_wset))
    save_json(directory.parent / f"arm-{arm}.json", summary)
    save_json(directory / "fixture-origin.json", dict(
        synthetic_fixture=True, scientific_control_executed=False, cell_order=order, face_order=face_order,
        native_modules={mod.__name__: str(Path(mod.__file__).resolve()) for mod in
                        (native, exterior_mesh_patch, heat_ledger_issuer_patch, live_spatial_patch)},
        sources={name: V.digest((HERE / name).read_bytes()) for name in
                 ("ab_heat_r13.py", "verify_d02_r13.py", Path(__file__).name)},
        native_statistics=budget.statistics()))
    scope.close()


class WriterVerifierIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ARTIFACTS.mkdir(exist_ok=True)
        cls.root = Path(tempfile.mkdtemp(prefix="native-3-8-", dir=ARTIFACTS))
        cls.a, cls.b = cls.root / "arm-0", cls.root / "arm-1"
        print("Writer/verifier native fixtures retained at " + str(cls.root), flush=True)
        for arm in (0, 1):
            command = [sys.executable, "-B", "-s", "-P", str(Path(__file__).resolve()),
                       "--emit-arm", str(arm), "--directory", str(cls.root / f"arm-{arm}")]
            process = subprocess.run(command, cwd=HERE, env=os.environ.copy(), capture_output=True,
                                     text=True, timeout=60)
            (cls.root / f"arm-{arm}.stdout.txt").write_text(process.stdout, encoding="utf8")
            (cls.root / f"arm-{arm}.stderr.txt").write_text(process.stderr, encoding="utf8")
            if process.returncode:
                raise AssertionError(f"Native writer arm {arm} failed ({process.returncode}): "
                                     f"{process.stderr}\nRetained: {cls.root}")

    def test_actual_native_writer_complete_mapped_pair(self):
        result = V.verify_correspondence(self.a, self.b)
        save_json(self.root / "positive-verification.json", result)
        self.assertEqual(result["new_run_verdict"], "METADATA_DISPOSITION_REQUIRED", result)
        self.assertEqual(result["cell_bijection_pi"], [2, 0, 1])
        self.assertEqual(result["face_bijection_sigma"], [4, 2, 6, 1, 5, 7, 3, 0])
        self.assertEqual(result["face_orientation"], [-1] * 8)
        self.assertTrue(result["corresponding_inputs_equal"], result)
        self.assertEqual(result["within_arm_ledger_errors"], dict(arm_a=[], arm_b=[]))
        self.assertTrue(all(row["bitwise_equal"] for row in result["arrays"].values()))
        self.assertTrue(all(row["exact_equal"] for row in result["exact_cell_accounts"].values()))
        self.assertTrue(result["exact_face_account"]["exact_equal"])
        self.assertEqual(result["metadata"]["invariant_differences"], [])
        self.assertFalse(result["scientific_acceptance"])
        self.assertEqual((result["historical_q10"], result["q22"]), ("FAIL", "HELD"))
        captures = [V.read_json(d / "d02_correspondence_capture.json") for d in (self.a, self.b)]
        self.assertNotEqual(captures[0]["compact_mesh_identity"]["array_descriptors"]["grid_lines.q"]["sha256"],
                            captures[1]["compact_mesh_identity"]["array_descriptors"]["grid_lines.q"]["sha256"],
                            "Fixture must exercise equal physical grids with different native pool indices")
        for directory in (self.a, self.b):
            capture = V.read_json(directory / "d02_correspondence_capture.json")
            self.assertTrue(capture["cells"][0]["volume_m3"][0].startswith("0x"))
            self.assertGreater(len(capture["compact_mesh_identity"]["grid_proof_arrays"]), 4)

    def test_actual_writer_grid_pool_tamper_refuses_bound_grid_evidence(self):
        damaged = self.root / "grid-pool-fault"
        shutil.copytree(self.b, damaged)
        capture = V.read_json(damaged / "d02_correspondence_capture.json")
        proof = capture["compact_mesh_identity"]["grid_proof_arrays"]["int.bytes"]
        path = damaged / proof["file"]
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        result = V.verify_correspondence(self.a, damaged)
        save_json(self.root / "grid-pool-fault-verification.json", result)
        self.assertEqual(result["new_run_verdict"], "VERIFY_REFUSE", result)
        self.assertEqual(result["refusal_code"], "VERIFY_REFUSE_GRID_BINDING", result)
        self.assertEqual(result["exit_code"], 2)


if __name__ == "__main__":
    if "--emit-arm" in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--emit-arm", type=int, choices=(0, 1), required=True)
        parser.add_argument("--directory", type=Path, required=True)
        args = parser.parse_args()
        emit_arm(args.directory, args.emit_arm)
    else:
        unittest.main(verbosity=2)
