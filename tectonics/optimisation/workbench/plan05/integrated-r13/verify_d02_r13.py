"""Offline exact D02 comparison. Never launches a capture or changes a hold.

The capture is evidence for its own run. Historical linkage requires identical
saved arrays AND metadata/source bindings; no historical map is reconstructed.
Native field definitions: mesh_tables.py, integration_exterior_mesh.py,
private_heat_native_issuer_r13.py and private_heat_native_projection_r4.py.
"""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

TASK_ROOT = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
SELECTION_ROOT = Path(__file__).resolve().parent
ORDER_REPAIR_ROOT = SELECTION_ROOT / "order-repair"
ORDER_REPAIR_SCHEMA = "plan05.physical-order-selection.r1"
ORDER_REPAIR_ISSUER_PIN = "ee6821b457370d131645a92de4ed94dc60128021557e006191e078c50d915d1b"
ORDER_REPAIR_ORDERING = "authenticated physical cell support; caller row order restored"
CAPTURE_SCHEMA = "atlas.private.d02-correspondence-capture.r13"
MESH_SCHEMA = "atlas.private.thermal-mesh-record.r13"
ARRAY_NAMES = ("enthalpy_j", "input_capacity_j_k", "input_enthalpy_j",
               "input_source_w", "temperature_k")
INPUT_NAMES = ARRAY_NAMES[1:4]
CELL_ACCOUNTS = ("exact_cell_storage_residual_j", "exact_corrected_enthalpy_j",
                 "exact_retained_solver_residual_j", "exact_stock_projection_residual_j")
FACE_ACCOUNT = "exact_paired_face_energy_j"
SCALARS = ("exact_outward_boundary_energy_j", "exact_source_energy_j",
           "independently_supplied_absolute_residual_target")
CORE_PINS = {
    "private_heat_native_issuer_r13.py": "549dbc86b9405323993e8d2aeb519ace7b50ad2d0d94e1bed66b59f81f7fe0c4",
    "mesh_tables.py": "5fd2afcde6064fcd004a041d0ecfa4a40da90c84f8b36e9c24df0f011cd897ab",
    "exterior_mesh_patch.py": "84367f31a6cb1cc32e8d111fa21f1b21f1dcaa12f82aa94266c00888a6a6d890",
    "heat_ledger_tables.py": "d2738a40e2c4378901bdb803fd8e4ad6c6e8f48755e26625dc96392d1ac72d77",
    "content_cache.py": "de7d3e454b41e78916a2c98cf76efe531e981be9a232915d6d152d6ad61e05bb",
    "private_heat_indexed_runtime.py": "997277d845d81db007933f7e0d21531044571d09b7b7de31ac567e84f3c65ead",
}
# Actual d02-capture-01/arm-0 caller bindings exposed these three shared
# dependencies omitted by r6's four roots. Admit exact files and bytes only;
# this does not widen a directory root or claim the old launch manifest covered them.
SUPPLEMENTAL_SOURCE_PINS = {
    "fidelity-integration-20261005/heat-repair-20261007/source/tectonics/src/atlas_tectonics/integration_exact_gmp.py":
        "1cecc336d4584f44ba3ae97636e22e4048638d627d656ab2cc766dc6b46d5f8f",
    "fidelity-integration-20261005/heat-repair-20261007/source/tectonics/src/atlas_tectonics/integration_mimetic_newton.py":
        "ef0f3b48ec1c992f2887f53b21c054d69439e58be2d3d445069162f29a51a0f0",
    "fidelity-integration-20261005/heat-repair-20261007/source/tectonics/src/atlas_tectonics/integration_spatial_transport.py":
        "70cdfc9a5b0a4e6b518f6354550fc2a23b333a0474c07dfac55f670cdffde230",
}
OUTPUT_POLICY_SOURCE_PINS = {
    "private_heat_native_projection_r4.py": "2c66898aea90f1613ef40b2ac570dda25f26d9f258a9fdf02efa71297479189f",
    "private_heat_issuer_resources_r1.py": "f46aefd332c97c5e7fd6ddd9de3a0783d7608d3820a9b440483bf0fee36d7318",
    "private_heat_low_ledger_inventory_r1.py": "462bf6a2a63cd11983da8c16ea3889a8cd72bfb374b09b3729907cb7a2a66596",
    "private_heat_gmp_resources_r1.py": "5ada7b86bc189393d74b20aad1f5eb312b0398f25dd74710f6209dfb94f2edca",
    "private_heat_decimal_inventory_r1.py": "ded95d895acd84dc3d6e858054a7b21d5a58cb45c9f07790b676c2ad926a02b5",
}
CONTROL_PINS = {
    "lf3": "e5cef40c1b15a263a74d894252321a5af969ce35b37b9dfcf31aa3b94fd123c6",
    "lh": "acd34ca42dc6464f4654e518d322d1ee03e1900b8159e0012fc3e6a2b27265d8",
}
STEP7_PIN = "91db76106dd18758d9c8b62173793d9ea33e1f35a03873112d8faf21dd7a027a"
STEP7_PATH = TASK_ROOT / ("fidelity-integration-20261005/continuation-repair-20261013/"
                         "optimisation-20261014/resumability-r1/compact-geometry-r1/"
                         "step7_same_call_heat_control.py")
TOP_METADATA = {
    "accounting", "call_id", "caller_snapshot", "cell_ids", "duration_s",
    "endpoint_face_trace_status", "face_ids", "fixed_forward_producer",
    "genuine_forward_origin", "geometry_id", "loaded_dependencies",
    "loaded_instructions_match_disk_source_not_asserted", "method_id",
    "native_heat_dispatch_enabled", "native_issue_performed", "native_resource_admitted",
    "origin_binding_status", "plan_id", "private_correction_method_id",
    "private_loaded_source_identity_certified", "private_result_id", "production_acceptance",
    "projection_resource_policy", "resource_scope", "schema", "source_policy", "state_id",
    "whole_method_memory_inventory_certified", *CELL_ACCOUNTS, FACE_ACCOUNT, *SCALARS,
}
CALL_METADATA = {
    "cell_ids", "duration_s", "execution", "fixture_only", "geometry_id", "graph_id",
    "heat_capacity_j_kg_k", "loaded_dependencies", "native_origin_signature",
    "owner_definition_id", "owner_id", "plan_id", "private_sources", "schema",
    "source_policy", "source_stage_id", "state_id", "thermal_mesh_id",
}
PROVENANCE_TOP = {"call_id", "geometry_id", "plan_id", "private_result_id", "state_id"}
PROVENANCE_CALL = {
    "geometry_id", "graph_id", "owner_definition_id", "owner_id", "plan_id",
    "source_stage_id", "state_id", "thermal_mesh_id",
}
ORIGIN_IDENTITIES = {
    "owner_id", "owner_definition_id", "funding_id", "transport_id", "state_id",
    "parent_state_id", "source_stage_id", "source_inventory_id", "native_source_inventory_id",
    "graph_id", "thermal_mesh_id",
}
RESOURCE_OBSERVATIONS = {
    "operations", "actual_retained_rational_bytes", "scalar_peak_bits",
    "retained_reserved_bytes", "released_last_use_scratch_bytes",
}
RESOURCE_OUTPUT_COMPONENTS = {
    "output_hex_strings_and_pairs", "output_stream_codec", "actual_output_conversion_work",
}
HEADER_IDENTITIES = {"funding_id", "support_id", "wall_measure_id", "source", "booked_cell_rule"}


