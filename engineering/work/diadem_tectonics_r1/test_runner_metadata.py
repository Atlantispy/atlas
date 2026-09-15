"""Synthetic metadata failures with matching container pins; no producer runs."""
from __future__ import annotations

import copy
import json
import unittest

import runner
import test_runner_failure as fixtures
from test_runner_failure import digest, write_json


class MetadataTests(unittest.TestCase):
    pin = fixtures.PackageBindingTests.pin

    def setUp(self):
        fixtures.PackageBindingTests.setUp(self)
        self.paths = {
            "shared": self.shared_path, "visual": self.visual_path, "review": self.review_path,
            "contract": self.package / runner.INPUT_NAMES[2],
        }
        self.original = {name: json.loads(path.read_bytes()) for name, path in self.paths.items()}

    def reset(self):
        for name, value in self.original.items():
            write_json(self.paths[name], value)
        self.shared = copy.deepcopy(self.original["shared"])

    def sign_bytes(self, name, payload):
        self.paths[name].write_bytes(payload)
        if name in ("visual", "review"):
            role = "visual_manifest" if name == "visual" else "visual_review"
            self.shared["histories"]["A"]["artifacts"][role]["sha256"] = digest(self.paths[name])
        elif name == "contract":
            self.shared["generator_sources"][1]["sha256"] = digest(self.paths[name])
        if name != "shared":
            write_json(self.shared_path, self.shared)

    def reject(self, name, mutate):
        self.reset()
        document = copy.deepcopy(self.original[name])
        mutate(document)
        self.sign_bytes(name, json.dumps(document, allow_nan=False).encode())
        with self.assertRaises(runner.ReplayError):
            runner.validate_package(self.sandbox, self.roles)

    def test_known_metadata_fixture_passes(self):
        self.assertEqual(len(runner.validate_package(self.sandbox, self.roles)),
                         len(runner.INPUT_NAMES) + len(runner.expected_products(self.roles)))

    def test_wrong_schemas_are_rejected(self):
        for name in self.paths:
            with self.subTest(name=name):
                self.reject(name, lambda d: d.update(schema_version="2.0-accepted"))

    def test_visual_and_review_history_or_status_cannot_promote(self):
        for name, key, value in (("visual", "history", "B"), ("review", "history", "B"),
                                 ("visual", "status", "ACCEPTED"), ("review", "status", "PASS"),
                                 ("review", "reviewer_role", "independent")):
            with self.subTest(name=name, key=key):
                self.reject(name, lambda d, k=key, v=value: d.update({k: v}))

    def test_shared_checkpoint_status_and_typed_flags(self):
        for key, value in (("checkpoint", "checkpoint-2"), ("status", "ACCEPTED"),
                           ("production_unchanged", 1), ("master_ledger_unchanged", 1)):
            with self.subTest(key=key):
                self.reject("shared", lambda d, k=key, v=value: d.update({k: v}))

    def test_every_shared_authority_field_is_bound(self):
        for key in self.original["shared"]["authority"]:
            with self.subTest(key=key):
                self.reject("shared", lambda d, k=key: d["authority"].update({k: "wrong"}))

    def test_extra_promotion_controls_rejected_at_all_metadata_roots(self):
        for name in self.paths:
            with self.subTest(name=name):
                self.reject(name, lambda d: d.update(production_authority_established=True))

    def test_extra_nested_controls_rejected(self):
        changes = [
            ("shared", lambda d: d["authority"].update(promotion_authorized=True)),
            ("shared", lambda d: d["histories"].update(C={"status": "accepted"})),
            ("shared", lambda d: d["histories"]["A"].update(production_authority=True)),
            ("shared", lambda d: d["histories"]["B"].update(production_authority=True)),
            ("shared", lambda d: d["generator_sources"][0].update(accepted=True)),
            ("shared", lambda d: d["histories"]["A"]["artifacts"]["events"].update(accepted=True)),
            ("visual", lambda d: d["artifacts"][0].update(accepted=True)),
            ("review", lambda d: d["items"][0].update(promotion_authorized=True)),
        ]
        for index, (name, mutate) in enumerate(changes):
            with self.subTest(case=index):
                self.reject(name, mutate)

    def test_contract_authority_and_selection_are_bound(self):
        changes = [
            lambda d: d.update(production_authority=True),
            lambda d: d.update(production_authority=0),
            lambda d: d.update(selected_history="b"),
            lambda d: d["authority"]["checkpoint0_manifest"].update(sha256="0" * 64),
            lambda d: d["authority"].update(approved_coordinate_sha256="0" * 64),
            lambda d: d["authority"]["anchor_source_review"].update(sha256="0" * 64),
            lambda d: d["history_selection"].update(approval_verbatim="approved for production"),
            lambda d: d["authority"].update(production_authority=True),
        ]
        for index, mutate in enumerate(changes):
            with self.subTest(case=index):
                self.reject("contract", mutate)

    def test_duplicate_keys_rejected_in_every_document(self):
        for name in self.paths:
            with self.subTest(name=name):
                self.reset()
                payload = json.dumps(self.original[name]).encode()
                self.sign_bytes(name, b'{"status":"ACCEPTED",' + payload[1:])
                with self.assertRaisesRegex(runner.ReplayError, "duplicate JSON key"):
                    runner.validate_package(self.sandbox, self.roles)

    def test_nested_duplicate_key_rejected(self):
        payload = json.dumps(self.original["shared"]).encode().replace(
            b'"authority": {', b'"authority": {"selected_history":"B",', 1)
        self.sign_bytes("shared", payload)
        with self.assertRaisesRegex(runner.ReplayError, "duplicate JSON key"):
            runner.validate_package(self.sandbox, self.roles)

    def test_nonfinite_and_exponent_overflow_rejected(self):
        for name in self.paths:
            for token in ("NaN", "Infinity", "-Infinity", "1e999"):
                with self.subTest(name=name, token=token):
                    self.reset()
                    payload = json.dumps(self.original[name]).encode()
                    self.sign_bytes(name, ('{"probe":' + token + ',').encode() + payload[1:])
                    with self.assertRaisesRegex(runner.ReplayError, "non-finite JSON number"):
                        runner.validate_package(self.sandbox, self.roles)

    def test_malformed_pin_rejected(self):
        self.reject("shared", lambda d: d["generator_sources"][0].update(sha256="not-a-hash"))

    def test_contract_hash_is_checked_before_parsing(self):
        with self.assertRaisesRegex(runner.ReplayError, "changed before parsing"):
            runner.read_json(self.paths["contract"], "0" * 64)


if __name__ == "__main__":
    unittest.main()
