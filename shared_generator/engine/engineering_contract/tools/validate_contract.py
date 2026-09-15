from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from diadem_contract.validation import validate_bundle, validate_file  # noqa: E402


def main() -> int:
    preservation = validate_file(ROOT / "contract/preservation_matrix.v1.json").as_dict()
    evidence = validate_bundle(ROOT / "examples/evidence")
    report = {
        "schema": "diadem.engineering.contract-self-validation.v1",
        "preservation_matrix": preservation,
        "evidence_examples": evidence,
        "passed": preservation["passed"] and evidence["passed"],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
