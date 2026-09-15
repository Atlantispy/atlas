"""Produce a bounded, source-verified design-intake checkpoint, never terrain."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from contract import PACKAGE_SHA256, file_pin, load_json, validate_recipe, verify_package
from template import make_recipe

INTEGRATION_PINS = {
    "launcher": ("06_Generator_System/Run-Generator.ps1", "7f3117e16cda036f22be72dcc2c082a845456b8c7bcc858d456853b310724dd5"),
    "engineering_contract": ("06_Generator_System/engine/GENERATOR_ENGINEERING_ACCEPTANCE_CONTRACT.md", "1332457736beec56f3520ab9e94aacdb5069380a55222283211b9fcc85a3cadb"),
    "refinement_method": ("06_Generator_System/engine/STAGE6C_ADAPTIVE_10M_REFINEMENT_WORKING_METHOD.md", "e0c0b5b6ee975744d4e2459d016047ac4cafc8416939fcf525fd5dfec3c37f97"),
    "terrain_reader": ("06_Generator_System/engine/stage6c_terrain_authority.py", "f7231dfd437c568f2bbf8608d60d0c33a291e95a224093bc04b5c772e80b5192"),
    "catalogue": ("06_Generator_System/generator_source_catalogue.json", "dc9c12e204b8c9050b0b8ef6ae4771db7f65d532f5a8582a4f4c05e0b2bb01b4"),
    "c1_approval": ("01_Current_Drive_Snapshot/Geography/Reproducibility & Provenance — REVIEW ONLY/30 Native-Resolution Parent Checkpoints/90 Large Parents Indexed Only/Diadem_C1_100m_Climate_Approval_Record_2026-08-03.json", "38d22c85713f3475494fa76d97446e783cc1e77dcb8ee636ad6241eedbbe5a32"),
    "active_terrain_manifest": ("06_Generator_System/working_authorities/effective_terrain_100m/AUTHORITY_MANIFEST.json", "4455a544011dddb13b1666a9fd4a51135593b7d2eab2949a591c0816893d12ab"),
}
PACKAGE_RELATIVE = "02_Working_Files/Geography/Generator_Terrain_Requirements/R1/PACKAGE_MANIFEST.json"


def collect(workspace):
    workspace = Path(workspace)
    package = verify_package(workspace / PACKAGE_RELATIVE)
    if package["status"] != "PASS":
        raise ValueError(package["issues"])
    prior_report = Path(__file__).resolve().parents[2] / "outputs/mountain-whole-r1/performance-r1/OPTIMISATION_REPORT.md"
    prior_pin = file_pin(prior_report)
    if prior_pin["sha256"] != "eafea380db61ac3ecb675861b2f5ef565f93356271a977dc5969dd2065890c32":
        raise ValueError("Prior optimisation completion evidence changed; Gate A cannot be inferred from idle state.")
    package["prior_optimisation_completion"] = prior_pin
    sources = []
    for index, pin in enumerate(package["verified"]):
        sources.append({"id": f"requirements_{index:02d}", **pin, "owner": "Physical/Water/Climate",
                        "source_status": "WORKING NON-CANON", "role": "REQUIREMENTS_NOT_CALIBRATION"})
    integration = []
    for identifier, (relative, expected) in INTEGRATION_PINS.items():
        pin = file_pin(workspace / relative)
        if pin["sha256"] != expected:
            raise ValueError(f"Pinned integration input changed: {identifier}; inspect drift, do not silently repin.")
        integration.append({"id": identifier, **pin, "design_pin_match": True})
        sources.append({"id": identifier, **pin, "owner": "Climate" if identifier == "c1_approval" else "Engineering",
                        "source_status": "APPROVED_C1_R1_REFERENCE_CLIMATE" if identifier == "c1_approval" else "EXISTING_CONTRACT_OR_IMPLEMENTATION_INSPECTION",
                        "role": "ORIGINAL_BINDING_ONLY" if identifier == "c1_approval" else "PRESERVE_AND_REUSE_WHERE_COMPATIBLE"})
    return package, integration, sources


def checkpoint(workspace, recipe_path=None):
    package, integration, sources = collect(workspace)
    recipe = make_recipe(sources) if recipe_path is None else load_json(recipe_path)
    validation = validate_recipe(recipe)
    # Input recipes are linted only. Arbitrary listed source files are not opened
    # and a claimed metadata PASS never changes gate B or invokes a producer.
    report = {"schema": "diadem.terrain.design-intake-report.v1", "package_sha256": PACKAGE_SHA256,
              "status": "INTAKE_COMPLETED_MODEL_NOT_IMPLEMENTED", "package": package,
              "integration_inputs": integration, "validation": validation,
              "gates": {"A": "PASS_SCOPED_PRIOR_OPTIMISATION", "B": "INCOMPLETE", "C": "NOT_RUN",
                        "D": "NOT_RUN", "E": "NOT_RUN", "F": "NOT_RUN"},
              "model_implemented": False, "production_ready": False, "terrain_generated": False,
              "runtime_registered": False, "performance_measurements": None,
              "recipe_source_verification": "INSPECTION_SOURCES_VERIFIED" if recipe_path is None else "NOT_VERIFIED_EXTERNAL_RECIPE_METADATA_ONLY"}
    if collect(workspace) != (package, integration, sources):
        raise ValueError("Inputs changed during intake.")
    return recipe, report


def write_checkpoint(output, recipe, report):
    output = Path(output).absolute()
    allowed = Path(__file__).resolve().parents[2] / "outputs" / "terrain-model-r1"
    if not output.resolve().is_relative_to(allowed.resolve()) or output.resolve() == allowed.resolve():
        raise ValueError("Output must be a new child of this task's outputs/terrain-model-r1.")
    # Resolve existing ancestors before creation; no redirection outside the scope.
    for parent in (output, *output.parents):
        if parent.exists() and (parent.is_symlink() or getattr(parent.stat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("Linked output paths are not allowed.")
    output.mkdir(parents=True, exist_ok=False)
    products = []
    for name, data in (("RECIPE_UNBOUND.json", recipe), ("INTAKE_REPORT.json", report)):
        with (output / name).open("x", encoding="utf-8", newline="\n") as target:
            target.write(json.dumps(data, indent=2, allow_nan=False) + "\n")
        products.append(file_pin(output / name))
    for product in products:
        if file_pin(product["path"]) != product:
            raise ValueError("Intake product changed before receipt commit.")
    receipt = {"schema": "diadem.terrain.intake-receipt.v1", "products": products,
               "terrain_generated": False, "authority_changed": False,
               "note": "Intake artifact receipt only; not a terrain checkpoint or production approval."}
    with (output / "INTAKE_RECEIPT.json").open("x", encoding="utf-8", newline="\n") as target:
        target.write(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    if load_json(output / "INTAKE_RECEIPT.json") != receipt:
        raise ValueError("Intake receipt readback failed.")
    for product in products:
        if file_pin(product["path"]) != product:
            raise ValueError("Intake product changed during receipt readback.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--recipe", type=Path, help="Optional metadata-only recipe lint; never executes the recipe.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    recipe, report = checkpoint(args.workspace, args.recipe)
    if args.output:
        write_checkpoint(args.output, recipe, report)
    print(json.dumps({"status": report["status"], "package_files_verified": len(report["package"]["verified"]),
                      "integration_pins_verified": len(report["integration_inputs"]),
                      "binding_validation": report["validation"]["binding_validation"],
                      "binding_issues": len(report["validation"]["issues"]), "gates": report["gates"],
                      "terrain_generated": False, "output": str(args.output) if args.output else None}, indent=2))
    return 2  # Expected non-ready status, not an execution failure.


if __name__ == "__main__":
    raise SystemExit(main())
