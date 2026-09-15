"""Reversible, typed and versioned Diadem structured identifiers."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import re
import uuid
from typing import Any, Mapping

from .canonical import canonical_json_bytes


STRUCTURED_ID_VERSION = 1
_KIND = re.compile(r"^(layer|resolution|tile|feature|run)$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _token(name: str, value: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError(f"{name} must be a non-empty portable token")
    return value


def _plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class StructuredId:
    kind: str
    payload: Mapping[str, Any]
    version: int = STRUCTURED_ID_VERSION

    def __post_init__(self) -> None:
        if self.version != STRUCTURED_ID_VERSION:
            raise ValueError(f"unsupported structured ID version: {self.version}")
        if not _KIND.fullmatch(self.kind):
            raise ValueError(f"unsupported structured ID kind: {self.kind!r}")
        canonical_json_bytes(self.payload)

    def encode(self) -> str:
        raw = canonical_json_bytes(dict(self.payload))
        payload = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        return f"dgid:v{self.version}:{self.kind}:{payload}"

    def __str__(self) -> str:
        return self.encode()

    @classmethod
    def decode(cls, encoded: str) -> "StructuredId":
        parts = encoded.split(":", 3)
        if len(parts) != 4 or parts[0] != "dgid" or not parts[1].startswith("v"):
            raise ValueError("invalid structured ID")
        try:
            version = int(parts[1][1:])
        except ValueError as exc:
            raise ValueError("invalid structured ID version") from exc
        kind = parts[2]
        padding = "=" * (-len(parts[3]) % 4)
        try:
            raw = base64.b64decode(parts[3] + padding, altchars=b"-_", validate=True)
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid structured ID payload") from exc
        if not isinstance(payload, dict):
            raise ValueError("structured ID payload must be an object")
        result = cls(kind=kind, payload=payload, version=version)
        if result.encode() != encoded:
            raise ValueError("structured ID is not in canonical form")
        validate_payload(result)
        return result


def layer_id(namespace: str, name: str) -> str:
    return StructuredId("layer", {"name": _token("name", name), "namespace": _token("namespace", namespace)}).encode()


def resolution_id(x_mm: int, y_mm: int | None = None, vertical_mm: int | None = None) -> str:
    y_mm = x_mm if y_mm is None else y_mm
    if not _plain_int(x_mm) or not _plain_int(y_mm) or x_mm <= 0 or y_mm <= 0:
        raise ValueError("horizontal resolutions must be positive integer millimetres")
    if vertical_mm is not None and (not _plain_int(vertical_mm) or vertical_mm <= 0):
        raise ValueError("vertical resolution must be positive integer millimetres")
    return StructuredId(
        "resolution",
        {"unit": "mm", "vertical": vertical_mm, "x": x_mm, "y": y_mm},
    ).encode()


def tile_id(layer: str, resolution: str, x: int, y: int, *, level: int = 0) -> str:
    layer_value = StructuredId.decode(layer)
    resolution_value = StructuredId.decode(resolution)
    if layer_value.kind != "layer" or resolution_value.kind != "resolution":
        raise ValueError("tile requires a layer ID and a resolution ID")
    if not all(_plain_int(value) for value in (x, y, level)) or level < 0:
        raise ValueError("tile x/y/level must be integers and level must be non-negative")
    return StructuredId(
        "tile",
        {"layer": layer, "level": level, "resolution": resolution, "x": x, "y": y},
    ).encode()


def feature_id(namespace: str, collection: str, local_id: str) -> str:
    return StructuredId(
        "feature",
        {
            "collection": _token("collection", collection),
            "local_id": _token("local_id", local_id),
            "namespace": _token("namespace", namespace),
        },
    ).encode()


def run_id(project: str, run_uuid: str | uuid.UUID, *, attempt: int = 1) -> str:
    if not _plain_int(attempt) or attempt < 1:
        raise ValueError("attempt must be a positive integer")
    parsed = uuid.UUID(str(run_uuid))
    return StructuredId(
        "run",
        {"attempt": attempt, "project": _token("project", project), "uuid": str(parsed)},
    ).encode()


def validate_payload(identifier: StructuredId) -> None:
    """Validate kind-specific payload shape and nested identifier types."""

    payload = dict(identifier.payload)
    expected = {
        "layer": {"namespace", "name"},
        "resolution": {"unit", "x", "y", "vertical"},
        "tile": {"layer", "resolution", "x", "y", "level"},
        "feature": {"namespace", "collection", "local_id"},
        "run": {"project", "uuid", "attempt"},
    }[identifier.kind]
    if set(payload) != expected:
        raise ValueError(f"{identifier.kind} ID has incorrect payload fields")
    if identifier.kind == "layer":
        _token("namespace", payload["namespace"])
        _token("name", payload["name"])
    elif identifier.kind == "resolution":
        if payload["unit"] != "mm" or not _plain_int(payload["x"]) or not _plain_int(payload["y"]):
            raise ValueError("invalid resolution payload")
        if payload["x"] <= 0 or payload["y"] <= 0:
            raise ValueError("resolution values must be positive")
        if payload["vertical"] is not None and (
            not _plain_int(payload["vertical"]) or payload["vertical"] <= 0
        ):
            raise ValueError("invalid vertical resolution")
    elif identifier.kind == "tile":
        if StructuredId.decode(payload["layer"]).kind != "layer":
            raise ValueError("tile layer reference is not a layer ID")
        if StructuredId.decode(payload["resolution"]).kind != "resolution":
            raise ValueError("tile resolution reference is not a resolution ID")
        if not all(_plain_int(payload[key]) for key in ("x", "y", "level")) or payload["level"] < 0:
            raise ValueError("invalid tile coordinates")
    elif identifier.kind == "feature":
        for key in expected:
            _token(key, payload[key])
    elif identifier.kind == "run":
        _token("project", payload["project"])
        uuid.UUID(payload["uuid"])
        if not _plain_int(payload["attempt"]) or payload["attempt"] < 1:
            raise ValueError("invalid run attempt")
