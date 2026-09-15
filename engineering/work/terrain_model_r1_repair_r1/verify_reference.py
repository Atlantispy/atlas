"""Verify bounded numerical building blocks; never run a Diadem terrain job."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import io
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import unittest

from contract import file_pin, load_json
from intake import checkpoint, collect, write_checkpoint

TEST_INVENTORY_PATH=Path(__file__).with_name("TEST_INVENTORY.json")
TEST_INVENTORY_SHA256="644da60d50561c5b64ca5b4699d64e7ca757d9ed66fdcdffce7aa97f9b345b58"


def test_ids(suite):
    ids=[]
    for test in suite:
        if isinstance(test,unittest.TestSuite): ids.extend(test_ids(test))
        else: ids.append(test.id())
    return ids


def expected_test_inventory():
    raw=TEST_INVENTORY_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=TEST_INVENTORY_SHA256:
        raise ValueError("reviewed test inventory identity changed")
    value=json.loads(raw)
    if (type(value) is not list or not value or any(type(v) is not str or not v for v in value)
            or len(set(value))!=len(value)):
        raise ValueError("invalid reviewed test inventory")
    return sorted(value)


def require_test_success(result,inventory):
    if sorted(inventory)!=expected_test_inventory() or len(set(inventory))!=len(inventory):
        raise ValueError("reviewed test inventory incomplete or changed")
    if (not result.wasSuccessful() or result.testsRun!=len(inventory) or result.skipped
            or result.expectedFailures or result.unexpectedSuccesses
            or not inventory):
        raise ValueError("Numerical/intake tests failed, skipped or incomplete; no verification receipt written.")


def canonical_bytes(value):
    """Finite, type- and signed-zero-sensitive JSON for logical result parity."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def implementation_pins(here):
    return [file_pin(path) for path in sorted(Path(here).iterdir())
            if path.suffix in {".py", ".json", ".md"}]


def assert_unchanged(workspace, sources, here, code, products=()):
    if collect(workspace) != sources or implementation_pins(here) != code:
        raise ValueError("Source/implementation changed during verification.")
    for pin in products:
        if file_pin(pin["path"]) != pin:
            raise ValueError("Verification artifact changed during receipt verification.")


def write_new_json(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + "\n")
    if canonical_bytes(load_json(path)) != canonical_bytes(value):
        raise ValueError(f"Readback failed: {path}")


def verify(workspace, output):
    started = time.perf_counter()
    here = Path(__file__).resolve().parent
    code_before = implementation_pins(here)
    sources_before = collect(workspace)
    transcript = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(here), pattern="test_*.py")
    inventory=test_ids(suite)
    if sorted(inventory)!=expected_test_inventory():
        raise ValueError("reviewed test inventory incomplete or changed before execution")
    result = unittest.TextTestRunner(stream=transcript, verbosity=2).run(suite)
    try:
        require_test_success(result,inventory)
    except ValueError:
        print(transcript.getvalue())
        raise
    from hillslope_reference import run_benchmark as hillslope
    from space_reference import run_benchmark as channel
    numerical = {"hillslope": hillslope(), "channel": channel()}
    if numerical["hillslope"].get("status") != "PASS_NUMERICAL_REFERENCE_ONLY" or numerical["channel"].get("status") != "PASS_ANALYTICAL_REFERENCE":
        raise ValueError("A numerical building block did not pass its frozen contract.")
    if canonical_bytes({"hillslope": hillslope(), "channel": channel()}) != canonical_bytes(numerical):
        raise ValueError("Repeated numerical building-block results changed.")
    recipe, intake = checkpoint(workspace)
    assert_unchanged(workspace, sources_before, here, code_before)
    report = {
        "schema": "diadem.terrain.numerical-building-block-verification.v1",
        "status": "PASS_BOUNDED_NUMERICAL_BUILDING_BLOCKS_NOT_TERRAIN_MODEL",
        "utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {"python": sys.version, "platform": platform.platform(), "dependencies": "stdlib only"},
        "tests": {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                  "skipped": len(result.skipped), "inventory":inventory,"log": transcript.getvalue()},
        "numerical": numerical, "repeat_exact": True,
        "repeat_comparison": "canonical finite JSON bytes; type and signed-zero sensitive",
        "source_and_implementation_pins": code_before,
        "original_design_and_integration_inputs_unchanged": True,
        "synthetic_numerical_profiles_and_rates_computed": True,
        "diadem_terrain_generated": False, "normal_workflow_stage_registered": False,
        "whole_model_functional_reference": "INCOMPLETE",
        "physical_validation": "NOT_RUN", "optimisation": "NOT_RUN",
        "production_resource_readiness": "NOT_ESTABLISHED", "production_authorised": False,
        "adoption": "NOT_RUN", "coordinator_feedback": "NOT_SENT_MODEL_WORK_NOT_FINISHED",
        "verification_elapsed_seconds_not_a_speedup_benchmark": time.perf_counter() - started,
    }
    write_checkpoint(output, recipe, intake)
    output = Path(output)
    write_new_json(output / "NUMERICAL_VERIFICATION.json", report)
    products = [file_pin(output / name) for name in
                ("RECIPE_UNBOUND.json", "INTAKE_REPORT.json", "INTAKE_RECEIPT.json", "NUMERICAL_VERIFICATION.json")]
    assert_unchanged(workspace, sources_before, here, code_before, products)
    write_new_json(output / "VERIFICATION_RECEIPT.json", {
        "schema": "diadem.terrain.reference-verification-receipt.v1", "products": products,
        "scope": "Bounded numerical components and engineering intake only",
        "model_complete": False, "production_authorised": False})
    assert_unchanged(workspace, sources_before, here, code_before, products)
    return {"status": report["status"], "tests": result.testsRun, "skipped": len(result.skipped),
            "repeat_exact": True, "diadem_terrain_generated": False, "output": str(output)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(verify(args.workspace, args.output), indent=2))


if __name__ == "__main__":
    main()
