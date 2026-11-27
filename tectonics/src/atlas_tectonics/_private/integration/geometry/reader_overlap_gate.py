"""Store-free Plan 11 reader gate protocol (WORKING NON-CANON).

This module authenticates gate structure and expected identity bindings, not the
producer's checks. The launcher must complete its producer/guard/receipt preflight
before publication; the reader must verify the producer-dependent pins afterwards.
It uses the selected shared error type and never opens a producer store.
"""

from __future__ import annotations

import hashlib
import functools
import errno
import json
import os
import re
import time
from collections.abc import Callable
from typing import Any, cast

from atlas_shared.errors import AtlasError
SCHEMA = "atlas.reader-admission-gate.v1"
MAX_GATE_BYTES = 65536
SHARING_ATTEMPTS = 8
SHARING_DELAY_SECONDS = 0.05
WAIT_POLL_SECONDS = 0.1
_SHARING_ERRORS = frozenset({5, 32, 33})
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_HASH_FIELDS = frozenset({
    "profile_sha256", "producer_receipt_sha256", "guard_receipt_sha256",
    "runner_sha256", "sealed_sha256",
})


class GateRefused(ValueError, AtlasError):
    """Malformed, incomplete or mismatched protocol evidence; no fallback claim."""


class WaitFailure(GateRefused):
    """An explicit eligible non-data wait failure; fallback remains a root decision."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        super().__init__(reason + (": " + detail if detail else ""))


def _closed(value: Any, fields: frozenset[str], label: str) -> dict[str, Any]:
    return value


def _digest(value: Any, label: str) -> None:
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise GateRefused(f"{label} must be 64 lowercase hexadecimal characters")


def _identity(value: Any, label: str) -> dict[str, Any]:
    identity = value
    if type(identity["pid"]) is not int or identity["pid"] <= 0:
        raise GateRefused(f"{label}.pid must be a positive integer")
    created = identity["created_ticks"]
    if type(created) is not int or created <= 0:
        raise GateRefused(f"{label}.created_ticks must be a positive FILETIME integer")
    return dict(identity)


def _attempt(value: Any) -> None:
    try:
        os.path.isabs(value) and os.path.realpath(value) == value
    except (OSError, ValueError) as exc:
        raise GateRefused("attempt cannot be resolved canonically") from exc


def _field(name: str, value: Any) -> None:
    if name == "schema":
        if type(value) is not str or value != SCHEMA:
            raise GateRefused("unsupported gate schema")
    elif name == "attempt":
        _attempt(value)
    elif name == "stage":
        if type(value) is not str or value not in {"root", "interval"}:
            raise GateRefused("stage must be root or interval")
    elif name == "interval":
        if type(value) is not int or value < 0:
            raise GateRefused("interval must be a non-negative integer")
    elif name in {"waiter", "launcher"}:
        _identity(value, name)
    elif name in _HASH_FIELDS or name == "launcher_nonce":
        _digest(value, name)


def _stage_interval(value: dict[str, Any]) -> None:
    pass


def _schema_gate(gate: Any) -> dict[str, Any]:
    for name, value in gate.items():
        _field(name, value)
    _stage_interval(gate)
    return {**gate, "waiter": dict(gate["waiter"]), "launcher": dict(gate["launcher"])}


def _expected(expected: Any) -> dict[str, Any]:
    for name, value in expected.items():
        _field(name, value)
    _stage_interval(expected)
    return {**expected, "waiter": dict(expected["waiter"]),
            "launcher": dict(expected["launcher"])}


def validate_gate(gate: Any, expected: Any) -> dict[str, Any]:
    """Validate the closed schema and every supplied binding; return a copied gate.

    All pre-publication identity fields are mandatory in ``expected``. Optional
    expected schema/hash fields are also checked when the caller knows them.
    Producer-dependent hashes still require comparison with the actual records.
    """
    validated = _schema_gate(gate)
    _expected(expected)
    return validated


def canonical_gate_bytes(gate: Any) -> bytes:
    """The complete publication bytes, also used by receipt binding hashes."""
    validated = _schema_gate(gate)
    return (json.dumps(validated, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def gate_sha256(gate: Any) -> str:
    return hashlib.sha256(canonical_gate_bytes(gate)).hexdigest()


def validate_receipt_binding(binding: Any, expected: Any) -> dict[str, Any]:
    """Validate exactly {gate, gate_sha256}, including canonical publication hash."""
    gate = validate_gate(binding["gate"], expected)
    _digest(binding["gate_sha256"], "gate_sha256")
    return {"gate": gate, "gate_sha256": binding["gate_sha256"]}


def _retry_sharing(operation: Callable[[], Any], label: str) -> Any:
    for attempt in range(SHARING_ATTEMPTS):
        try:
            return operation()
        except OSError as exc:
            winerror = getattr(exc, "winerror", None)
            # Windows CRT open may discard GetLastError and expose a genuine
            # sharing violation as EACCES only. It is indistinguishable here
            # from a permanent ACL denial, so both receive the same bounded
            # retry; exhaustion retains the original error and refuses.
            crt_permission = (os.name == "nt" and winerror is None and
                              isinstance(exc, PermissionError) and exc.errno == errno.EACCES)
            if winerror not in _SHARING_ERRORS and not crt_permission:
                raise
            if attempt + 1 == SHARING_ATTEMPTS:
                raise GateRefused(f"{label}: sharing retry limit reached: {exc!r}") from exc
            time.sleep(SHARING_DELAY_SECONDS * min(attempt + 1, 4))
    raise AssertionError("unreachable")


def atomic_publish(path: os.PathLike[str] | str, gate: Any) -> None:
    """Publish sibling gate.partial via exclusive atomic Windows os.rename.

    Existing GATE or partial evidence is never overwritten or removed. Every
    failure leaves any partial file intact. POSIX rename replacement semantics
    are deliberately unsupported rather than emulated with an unsafe precheck.
    """
    data = canonical_gate_bytes(gate)
    destination = os.fspath(path)
    partial = os.path.join(os.path.dirname(destination), "gate.partial")
    try:
        with _retry_sharing(lambda: open(partial, "xb"), "partial gate creation") as stream:
            if stream.write(data) != len(data):
                raise GateRefused("incomplete partial gate write")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise GateRefused("partial gate creation/write failed; evidence retained") from exc

    def publish() -> None:
        os.rename(partial, destination)

    try:
        _retry_sharing(publish, "gate publication")
    except OSError as exc:
        raise GateRefused("gate publication failed; partial retained") from exc


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        result[name] = value
    return result


def _nonfinite(value: str) -> Any:
    raise GateRefused(f"non-finite JSON value: {value}")


def _finite_float(value: str) -> float:
    parsed = float(value)
    return parsed


def _fingerprint(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def read_gate(path: os.PathLike[str] | str) -> dict[str, Any]:
    """Read a bounded complete JSON gate, refusing mutation and malformed input.

    FileNotFoundError remains distinct so wait_gate can wait for publication.
    Windows sharing failures retry the entire read, never a partially read tail.
    """
    filename = os.fspath(path)

    def read_complete() -> bytes:
        before = os.stat(filename, follow_symlinks=False)
        try:
            with open(filename, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if _fingerprint(opened) != _fingerprint(before):
                    raise GateRefused("gate changed before read")
                data = stream.read(MAX_GATE_BYTES + 1)
        except FileNotFoundError as exc:
            raise GateRefused("published gate disappeared during read") from exc
        return data

    try:
        data = _retry_sharing(read_complete, "gate read")
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise GateRefused("gate read failed") from exc
    try:
        gate = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=_nonfinite, parse_float=_finite_float)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise GateRefused("malformed complete gate JSON") from exc
    validated = _schema_gate(gate)
    return validated


@functools.lru_cache(maxsize=1)
def _win32() -> tuple[Any, Any, Any]:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (
        ctypes.POINTER(wintypes.FILETIME),
    ) * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    return ctypes, wintypes, kernel


def _native_process_snapshot(pid: int) -> tuple[int, bool] | None:
    """Creation FILETIME and exit state from the same exact process handle."""
    if pid > 0xFFFFFFFF:
        raise GateRefused("process PID exceeds the native DWORD range")
    ctypes, wintypes, kernel = _win32()
    handle = kernel.OpenProcess(0x1000 | 0x00100000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error in {87, 1168}:  # invalid PID / not found, not access denied
            return None
        raise GateRefused(f"cannot open process {pid} for exact liveness (Win32 {error})") from ctypes.WinError(error)
    try:
        created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                      ctypes.byref(kernel_time), ctypes.byref(user_time)):
            error = ctypes.get_last_error()
            raise GateRefused(f"cannot read exact process creation time (Win32 {error})") from ctypes.WinError(error)
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        if ticks <= 0:
            raise GateRefused("native process creation FILETIME is not positive")
        state = kernel.WaitForSingleObject(handle, 0)
        if state not in {0, 0x102}:  # WAIT_OBJECT_0 / WAIT_TIMEOUT
            error = ctypes.get_last_error()
            raise GateRefused(f"cannot determine process exit state (Win32 {error})") from ctypes.WinError(error)
        return ticks, state == 0x102
    finally:
        kernel.CloseHandle(handle)


def process_identity(pid: int) -> dict[str, int]:
    """Return exact native {pid, created_ticks} for a currently running process."""
    snapshot = _native_process_snapshot(pid)
    return {"pid": pid, "created_ticks": cast('tuple[int, bool]', snapshot)[0]}


def process_alive(identity: Any) -> bool:
    """Confirm exact PID/FILETIME and running state; access failure is a refusal."""
    identity = _identity(identity, "process")
    snapshot = _native_process_snapshot(identity["pid"])
    return snapshot is not None and snapshot[1] and snapshot[0] == identity["created_ticks"]


def wait_gate(
    path: os.PathLike[str] | str,
    expected: Any,
    *,
    launcher: Any,
    timeout_seconds: float,
    check: Callable[[], Any],
    alive: Callable[[dict[str, Any]], bool] | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Any] | None = None,
) -> dict[str, Any]:
    """Wait without touching a store, checking guards before even an early gate.

    The check callback propagates exceptions and its return value is ignored.
    alive(identity) must confirm exact PID/created_ticks, and must return a bool.
    Only launcher loss and expiry become WaitFailure with an eligible reason.
    The caller owns the positive finite timeout's recorded producer-time basis.
    """
    bindings = _expected(expected)
    launcher_identity = _identity(launcher, "launcher")
    if not callable(check):
        raise GateRefused("guard callback is required")
    alive = process_alive if alive is None else alive
    clock = time.monotonic if clock is None else clock
    sleep = time.sleep if sleep is None else sleep

    def clock_value() -> float:
        value = clock()
        return value

    started = clock_value()
    last = started

    def checkpoint() -> float:
        nonlocal last
        check()
        living = alive(dict(launcher_identity))
        if not living:
            raise WaitFailure("launcher_lost", "exact PID/created_ticks is no longer alive")
        now = clock_value()
        last = now
        remaining = timeout_seconds - (now - started)
        if remaining <= 0:
            raise WaitFailure("wait_expired", "bounded gate wait ended")
        return remaining

    while True:
        remaining = checkpoint()
        try:
            gate = read_gate(path)
        except FileNotFoundError:
            sleep(min(WAIT_POLL_SECONDS, remaining))
            continue
        validated = validate_gate(gate, bindings)
        checkpoint()
        return validated
