"""Command-line validator and identity inspector."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters import fingerprint_lineage, fingerprint_manifest
from .ids import StructuredId
from .validation import validate_bundle, validate_file


def main() -> int:
    parser = argparse.ArgumentParser(prog="diadem-contract")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("path", type=Path)
    bundle = commands.add_parser("validate-bundle")
    bundle.add_argument("directory", type=Path)
    decode = commands.add_parser("decode-id")
    decode.add_argument("identifier")
    fingerprint = commands.add_parser("fingerprint")
    fingerprint.add_argument("kind", choices=("manifest", "lineage"))
    fingerprint.add_argument("path", type=Path)
    args = parser.parse_args()

    if args.command == "validate":
        report = validate_file(args.path).as_dict()
    elif args.command == "validate-bundle":
        report = validate_bundle(args.directory)
    elif args.command == "decode-id":
        identifier = StructuredId.decode(args.identifier)
        report = {"kind": identifier.kind, "version": identifier.version, "payload": dict(identifier.payload)}
    else:
        value = json.loads(args.path.read_text(encoding="utf-8"))
        observed = fingerprint_manifest(value) if args.kind == "manifest" else fingerprint_lineage(value)
        report = {"fingerprint": str(observed)}
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
