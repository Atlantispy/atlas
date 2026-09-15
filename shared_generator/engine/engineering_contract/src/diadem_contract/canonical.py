"""Canonical semantic encoding and type-separated content fingerprints."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
import unicodedata
from typing import Any, Iterable, Mapping


CANONICALIZATION_VERSION = "diadem-canonical-json-v1"
FINGERPRINT_VERSION = 1
FINGERPRINT_ALGORITHM = "sha256"
_TYPE_TAG = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented by the canonical format."""


def _normalise_string(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _number_text(value: int | float | Decimal) -> str:
    if isinstance(value, bool):
        raise CanonicalizationError("booleans are not numbers in this encoder")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError("NaN and infinity are forbidden")
        value = Decimal(str(value))
    if not isinstance(value, Decimal):
        raise CanonicalizationError(f"unsupported number type: {type(value).__name__}")
    if not value.is_finite():
        raise CanonicalizationError("NaN and infinity are forbidden")
    if value == 0:
        return "0"
    try:
        text = format(value.normalize(), "f")
    except InvalidOperation as exc:
        raise CanonicalizationError("invalid decimal") from exc
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _encode(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float, Decimal)):
        return _number_text(value)
    if isinstance(value, str):
        return json.dumps(_normalise_string(value), ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    if isinstance(value, Mapping):
        normalised: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError("object keys must be strings")
            normalised_key = _normalise_string(key)
            if normalised_key in normalised:
                raise CanonicalizationError(
                    f"key collision after Unicode NFC normalisation: {normalised_key!r}"
                )
            normalised[normalised_key] = item
        return "{" + ",".join(
            json.dumps(key, ensure_ascii=False, separators=(",", ":")) + ":" + _encode(normalised[key])
            for key in sorted(normalised)
        ) + "}"
    raise CanonicalizationError(f"unsupported value type: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 bytes for supported JSON-like data."""

    return _encode(value).encode("utf-8")


def project_semantic_value(
    value: Any,
    *,
    omit_fields: Iterable[str] = (),
    unordered_record_lists: Iterable[str] = (),
) -> Any:
    """Project transport metadata out of a value under an explicit profile.

    Omission is opt-in. Core canonicalisation never guesses that a timestamp,
    path, or codec is irrelevant. Known record-list keys may be sorted by their
    own canonical bytes when the profile declares their order non-semantic.
    """

    omitted = set(omit_fields)
    unordered = set(unordered_record_lists)

    def walk(item: Any, parent_key: str | None = None) -> Any:
        if isinstance(item, Mapping):
            return {
                key: walk(child, key)
                for key, child in item.items()
                if key not in omitted
            }
        if isinstance(item, (list, tuple)):
            projected = [walk(child, parent_key) for child in item]
            if parent_key in unordered:
                projected.sort(key=canonical_json_bytes)
            return projected
        return item

    return walk(value)


@dataclass(frozen=True)
class SemanticFingerprint:
    """A non-reversible, domain-separated semantic content fingerprint."""

    type_tag: str
    digest: str
    version: int = FINGERPRINT_VERSION
    algorithm: str = FINGERPRINT_ALGORITHM

    def __post_init__(self) -> None:
        if not _TYPE_TAG.fullmatch(self.type_tag):
            raise ValueError(f"invalid fingerprint type tag: {self.type_tag!r}")
        if self.version != FINGERPRINT_VERSION:
            raise ValueError(f"unsupported fingerprint version: {self.version}")
        if self.algorithm != FINGERPRINT_ALGORITHM:
            raise ValueError(f"unsupported fingerprint algorithm: {self.algorithm}")
        if not _HEX_64.fullmatch(self.digest):
            raise ValueError("fingerprint digest must be 64 lowercase hexadecimal characters")

    def __str__(self) -> str:
        return f"dgh:v{self.version}:{self.type_tag}:{self.algorithm}:{self.digest}"

    @classmethod
    def parse(cls, encoded: str) -> "SemanticFingerprint":
        parts = encoded.split(":")
        if len(parts) != 5 or parts[0] != "dgh" or not parts[1].startswith("v"):
            raise ValueError("invalid semantic fingerprint")
        try:
            version = int(parts[1][1:])
        except ValueError as exc:
            raise ValueError("invalid fingerprint version") from exc
        return cls(type_tag=parts[2], algorithm=parts[3], digest=parts[4], version=version)


def semantic_fingerprint(
    type_tag: str,
    value: Any,
    *,
    omit_fields: Iterable[str] = (),
    unordered_record_lists: Iterable[str] = (),
) -> SemanticFingerprint:
    """Fingerprint semantic data with explicit type/domain separation."""

    if not _TYPE_TAG.fullmatch(type_tag):
        raise ValueError(f"invalid fingerprint type tag: {type_tag!r}")
    projected = project_semantic_value(
        value,
        omit_fields=omit_fields,
        unordered_record_lists=unordered_record_lists,
    )
    domain = (
        b"DIADEM\x00SEMANTIC-FINGERPRINT\x00"
        + f"v{FINGERPRINT_VERSION}\x00{type_tag}\x00{CANONICALIZATION_VERSION}\x00".encode("ascii")
    )
    digest = hashlib.sha256(domain + canonical_json_bytes(projected)).hexdigest()
    return SemanticFingerprint(type_tag=type_tag, digest=digest)


def binary_fingerprint(type_tag: str, payload: bytes, *, semantic_metadata: Any = None) -> SemanticFingerprint:
    """Fingerprint authoritative binary semantics with optional canonical metadata."""

    if not _TYPE_TAG.fullmatch(type_tag):
        raise ValueError(f"invalid fingerprint type tag: {type_tag!r}")
    metadata = canonical_json_bytes(semantic_metadata if semantic_metadata is not None else {})
    domain = (
        b"DIADEM\x00BINARY-SEMANTIC-FINGERPRINT\x00"
        + f"v{FINGERPRINT_VERSION}\x00{type_tag}\x00".encode("ascii")
    )
    framed = len(metadata).to_bytes(8, "big") + metadata + len(payload).to_bytes(8, "big") + payload
    return SemanticFingerprint(type_tag=type_tag, digest=hashlib.sha256(domain + framed).hexdigest())
