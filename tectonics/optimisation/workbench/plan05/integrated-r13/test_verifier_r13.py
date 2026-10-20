"""Disposable exact mapped controls, not simulation or scientific acceptance.

These fixtures use real current source pins but entirely synthetic geometry and
stocks. Both arms are complete. Each mutation reaches the named contract check;
missing capture evidence is never used to stand in for a numerical defect.
"""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

_SPEC = importlib.util.spec_from_file_location("d02_verifier_r13", Path(__file__).with_name("verify_d02_r13.py"))
V = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(V)


def q(value):
    return [value, 1]


def hx(value):
    return [hex(value), "0x1"]


def xyz(x, y=0, z=0):
    return [q(x), q(y), q(z)]


def write(path, value):
    path.write_bytes(V.canonical(value))


def fixture(directory, arm, order, flipped=False):
    directory.mkdir(parents=True)
    layout = ("lf3", "lh")[arm]
    H = V.object_hash
    sources = {str(V.TASK_ROOT / "hs" / layout / "helpers" / key): value
               for key, value in (V.CORE_PINS | V.OUTPUT_POLICY_SOURCE_PINS).items()}
    header = dict(funding_id=H(["funding", arm]), support_id=H(["support", arm]),
                  grid_id=H("grid"), time_s="1", trajectory_id=H("trajectory"), endpoint="end",
                  schema="fixture.native.mesh", method="fixture",
                  trajectory_segments=[], radial_rule="fixture")
    geom = H(["geometry", arm])
    material = H("material")
    native = []
    resolved = []
    for i in range(3):
        voxel = dict(lower_m=xyz(i), upper_m=xyz(i + 1, 1, 1))
        vid = H(voxel)
        refs = dict(voxel_id=vid)
        if i < 2:
            logical = H(dict(kind="collar", funding_id=header["funding_id"], cell_id=vid))
            c = dict(kind="collar", index=[i, 0, 0], logical_cell_id=logical,
                     cell_id=logical, physical_cell_id=vid)
            support = dict(voxel=voxel)
        else:
            layer, cone = dict(radius_m=q(10)), [xyz(1), xyz(1, 1), xyz(1, 0, 1)]
            refs.update(radial_layer_id=H(layer), cone_id=H(cone))
            c = dict(kind="exterior", source_key=[material, "layer"], voxel_index=[i, 0, 0],
                     radial_band=0, chart=0)
            logical = H({k: c[k] for k in ("source_key", "voxel_index", "radial_band", "chart")}
                        | {"grid_id": header["grid_id"]})
            c.update(logical_cell_id=logical,
                     cell_id=H(dict(logical_cell_id=logical, support_id=header["support_id"])))
            support = dict(voxel=voxel, radial_layer=layer, original_cone=cone,
                           trajectory_id=header["trajectory_id"])
        c.update(volume_m3=q(1), centroid_m=xyz(i), physical_volume_bounds_m3=[q(1), q(1)],
                 geometry_volume_max_deviation_m3=q(0), physical_support=refs, faces=[])
        native.append(c)
        resolved.append(support)
    face_order = [3, 1, 0, 2] if arm else list(range(4))
    faces = []
    orient = -1 if flipped else 1
    for fi in range(4):
        fid = H(["face", fi, arm])
        owners = []
        if fi > 0:
            native[fi - 1]["faces"].append([fid, orient])
            owners.append(native[fi - 1]["cell_id"])
        if fi < 3:
            native[fi]["faces"].append([fid, -orient])
            owners.append(native[fi]["cell_id"])
        face = dict(face_id=fid, centroid_m=xyz(fi), area_vector_m2=xyz(orient),
                    vertices_m=[xyz(fi), xyz(fi, 1), xyz(fi, 1, 1), xyz(fi, 0, 1)],
                    owners=owners, kind="interior" if len(owners) == 2 else "boundary",
                    geometry_kind="cartesian", relative_advection="fixture")
        if flipped:
            face["vertices_m"].reverse()
        faces.append(face)
    cells = []
    for ri, original in enumerate(order):
        c, support = native[original], resolved[original]
        if c["kind"] == "collar":
            independent = {k: c[k] for k in ("kind", "index", "physical_cell_id")} | c["physical_support"]
        else:
            independent = {k: c[k] for k in ("kind", "logical_cell_id", "source_key",
                                            "voxel_index", "radial_band", "chart")} | c["physical_support"]
        row = {k: c.get(k) for k in ("cell_id", "kind", "logical_cell_id", "physical_volume_bounds_m3",
                                    "geometry_volume_max_deviation_m3", "volume_m3", "centroid_m",
                                    "faces", "physical_support")}
        row.update(row_index=ri, native_cell=c, independent_key=independent,
                   independent_key_sha256=H(independent), resolved_support=support,
                   input_provenance=dict(graph_end_volume_m3=q(1),
                       transport_exact_enthalpy_j=q([10, 20, 30][original]),
                       transport_exact_component_masses_kg=[q(original + 1)]))
        cells.append(row)
    emitted_faces = []
    for ri, original in enumerate(face_order):
        face = faces[original]
        emitted = {k: face.get(k) for k in ("face_id", "kind", "geometry_kind", "centroid_m",
                   "area_vector_m2", "vertices_m", "owners", "cartesian_support", "relative_advection")}
        emitted.update(face_index=ri, native_face=face)
        emitted_faces.append(emitted)
    cids, fids = [c["cell_id"] for c in cells], [f["face_id"] for f in emitted_faces]
    boundary = {f["face_id"]: ["power", 0.0] for f in faces if len(f["owners"]) == 1}
    plan = dict(schema="atlas.private.composed-heat-plan.r1", geometry_id=geom, method_id="fixture",
                conductivity_w_m_k=[1.0] * 3, boundary=boundary,
                absolute_residual_target=["1", "1000000000000000000000000"],
                absolute_residual_target_decimal="1e-24", original_target="1e-24",
                endpoint_face_trace_status="fixture")
    caller = {key: "fixture" for key in V.CALL_METADATA}
    caller.update(cell_ids=cids, duration_s=1.0, fixture_only=True, geometry_id=geom,
                  thermal_mesh_id=geom, heat_capacity_j_kg_k=1.0, plan_id=H(plan),
                  private_sources=sources, loaded_dependencies=dict(schema="fixture", identity=H(["loaded", arm]),
                  source_and_loaded_semantics_bound=True, source_matches_loaded_not_asserted=True),
                  execution=dict(execution_mode="strict", execution_identity=H(["execution", arm])),
                  state_id=H(["state", arm]), owner_id=H(["owner", arm]),
                  owner_definition_id=H(["definition", arm]))
    caller["native_origin_signature"] = dict(
        owner_id=caller["owner_id"], owner_definition_id=caller["owner_definition_id"],
        funding_id=header["funding_id"], component_count=1, heat_capacity_j_kg_k=1.0,
        transport_id=H(["transport", arm]), state_id=caller["state_id"],
        parent_state_id=H(["parent", arm]), source_stage_id=caller["source_stage_id"],
        source_inventory_id=H(["inventory", arm]), native_source_inventory_id=H(["native-inventory", arm]),
        graph_id=caller["graph_id"], thermal_mesh_id=geom, duration_s=1.0)
    metadata = {key: "fixture" for key in V.TOP_METADATA}
    metadata.update(schema="atlas.private.composed-heat-advance.r12", call_id=H(["call", arm]),
                    caller_snapshot=caller, cell_ids=cids, face_ids=fids, geometry_id=geom,
                    duration_s=1.0, plan_id=H(plan), state_id=caller["state_id"],
                    private_result_id=H(["private", arm]), loaded_dependencies=caller["loaded_dependencies"],
                    production_acceptance=False, genuine_forward_origin=False,
                    projection_resource_policy=dict(numerical=dict(scalar_peak_bits=64, scalar_slots=64,
                        route="ACTUAL_REDUCED_OPERAND_CANONICAL_EQUALITY_PROJECTION",
                        exact_canonical_part_equality=True),
                        # 19 pairs: 287 reserved characters; 27/51 containers.
                        # Conversion work remains an explicit synthetic observation.
                        output_components=dict(output_hex_strings_and_pairs=27935,
                            output_stream_codec=53085, actual_output_conversion_work=120064)))
    new = [9, 23, 28]
    for name in V.CELL_ACCOUNTS:
        metadata[name] = [hx(new[i] if name == "exact_corrected_enthalpy_j" else 0) for i in order]
    metadata[V.FACE_ACCOUNT] = [hx(orient * [0, 1, -2, 0][i]) for i in face_order]
    metadata["exact_source_energy_j"] = hx(0)
    metadata["exact_outward_boundary_energy_j"] = hx(0)
    metadata["independently_supplied_absolute_residual_target"] = ["0x1", hex(10**24)]
    arrays = dict(enthalpy_j=new, input_enthalpy_j=[10, 20, 30],
                  input_capacity_j_k=[1, 2, 3], input_source_w=[0, 0, 0],
                  temperature_k=[9, 11.5, 28 / 3])
    for name, values in arrays.items():
        np.save(directory / (name + ".npy"), np.asarray([values[i] for i in order], dtype=np.float64))
    write(directory / "arrays.json", {name: [3] for name in V.ARRAY_NAMES})
    compact = dict(schema="fixture.compact", geometry_id=geom, header=header, cell_count=3,
                   face_count=4, arrays={}, grid_fields=[], support_tables=["voxels", "radial_layers", "cones"])
    logical = dict(record_schema="fixture.native.mesh", sha256=geom, canonical_bytes=100)
    identity = dict(expected_geometry_id=geom, metadata_digest=H(compact),
                    metadata_utf8=V.canonical(compact).decode(), logical_identity=logical | dict(
                        wire=logical.copy(), expected_geometry_id=geom), array_descriptors={},
                    tables=compact["support_tables"], grids=[])
    context = {k: header[k] for k in ("time_s", "grid_id", "support_id", "funding_id", "trajectory_id", "endpoint")}
    context.update(duration_s=1.0, heat_capacity_j_kg_k=1.0, boundary=boundary)
    preserved = {key: context[key] for key in ("boundary", "time_s", "duration_s", "grid_id",
                 "support_id", "funding_id", "trajectory_id", "endpoint")}
    preserved.update(mesh_geometry_id=geom, mesh_counts=dict(cell_count=3, face_count=4),
                     ordered_cell_ids_observed_in_process=True, compact_metadata_digest=identity["metadata_digest"],
                     compact_array_descriptors_count=0)
    retained_header = {"support_id", "funding_id", "grid_id", "time_s", "trajectory_id",
                       "endpoint", "schema", "method"}
    disposition = dict(preserved=preserved, disposed=dict(header_fields=sorted(set(header) - retained_header),
                       call_plan_fields=sorted(set(plan) - {"boundary"}),
                       raw_lookup_permutations=["c.lookup", "f.lookup"], unexpanded_legacy_record=True))
    mesh = {k: context[k] for k in ("time_s", "duration_s", "grid_id", "support_id", "funding_id")}
    mesh.update(schema=V.MESH_SCHEMA, geometry_id=geom, cell_count=3, face_count=4,
                cells=cells, faces=emitted_faces, context_disposition=disposition)
    provenance = {k: caller[k] for k in ("plan_id", "state_id", "owner_id", "owner_definition_id",
                                      "loaded_dependencies", "private_sources")}
    provenance.update(arm_index=arm, layout_name=layout, layout_control_sha256=V.CONTROL_PINS[layout],
                      step7_control_sha256=V.STEP7_PIN,
                      issuer_sha256=V.CORE_PINS["private_heat_native_issuer_r13.py"],
                      call_id=metadata["call_id"])
    capture = dict(schema=V.CAPTURE_SCHEMA, bindings=dict(geometry_id=geom, legacy_result_id=H(["result", arm]),
                    advance_result_id=H(["result", arm]), arrays={}), compact_mesh_identity=identity,
                   provenance=provenance, context_disposition=disposition, physical_context=context,
                   physical_plan=plan, ordered_cell_ids=cids, cell_count=3, face_count=4,
                   input_bindings={key: caller[key] for key in ("graph_id", "state_id", "source_stage_id")}
                   | dict(parent_state_id=caller["native_origin_signature"]["parent_state_id"]),
                   cells=cells, faces=emitted_faces)
    write(directory / "legacy_metadata.json", metadata)
    write(directory / "thermal_mesh_record.json", mesh)
    write(directory / "d02_correspondence_capture.json", capture)
    reseal(directory)


