"""Focused R3 input-path regression; all fixture decisions remain SYNTHETIC TEST."""

import copy
import hashlib
import json
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest import mock

from work.diadem_tectonics_r2 import test_snapshot as fixtures
from work.diadem_tectonics_r3 import snapshot


class SnapshotInputTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SnapshotTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.package = self.fixture.package

    def pins(self):
        return {name: hashlib.sha256((self.package / name).read_bytes()).hexdigest()
                for name in (snapshot.MANIFEST, *snapshot.FILES.values())}

    def test_exact_r2_products_order_status_nulls_and_detached_runs(self):
        partial = self.fixture.two_motions((None, 0), (3, 4))
        partial["faults"] = [{"fault_id": self.fixture.faults[0], "plate_boundary": False,
                               "source_refs": ["synthetic"]}]
        complete = self.fixture.decisions()
        complete["source_status"] = "APPROVED"
        complete["blocks"] = [self.fixture.block(name, 0, 0, "SYNTHETIC-" + name)
                                for name in self.fixture.blocks]
        complete["faults"] = [{"fault_id": name, "plate_boundary": False,
                                "source_refs": ["synthetic"]} for name in self.fixture.faults]
        for decisions in (None, self.fixture.two_motions(), partial, complete):
            with self.subTest(decisions="none" if decisions is None else decisions["blocks"]):
                original = copy.deepcopy(decisions)
                previous = fixtures.snapshot.build_snapshot(self.package, decisions)
                serialised = json.dumps(previous, allow_nan=False)
                pins = self.pins()
                for supplied in (None, pins):
                    result = snapshot.build_snapshot(self.package, decisions, package_pins=supplied)
                    self.assertEqual(json.dumps(result, allow_nan=False), serialised)
                result["products"][snapshot.PRODUCT_NAMES[2]]["blocks"].clear()
                result["products"][snapshot.PRODUCT_NAMES[0]]["provenance"]["consumed_input_pins"].clear()
                self.assertEqual(json.dumps(snapshot.build_snapshot(self.package, decisions,
                                 package_pins=pins), allow_nan=False), serialised)
                self.assertEqual(decisions, original)
                self.assertEqual(pins, self.pins())

    def test_one_decode_per_file_and_raw_only_final_and_restore_checks(self):
        pins = self.pins()
        for supplied in (None, pins):
            with mock.patch.object(snapshot.json, "loads", wraps=json.loads) as loads, \
                    mock.patch.object(snapshot, "_raw", wraps=snapshot._raw) as raw:
                snapshot.build_snapshot(self.package, package_pins=supplied)
                self.assertEqual(loads.call_count, 4)
                self.assertEqual(raw.call_count, 8)
                self.assertEqual([call.args[0].name for call in raw.call_args_list],
                                 [snapshot.MANIFEST, *snapshot.FILES.values()] * 2)
        with mock.patch.object(snapshot.json, "loads", side_effect=AssertionError("decoded")), \
                mock.patch.object(snapshot, "_raw", wraps=snapshot._raw) as raw:
            self.assertIsNone(snapshot.verify_package(self.package, pins))
            self.assertEqual(raw.call_count, 4)

    def test_all_consumed_files_detect_initial_and_during_snapshot_drift(self):
        for name in self.pins():
            path = self.package / name
            original = path.read_bytes()
            pins = self.pins()
            with self.subTest(file=name, boundary="initial"):
                path.write_bytes(original + b" ")
                for operation in (lambda: snapshot.build_snapshot(self.package, package_pins=pins),
                                  lambda: snapshot.verify_package(self.package, pins)):
                    with self.assertRaisesRegex(snapshot.SnapshotError, "changed; no repin"):
                        operation()
                path.write_bytes(original)
            for supplied in (None, pins):
                with self.subTest(file=name, boundary="final", pinned=supplied is not None):
                    segments = snapshot._segments

                    def drift(*args):
                        path.write_bytes(original + b" ")
                        return segments(*args)

                    with mock.patch.object(snapshot, "_segments", side_effect=drift), \
                            self.assertRaisesRegex(snapshot.SnapshotError, "changed during snapshot"):
                        snapshot.build_snapshot(self.package, package_pins=supplied)
                    path.write_bytes(original)

    def test_external_pins_require_exact_inventory_and_plain_hashes(self):
        pins = self.pins()
        invalid = [[], list(pins), {}, {**pins, "extra.json": "a" * 64},
                   {key: value for key, value in pins.items() if key != snapshot.MANIFEST}]
        for value in (None, True, 12, "A" * 64, "a" * 63, {"sha256": "a" * 64}):
            invalid.append({**pins, snapshot.MANIFEST: value})
        invalid.append({**{key: value for key, value in pins.items() if key != snapshot.MANIFEST},
                        "../" + snapshot.MANIFEST: pins[snapshot.MANIFEST]})
        for value in invalid:
            with self.subTest(pins=value):
                for operation in (lambda: snapshot.build_snapshot(self.package, package_pins=value),
                                  lambda: snapshot.verify_package(self.package, value)):
                    with mock.patch.object(snapshot, "_raw", side_effect=AssertionError("read invalid pins")), \
                            self.assertRaises(snapshot.SnapshotError):
                        operation()
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.verify_package(self.package, None)

    def test_matching_pins_do_not_bypass_json_or_manifest_validation(self):
        path = self.package / snapshot.MANIFEST
        original = path.read_bytes()
        for raw in (b'{"status":"x","status":"y"}', b'{"bad":NaN}', b'null', b'[]',
                    b'{"bad":Infinity}', b'{"bad":', b'\xff'):
            with self.subTest(raw=raw):
                path.write_bytes(raw)
                with self.assertRaises(snapshot.SnapshotError):
                    snapshot.build_snapshot(self.package, package_pins=self.pins())
        path.write_bytes(original)
        for field, value in (("path", "elsewhere/events.json"), ("sha256", "a" * 64)):
            with self.subTest(field=field):
                manifest = copy.deepcopy(self.fixture.manifest)
                manifest["histories"]["A"]["artifacts"]["events"][field] = value
                self.fixture.write(snapshot.MANIFEST, manifest)
                for supplied in (None, self.pins()):
                    with self.assertRaisesRegex(snapshot.SnapshotError, "manifest mismatch"):
                        snapshot.build_snapshot(self.package, package_pins=supplied)
        path.write_bytes(original)

    def test_path_links_reparse_regular_file_and_size_bounds(self):
        pins = self.pins()
        original_lstat = Path.lstat
        for target in (self.package, self.package / snapshot.MANIFEST):
            for info in (SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0),
                         SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)):
                with self.subTest(target=target.name, mode=info):
                    with mock.patch.object(Path, "lstat", lambda path: info if path == target
                                           else original_lstat(path)):
                        for operation in (lambda: snapshot.build_snapshot(self.package, package_pins=pins),
                                          lambda: snapshot.verify_package(self.package, pins)):
                            with self.assertRaisesRegex(snapshot.SnapshotError, "linked/reparse"):
                                operation()
        with self.assertRaisesRegex(snapshot.SnapshotError, "bounded JSON file"):
            snapshot._raw(self.package)
        with mock.patch.object(snapshot, "MAX_JSON_BYTES", 10):
            for operation in (lambda: snapshot.build_snapshot(self.package, package_pins=pins),
                              lambda: snapshot.verify_package(self.package, pins)):
                with self.assertRaisesRegex(snapshot.SnapshotError, "bounded JSON file"):
                    operation()
            with mock.patch.object(Path, "is_file", return_value=True), \
                    mock.patch.object(Path, "stat", return_value=SimpleNamespace(
                        st_size=0, st_mode=stat.S_IFREG, st_file_attributes=0)), \
                    self.assertRaisesRegex(snapshot.SnapshotError, "grew beyond bound"):
                snapshot._raw(self.package / snapshot.MANIFEST)

    def test_actual_symlink_input_is_rejected(self):
        alias = self.package / "package-link"
        try:
            alias.symlink_to(self.package, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"OS disallows symlink creation: {exc}")
        for operation in (lambda: snapshot.build_snapshot(alias, package_pins=self.pins()),
                          lambda: snapshot.verify_package(alias, self.pins())):
            with self.assertRaisesRegex(snapshot.SnapshotError, "linked/reparse"):
                operation()


if __name__ == "__main__":
    unittest.main()
