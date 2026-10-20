"""Synthetic r5/source-shaped fixture migration. Never production evidence."""
import copy
from pathlib import Path
import sys

OBSERVER_BYTES = b"# synthetic observer entry\n"


def install(C, F, producer_bytes):
    F.OBSERVER_PIN = F.sha256(OBSERVER_BYTES).hexdigest()
    F.NETWORK = {
        "vertex_ids": F.np.frombuffer(b'"v0"\n"v1"\n"v2"', dtype="u1"),
        "vertex_home": F.np.zeros(3, dtype="<i8"),
        "vertex_reference": F.np.eye(3),
        "view_vertex": F.np.arange(3, dtype="<i8"),
        "view_plate": F.np.zeros(3, dtype="<i8"),
        "view_reference": F.np.eye(3),
        "faces": F.np.frombuffer(b'{"face_id":"f0"}', dtype="u1"),
        "boundaries": F.np.array([], dtype="u1"),
    }
    original_composite = F.composite_records

    def composite(*args, **kwargs):
        value = original_composite(*args, **kwargs)
        desc = value["differential"]["endpoint_network"]
        desc["plates"] = [{"plate_id": "p0"}]
        desc["network_id"] = F.network_id(desc, F.NETWORK)
        return value

    F.composite_records = composite
    original_arrays = F.i1_arrays

    def arrays():
        value = original_arrays()
        value["spatial-audit:joined-heat:temperature_k"] = value.pop("spatial-audit:b")
        return value

    F.i1_arrays = arrays
    F._historical_E_source = producer_bytes
    F._migration_C = C


def records(F, supplied):
    """Complete synthetic E source shapes before the coherent proof is built.

    Existing changed per-cell deviation values remain changed. Bounds are derived
    from those inputs, so no numerical mutation is overwritten or normalised away.
    """
    C = F._migration_C
    values = copy.deepcopy(F.base_records() if supplied is None else supplied)
    for interval, mapping in values.items():
        header = mapping.get("mesh")
        if isinstance(header, dict) and "cells" in header and C.DEVIATION_FIELD in header:
            header["schema"] = "atlas.source-bound-exterior-thermal-mesh.v1"
            header.setdefault("time_s", F.enc(interval))
            header.setdefault("trajectory_id", F.H("synthetic-trajectory-%d" % interval))
            for cell in header["cells"]:
                error = C.Fraction(*C.rational(cell[C.DEVIATION_FIELD]))
                volume = max(C.Fraction(10), error + 1)
                cell.update(kind="exterior", volume_m3=F.enc(volume),
                            physical_volume_bounds_m3=[F.enc(volume-error), F.enc(volume+error)])
        if interval == 1:
            mapping["exchange"] = {"joined_heat": {"plan_id": "synthetic-heat-plan",
                                                     "geometry_id": "synthetic-heat-geometry"}}
    return values


def before_build(F, arm):
    F.write(Path(arm.observer), OBSERVER_BYTES)
    F.write(arm.dir / "n/integration_exterior_mesh.py", F._historical_E_source)


def observation(F, arm, record, metadata):
    C = F._migration_C
    record["schema"] = "atlas.private.iv1-arm-dump.r5-draft"
    record["head"]["root_metadata"] = copy.deepcopy(metadata)
    environment = record["environment"]
    environment.update(executable=sys.executable, executable_sha256=C.file_sha(sys.executable),
                       version=sys.version, version_info=list(sys.version_info[:3]),
                       implementation=sys.implementation.name, cache_tag=sys.implementation.cache_tag,
                       prefix=sys.prefix, base_prefix=sys.base_prefix, platform=sys.platform,
                       byteorder=sys.byteorder)
    environment["python_environment"] = {"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    environment["argv"] = [arm.observer, "--profile", str(arm.profile),
                           "--profile-sha256", arm.sha, "--interval", str(record["interval"]),
                           "--out", str(arm.dumps / ("i%d" % record["interval"])),
                           "--observer-path", arm.observer, "--observer-sha256", F.OBSERVER_PIN]
    record["environment_after"] = copy.deepcopy(environment)
    record["interpreter"]["launch_environment"] = {
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
        "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    for name, ref in record["bindings"].items():
        if name != "catalog":
            ref["nbytes"] = Path(ref["path"]).stat().st_size
        else:
            ref["nbytes"] = len(b"catalog-i%d-%s" % (record["interval"], arm.name.encode()))
    return record


def override_retained(C, F, K, Cases):
    def legacy_covered(self, delta):
        value = self.covered(delta)
        self.check(value, "REVIEW", "v2 lacks independently established quantity/norm/source semantics")
        row = self.field(value, "i1/mesh", "mesh.volume_m3")
        self.assertIsNone(row["radius"])
        self.assertEqual(row["bound_violations"], 0)
        self.assertEqual(row["changed"], 1)

    def vol_fail(self):
        legacy_covered(self, 2)

    def vol_review(self):
        legacy_covered(self, C.Fraction(1, 2**8))

    def vol_pass(self):
        legacy_covered(self, C.Fraction(1, 2**14))

    Cases.test_s03_vol_fail = vol_fail
    Cases.test_s04_vol_review = vol_review
    Cases.test_s05_vol_pass = vol_pass