def reseal(directory, *, rebind_call=True):
    cap = V.read_json(directory / "d02_correspondence_capture.json")
    mesh = V.read_json(directory / "thermal_mesh_record.json")
    mesh["cells"], mesh["faces"] = cap["cells"], cap["faces"]
    write(directory / "thermal_mesh_record.json", mesh)
    cap["bindings"]["thermal_mesh_record_sha256"] = V.digest((directory / "thermal_mesh_record.json").read_bytes())
    for name in V.ARRAY_NAMES:
        path = directory / (name + ".npy")
        array = np.load(path, allow_pickle=False)
        cap["bindings"]["arrays"][name] = dict(dtype=str(array.dtype), shape=list(array.shape),
                                              npy_sha256=V.digest(path.read_bytes()), raw_sha256=V.digest(array.tobytes()))
    metadata = V.read_json(directory / "legacy_metadata.json")
    if rebind_call:
        call_id = V.object_hash(dict(metadata=metadata["caller_snapshot"], arrays={
            native: dict(shape=cap["bindings"]["arrays"][saved]["shape"],
                         sha256=cap["bindings"]["arrays"][saved]["raw_sha256"])
            for native, saved in (("enthalpy_j", "input_enthalpy_j"),
                                  ("capacity_j_k", "input_capacity_j_k"),
                                  ("source_w", "input_source_w"))}))
        metadata["call_id"] = cap["provenance"]["call_id"] = call_id
        write(directory / "legacy_metadata.json", metadata)
    cap["bindings"]["legacy_metadata_sha256"] = V.digest((directory / "legacy_metadata.json").read_bytes())
    result_id = V.object_hash(dict(metadata=metadata, arrays={name: dict(
        shape=cap["bindings"]["arrays"][name]["shape"],
        sha256=cap["bindings"]["arrays"][name]["raw_sha256"]) for name in V.ARRAY_NAMES}))
    cap["bindings"]["legacy_result_id"] = cap["bindings"]["advance_result_id"] = result_id
    write(directory / "d02_correspondence_capture.json", cap)
    phases = ("bind_owner_call", "advance_legacy_packaging", "advance")
    release = dict(released=True, callback_finalised=True, retained_funding=False,
                   explicit_release_required=False, native_owners_retained=0,
                   observer_reserved_bytes=0, observer_before_bytes=0)
    observer = dict(schema="atlas.private.observer-disposition.r13", path="normal",
                    control_failure=None, observer_stopped=True, secondary_failures=[],
                    callback_slots={phase: True for phase in phases},
                    callback_releases={phase: release.copy() for phase in phases})
    write(directory / "observer_disposition.json", observer)
    snapshot = dict(result_id=result_id, metadata_sha256=cap["bindings"]["legacy_metadata_sha256"],
                    metadata_bytes=len((directory / "legacy_metadata.json").read_bytes()))
    check_names = ("result_id", "plan_descriptor", "metadata_sha256", "metadata_length",
                   "metadata_bytes", "array_names", "arrays", "exact_accounts", "snapshot_identity")
    summary = dict(status="PASS", cell_count=3, face_count=4,
                   checks={key: True for key in check_names},
                   arrays_equal={key: True for key in V.ARRAY_NAMES},
                   arrays={key: cap["bindings"]["arrays"][key]["raw_sha256"] for key in V.ARRAY_NAMES},
                   legacy=snapshot.copy(), compact=snapshot.copy(),
                   ab=dict(observer_disposition=observer, leaks=[], parent_peak_working_set=1000))
    write(directory.parent / (directory.name + ".json"), summary)