class Refuse(ValueError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


def require(condition, code, detail):
    if not condition:
        raise Refuse(code, detail)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def object_hash(value):
    return digest(canonical(value))


def _pairs(values):
    out = {}
    for key, value in values:
        require(key not in out, "VERIFY_REFUSE_SCHEMA", f"duplicate JSON key: {key}")
        out[key] = value
    return out


def parse(raw):
    return json.loads(raw, object_pairs_hook=_pairs,
                      parse_constant=lambda v: (_ for _ in ()).throw(Refuse(
                          "VERIFY_REFUSE_SCHEMA", f"nonfinite JSON: {v}")))


def read_json(path):
    try:
        return parse(path.read_bytes())
    except Refuse:
        raise
    except (OSError, ValueError, UnicodeError) as error:
        raise Refuse("VERIFY_REFUSE_SCHEMA", f"{path.name}: {error}") from error


def keys(value, expected, path):
    require(isinstance(value, dict) and set(value) == set(expected),
            "VERIFY_REFUSE_SCHEMA", f"{path}: required exact field set {sorted(expected)}")


def rational(pair, *, hexadecimal=False):
    require(isinstance(pair, list) and len(pair) == 2,
            "VERIFY_REFUSE_EXACT_ACCOUNT", "rational must have two components")
    if hexadecimal:
        require(all(type(v) is str for v in pair), "VERIFY_REFUSE_EXACT_ACCOUNT", "hex pair required")
        a, b = (int(v, 16) for v in pair)
    else:
        require(all(type(v) in (str, int) for v in pair),
                "VERIFY_REFUSE_EXACT_ACCOUNT", "native rational pair required")
        # Mesh tables expose canonical hex parts; transported stocks and plans
        # expose decimal parts. Preserve each native encoding, without rounding.
        def native_integer(value):
            if type(value) is int:
                return value
            base = 16 if value.startswith(("0x", "-0x")) else 10
            parsed = int(value, base)
            require(value == (hex(parsed) if base == 16 else str(parsed)),
                    "VERIFY_REFUSE_EXACT_ACCOUNT", "noncanonical native integer")
            return parsed
        a, b = map(native_integer, pair)
    require(b > 0, "VERIFY_REFUSE_EXACT_ACCOUNT", "nonpositive denominator")
    q = Fraction(a, b)
    if hexadecimal:
        require(pair == [hex(q.numerator), hex(q.denominator)],
                "VERIFY_REFUSE_EXACT_ACCOUNT", "noncanonical hex rational")
    else:
        require(a == q.numerator and b == q.denominator,
                "VERIFY_REFUSE_EXACT_ACCOUNT", "noncanonical native rational")
    return q


def point(value):
    require(isinstance(value, list) and len(value) == 3,
            "VERIFY_REFUSE_SCHEMA", "three exact coordinates required")
    return tuple(rational(q) for q in value)


def _order_repair_paths(layout):
    return (
        (ORDER_REPAIR_ROOT / "private_heat_physical_order_r1.py").resolve(),
        (ORDER_REPAIR_ROOT / layout / "private_heat_forward_kernel_r13.py").resolve(),
        (ORDER_REPAIR_ROOT / layout / "private_heat_native_issuer_r13.py").resolve(),
    )


def _order_repair(provenance, caller, layout, run_root):
    """Admit only the three selected files, bound to the retained launch receipt."""
    if "order_repair" not in provenance:
        return None
    code = "VERIFY_REFUSE_ORDER_REPAIR"
    repair = provenance["order_repair"]
    fields = {"schema", "layout", "manifest_path", "manifest_sha256", "source_pins",
              "numerical_tolerances_changed", "original_metric_mutated", "ordering"}
    require(isinstance(repair, dict) and set(repair) == fields, code,
            "complete exact repair descriptor required")
    require(repair["schema"] == ORDER_REPAIR_SCHEMA and repair["layout"] == layout
            and repair["numerical_tolerances_changed"] is False
            and repair["original_metric_mutated"] is False
            and repair["ordering"] == ORDER_REPAIR_ORDERING, code,
            "repair descriptor policy or layout differs")
    expected_paths = {str(path) for path in _order_repair_paths(layout)}
    pins = repair["source_pins"]
    require(isinstance(pins, dict) and set(pins) == expected_paths, code,
            "repair descriptor must bind exactly the shared helper and this arm's forward/issuer files")
    require(pins[str(_order_repair_paths(layout)[2])] == ORDER_REPAIR_ISSUER_PIN, code,
            "selected issuer variant differs")
    manifest_path = Path(repair["manifest_path"]).resolve()
    require(manifest_path.is_relative_to(SELECTION_ROOT.resolve()) and manifest_path.is_file(), code,
            "retained selection manifest missing or outside the integration workspace")
    raw = manifest_path.read_bytes()
    require(digest(raw) == repair["manifest_sha256"], code, "selection manifest bytes differ")
    selection = parse(raw)
    require(isinstance(selection, dict) and selection.get("schema") == "plan05-integrated-r13.v1"
            and selection.get("scope") == ["lf3", "lh"]
            and selection.get("historical_q10") == "FAIL" and selection.get("q22") == "HELD", code,
            "selection scope or retained historical status differs")
    selected = selection.get("order_repair")
    all_paths = {str(path) for arm in ("lf3", "lh") for path in _order_repair_paths(arm)}
    require(isinstance(selected, dict) and selected.get("schema") == ORDER_REPAIR_SCHEMA
            and selected.get("scope") == ["lf3", "lh"]
            and isinstance(selected.get("source_pins"), dict)
            and set(selected["source_pins"]) == all_paths
            and isinstance(selection.get("source_pins"), dict), code,
            "selection must bind exactly the five permitted repair files")
    require(run_root is not None and (run_root / "attempt.json").is_file(), code,
            "retained launch selection receipt missing")
    attempt = read_json(run_root / "attempt.json")
    require(attempt.get("mode") == "capture"
            and attempt.get("manifest_sha256") == repair["manifest_sha256"], code,
            "repair selection differs from retained launch receipt")
    for name, pin in selected["source_pins"].items():
        require(selection["source_pins"].get(name) == pin, code,
                f"repair file absent or different in full selection: {name}")
    for name, pin in pins.items():
        require(selected["source_pins"].get(name) == pin
                and caller["private_sources"].get(name) == pin, code,
                f"repair file absent or different in caller/selection binding: {name}")
        require(Path(name).is_file() and digest(Path(name).read_bytes()) == pin, code,
                f"repair source bytes differ: {name}")
    return dict(status="EXACT_SELECTED_REPAIR_SOURCES_BOUND", descriptor=repair,
                launch_manifest_sha256=attempt["manifest_sha256"],
                numerical_equivalence_asserted=False, scientific_acceptance=False)


def _source_check(provenance, caller, layout, index, run_root=None):
    require(provenance["arm_index"] == index and provenance["layout_name"] == layout,
            "VERIFY_REFUSE_PROVENANCE", "arm directory/provenance mismatch")
    repair = _order_repair(provenance, caller, layout, run_root)
    issuer_pin = ORDER_REPAIR_ISSUER_PIN if repair is not None else CORE_PINS["private_heat_native_issuer_r13.py"]
    require(provenance["layout_control_sha256"] == CONTROL_PINS[layout]
            and provenance["step7_control_sha256"] == STEP7_PIN
            and provenance["issuer_sha256"] == issuer_pin,
            "VERIFY_REFUSE_SOURCES", "control/issuer pins differ")
    sources = provenance["private_sources"]
    require(sources == caller["private_sources"] and isinstance(sources, dict),
            "VERIFY_REFUSE_SOURCES", "captured source bindings differ from caller snapshot")
    roots = [TASK_ROOT / "hs" / layout / name for name in ("helpers", "runtime-src", "ram")]
    roots.append(TASK_ROOT / "fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests")
    supplemental = {(TASK_ROOT / name).resolve(): value for name, value in SUPPLEMENTAL_SOURCE_PINS.items()}
    overlay = ({Path(name): value for name, value in repair["descriptor"]["source_pins"].items()}
               if repair is not None else {})
    normalised = {}
    for filename, expected in sources.items():
        path = Path(filename).resolve()
        require(any(path.is_relative_to(root.resolve()) for root in roots)
                or (path in supplemental and supplemental[path] == expected)
                or (path in overlay and overlay[path] == expected),
                "VERIFY_REFUSE_SOURCES", f"source outside permitted roots: {filename}")
        require(path not in normalised, "VERIFY_REFUSE_SOURCES", f"aliased source path: {filename}")
        require(path.is_file() and digest(path.read_bytes()) == expected,
                "VERIFY_REFUSE_SOURCES", f"source bytes differ: {filename}")
        normalised[path] = expected
    for filename, expected in CORE_PINS.items():
        selected = (roots[0] / filename).resolve()
        if repair is not None and filename == "private_heat_native_issuer_r13.py":
            selected, expected = _order_repair_paths(layout)[2], ORDER_REPAIR_ISSUER_PIN
        require(normalised.get(selected) == expected,
                "VERIFY_REFUSE_SOURCES", f"required source missing or changed: {filename}")
    require(digest((TASK_ROOT / "hs" / layout / "control.json").read_bytes()) == CONTROL_PINS[layout],
            "VERIFY_REFUSE_SOURCES", "current layout control changed")
    require(digest(STEP7_PATH.read_bytes()) == STEP7_PIN,
            "VERIFY_REFUSE_SOURCES", "current native control source changed")
    return repair


def _cell_key(row, header):
    c, support = row["native_cell"], row["resolved_support"]
    require(row["cell_id"] == c["cell_id"] and row["kind"] == c["kind"],
            "VERIFY_REFUSE_CELL_ALIGNMENT", "native cell projection differs")
    for field in ("logical_cell_id", "physical_support", "volume_m3", "centroid_m", "faces",
                  "physical_volume_bounds_m3", "geometry_volume_max_deviation_m3"):
        require(row[field] == c.get(field), "VERIFY_REFUSE_CELL_ALIGNMENT",
                f"native cell projection differs at {field}")
    refs = c["physical_support"]
    require("differential_support_id" not in refs, "VERIFY_REFUSE_CELL_KEY",
            "differential support requires a separately specified authentic map")
    require(object_hash(support["voxel"]) == refs["voxel_id"],
            "VERIFY_REFUSE_CELL_KEY", "voxel support preimage differs")
    kind = c["kind"]
    if kind == "collar":
        keys(refs, {"voxel_id"}, "collar support")
        keys(support, {"voxel"}, "collar resolved support")
        require(c["physical_cell_id"] == refs["voxel_id"],
                "VERIFY_REFUSE_CELL_KEY", "collar physical identity differs from voxel")
        logical = object_hash(dict(kind="collar", funding_id=header["funding_id"],
                                   cell_id=c["physical_cell_id"]))
        require(c["logical_cell_id"] == logical and c["cell_id"] == logical,
                "VERIFY_REFUSE_CELL_KEY", "collar identity preimage differs")
        independent = dict(kind=kind, index=c["index"], physical_cell_id=c["physical_cell_id"],
                           voxel_id=refs["voxel_id"])
        physical = independent
    elif kind == "exterior":
        keys(refs, {"voxel_id", "radial_layer_id", "cone_id"}, "exterior support")
        keys(support, {"voxel", "radial_layer", "original_cone", "trajectory_id"},
             "exterior resolved support")
        require(object_hash(support["radial_layer"]) == refs["radial_layer_id"]
                and object_hash(support["original_cone"]) == refs["cone_id"]
                and support["trajectory_id"] == header["trajectory_id"],
                "VERIFY_REFUSE_CELL_KEY", "exterior support preimage differs")
        logical = object_hash({k: c[k] for k in ("source_key", "voxel_index", "radial_band", "chart")}
                              | {"grid_id": header["grid_id"]})
        require(logical == c["logical_cell_id"] and object_hash(dict(
            logical_cell_id=logical, support_id=header["support_id"])) == c["cell_id"],
            "VERIFY_REFUSE_CELL_KEY", "exterior identity preimage differs")
        independent = {k: c[k] for k in ("kind", "logical_cell_id", "source_key",
                                         "voxel_index", "radial_band", "chart")} | refs
        physical = {k: v for k, v in independent.items() if k != "logical_cell_id"}
    else:
        raise Refuse("VERIFY_REFUSE_CELL_KEY", f"unsupported cell kind: {kind}")
    require(row["independent_key"] == independent
            and row["independent_key_sha256"] == object_hash(independent),
            "VERIFY_REFUSE_CELL_KEY", "independent key differs from native field derivation")
    require(rational(c["volume_m3"]) > 0, "VERIFY_REFUSE_SCHEMA", "nonpositive cell volume")
    point(c["centroid_m"])
    provenance = row["input_provenance"]
    keys(provenance, {"graph_end_volume_m3", "transport_exact_enthalpy_j",
                      "transport_exact_component_masses_kg"}, "cell input provenance")
    require(rational(provenance["graph_end_volume_m3"]) > 0,
            "VERIFY_REFUSE_INPUT_BINDING", "transported cell is not positive")
    rational(provenance["transport_exact_enthalpy_j"])
    require(isinstance(provenance["transport_exact_component_masses_kg"], list)
            and provenance["transport_exact_component_masses_kg"],
            "VERIFY_REFUSE_INPUT_BINDING", "missing exact component stocks")
    for value in provenance["transport_exact_component_masses_kg"]:
        rational(value)
    return canonical(physical)


def _incidence(cells, faces):
    face_index = {f["face_id"]: i for i, f in enumerate(faces)}
    require(len(face_index) == len(faces), "VERIFY_REFUSE_FACE_ALIGNMENT", "duplicate face IDs")
    cids = [c["cell_id"] for c in cells]
    require(len(set(cids)) == len(cids), "VERIFY_REFUSE_CELL_ALIGNMENT", "duplicate cell IDs")
    incidence = [[] for _ in faces]
    for ci, cell in enumerate(cells):
        seen = set()
        for fid, sign in cell["native_cell"]["faces"]:
            require(fid in face_index and fid not in seen and type(sign) is int and sign in (-1, 1),
                    "VERIFY_REFUSE_FACE_INCIDENCE", "missing/duplicate face or invalid incidence sign")
            seen.add(fid)
            incidence[face_index[fid]].append((ci, sign))
    for fi, face in enumerate(faces):
        native = face["native_face"]
        require(face["face_id"] == native["face_id"], "VERIFY_REFUSE_FACE_ALIGNMENT", "native face ID differs")
        for key in ("kind", "geometry_kind", "centroid_m", "area_vector_m2", "vertices_m",
                    "owners", "cartesian_support", "relative_advection"):
            require(face[key] == native.get(key), "VERIFY_REFUSE_FACE_ALIGNMENT",
                    f"native face projection differs: {key}")
        expected_owners = [cids[i] for i, _ in incidence[fi]]
        require(len(expected_owners) in (1, 2) and len(native["owners"]) == len(expected_owners)
                and set(native["owners"]) == set(expected_owners),
                "VERIFY_REFUSE_FACE_INCIDENCE", "face owners do not equal cell incidence")
        require(len(expected_owners) != 2 or sum(s for _, s in incidence[fi]) == 0,
                "VERIFY_REFUSE_FACE_INCIDENCE", "paired face signs are not opposite")
        require(any(point(native["area_vector_m2"])), "VERIFY_REFUSE_FACE_INCIDENCE", "zero face vector")
        point(native["centroid_m"])
    return incidence


def _grid_proof(root, compact, identity):
    """Decode coordinates from authenticated native pools, not pool positions."""
    fields = compact["grid_fields"]
    if not fields:
        require(not identity.get("grid_proof_arrays"), "VERIFY_REFUSE_GRID_BINDING",
                "grid proof present without native grid fields")
        return {}
    require(fields in (["grid_lines"], ["grid_lines", "thermal_shared_lines"]),
            "VERIFY_REFUSE_GRID_BINDING", "unknown or missing native grid fields")
    names = {"q.pair", "int.sign", "int.offset", "int.bytes"}
    names.update(field + suffix for field in fields for suffix in (".q", ".offset"))
    proofs = identity.get("grid_proof_arrays")
    require(isinstance(proofs, dict) and set(proofs) == names,
            "VERIFY_REFUSE_GRID_BINDING", "complete authenticated grid pools required")
    columns = {}
    for name in sorted(names):
        proof = proofs[name]
        filename = "compact-grid-" + name + ".npy"
        require(isinstance(proof, dict) and set(proof) ==
                {"dtype", "shape", "nbytes", "sha256", "file", "file_sha256"}
                and proof["file"] == filename,
                "VERIFY_REFUSE_GRID_BINDING", f"invalid grid proof descriptor: {name}")
        path = root / filename
        try:
            raw = path.read_bytes()
            require(digest(raw) == proof["file_sha256"],
                    "VERIFY_REFUSE_GRID_BINDING", f"grid proof file hash differs: {name}")
            data = np.load(path, allow_pickle=False)
        except (OSError, ValueError) as error:
            if isinstance(error, Refuse):
                raise
            raise Refuse("VERIFY_REFUSE_GRID_BINDING", f"unreadable grid proof {name}: {error}") from error
        descriptor = dict(dtype=data.dtype.str, shape=list(data.shape), sha256=digest(data.tobytes()))
        require(data.flags.c_contiguous and data.dtype.kind in "iu"
                and descriptor == compact["arrays"].get(name)
                and all(proof[k] == descriptor[k] for k in descriptor)
                and proof["nbytes"] == data.nbytes,
                "VERIFY_REFUSE_GRID_BINDING", f"grid pool differs from native compact binding: {name}")
        columns[name] = data
    signs, offsets, octets, pairs = (columns[name] for name in ("int.sign", "int.offset", "int.bytes", "q.pair"))
    require(signs.ndim == offsets.ndim == octets.ndim == 1 and pairs.ndim == 2
            and pairs.shape[1] == 2 and len(offsets) == len(signs) + 1
            and offsets[0] == 0 and offsets[-1] == len(octets)
            and all(int(offsets[i]) <= int(offsets[i + 1]) for i in range(len(signs)))
            and all(int(v) in (-1, 0, 1) for v in signs)
            and octets.dtype == np.dtype("uint8"),
            "VERIFY_REFUSE_GRID_BINDING", "invalid native integer pool")

    def integer(index):
        index = int(index)
        require(0 <= index < len(signs), "VERIFY_REFUSE_GRID_BINDING", "integer index outside pool")
        start, end = int(offsets[index]), int(offsets[index + 1])
        return int(signs[index]) * int.from_bytes(octets[start:end].tobytes(), "little")

    def pair(index):
        index = int(index)
        require(0 <= index < len(pairs), "VERIFY_REFUSE_GRID_BINDING", "rational index outside pool")
        numerator, denominator = (integer(v) for v in pairs[index])
        require(denominator > 0, "VERIFY_REFUSE_GRID_BINDING", "grid denominator is not positive")
        value = Fraction(numerator, denominator)
        require((value.numerator, value.denominator) == (numerator, denominator),
                "VERIFY_REFUSE_GRID_BINDING", "grid rational is not canonical")
        return [hex(numerator), hex(denominator)]

    grids = {}
    for name in fields:
        linked, start = columns[name + ".q"], columns[name + ".offset"]
        require(linked.ndim == start.ndim == 1 and len(start) == 4
                and start[0] == 0 and start[-1] == len(linked)
                and all(int(start[i]) <= int(start[i + 1]) for i in range(3)),
                "VERIFY_REFUSE_GRID_BINDING", f"invalid native grid offsets: {name}")
        grids[name] = [[pair(v) for v in linked[int(start[i]):int(start[i + 1])]] for i in range(3)]
    return grids


def _load(directory, index):
    root = Path(directory).resolve()
    # Completion token MUST be parsed before even reading partial companions.
    capture = read_json(root / "d02_correspondence_capture.json")
    require(capture.get("schema") == CAPTURE_SCHEMA, "VERIFY_REFUSE_SCHEMA", "r13 capture completion token required")
    required = {"schema", "bindings", "compact_mesh_identity", "provenance", "context_disposition",
                "physical_context", "physical_plan", "input_bindings", "ordered_cell_ids",
                "cell_count", "face_count", "cells", "faces"}
    require(required <= set(capture), "VERIFY_REFUSE_SCHEMA", "incomplete capture completion token")
    mesh_path, meta_path = root / "thermal_mesh_record.json", root / "legacy_metadata.json"
    mesh, meta = read_json(mesh_path), read_json(meta_path)
    binding = capture["bindings"]
    require(mesh.get("schema") == MESH_SCHEMA, "VERIFY_REFUSE_SCHEMA", "r13 mesh schema required")
    require(digest(mesh_path.read_bytes()) == binding["thermal_mesh_record_sha256"]
            and digest(meta_path.read_bytes()) == binding["legacy_metadata_sha256"],
            "VERIFY_REFUSE_HASH", "companion hash differs")
    keys(meta, TOP_METADATA, "legacy metadata")
    caller = meta["caller_snapshot"]
    keys(caller, CALL_METADATA, "caller snapshot")
    n, nf = capture["cell_count"], capture["face_count"]
    require(type(n) is int and type(nf) is int and n > 0 and nf > 0,
            "VERIFY_REFUSE_SCHEMA", "positive dynamic mesh counts required")
    require(len(capture["cells"]) == n and len(capture["faces"]) == nf
            and mesh["cell_count"] == n and mesh["face_count"] == nf
            and mesh["cells"] == capture["cells"] and mesh["faces"] == capture["faces"],
            "VERIFY_REFUSE_CELL_ALIGNMENT", "capture/mesh counts or rows differ")
    cells, faces = capture["cells"], capture["faces"]
    require([c["row_index"] for c in cells] == list(range(n))
            and [f["face_index"] for f in faces] == list(range(nf)),
            "VERIFY_REFUSE_CELL_ALIGNMENT", "row indices are not complete ordered axes")
    require(capture["ordered_cell_ids"] == meta["cell_ids"] == caller["cell_ids"]
            == [c["cell_id"] for c in cells] and meta["face_ids"] == [f["face_id"] for f in faces],
            "VERIFY_REFUSE_CELL_ALIGNMENT", "native array/account row identities differ")
    identity = capture["compact_mesh_identity"]
    compact = parse(identity["metadata_utf8"])
    require(digest(identity["metadata_utf8"].encode()) == identity["metadata_digest"],
            "VERIFY_REFUSE_HASH", "compact metadata digest differs")
    geometry = binding["geometry_id"]
    logical = identity["logical_identity"]
    require(all(v == geometry for v in (identity["expected_geometry_id"], logical["sha256"],
            logical["expected_geometry_id"], mesh["geometry_id"], meta["geometry_id"],
            caller["geometry_id"], caller["thermal_mesh_id"], compact["geometry_id"])),
            "VERIFY_REFUSE_GEOMETRY_ID", "geometry identity bindings differ")
    require(logical["wire"] == {k: logical[k] for k in ("record_schema", "sha256", "canonical_bytes")}
            and type(logical["canonical_bytes"]) is int and logical["canonical_bytes"] > 0,
            "VERIFY_REFUSE_GEOMETRY_ID", "logical identity wire differs")
    require(compact["cell_count"] == n and compact["face_count"] == nf
            and compact["grid_fields"] == identity["grids"] and compact["support_tables"] == identity["tables"],
            "VERIFY_REFUSE_GEOMETRY_ID", "compact descriptor counts differ")
    require(set(compact["arrays"]) == set(identity["array_descriptors"]),
            "VERIFY_REFUSE_GEOMETRY_ID", "compact descriptor names differ")
    for name, descriptor in compact["arrays"].items():
        require(all(identity["array_descriptors"][name][k] == descriptor[k]
                    for k in ("dtype", "shape", "sha256")),
                "VERIFY_REFUSE_GEOMETRY_ID", f"compact descriptor differs: {name}")
    grids = _grid_proof(root, compact, identity)
    header = compact["header"]
    context, plan = capture["physical_context"], capture["physical_plan"]
    for key in ("time_s", "grid_id", "support_id", "funding_id", "trajectory_id", "endpoint"):
        require(context[key] == header[key], "VERIFY_REFUSE_INPUT_BINDING", f"header/context differs: {key}")
    for key in ("time_s", "grid_id", "support_id", "funding_id", "duration_s"):
        require(mesh[key] == context[key], "VERIFY_REFUSE_INPUT_BINDING", f"mesh/context differs: {key}")
    require(context["duration_s"] == meta["duration_s"] == caller["duration_s"]
            and context["heat_capacity_j_kg_k"] == caller["heat_capacity_j_kg_k"]
            and plan["geometry_id"] == geometry and object_hash(plan) == meta["plan_id"] == caller["plan_id"]
            and context["boundary"] == plan["boundary"],
            "VERIFY_REFUSE_INPUT_BINDING", "plan/input context binding differs")
    provenance = capture["provenance"]
    for key in ("plan_id", "state_id", "owner_id", "owner_definition_id", "loaded_dependencies"):
        require(provenance[key] == caller[key], "VERIFY_REFUSE_PROVENANCE", f"caller provenance differs: {key}")
    require(provenance["call_id"] == meta["call_id"], "VERIFY_REFUSE_PROVENANCE", "call identity differs")
    for key in ("graph_id", "state_id", "source_stage_id"):
        require(capture["input_bindings"][key] == caller[key],
                "VERIFY_REFUSE_INPUT_BINDING", f"transport binding differs: {key}")
    require(isinstance(capture["input_bindings"]["parent_state_id"], str)
            and capture["input_bindings"]["parent_state_id"],
            "VERIFY_REFUSE_INPUT_BINDING", "parent state identity missing")
    origin = caller["native_origin_signature"]
    require(isinstance(origin, dict)
            and capture["input_bindings"]["parent_state_id"] == origin.get("parent_state_id"),
            "VERIFY_REFUSE_INPUT_BINDING", "parent state identity differs from native origin")
    order_repair = _source_check(provenance, caller, ("lf3", "lh")[index], index, root.parent)
    require(mesh["context_disposition"] == capture["context_disposition"]
            and capture["context_disposition"]["disposed"]["unexpanded_legacy_record"] is True,
            "VERIFY_REFUSE_EXPANSION", "unexpanded native mesh disposition required")
    preserved = {key: context[key] for key in ("boundary", "time_s", "duration_s", "grid_id",
                 "support_id", "funding_id", "trajectory_id", "endpoint")}
    preserved.update(mesh_geometry_id=geometry, mesh_counts=dict(cell_count=n, face_count=nf),
                     ordered_cell_ids_observed_in_process=True,
                     compact_metadata_digest=identity["metadata_digest"],
                     compact_array_descriptors_count=len(identity["array_descriptors"]))
    retained_header = {"support_id", "funding_id", "grid_id", "time_s", "trajectory_id",
                       "endpoint", "schema", "method"}
    disposed = dict(header_fields=sorted(set(header) - retained_header),
                    call_plan_fields=sorted(set(plan) - {"boundary"}),
                    raw_lookup_permutations=["c.lookup", "f.lookup"], unexpanded_legacy_record=True)
    require(capture["context_disposition"] == dict(preserved=preserved, disposed=disposed),
            "VERIFY_REFUSE_INPUT_BINDING", "context preservation/disposition fields differ")
    arrays = {}
    keys(binding["arrays"], ARRAY_NAMES, "array binding inventory")
    require(_array_inventory(root / "arrays.json") == {name: [n] for name in ARRAY_NAMES},
            "VERIFY_REFUSE_ARRAY", "array shape inventory differs")
    for name in ARRAY_NAMES:
        filename = root / (name + ".npy")
        data = np.load(filename, allow_pickle=False)
        bound = binding["arrays"][name]
        require(data.dtype == np.dtype("float64") and data.shape == (n,) and np.isfinite(data).all(),
                "VERIFY_REFUSE_ARRAY", f"invalid binary64 vector: {name}")
        require(bound == dict(dtype="float64", shape=[n], npy_sha256=digest(filename.read_bytes()),
                              raw_sha256=digest(data.tobytes())),
                "VERIFY_REFUSE_HASH", f"array bytes/binding differ: {name}")
        arrays[name] = data
    # _bind_indexed_owner_call supplies these three arrays to _make_call;
    # _legacy_snapshot_identity hashes their original names and saved order.
    call_id = object_hash(dict(metadata=caller, arrays={native: dict(
        shape=list(arrays[saved].shape), sha256=digest(arrays[saved].tobytes()))
        for native, saved in (("enthalpy_j", "input_enthalpy_j"),
                              ("capacity_j_k", "input_capacity_j_k"),
                              ("source_w", "input_source_w"))}))
    require(call_id == meta["call_id"] == provenance["call_id"],
            "VERIFY_REFUSE_CALL_BINDING", "native call identity does not bind caller and input array rows")
    result_id = object_hash(dict(metadata=meta, arrays={name: dict(
        shape=list(arrays[name].shape), sha256=digest(arrays[name].tobytes())) for name in ARRAY_NAMES}))
    require(binding["legacy_result_id"] == result_id == binding["advance_result_id"],
            "VERIFY_REFUSE_RESULT_BINDING", "native snapshot identity does not bind metadata and all array rows")
    native = read_json(root.parent / f"arm-{index}.json")
    require(native["status"] == "PASS" and native["cell_count"] == n and native["face_count"] == nf,
            "VERIFY_REFUSE_NATIVE_CONTROL", "native control did not pass with captured counts")
    expected_checks = {"result_id", "plan_descriptor", "metadata_sha256", "metadata_length",
                       "metadata_bytes", "array_names", "arrays", "exact_accounts", "snapshot_identity"}
    require(set(native["checks"]) == expected_checks and all(v is True for v in native["checks"].values())
            and set(native["arrays_equal"]) == set(ARRAY_NAMES)
            and all(v is True for v in native["arrays_equal"].values())
            and native["arrays"] == {name: digest(arrays[name].tobytes()) for name in ARRAY_NAMES},
            "VERIFY_REFUSE_NATIVE_CONTROL", "native equal-result checks or array bindings failed")
    for side in ("legacy", "compact"):
        require(native[side]["result_id"] == result_id
                and native[side]["metadata_sha256"] == binding["legacy_metadata_sha256"]
                and native[side]["metadata_bytes"] == len(meta_path.read_bytes()),
                "VERIFY_REFUSE_NATIVE_CONTROL", f"native {side} snapshot identity differs")
    observer = read_json(root / "observer_disposition.json")
    require(native["ab"]["observer_disposition"] == observer and native["ab"]["leaks"] == []
            and native["ab"]["parent_peak_working_set"] <= 12 * 1024**3,
            "VERIFY_REFUSE_REFERENCE_LEAK", "observer/native receipt differs or import/resource failure")
    phases = {"bind_owner_call", "advance_legacy_packaging", "advance"}
    require(observer["schema"] == "atlas.private.observer-disposition.r13"
            and observer["path"] == "normal" and observer["control_failure"] is None
            and observer["observer_stopped"] is True and observer["secondary_failures"] == []
            and set(observer["callback_slots"]) == phases
            and all(v is True for v in observer["callback_slots"].values())
            and set(observer["callback_releases"]) == phases,
            "VERIFY_REFUSE_REFERENCE_LEAK", "observer completion/slot release evidence missing")
    for phase, release in observer["callback_releases"].items():
        require(release["released"] is True and release["callback_finalised"] is True
                and release["retained_funding"] is False and release["explicit_release_required"] is False
                and release["native_owners_retained"] == 0
                and release["observer_reserved_bytes"] == release["observer_before_bytes"],
                "VERIFY_REFUSE_REFERENCE_LEAK", f"observer owner release incomplete: {phase}")
    for name in CELL_ACCOUNTS + (FACE_ACCOUNT,):
        values = meta[name]
        require(isinstance(values, list) and len(values) == (nf if name == FACE_ACCOUNT else n),
                "VERIFY_REFUSE_EXACT_ACCOUNT", f"incomplete account: {name}")
        for value in values:
            rational(value, hexadecimal=True)
    for name in SCALARS:
        rational(meta[name], hexadecimal=True)
    require(rational(plan["absolute_residual_target"])
            == rational(meta["independently_supplied_absolute_residual_target"], hexadecimal=True),
            "VERIFY_REFUSE_INPUT_BINDING", "plan residual target differs from exact account target")
    physical_keys = [_cell_key(row, header) for row in cells]
    require(len(set(physical_keys)) == n, "VERIFY_REFUSE_CELL_KEY", "duplicate independent physical key")
    incidence = _incidence(cells, faces)
    require(len(plan["conductivity_w_m_k"]) == n, "VERIFY_REFUSE_INPUT_BINDING", "conductivity coverage differs")
    for fid, declaration in plan["boundary"].items():
        require(fid in meta["face_ids"] and len(incidence[meta["face_ids"].index(fid)]) == 1
                and isinstance(declaration, list) and len(declaration) == 2
                and declaration[0] in ("power", "temperature"),
                "VERIFY_REFUSE_INPUT_BINDING", "boundary does not name a one-owner face")
    return dict(root=root, capture=capture, mesh=mesh, meta=meta, caller=caller, arrays=arrays,
                header=header, compact=compact, grids=grids, keys=physical_keys, incidence=incidence,
                order_repair=order_repair)


def _ring(vertices):
    ring = tuple(point(v) for v in vertices)
    require(len(ring) >= 3 and len(set(ring)) == len(ring), "VERIFY_REFUSE_FACE_MAP", "invalid exact polygon ring")
    # Cyclic polygon reindexing is geometry, never sorting solution values.
    candidates = [ring[i:] + ring[:i] for i in range(len(ring))]
    reverse = tuple(reversed(ring))
    candidates.extend(reverse[i:] + reverse[:i] for i in range(len(reverse)))
    return min(candidates)


def _maps(a, b):
    require(set(a["keys"]) == set(b["keys"]), "VERIFY_REFUSE_CELL_MAP", "physical cell key sets differ")
    lookup = {key: i for i, key in enumerate(b["keys"])}
    pi = [lookup[key] for key in a["keys"]]
    a_faces, b_faces = a["capture"]["faces"], b["capture"]["faces"]
    def face_key(bundle, fi, mapping):
        f = bundle["capture"]["faces"][fi]["native_face"]
        return (_ring(f["vertices_m"]), point(f["centroid_m"]),
                tuple(sorted(mapping[ci] for ci, _ in bundle["incidence"][fi])))
    bkeys = [face_key(b, i, list(range(len(pi)))) for i in range(len(b_faces))]
    require(len(set(bkeys)) == len(bkeys), "VERIFY_REFUSE_FACE_MAP", "ambiguous physical faces")
    lookup = {key: i for i, key in enumerate(bkeys)}
    akeys = [face_key(a, i, pi) for i in range(len(a_faces))]
    require(len(set(akeys)) == len(akeys) and set(akeys) == set(bkeys),
            "VERIFY_REFUSE_FACE_MAP", "incomplete or ambiguous face map")
    sigma, orientation = [], []
    for fi, key in enumerate(akeys):
        fj = lookup[key]
        va, vb = (point(faces[i]["native_face"]["area_vector_m2"])
                  for faces, i in ((a_faces, fi), (b_faces, fj)))
        sign = 1 if va == vb else -1 if va == tuple(-v for v in vb) else 0
        require(sign != 0, "VERIFY_REFUSE_FACE_MAP", "face vectors are not exactly equal/opposite")
        ia = {pi[ci]: s for ci, s in a["incidence"][fi]}
        ib = {ci: s * sign for ci, s in b["incidence"][fj]}
        require(ia == ib, "VERIFY_REFUSE_FACE_ORIENTATION", "mapped face incidence sign differs")
        sigma.append(fj)
        orientation.append(sign)
    return pi, sigma, orientation


def _physical(a, b, pi, sigma):
    differences = []
    def compare(path, va, vb):
        if canonical(va) != canonical(vb):
            differences.append(path)
    ha, hb = a["header"], b["header"]
    compare("header.field_inventory", sorted(ha), sorted(hb))
    for key in sorted(set(ha) | set(hb)):
        if key not in HEADER_IDENTITIES:
            compare("header." + key, ha.get(key), hb.get(key))
        elif ha.get(key) != hb.get(key):
            va, vb = ha.get(key), hb.get(key)
            identity_change = (isinstance(va, str) and isinstance(vb, str)
                               and len(va) == len(vb) == 64
                               and all(c in "0123456789abcdef" for c in va + vb))
            if not identity_change:
                compare("header." + key, va, vb)
    # Every header leaf omitted as provenance is reported separately below.
    compare("grid.field_inventory", sorted(a["grids"]), sorted(b["grids"]))
    for name in set(a["grids"]) | set(b["grids"]):
        compare("grid." + name, a["grids"].get(name), b["grids"].get(name))
    ca, cb = a["capture"], b["capture"]
    for key in ("duration_s", "heat_capacity_j_kg_k"):
        compare("physical_context." + key, ca["physical_context"][key], cb["physical_context"][key])
    origins = [bundle["caller"]["native_origin_signature"] for bundle in (a, b)]
    for key in ("component_count", "heat_capacity_j_kg_k", "duration_s"):
        if any(isinstance(origin, dict) and key in origin for origin in origins):
            compare("native_origin_signature." + key,
                    origins[0].get(key) if isinstance(origins[0], dict) else None,
                    origins[1].get(key) if isinstance(origins[1], dict) else None)
    pa, pb = ca["physical_plan"], cb["physical_plan"]
    compare("physical_plan.field_inventory", sorted(pa), sorted(pb))
    for key in set(pa) | set(pb):
        if key not in {"geometry_id", "conductivity_w_m_k", "boundary"}:
            compare("physical_plan." + key, pa.get(key), pb.get(key))
    compare("physical_plan.conductivity_w_m_k", pa["conductivity_w_m_k"],
            [pb["conductivity_w_m_k"][j] for j in pi])
    afid = a["meta"]["face_ids"]
    bfid = b["meta"]["face_ids"]
    ftranslate = {fid: bfid[sigma[i]] for i, fid in enumerate(afid)}
    mapped_boundary = {ftranslate[fid]: value for fid, value in pa["boundary"].items()}
    compare("physical_plan.boundary", mapped_boundary, pb["boundary"])
    ctranslate = {cid: b["meta"]["cell_ids"][pi[i]] for i, cid in enumerate(a["meta"]["cell_ids"])}
    for i, j in enumerate(pi):
        ra, rb = ca["cells"][i], cb["cells"][j]
        na, nb = ra["native_cell"], rb["native_cell"]
        for key in set(na) | set(nb):
            if key not in {"cell_id", "logical_cell_id", "faces"}:
                compare(f"cell[{i}->{j}].{key}", na.get(key), nb.get(key))
        compare(f"cell[{i}->{j}].resolved_support", ra["resolved_support"], rb["resolved_support"])
        compare(f"cell[{i}->{j}].exact_transport_inputs", ra["input_provenance"], rb["input_provenance"])
    for i, j in enumerate(sigma):
        fa, fb = ca["faces"][i]["native_face"], cb["faces"][j]["native_face"]
        for key in set(fa) | set(fb):
            if key not in {"face_id", "owners", "vertices_m", "centroid_m", "area_vector_m2",
                           "cartesian_support", "reservoir_cut"}:
                compare(f"face[{i}->{j}].{key}", fa.get(key), fb.get(key))
        def translate(value):
            if isinstance(value, list):
                return [translate(v) for v in value]
            if isinstance(value, dict):
                return {k: ctranslate.get(v, v) if k == "cell_id" else translate(v)
                        for k, v in value.items()}
            return value
        for key in ("cartesian_support", "reservoir_cut"):
            va, vb = translate(fa.get(key)), fb.get(key)
            # These are unordered support records, not numerical solution fields.
            if isinstance(va, list) and isinstance(vb, list):
                va, vb = sorted(va, key=canonical), sorted(vb, key=canonical)
            compare(f"face[{i}->{j}].{key}", va, vb)
    return differences


def _ledger(bundle):
    m, arrays = bundle["meta"], bundle["arrays"]
    exact = {name: [rational(v, hexadecimal=True) for v in m[name]]
             for name in CELL_ACCOUNTS + (FACE_ACCOUNT,)}
    new, retained, projection, storage = (exact[name] for name in (
        "exact_corrected_enthalpy_j", "exact_retained_solver_residual_j",
        "exact_stock_projection_residual_j", "exact_cell_storage_residual_j"))
    dt = Fraction(m["duration_s"])
    source = [dt * Fraction(float(v)) for v in arrays["input_source_w"]]
    outward = [Fraction(0) for _ in new]
    total_boundary = Fraction(0)
    failures = []
    for fi, inc in enumerate(bundle["incidence"]):
        q = exact[FACE_ACCOUNT][fi]
        for ci, sign in inc:
            outward[ci] += sign * q
        if len(inc) == 1:
            total_boundary += inc[0][1] * q
    target = rational(m["independently_supplied_absolute_residual_target"], hexadecimal=True)
    require(target > 0, "VERIFY_REFUSE_EXACT_ACCOUNT", "nonpositive residual target")
    for i in range(len(new)):
        conditions = {
            "stock_projection": Fraction(float(arrays["enthalpy_j"][i])) - new[i] == projection[i],
            "total_public_residual": retained[i] + projection[i] == storage[i],
            "exact_cell_balance": new[i] - Fraction(float(arrays["input_enthalpy_j"][i]))
                                  + outward[i] - source[i] == retained[i],
            "retained_target": abs(retained[i]) <= target,
        }
        failures.extend(f"row[{i}].{name}" for name, ok in conditions.items() if not ok)
        inputs = bundle["capture"]["cells"][i]["input_provenance"]
        projected_old = float(rational(inputs["transport_exact_enthalpy_j"]))
        masses = np.asarray([float(rational(q)) for q in inputs["transport_exact_component_masses_kg"]])
        projected_capacity = float(np.sum(masses) * bundle["caller"]["heat_capacity_j_kg_k"])
        if np.float64(projected_old).tobytes() != arrays["input_enthalpy_j"][i].tobytes():
            failures.append(f"row[{i}].transport_enthalpy_projection")
        if np.float64(projected_capacity).tobytes() != arrays["input_capacity_j_k"][i].tobytes():
            failures.append(f"row[{i}].transport_capacity_projection")
    if sum(source, Fraction(0)) != rational(m["exact_source_energy_j"], hexadecimal=True):
        failures.append("exact_source_energy_sum")
    if total_boundary != rational(m["exact_outward_boundary_energy_j"], hexadecimal=True):
        failures.append("exact_outward_boundary_energy_sum")
    if (bundle["caller"]["source_policy"] == "already-booked-transport; zero added heat source"
            and any(v != 0 for v in arrays["input_source_w"])):
        failures.append("transport_source_policy")
    return failures


def _leaves(value, path=()):
    if isinstance(value, dict) and value:
        for key in sorted(value):
            yield from _leaves(value[key], path + (key,))
    elif isinstance(value, list) and value:
        for i, item in enumerate(value):
            yield from _leaves(item, path + (i,))
    else:
        yield path, value


def _difference_family(path, left, right):
    """Only named native fields are identity/resource observations.

    Sources: issuer._origin_signature, reuse.ExecutionContext.provenance,
    LoadedIdentity.descriptor, ProjectionNumerics.inventory and
    projection_output_plan. Policy, physical and unknown leaves are invariant.
    """
    identity = ((len(path) == 1 and path[0] in PROVENANCE_TOP)
                or path in {("loaded_dependencies", "identity"),
                            ("caller_snapshot", "loaded_dependencies", "identity"),
                            ("caller_snapshot", "execution", "execution_identity")}
                or (len(path) == 2 and path[0] == "caller_snapshot" and path[1] in PROVENANCE_CALL)
                or (len(path) == 3 and path[:2] == ("caller_snapshot", "private_sources"))
                or (len(path) == 3 and path[:2] == ("caller_snapshot", "native_origin_signature")
                    and path[2] in ORIGIN_IDENTITIES))
    relocated_source_key = len(path) == 3 and path[:2] == ("caller_snapshot", "private_sources")
    if identity and all((value is None and relocated_source_key)
                        or (isinstance(value, str) and len(value) == 64
                            and all(c in "0123456789abcdef" for c in value))
                        for value in (left, right)):
        return "provenance"
    observation = (
        len(path) == 3 and path[:2] == ("projection_resource_policy", "numerical")
        and path[2] in RESOURCE_OBSERVATIONS
        or len(path) == 3 and path[:2] == ("projection_resource_policy", "output_components")
        and path[2] in RESOURCE_OUTPUT_COMPONENTS
        or len(path) == 4 and path[:3] == ("projection_resource_policy", "numerical", "equality_evidence")
        and path[3] in {"required_part_bits", "unused_cross_product_bits"}
        or len(path) == 5 and path[:4] == ("projection_resource_policy", "numerical", "equality_evidence", "part_bits")
        and type(path[4]) is int and 0 <= path[4] < 4)
    if observation and all(type(value) is int and value >= 0 for value in (left, right)):
        return "resource"
    return "invariant"


def _source_correspondence(a, b):
    """Pair only exact arm-relative paths; never basename or value matching."""
    normalised = []
    for bundle in (a, b):
        layout = bundle["capture"]["provenance"]["layout_name"]
        arm_root = (TASK_ROOT / "hs" / layout).resolve()
        mapping = {}
        for filename, value in bundle["caller"]["private_sources"].items():
            path = Path(filename).resolve()
            repair_paths = _order_repair_paths(layout) if bundle.get("order_repair") is not None else ()
            if path in repair_paths:
                label = ("repair/shared/" + path.name if path == repair_paths[0]
                         else "repair/arm/" + path.relative_to((ORDER_REPAIR_ROOT / layout).resolve()).as_posix())
            else:
                label = ("arm/" + path.relative_to(arm_root).as_posix() if path.is_relative_to(arm_root)
                         else "shared/" + path.relative_to(TASK_ROOT.resolve()).as_posix())
            require(label not in mapping, "VERIFY_REFUSE_SOURCES", "ambiguous source-relative path")
            mapping[label] = dict(path=filename, sha256=value)
        normalised.append(mapping)
    by_path = {}
    records = []
    for label in sorted(set(normalised[0]) | set(normalised[1])):
        left, right = normalised[0].get(label), normalised[1].get(label)
        status = ("UNPAIRED_BOUND_SOURCE" if left is None or right is None
                  else "SAME_BYTES_AT_BOUND_RELATIVE_PATHS" if left["sha256"] == right["sha256"]
                  else "BOUND_SOURCE_BYTES_DIFFER")
        record = dict(status=status, relative_path=label, arm_a=left, arm_b=right,
                      full_dependency_graph_completeness="NOT_ASSERTED")
        records.append(record)
        for side in (left, right):
            if side is not None:
                by_path[side["path"]] = record
    return records, by_path


def _output_component_evidence(bundle):
    """Replay only the ABI-independent native codec formulas from saved accounts.

    projection_output_plan(r1):273, RationalGrowth.q:156, hex_pair_char_bound:185.
    Native q() uses at least one numerator bit even for zero; RationalShape's
    default reserves a sign for every value. Do not size actual JSON strings.
    """
    policy = bundle["meta"]["projection_resource_policy"]
    components = policy.get("output_components") if isinstance(policy, dict) else None
    result = dict(status="NOT_PRESENT_FOR_SYNTHETIC_CALL", failures=[], unresolved=[],
                  observed=components, replayed_components={})
    if components is None and bundle["caller"]["fixture_only"] is True:
        return result
    if (not isinstance(components, dict) or set(components) != RESOURCE_OUTPUT_COMPONENTS
            or any(type(value) is not int or value < 0 for value in components.values())):
        result.update(status="INVALID_OUTPUT_COMPONENT_SCHEMA",
                      failures=[dict(path="/projection_resource_policy/output_components",
                                     reason="three native nonnegative integer components required")])
        return result
    layout = bundle["capture"]["provenance"]["layout_name"]
    sources = {Path(name).resolve(): value for name, value in bundle["caller"]["private_sources"].items()}
    missing = [name for name, expected in OUTPUT_POLICY_SOURCE_PINS.items()
               if sources.get((TASK_ROOT / "hs" / layout / "helpers" / name).resolve()) != expected]
    result["authority"] = dict(source_pins=OUTPUT_POLICY_SOURCE_PINS, unmatched_bindings=missing)
    if missing:
        result.update(status="SOURCE_AUTHORITY_NOT_ESTABLISHED",
                      unresolved=[dict(path="/projection_resource_policy/output_components",
                                       reason="captured bindings do not establish the reviewed formula",
                                       sources=missing)])
        return result
    groups = [bundle["meta"][name] for name in CELL_ACCOUNTS + (FACE_ACCOUNT,)]
    groups.append([bundle["meta"][name] for name in SCALARS])
    chars = count = 0
    expression_bits = 1
    for group in groups:
        for encoded in group:
            value = rational(encoded, hexadecimal=True)
            numerator_bits = max(1, value.numerator.bit_length())
            denominator_bits = value.denominator.bit_length()
            chars += 12 + max(1, (numerator_bits + 3) // 4) + max(1, (denominator_bits + 3) // 4)
            count += 1
            expression_bits = max(expression_bits, 4 * (numerator_bits + denominator_bits))
    expected = dict(output_hex_strings_and_pairs=chars + 1024 * (count + 8),
                    output_stream_codec=3 * chars + 1024 * (count + 32))
    result.update(status="ABI_INDEPENDENT_COMPONENTS_REPLAYED", replayed_components=expected,
                  rational_count=count, admitted_character_bound=chars, expression_bits=expression_bits)
    for name, value in expected.items():
        if components[name] != value:
            result["failures"].append(dict(path="/projection_resource_policy/output_components/" + name,
                                            expected=value, observed=components[name],
                                            reason="native formula differs from saved exact accounts"))
    # scalar_work(8) also uses process-local Fraction/int object sizes. Neither
    # opaque execution hash nor current verifier ABI is the original preimage.
    result["conversion_work"] = dict(
        status="NATIVE_OBSERVATION_WITH_UNCAPTURED_OBJECT_SIZE_PREIMAGE",
        observed=components["actual_output_conversion_work"], rational_slots=8,
        expression_bits=expression_bits,
        source="private_heat_low_ledger_inventory_r1.py:253-281",
        formula="65536 + 128*b + 256*8 + 8*(Fraction_zero_size + 2*(int_zero_size + digit_size*ceil(b/bits_per_digit)) + 160 + 16*max(64,ceil(b/64)+2))",
        equivalence_asserted=False)
    if result["failures"]:
        result["status"] = "OUTPUT_COMPONENT_FORMULA_FAILURE"
    return result


def _difference_evidence(path, family, source_by_path, output):
    if family == "resource":
        if path[:2] == ("projection_resource_policy", "output_components"):
            field = path[-1]
            if field == "actual_output_conversion_work":
                return dict(status="NATIVE_ACCOUNTING_OBSERVATION",
                            limitation="original Python object-size preimage is not captured",
                            equivalence_asserted=False)
            return dict(status="SAVED_EXACT_ACCOUNT_FORMULA_CHECK",
                        arm_a=output["arm_a"]["status"], arm_b=output["arm_b"]["status"],
                        claim="see per-arm replayed component and any proof failure")
        return dict(status="NATIVE_ACCOUNTING_OBSERVATION",
                    source="private_heat_issuer_resources_r3.py:124-134",
                    limitation="operation history is not captured; these are not allocator or RSS bounds",
                    equivalence_asserted=False)
    if len(path) == 3 and path[:2] == ("caller_snapshot", "private_sources"):
        return source_by_path[path[2]]
    if path in {("loaded_dependencies", "identity"), ("caller_snapshot", "loaded_dependencies", "identity"),
                ("caller_snapshot", "execution", "execution_identity")}:
        return dict(status="DISTINCT_OPAQUE_NATIVE_BOUND_CONTEXTS", equivalence_asserted=False,
                    limitation="full loaded-code/defaults/constants/runtime preimages are not captured",
                    path_only_cause_asserted=False)
    if path[-1] == "call_id":
        return dict(status="PER_ARM_CALL_IDENTITIES_REPLAYED",
                    preimage="captured caller metadata and three original input arrays",
                    cross_arm_identity_equality_asserted=False)
    if path[-1] == "plan_id":
        return dict(status="PER_ARM_PLAN_IDENTITIES_REPLAYED", preimage="complete captured physical plan",
                    physical_parity="reported separately under physical_context_mismatches")
    if path[-1] in {"geometry_id", "thermal_mesh_id"}:
        return dict(status="NATIVE_GEOMETRY_BINDINGS_CHECKED",
                    physical_parity="reported separately through cell/face maps and physical context",
                    whole_geometry_preimage_equality_asserted=False)
    return dict(status="DISTINCT_NATIVE_BOUND_IDENTITIES", equivalence_asserted=False,
                limitation="full owner, state, source-inventory or private-result preimage is not captured",
                captured_input_binding_checks="reported separately; no historical crosswalk inferred")


def _metadata(a, b):
    handled = set(CELL_ACCOUNTS) | set(SCALARS) | {FACE_ACCOUNT, "cell_ids", "face_ids"}
    provenance, resource, invariant = [], [], []
    left, right = dict(_leaves(a["meta"])), dict(_leaves(b["meta"]))
    equal = compared = mapped = 0
    dispositions = {}
    source_records, source_by_path = _source_correspondence(a, b)
    output = dict(arm_a=_output_component_evidence(a), arm_b=_output_component_evidence(b))
    for path in sorted(set(left) | set(right), key=str):
        label = "/" + "/".join(map(str, path))
        if path[0] in handled or path[:2] == ("caller_snapshot", "cell_ids"):
            mapped += 1
            dispositions[label] = ("FACE_AXIS_SIGNED_EXACT_COMPARISON" if path[0] == FACE_ACCOUNT
                                   else "SCALAR_EXACT_COMPARISON" if path[0] in SCALARS
                                   else "PROVED_ROW_AXIS_COMPARISON")
            continue
        compared += 1
        missing = path not in left or path not in right
        if not missing and canonical(left[path]) == canonical(right[path]):
            equal += 1
            dispositions[label] = "EXACT_EQUAL"
            continue
        entry = dict(path=label, missing=missing,
                     arm_a=left.get(path), arm_b=right.get(path))
        family = _difference_family(path, left.get(path), right.get(path))
        if family == "provenance":
            provenance.append(entry)
            entry["disposition"] = "BOUND_IDENTITY_DIFFERENCE_REQUIRES_DISPOSITION"
        elif family == "resource":
            resource.append(entry)
            entry["disposition"] = "RESOURCE_DIFFERENCE_NO_NUMERICAL_TOLERANCE_OR_EXCEPTION"
        else:
            invariant.append(entry)
            entry["disposition"] = "INVARIANT_CONTRACT_FAILURE"
        if family in {"provenance", "resource"}:
            entry["evidence"] = _difference_evidence(path, family, source_by_path, output)
        dispositions[label] = entry["disposition"]
    header_disposition = []
    for key in sorted(HEADER_IDENTITIES):
        if a["header"].get(key) != b["header"].get(key):
            header_disposition.append(dict(path=key, arm_a=a["header"].get(key), arm_b=b["header"].get(key),
                evidence=dict(status="NATIVE_HEADER_BINDING_RETAINED",
                              physical_parity="reported separately under physical_context_mismatches",
                              full_identity_preimage_equality_asserted=False)))
    failures = [dict(arm=arm, **failure) for arm, check in output.items() for failure in check["failures"]]
    unresolved = [dict(arm=arm, **item) for arm, check in output.items() for item in check["unresolved"]]
    for failure in failures:
        dispositions[failure["path"]] = "SOURCE_DERIVED_METADATA_FAILURE"
    return dict(coverage="ALL_LEAVES", compared_leaves=compared, equal_leaves=equal,
                separately_mapped_account_and_axis_leaves=mapped,
                provenance_differences=provenance, resource_differences=resource,
                invariant_differences=invariant, header_provenance_differences=header_disposition,
                leaf_dispositions=dispositions,
                evidence=dict(source_correspondence=source_records, output_components=output,
                              order_repair=dict(arm_a=a.get("order_repair"), arm_b=b.get("order_repair"))),
                proof_failures=failures, unresolved_required_evidence=unresolved,
                disposition="Differences are retained for explicit acceptance; no metadata exception granted.")


def _array_inventory(path):
    inventory = read_json(path)
    require(isinstance(inventory, dict) and set(inventory) == set(ARRAY_NAMES)
            and all(isinstance(shape, list) and len(shape) == 1
                    and type(shape[0]) is int and shape[0] > 0 for shape in inventory.values()),
            "VERIFY_REFUSE_ARRAY", "five named positive one-dimensional array shapes required")
    return inventory


def _historical(bundle, directory):
    root = Path(directory)
    raw_differences = []
    # Exact metadata bytes include all required old identities and source bindings.
    # Matching rounded arrays alone can never manufacture historical linkage.
    for name in ("arrays.json", "legacy_metadata.json", *(f"{n}.npy" for n in ARRAY_NAMES)):
        path = root / name
        if not path.is_file() or path.read_bytes() != (bundle["root"] / name).read_bytes():
            raw_differences.append(name)
    differences = raw_differences.copy()
    inventory_error = None
    try:
        inventory_equal = _array_inventory(root / "arrays.json") == _array_inventory(
            bundle["root"] / "arrays.json")
    except (Refuse, OSError, ValueError, TypeError) as error:
        inventory_equal, inventory_error = False, str(error)
    if inventory_equal and "arrays.json" in differences:
        differences.remove("arrays.json")
    elif not inventory_equal and "arrays.json" not in differences:
        differences.append("arrays.json")
    array_files = [name + ".npy" for name in ARRAY_NAMES]
    detail = dict(
        comparison="SAVED_ORDER_EXACT_ARRAY_AND_METADATA_BYTES; VALIDATED_ARRAY_INVENTORY; NO_HISTORICAL_CROSSWALK",
        differing_files=differences, raw_differing_files=raw_differences,
        arrays_status="DIFFERENT_OR_MISSING" if any(n in differences for n in array_files) else "EXACT_BYTES_MATCH",
        differing_array_files=[n for n in differences if n in array_files],
        array_inventory_status="EXACT_SEMANTIC_MATCH" if inventory_equal else "DIFFERENT_OR_MISSING",
        array_inventory_raw_status="DIFFERENT_OR_MISSING" if "arrays.json" in raw_differences else "EXACT_BYTES_MATCH",
        metadata_raw_status="DIFFERENT_OR_MISSING" if "legacy_metadata.json" in differences else "EXACT_BYTES_MATCH",
        metadata_difference_families={}, metadata_differing_leaves=[])
    if inventory_error is not None:
        detail["array_inventory_error"] = inventory_error
    if "legacy_metadata.json" in differences:
        try:
            historical = read_json(root / "legacy_metadata.json")
            old, current = dict(_leaves(historical)), dict(_leaves(bundle["meta"]))
            accounted = set(CELL_ACCOUNTS) | set(SCALARS) | {FACE_ACCOUNT, "cell_ids", "face_ids"}
            for path in sorted(set(old) | set(current), key=str):
                missing = path not in old or path not in current
                if not missing and canonical(old[path]) == canonical(current[path]):
                    continue
                family = ("account_or_axis_saved_order" if path[0] in accounted
                          or path[:2] == ("caller_snapshot", "cell_ids")
                          else _difference_family(path, old.get(path), current.get(path)))
                counts = detail["metadata_difference_families"]
                counts[family] = counts.get(family, 0) + 1
                detail["metadata_differing_leaves"].append(dict(
                    path="/" + "/".join(map(str, path)), family=family, missing=missing,
                    historical=old.get(path), current=current.get(path)))
            detail["metadata_leaf_comparison"] = "COMPLETE"
        except (Refuse, OSError, ValueError, TypeError) as error:
            detail["metadata_leaf_comparison"] = "UNAVAILABLE"
            detail["metadata_error"] = str(error)
    else:
        detail["metadata_leaf_comparison"] = "EXACT_BYTES_MATCH"
    detail["metadata_only_resource_differences"] = detail["metadata_difference_families"].keys() == {"resource"}
    return detail


def verify_correspondence(arm_a, arm_b, *, preserved_q10_arm_a=None, preserved_q10_arm_b=None):
    base = dict(schema="atlas.private.d02-verifier.r13", historical_q10="FAIL",
                q22="HELD", scientific_acceptance=False,
                historical_q10_binding_status="UNCHECKED", historical_differing_files=None,
                historical_linkage_details=None)
    try:
        require((preserved_q10_arm_a is None) == (preserved_q10_arm_b is None),
                "VERIFY_REFUSE_HISTORY", "both historical arms must be supplied together")
        a, b = _load(arm_a, 0), _load(arm_b, 1)
        details = (dict(arm_a=_historical(a, preserved_q10_arm_a),
                        arm_b=_historical(b, preserved_q10_arm_b))
                   if preserved_q10_arm_a is not None else None)
        history = {arm: value["differing_files"] for arm, value in details.items()} if details is not None else None
        not_reproduced = history is not None and any(history.values())
        historical = ("NOT_SUPPLIED" if history is None else "NOT_REPRODUCED"
                      if not_reproduced else "AGREES_WITH_PRESERVED_Q10")
        base.update(historical_q10_binding_status=historical, historical_differing_files=history,
                    historical_linkage_details=details)
        pi, sigma, orientation = _maps(a, b)
        physical = _physical(a, b, pi, sigma)
        arrays = {}
        for name in ARRAY_NAMES:
            bad = [i for i, j in enumerate(pi) if a["arrays"][name][i].tobytes()
                   != b["arrays"][name][j].tobytes()]
            arrays[name] = dict(bitwise_equal=not bad, differing_rows=bad)
        cell = {name: dict(exact_equal=all(a["meta"][name][i] == b["meta"][name][j]
                                         for i, j in enumerate(pi)),
                           differing_rows=[i for i, j in enumerate(pi)
                                           if a["meta"][name][i] != b["meta"][name][j]])
                for name in CELL_ACCOUNTS}
        bad_faces = [i for i, j in enumerate(sigma)
                     if rational(a["meta"][FACE_ACCOUNT][i], hexadecimal=True)
                     != orientation[i] * rational(b["meta"][FACE_ACCOUNT][j], hexadecimal=True)]
        scalars = {name: a["meta"][name] == b["meta"][name] for name in SCALARS}
        ledger_a, ledger_b = _ledger(a), _ledger(b)
        metadata = _metadata(a, b)
        input_equal = not physical and all(arrays[n]["bitwise_equal"] for n in INPUT_NAMES)
        input_projection_failure = any("transport_" in v for v in ledger_a + ledger_b)
        proof_defect = (ledger_a or ledger_b or bad_faces or not all(scalars.values())
                        or not all(v["bitwise_equal"] for v in arrays.values())
                        or not all(v["exact_equal"] for v in cell.values())
                        or metadata["invariant_differences"] or metadata["proof_failures"])
        metadata_pending = any(metadata[k] for k in ("provenance_differences", "resource_differences",
                                                     "header_provenance_differences",
                                                     "unresolved_required_evidence"))
        if not input_equal or input_projection_failure:
            outcome = "INPUT_OR_CONTEXT_MISMATCH"
        elif proof_defect:
            outcome = "NUMERICAL_OR_REPRESENTATION_DEFECT"
        elif metadata_pending:
            outcome = "METADATA_DISPOSITION_REQUIRED"
        else:
            outcome = "EXACT_COMPARISON_COMPLETE"
        return base | dict(verdict="NOT_REPRODUCED" if not_reproduced else outcome, new_run_verdict=outcome,
            historical_q10_binding_status=historical, historical_differing_files=history,
            exit_code=0 if outcome == "EXACT_COMPARISON_COMPLETE" and not not_reproduced else 1,
            cell_bijection_pi=pi, face_bijection_sigma=sigma, face_orientation=orientation,
            physical_context_mismatches=physical, corresponding_inputs_equal=input_equal and not input_projection_failure,
            solver_attribution_permitted=input_equal and not input_projection_failure,
            arrays=arrays, exact_cell_accounts=cell, exact_face_account=dict(
                exact_equal=not bad_faces, differing_faces=bad_faces), exact_scalars=scalars,
            within_arm_ledger_errors=dict(arm_a=ledger_a, arm_b=ledger_b), metadata=metadata)
    except (Refuse, OSError, ValueError, TypeError, KeyError, IndexError, OverflowError) as error:
        return base | dict(verdict="NOT_REPRODUCED" if base["historical_q10_binding_status"] == "NOT_REPRODUCED"
                           else "VERIFY_REFUSE", new_run_verdict="VERIFY_REFUSE",
                           refusal_code=getattr(error, "code", "VERIFY_REFUSE_SCHEMA"),
                           error=str(error), exit_code=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", help="Run directory containing arm-0 and arm-1")
    parser.add_argument("--historical", help="Historical q10 directory containing arm-3 and arm-4")
    parser.add_argument("--arm-a")
    parser.add_argument("--arm-b")
    parser.add_argument("--preserved-q10-arm-a")
    parser.add_argument("--preserved-q10-arm-b")
    parser.add_argument("--out-json", "--out", dest="out_json")
    args = parser.parse_args()
    if args.pair:
        if args.arm_a or args.arm_b:
            parser.error("--pair cannot be combined with --arm-a/--arm-b")
        args.arm_a, args.arm_b = Path(args.pair) / "arm-0", Path(args.pair) / "arm-1"
    if not args.arm_a or not args.arm_b:
        parser.error("--pair or both --arm-a and --arm-b required")
    if args.historical:
        if args.preserved_q10_arm_a or args.preserved_q10_arm_b:
            parser.error("--historical cannot be combined with preserved arm arguments")
        args.preserved_q10_arm_a = Path(args.historical) / "arm-3"
        args.preserved_q10_arm_b = Path(args.historical) / "arm-4"
    report = verify_correspondence(args.arm_a, args.arm_b,
        preserved_q10_arm_a=args.preserved_q10_arm_a, preserved_q10_arm_b=args.preserved_q10_arm_b)
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.out_json:
        with Path(args.out_json).open("x", encoding="utf8") as output:
            output.write(encoded + "\n")
    print(encoded)
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
