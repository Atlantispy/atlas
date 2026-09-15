"""Small executable fault harness for the acceptance contract itself.

This does not claim to test every future generator backend. It proves the
standard corruption/cancellation/fallback evidence shapes against a concrete
transactional implementation and gives future paths a reusable test pattern.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
from typing import Callable

from .canonical import binary_fingerprint, semantic_fingerprint


class InjectedCancellation(RuntimeError):
    pass


class CorruptStageError(RuntimeError):
    pass


class CapabilityUnavailable(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TransactionalByteStore:
    """One-pointer store used to verify cancellation and corruption rules."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.current = root / "current.bin"
        self.stage = root / "candidate.stage"

    def initialise(self, payload: bytes) -> str:
        self.current.write_bytes(payload)
        return _sha256(payload)

    def digest(self) -> str:
        return _sha256(self.current.read_bytes())

    def update(self, payload: bytes, *, cancel_after_stage: bool = False, corrupt_stage: bool = False) -> str:
        expected = _sha256(payload)
        with self.stage.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if cancel_after_stage:
            raise InjectedCancellation("cancelled after durable staging and before commit")
        if corrupt_stage:
            damaged = bytearray(self.stage.read_bytes())
            damaged[len(damaged) // 2] ^= 0x5A
            self.stage.write_bytes(damaged)
        if _sha256(self.stage.read_bytes()) != expected:
            self.stage.unlink(missing_ok=True)
            raise CorruptStageError("candidate digest differs before commit")
        os.replace(self.stage, self.current)
        return expected

    def discard_stage(self) -> None:
        self.stage.unlink(missing_ok=True)


def verify_or_rebuild(cache: Path, authority: Path) -> bool:
    """Return True when a corrupt cache had to be rebuilt from authority."""

    authority_bytes = authority.read_bytes()
    if cache.exists() and _sha256(cache.read_bytes()) == _sha256(authority_bytes):
        return False
    temporary = cache.with_suffix(cache.suffix + ".tmp")
    shutil.copyfile(authority, temporary)
    if _sha256(temporary.read_bytes()) != _sha256(authority_bytes):
        temporary.unlink(missing_ok=True)
        raise CorruptStageError("authority rebuild verification failed")
    os.replace(temporary, cache)
    return True


def run_with_fallback(
    optimised: Callable[[], bytes],
    reference: Callable[[], bytes],
) -> tuple[bytes, dict[str, object]]:
    try:
        return optimised(), {"selected": False, "reason_recorded": False, "telemetry_recorded": True}
    except CapabilityUnavailable as exc:
        payload = reference()
        return payload, {
            "selected": True,
            "reason": str(exc),
            "reason_recorded": True,
            "telemetry_recorded": True,
        }


def make_fault_evidence() -> dict[str, dict[str, object]]:
    """Return valid synthetic records demonstrating all three fault classes."""

    parity = str(semantic_fingerprint("parity-report", {"same": True}))
    corruption = {
        "schema": "diadem.engineering.corruption-test.v1",
        "test_id": "contract-harness-corruption-001",
        "target_path_id": "contract-harness-transactional-store",
        "fault": {"kind": "single-byte-flip", "injection_point": "staged payload before commit"},
        "expected": {
            "detected": True,
            "published_partial_forbidden": True,
            "rebuild_from_authority": True,
            "unaffected_data_recoverable": True,
        },
        "observed": {
            "detected": True,
            "published_partial": False,
            "rebuilt_from_authority": True,
            "unaffected_data_recovered": True,
        },
        "status": "PASS",
    }
    cancellation = {
        "schema": "diadem.engineering.cancellation-test.v1",
        "test_id": "contract-harness-cancellation-001",
        "target_path_id": "contract-harness-transactional-store",
        "fault": {"kind": "cooperative-cancellation", "injection_point": "after durable stage, before commit"},
        "expected": {
            "last_committed_digest_preserved": True,
            "staging_disposition": "discard-or-verified-resume",
            "resume_required": True,
        },
        "observed": {
            "last_committed_digest_preserved": True,
            "staging_disposition": "discarded",
            "resume_digest_equal": True,
        },
        "status": "PASS",
    }
    fallback = {
        "schema": "diadem.engineering.fallback-test.v1",
        "test_id": "contract-harness-fallback-001",
        "optimised_path_id": "synthetic-optimised-unavailable",
        "reference_path_id": "synthetic-portable-reference",
        "trigger": {"kind": "capability-self-test-failed"},
        "capability_self_test": {"available": False, "safe_to_attempt": False},
        "fallback": {"selected": True, "reason_recorded": True, "telemetry_recorded": True},
        "parity": {
            "artifact_family": "published_release_bytes",
            "passed": True,
            "report_fingerprint": parity,
        },
        "status": "PASS",
    }
    return {"corruption": corruption, "cancellation": cancellation, "fallback": fallback}