class VerifierControls(unittest.TestCase):
    def setUp(self):
        artifacts = Path(__file__).with_name("verifier-test-artifacts")
        artifacts.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="control-", dir=artifacts)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a, self.b = self.root / "arm-0", self.root / "arm-1"
        fixture(self.a, 0, [0, 1, 2])
        fixture(self.b, 1, [1, 2, 0], flipped=True)

    def verify(self, **kwargs):
        return V.verify_correspondence(self.a, self.b, **kwargs)

    def update(self, directory, filename, mutate, seal=True):
        path = directory / filename
        value = V.read_json(path)
        mutate(value)
        write(path, value)
        if seal:
            reseal(directory)

    def assert_refusal(self, result, code):
        self.assertEqual(result["verdict"], "VERIFY_REFUSE", result)
        self.assertEqual(result["refusal_code"], code, result)

    def select_order_repair(self):
        """Bind the actual additive files to a synthetic retained launch."""
        pins = {str(path): V.digest(path.read_bytes())
                for layout in ("lf3", "lh") for path in V._order_repair_paths(layout)}
        manifest = self.root / "selected-order-repair.json"
        selection = dict(schema="plan05-integrated-r13.v1", scope=["lf3", "lh"],
                         historical_q10="FAIL", q22="HELD", source_pins=pins.copy(),
                         order_repair=dict(schema=V.ORDER_REPAIR_SCHEMA, scope=["lf3", "lh"],
                                           source_pins=pins.copy(), policy="synthetic launch fixture"))
        write(manifest, selection)
        manifest_sha = V.digest(manifest.read_bytes())
        write(self.root / "attempt.json", dict(mode="capture", manifest_sha256=manifest_sha))
        for directory, layout in ((self.a, "lf3"), (self.b, "lh")):
            cap = V.read_json(directory / "d02_correspondence_capture.json")
            meta = V.read_json(directory / "legacy_metadata.json")
            sources = meta["caller_snapshot"]["private_sources"]
            del sources[str(V.TASK_ROOT / "hs" / layout / "helpers" / "private_heat_native_issuer_r13.py")]
            selected = {str(path): pins[str(path)] for path in V._order_repair_paths(layout)}
            sources.update(selected)
            cap["provenance"].update(
                issuer_sha256=V.ORDER_REPAIR_ISSUER_PIN, private_sources=sources,
                order_repair=dict(schema=V.ORDER_REPAIR_SCHEMA, layout=layout,
                                  manifest_path=str(manifest.resolve()), manifest_sha256=manifest_sha,
                                  source_pins=selected, numerical_tolerances_changed=False,
                                  original_metric_mutated=False, ordering=V.ORDER_REPAIR_ORDERING))
            write(directory / "legacy_metadata.json", meta)
            write(directory / "d02_correspondence_capture.json", cap)
            reseal(directory)
        return manifest

    def rebind_order_manifest(self, manifest):
        """Use only for a fault beneath the outer manifest/launch bindings."""
        selected_sha = V.digest(manifest.read_bytes())
        write(self.root / "attempt.json", dict(mode="capture", manifest_sha256=selected_sha))
        for directory in (self.a, self.b):
            self.update(directory, "d02_correspondence_capture.json",
                        lambda cap: cap["provenance"]["order_repair"].update(manifest_sha256=selected_sha))

    def test_selected_order_repair_positive_preserves_strict_historical_failure(self):
        old_a, old_b = self.root / "old-a", self.root / "old-b"
        shutil.copytree(self.a, old_a)
        shutil.copytree(self.b, old_b)
        self.select_order_repair()
        result = self.verify(preserved_q10_arm_a=old_a, preserved_q10_arm_b=old_b)
        self.assertEqual(result["verdict"], "NOT_REPRODUCED", result)
        self.assertEqual(result["new_run_verdict"], "METADATA_DISPOSITION_REQUIRED", result)
        self.assertTrue(result["corresponding_inputs_equal"])
        self.assertTrue(all(row["exact_equal"] for row in result["exact_cell_accounts"].values()))
        self.assertEqual(result["metadata"]["invariant_differences"], [])
        evidence = result["metadata"]["evidence"]
        records = [row for row in evidence["source_correspondence"]
                   if row["relative_path"].startswith("repair/")]
        self.assertEqual({row["relative_path"] for row in records}, {
            "repair/shared/private_heat_physical_order_r1.py",
            "repair/arm/private_heat_forward_kernel_r13.py",
            "repair/arm/private_heat_native_issuer_r13.py",
        })
        for arm in ("arm_a", "arm_b"):
            self.assertEqual(evidence["order_repair"][arm]["status"], "EXACT_SELECTED_REPAIR_SOURCES_BOUND")
            self.assertFalse(evidence["order_repair"][arm]["numerical_equivalence_asserted"])
            self.assertEqual(result["historical_linkage_details"][arm]["arrays_status"], "EXACT_BYTES_MATCH")
            self.assertIn("legacy_metadata.json", result["historical_differing_files"][arm])

    def test_order_repair_missing_manifest_is_refused(self):
        manifest = self.select_order_repair()
        manifest.rename(manifest.with_suffix(".retained"))
        result = self.verify()
        self.assert_refusal(result, "VERIFY_REFUSE_ORDER_REPAIR")
        self.assertIn("manifest missing", result["error"])

    def test_order_repair_modified_manifest_is_refused(self):
        manifest = self.select_order_repair()
        manifest.write_bytes(manifest.read_bytes() + b"\n")
        result = self.verify()
        self.assert_refusal(result, "VERIFY_REFUSE_ORDER_REPAIR")
        self.assertIn("manifest bytes differ", result["error"])

    def test_order_repair_cross_layout_file_is_refused(self):
        self.select_order_repair()
        def mutate(cap):
            pins = cap["provenance"]["order_repair"]["source_pins"]
            pin = pins.pop(str(V._order_repair_paths("lh")[1]))
            pins[str(V._order_repair_paths("lf3")[1])] = pin
        self.update(self.b, "d02_correspondence_capture.json", mutate)
        result = self.verify()
        self.assert_refusal(result, "VERIFY_REFUSE_ORDER_REPAIR")
        self.assertIn("exactly the shared helper and this arm", result["error"])

    def test_order_repair_helper_missing_from_native_binding_is_refused(self):
        self.select_order_repair()
        helper = str(V._order_repair_paths("lh")[0])
        self.update(self.b, "legacy_metadata.json",
                    lambda meta: meta["caller_snapshot"]["private_sources"].pop(helper))
        self.update(self.b, "d02_correspondence_capture.json",
                    lambda cap: cap["provenance"]["private_sources"].pop(helper))
        result = self.verify()
        self.assert_refusal(result, "VERIFY_REFUSE_ORDER_REPAIR")
        self.assertIn("caller/selection binding", result["error"])

    def test_order_repair_selection_and_native_source_pins_must_agree(self):
        manifest = self.select_order_repair()
        value = V.read_json(manifest)
        helper = str(V._order_repair_paths("lh")[0])
        value["source_pins"][helper] = "0" * 64
        write(manifest, value)
        self.rebind_order_manifest(manifest)
        result = self.verify()
        self.assert_refusal(result, "VERIFY_REFUSE_ORDER_REPAIR")
        self.assertIn("different in full selection", result["error"])

    def test_order_repair_manifest_inventory_cannot_admit_neighbour_file(self):
        manifest = self.select_order_repair()
        value = V.read_json(manifest)
        name = str(V.ORDER_REPAIR_ROOT / "unselected_neighbour.py")
        value["order_repair"]["source_pins"][name] = "0" * 64
        value["source_pins"][name] = "0" * 64
        write(manifest, value)
        self.rebind_order_manifest(manifest)
        result = self.verify()
        self.assert_refusal(result, "VERIFY_REFUSE_ORDER_REPAIR")
        self.assertIn("exactly the five permitted repair files", result["error"])

    def test_order_repair_consistent_false_source_pin_is_refused_against_disk(self):
        manifest = self.select_order_repair()
        helper = str(V._order_repair_paths("lf3")[0])
        value = V.read_json(manifest)
        value["source_pins"][helper] = "0" * 64
        value["order_repair"]["source_pins"][helper] = "0" * 64
        write(manifest, value)
        for directory in (self.a, self.b):
            self.update(directory, "legacy_metadata.json",
                        lambda meta: meta["caller_snapshot"]["private_sources"].update({helper: "0" * 64}))
            self.update(directory, "d02_correspondence_capture.json", lambda cap: (
                cap["provenance"]["private_sources"].update({helper: "0" * 64}),
                cap["provenance"]["order_repair"]["source_pins"].update({helper: "0" * 64})))
        self.rebind_order_manifest(manifest)
        result = self.verify()
        self.assert_refusal(result, "VERIFY_REFUSE_ORDER_REPAIR")
        self.assertIn("repair source bytes differ", result["error"])

    def test_order_repair_must_match_retained_launch_selection(self):
        self.select_order_repair()
        write(self.root / "attempt.json", dict(mode="capture", manifest_sha256="0" * 64))
        result = self.verify()
        self.assert_refusal(result, "VERIFY_REFUSE_ORDER_REPAIR")
        self.assertIn("retained launch receipt", result["error"])

    def test_order_repair_files_without_descriptor_are_not_admitted(self):
        self.select_order_repair()
        self.update(self.a, "d02_correspondence_capture.json", lambda cap: (
            cap["provenance"].pop("order_repair"),
            cap["provenance"].update(issuer_sha256=V.CORE_PINS["private_heat_native_issuer_r13.py"])))
        result = self.verify()
        self.assert_refusal(result, "VERIFY_REFUSE_SOURCES")
        self.assertIn("outside permitted roots", result["error"])

    def test_complete_mapped_positive_including_face_orientation(self):
        result = self.verify()
        self.assertEqual(result["new_run_verdict"], "METADATA_DISPOSITION_REQUIRED", result)
        self.assertEqual(result["cell_bijection_pi"], [2, 0, 1])
        self.assertEqual(result["face_bijection_sigma"], [2, 1, 3, 0])
        self.assertEqual(result["face_orientation"], [-1] * 4)
        self.assertTrue(result["corresponding_inputs_equal"])
        self.assertTrue(all(v["bitwise_equal"] for v in result["arrays"].values()))
        self.assertTrue(all(v["exact_equal"] for v in result["exact_cell_accounts"].values()))
        self.assertTrue(result["exact_face_account"]["exact_equal"])
        self.assertEqual(result["within_arm_ledger_errors"], dict(arm_a=[], arm_b=[]))
        self.assertEqual(result["metadata"]["invariant_differences"], [])
        self.assertEqual(result["metadata"]["coverage"], "ALL_LEAVES")
        self.assertFalse(result["scientific_acceptance"])
        self.assertEqual(result["historical_q10"], "FAIL")
        self.assertEqual(result["q22"], "HELD")

    def test_missing_completion_does_not_read_partial_files(self):
        (self.b / "d02_correspondence_capture.json").unlink()
        (self.b / "legacy_metadata.json").write_text("unreadable partial")
        result = self.verify()
        self.assert_refusal(result, "VERIFY_REFUSE_SCHEMA")
        self.assertIn("d02_correspondence_capture.json", result["error"])

    def test_duplicate_physical_key_is_refused(self):
        cap = V.read_json(self.b / "d02_correspondence_capture.json")
        cap["cells"][1] = copy.deepcopy(cap["cells"][0])
        cap["cells"][1]["row_index"] = 1
        cids = [c["cell_id"] for c in cap["cells"]]
        cap["ordered_cell_ids"] = cids
        write(self.b / "d02_correspondence_capture.json", cap)
        self.update(self.b, "legacy_metadata.json", lambda m: (
            m.update(cell_ids=cids), m["caller_snapshot"].update(cell_ids=cids)))
        self.assert_refusal(self.verify(), "VERIFY_REFUSE_CELL_KEY")

    def test_array_binding_tamper(self):
        path = self.b / "enthalpy_j.npy"
        value = np.load(path)
        value[0] += 1
        np.save(path, value)
        self.assert_refusal(self.verify(), "VERIFY_REFUSE_HASH")

    def test_authentic_misplaced_output_reaches_numerical_check(self):
        path = self.b / "enthalpy_j.npy"
        value = np.load(path)
        value[[0, 1]] = value[[1, 0]]
        np.save(path, value)
        reseal(self.b)
        result = self.verify()
        self.assertEqual(result["new_run_verdict"], "NUMERICAL_OR_REPRESENTATION_DEFECT", result)
        self.assertTrue(result["corresponding_inputs_equal"])
        self.assertFalse(result["arrays"]["enthalpy_j"]["bitwise_equal"])
        self.assertIn("row[0].stock_projection", result["within_arm_ledger_errors"]["arm_b"])

    def test_input_misplacement_prevents_solver_attribution(self):
        path = self.b / "input_enthalpy_j.npy"
        value = np.load(path)
        value[[0, 1]] = value[[1, 0]]
        np.save(path, value)
        reseal(self.b)
        result = self.verify()
        self.assertEqual(result["new_run_verdict"], "INPUT_OR_CONTEXT_MISMATCH", result)
        self.assertFalse(result["solver_attribution_permitted"])

    def test_face_sign_fault_has_specific_refusal(self):
        def mutate(cap):
            cell = cap["cells"][0]
            cell["native_cell"]["faces"][0][1] *= -1
            cell["faces"] = copy.deepcopy(cell["native_cell"]["faces"])
        self.update(self.b, "d02_correspondence_capture.json", mutate)
        self.assert_refusal(self.verify(), "VERIFY_REFUSE_FACE_INCIDENCE")

    def test_face_energy_fault_reaches_exact_account_check(self):
        self.update(self.b, "legacy_metadata.json", lambda m: m[V.FACE_ACCOUNT].__setitem__(1, hx(1)))
        result = self.verify()
        self.assertEqual(result["new_run_verdict"], "NUMERICAL_OR_REPRESENTATION_DEFECT", result)
        self.assertFalse(result["exact_face_account"]["exact_equal"])

    def test_unknown_metadata_is_not_silently_dropped(self):
        self.update(self.b, "legacy_metadata.json", lambda m: m.update(undisposed_quantity=4))
        self.assert_refusal(self.verify(), "VERIFY_REFUSE_SCHEMA")

    def test_invariant_metadata_difference_is_reported(self):
        self.update(self.b, "legacy_metadata.json", lambda m: m.update(accounting="wrong accounting"))
        result = self.verify()
        self.assertEqual(result["new_run_verdict"], "NUMERICAL_OR_REPRESENTATION_DEFECT", result)
        self.assertEqual(result["metadata"]["invariant_differences"][0]["path"], "/accounting")

    def test_resource_difference_has_complete_separate_disposition(self):
        self.update(self.b, "legacy_metadata.json",
                    lambda m: m["projection_resource_policy"]["numerical"].update(scalar_peak_bits=65))
        result = self.verify()
        self.assertEqual(result["new_run_verdict"], "METADATA_DISPOSITION_REQUIRED", result)
        self.assertEqual(result["metadata"]["resource_differences"][0]["path"],
                         "/projection_resource_policy/numerical/scalar_peak_bits")

    def test_metadata_annex_distinguishes_replayed_and_opaque_identities(self):
        result = self.verify()
        self.assertEqual(result["new_run_verdict"], "METADATA_DISPOSITION_REQUIRED", result)
        metadata = result["metadata"]
        differences = {item["path"]: item for item in metadata["provenance_differences"]}
        self.assertEqual(differences["/call_id"]["evidence"]["status"], "PER_ARM_CALL_IDENTITIES_REPLAYED")
        self.assertEqual(differences["/plan_id"]["evidence"]["status"], "PER_ARM_PLAN_IDENTITIES_REPLAYED")
        opaque = differences["/caller_snapshot/execution/execution_identity"]["evidence"]
        self.assertEqual(opaque["status"], "DISTINCT_OPAQUE_NATIVE_BOUND_CONTEXTS")
        self.assertFalse(opaque["equivalence_asserted"])
        self.assertFalse(opaque["path_only_cause_asserted"])
        sources = metadata["evidence"]["source_correspondence"]
        self.assertEqual(len(sources), len(V.CORE_PINS | V.OUTPUT_POLICY_SOURCE_PINS))
        self.assertTrue(all(item["status"] == "SAME_BYTES_AT_BOUND_RELATIVE_PATHS" for item in sources))
        self.assertTrue(all(item["arm_a"]["path"] != item["arm_b"]["path"] for item in sources))

    def test_native_codec_formula_handles_zero_signed_and_wide_exact_parts(self):
        result = self.verify()
        for check in result["metadata"]["evidence"]["output_components"].values():
            self.assertEqual(check["status"], "ABI_INDEPENDENT_COMPONENTS_REPLAYED")
            self.assertEqual(check["rational_count"], 19)
            self.assertEqual(check["admitted_character_bound"], 287)
            self.assertEqual(check["expression_bits"], 324)
            self.assertEqual(check["replayed_components"],
                             dict(output_hex_strings_and_pairs=27935, output_stream_codec=53085))
            self.assertEqual(check["failures"], [])
            self.assertFalse(check["conversion_work"]["equivalence_asserted"])

    def test_same_wrong_codec_metadata_in_both_arms_is_a_proof_failure(self):
        for directory in (self.a, self.b):
            self.update(directory, "legacy_metadata.json", lambda m:
                        m["projection_resource_policy"]["output_components"].update(output_stream_codec=53086))
        result = self.verify()
        self.assertEqual(result["new_run_verdict"], "NUMERICAL_OR_REPRESENTATION_DEFECT", result)
        self.assertTrue(result["corresponding_inputs_equal"])
        self.assertEqual(result["metadata"]["invariant_differences"], [])
        failures = result["metadata"]["proof_failures"]
        self.assertEqual({failure["arm"] for failure in failures}, {"arm_a", "arm_b"})
        self.assertTrue(all(failure["expected"] == 53085 and failure["observed"] == 53086 for failure in failures))
        self.assertEqual(result["metadata"]["leaf_dispositions"]["/projection_resource_policy/output_components/output_stream_codec"],
                         "SOURCE_DERIVED_METADATA_FAILURE")

    def test_codec_replay_requires_its_captured_source_authority(self):
        name = str(V.TASK_ROOT / "hs/lh/helpers/private_heat_low_ledger_inventory_r1.py")
        self.update(self.b, "d02_correspondence_capture.json",
                    lambda c: c["provenance"]["private_sources"].pop(name), seal=False)
        self.update(self.b, "legacy_metadata.json", lambda m: m["caller_snapshot"]["private_sources"].pop(name))
        result = self.verify()
        self.assertEqual(result["new_run_verdict"], "METADATA_DISPOSITION_REQUIRED", result)
        check = result["metadata"]["evidence"]["output_components"]["arm_b"]
        self.assertEqual(check["status"], "SOURCE_AUTHORITY_NOT_ESTABLISHED")
        self.assertEqual(check["replayed_components"], {})
        self.assertTrue(result["metadata"]["unresolved_required_evidence"])

    def test_conversion_work_difference_is_not_replayed_with_current_abi(self):
        self.update(self.b, "legacy_metadata.json", lambda m:
                    m["projection_resource_policy"]["output_components"].update(actual_output_conversion_work=120065))
        result = self.verify()
        self.assertEqual(result["new_run_verdict"], "METADATA_DISPOSITION_REQUIRED", result)
        self.assertEqual(result["metadata"]["proof_failures"], [])
        difference = result["metadata"]["resource_differences"][0]
        self.assertEqual(difference["path"], "/projection_resource_policy/output_components/actual_output_conversion_work")
        self.assertEqual(difference["evidence"]["status"], "NATIVE_ACCOUNTING_OBSERVATION")
        self.assertFalse(difference["evidence"]["equivalence_asserted"])

    def test_execution_mode_difference_is_invariant(self):
        self.update(self.b, "legacy_metadata.json",
                    lambda m: m["caller_snapshot"]["execution"].update(execution_mode="release"))
        result = self.verify()
        self.assertEqual(result["new_run_verdict"], "NUMERICAL_OR_REPRESENTATION_DEFECT", result)
        path = "/caller_snapshot/execution/execution_mode"
        self.assertEqual(result["metadata"]["leaf_dispositions"][path], "INVARIANT_CONTRACT_FAILURE")
        self.assertNotIn(path, [row["path"] for row in result["metadata"]["provenance_differences"]])

    def test_origin_component_count_prevents_solver_attribution(self):
        self.update(self.b, "legacy_metadata.json",
                    lambda m: m["caller_snapshot"]["native_origin_signature"].update(component_count=2))
        result = self.verify()
        self.assertEqual(result["new_run_verdict"], "INPUT_OR_CONTEXT_MISMATCH", result)
        self.assertFalse(result["solver_attribution_permitted"])
        path = "/caller_snapshot/native_origin_signature/component_count"
        self.assertEqual(result["metadata"]["leaf_dispositions"][path], "INVARIANT_CONTRACT_FAILURE")

    def test_resource_numerical_policy_difference_is_invariant(self):
        self.update(self.b, "legacy_metadata.json",
                    lambda m: m["projection_resource_policy"]["numerical"].update(scalar_slots=32))
        result = self.verify()
        self.assertEqual(result["new_run_verdict"], "NUMERICAL_OR_REPRESENTATION_DEFECT", result)
        path = "/projection_resource_policy/numerical/scalar_slots"
        self.assertEqual(result["metadata"]["leaf_dispositions"][path], "INVARIANT_CONTRACT_FAILURE")
        self.assertEqual(result["metadata"]["resource_differences"], [])

    def test_missing_source_is_not_admitted_by_equal_arrays(self):
        source = next(iter(V.CORE_PINS))
        cap = V.read_json(self.b / "d02_correspondence_capture.json")
        name = str(V.TASK_ROOT / "hs/lh/helpers" / source)
        cap["provenance"]["private_sources"].pop(name)
        write(self.b / "d02_correspondence_capture.json", cap)
        self.update(self.b, "legacy_metadata.json", lambda m: m["caller_snapshot"]["private_sources"].pop(name))
        self.assert_refusal(self.verify(), "VERIFY_REFUSE_SOURCES")

    def bind_supplemental_sources(self, bindings):
        cap = V.read_json(self.b / "d02_correspondence_capture.json")
        cap["provenance"]["private_sources"].update(bindings)
        write(self.b / "d02_correspondence_capture.json", cap)
        self.update(self.b, "legacy_metadata.json",
                    lambda m: m["caller_snapshot"]["private_sources"].update(bindings))

    def test_exact_pinned_supplemental_sources_are_admitted(self):
        self.bind_supplemental_sources({str(V.TASK_ROOT / name): value
                                       for name, value in V.SUPPLEMENTAL_SOURCE_PINS.items()})
        result = self.verify()
        self.assertEqual(result["new_run_verdict"], "METADATA_DISPOSITION_REQUIRED", result)
        self.assertTrue(result["corresponding_inputs_equal"])
        self.assertEqual(result["within_arm_ledger_errors"], dict(arm_a=[], arm_b=[]))

    def test_supplemental_source_wrong_pin_is_refused(self):
        name = next(iter(V.SUPPLEMENTAL_SOURCE_PINS))
        self.bind_supplemental_sources({str(V.TASK_ROOT / name): "0" * 64})
        result = self.verify()
        self.assert_refusal(result, "VERIFY_REFUSE_SOURCES")
        self.assertIn("outside permitted roots", result["error"])

    def test_supplemental_allowlist_does_not_admit_neighbouring_file(self):
        name = next(iter(V.SUPPLEMENTAL_SOURCE_PINS))
        neighbour = (V.TASK_ROOT / name).with_name("not-an-admitted-dependency.py")
        self.bind_supplemental_sources({str(neighbour): "0" * 64})
        result = self.verify()
        self.assert_refusal(result, "VERIFY_REFUSE_SOURCES")
        self.assertIn("outside permitted roots", result["error"])

    def test_repeated_call_identity_tamper_is_refused(self):
        wrong = V.object_hash("forged but internally repeated call identity")
        self.update(self.b, "legacy_metadata.json", lambda m: m.update(call_id=wrong), seal=False)
        self.update(self.b, "d02_correspondence_capture.json",
                    lambda c: c["provenance"].update(call_id=wrong), seal=False)
        reseal(self.b, rebind_call=False)
        self.assert_refusal(self.verify(), "VERIFY_REFUSE_CALL_BINDING")

    def test_resealed_input_bytes_without_call_rebinding_are_refused(self):
        path = self.b / "input_enthalpy_j.npy"
        values = np.load(path, allow_pickle=False)
        values[[0, 1]] = values[[1, 0]]
        np.save(path, values)
        reseal(self.b, rebind_call=False)
        self.assert_refusal(self.verify(), "VERIFY_REFUSE_CALL_BINDING")

    def test_parent_state_must_match_native_origin(self):
        self.update(self.b, "d02_correspondence_capture.json",
                    lambda c: c["input_bindings"].update(parent_state_id=V.object_hash("wrong parent")))
        result = self.verify()
        self.assert_refusal(result, "VERIFY_REFUSE_INPUT_BINDING")
        self.assertIn("parent state identity differs", result["error"])

    def test_historical_mismatch_does_not_hide_new_defect(self):
        old_a, old_b = self.root / "old-a", self.root / "old-b"
        shutil.copytree(self.a, old_a)
        shutil.copytree(self.b, old_b)
        path = self.b / "enthalpy_j.npy"
        value = np.load(path)
        value[0] += 1
        np.save(path, value)
        reseal(self.b)
        result = self.verify(preserved_q10_arm_a=old_a, preserved_q10_arm_b=old_b)
        self.assertEqual(result["verdict"], "NOT_REPRODUCED", result)
        self.assertEqual(result["new_run_verdict"], "NUMERICAL_OR_REPRESENTATION_DEFECT")
        self.assertIn("enthalpy_j.npy", result["historical_differing_files"]["arm_b"])

    def test_historical_mismatch_survives_new_correspondence_refusal(self):
        old_a, old_b = self.root / "old-a", self.root / "old-b"
        shutil.copytree(self.a, old_a)
        shutil.copytree(self.b, old_b)
        (old_b / "enthalpy_j.npy").write_bytes(b"different historical bytes")
        # A local incidence fault would fail before historical comparison;
        # this creates a complete within-arm key but no cross-arm bijection.
        cap = V.read_json(self.b / "d02_correspondence_capture.json")
        cell = cap["cells"][0]
        cell["native_cell"]["index"][0] += 100
        cell["independent_key"]["index"][0] += 100
        cell["independent_key_sha256"] = V.object_hash(cell["independent_key"])
        write(self.b / "d02_correspondence_capture.json", cap)
        reseal(self.b)
        result = self.verify(preserved_q10_arm_a=old_a, preserved_q10_arm_b=old_b)
        self.assertEqual(result["verdict"], "NOT_REPRODUCED", result)
        self.assertEqual(result["new_run_verdict"], "VERIFY_REFUSE", result)
        self.assertEqual(result["refusal_code"], "VERIFY_REFUSE_CELL_MAP", result)
        self.assertIn("enthalpy_j.npy", result["historical_differing_files"]["arm_b"])

    def test_historical_resource_only_difference_keeps_strict_linkage_failure(self):
        old_a, old_b = self.root / "old-a", self.root / "old-b"
        shutil.copytree(self.a, old_a)
        shutil.copytree(self.b, old_b)
        self.update(self.b, "legacy_metadata.json",
                    lambda m: m["projection_resource_policy"]["numerical"].update(scalar_peak_bits=65))
        result = self.verify(preserved_q10_arm_a=old_a, preserved_q10_arm_b=old_b)
        self.assertEqual(result["verdict"], "NOT_REPRODUCED", result)
        self.assertEqual(result["new_run_verdict"], "METADATA_DISPOSITION_REQUIRED", result)
        detail = result["historical_linkage_details"]["arm_b"]
        self.assertEqual(detail["arrays_status"], "EXACT_BYTES_MATCH")
        self.assertEqual(detail["metadata_raw_status"], "DIFFERENT_OR_MISSING")
        self.assertTrue(detail["metadata_only_resource_differences"])
        self.assertEqual(detail["metadata_difference_families"], {"resource": 1})
        self.assertEqual(detail["metadata_differing_leaves"][0]["path"],
                         "/projection_resource_policy/numerical/scalar_peak_bits")

    def test_historical_inventory_formatting_preserves_exact_linkage(self):
        old_a, old_b = self.root / "old-a", self.root / "old-b"
        shutil.copytree(self.a, old_a)
        shutil.copytree(self.b, old_b)
        for directory in (old_a, old_b):
            path = directory / "arrays.json"
            inventory = V.read_json(path)
            path.write_text(json.dumps(dict(reversed(list(inventory.items()))), indent=2), encoding="utf8")
        result = self.verify(preserved_q10_arm_a=old_a, preserved_q10_arm_b=old_b)
        self.assertEqual(result["historical_q10_binding_status"], "AGREES_WITH_PRESERVED_Q10", result)
        self.assertEqual(result["new_run_verdict"], "METADATA_DISPOSITION_REQUIRED", result)
        for detail in result["historical_linkage_details"].values():
            self.assertEqual(detail["differing_files"], [])
            self.assertEqual(detail["raw_differing_files"], ["arrays.json"])
            self.assertEqual(detail["array_inventory_status"], "EXACT_SEMANTIC_MATCH")
            self.assertEqual(detail["array_inventory_raw_status"], "DIFFERENT_OR_MISSING")
            self.assertEqual(detail["arrays_status"], "EXACT_BYTES_MATCH")
            self.assertEqual(detail["metadata_raw_status"], "EXACT_BYTES_MATCH")

    def test_historical_inventory_shape_name_and_type_faults_break_linkage(self):
        old_a, old_b = self.root / "old-a", self.root / "old-b"
        shutil.copytree(self.a, old_a)
        shutil.copytree(self.b, old_b)
        original = V.read_json(old_b / "arrays.json")
        for defect in ("shape", "name", "type"):
            with self.subTest(defect=defect):
                inventory = copy.deepcopy(original)
                if defect == "shape":
                    inventory["enthalpy_j"] = [4]
                elif defect == "name":
                    inventory["unknown_array"] = inventory.pop("enthalpy_j")
                else:
                    inventory["enthalpy_j"] = ["3"]
                write(old_b / "arrays.json", inventory)
                result = self.verify(preserved_q10_arm_a=old_a, preserved_q10_arm_b=old_b)
                self.assertEqual(result["verdict"], "NOT_REPRODUCED", result)
                detail = result["historical_linkage_details"]["arm_b"]
                self.assertEqual(detail["differing_files"], ["arrays.json"])
                self.assertEqual(detail["array_inventory_status"], "DIFFERENT_OR_MISSING")
                self.assertEqual(detail["arrays_status"], "EXACT_BYTES_MATCH")
                if defect != "shape":
                    self.assertIn("array_inventory_error", detail)


if __name__ == "__main__":
    unittest.main()
