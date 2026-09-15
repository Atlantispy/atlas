"""Fail-closed local launch-gate CLI with native-shell-safe option transport."""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import sys
from pathlib import Path

from diadem_safety.common import PathSafetyError, SafetyError
from .gate import GateError, authorize_run, finish_run, prepare_run

MAX_RUN_OPTIONS_BYTES = 12 * 1024
MAX_ENCODED_RUN_OPTIONS_BYTES = 16 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local-only Diadem generator launch gate")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--workspace", type=Path, required=True)
    prepare.add_argument("--task", required=True)
    prepare.add_argument("--database")
    prepare.add_argument("--output-directory")
    options = prepare.add_mutually_exclusive_group()
    options.add_argument("--run-options", help="Legacy raw JSON object")
    options.add_argument("--run-options-base64", help="ASCII base64 of a UTF-8 JSON object")
    authorize = sub.add_parser("authorize")
    authorize.add_argument("--workspace", type=Path, required=True)
    authorize.add_argument("--run-id", required=True)
    authorize.add_argument("--token", required=True)
    finish = sub.add_parser("finish")
    finish.add_argument("--workspace", type=Path, required=True)
    finish.add_argument("--run-id", required=True)
    finish.add_argument("--token", required=True)
    finish.add_argument("--state", choices=["SUCCEEDED", "FAILED", "ABORTED"], required=True)
    finish.add_argument("--exit-code", type=int, required=True)
    return parser


def _run_options(args: argparse.Namespace) -> dict:
    if args.run_options_base64 is not None:
        encoded = args.run_options_base64
        if len(encoded) > MAX_ENCODED_RUN_OPTIONS_BYTES:
            raise ValueError("Encoded run options exceed the 16 KiB limit")
        try:
            raw = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeError, binascii.Error) as exc:
            raise ValueError("Run options are not valid ASCII base64") from exc
    else:
        value = args.run_options if args.run_options is not None else "{}"
        if len(value) > MAX_RUN_OPTIONS_BYTES:
            raise ValueError("Run options exceed the 12 KiB limit")
        raw = value.encode("utf-8")
    if len(raw) > MAX_RUN_OPTIONS_BYTES:
        raise ValueError("Decoded run options exceed the 12 KiB limit")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Run options must be bounded UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Run options must decode to a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_run(workspace_root=args.workspace, task=args.task, database=args.database, output_directory=args.output_directory, run_options=_run_options(args))
        elif args.command == "authorize":
            result = authorize_run(workspace_root=args.workspace, run_id=args.run_id, token=args.token)
        else:
            result = finish_run(workspace_root=args.workspace, run_id=args.run_id, token=args.token, state=args.state, exit_code=args.exit_code)
    except (GateError, SafetyError, PathSafetyError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__, "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **result}, separators=(",", ":")))
    return 0
