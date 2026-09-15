"""Recovery-safe content cache and independent-Zstd-frame tile transport.

This is an offline geospatial analogue of a reconnect-safe viewer cache:

* immutable SHA-256 addressed chunks persist across runs;
* every FULL or PATCH payload is a separate Zstd frame;
* ordered batches are written to a temporary segment, fsynced, then renamed;
* REF packets reuse an existing chunk, and XOR PATCH packets verify both base
  and reconstructed target hashes;
* a damaged frame does not prevent later independent frames being recovered;
* SQLite access metadata supports incremental writes and bounded LRU retention.

Viewer traffic/idle policy is represented separately from compute/RAM caching;
the tile generator itself performs no network activity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
from enum import Enum
from hashlib import sha256
import json
from io import BytesIO
import os
from pathlib import Path
import sqlite3
import struct
import sys
import threading
import time
import tarfile
from typing import Any, Iterable, Literal, Mapping
from uuid import uuid4
import zipfile

import numpy as np

try:
    import zstandard as zstd
except ModuleNotFoundError:  # local isolated dependency supplied with Stage 6C
    dependency_dir = Path(__file__).resolve().parent.parent / "generator_deps"
    if dependency_dir.is_dir():
        sys.path.insert(0, str(dependency_dir))
    import zstandard as zstd

from .engine import EvidenceTile, canonical_hash, canonical_json


OBJECT_MAGIC = b"D10OBJ1\0"
SEGMENT_MAGIC = b"D10SEG1\0"
UINT32 = struct.Struct("<I")
PacketKind = Literal["full", "ref", "patch"]


class CacheCorruptionError(IOError):
    pass


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the temporary basename short.  Cache objects already use a 64-char
    # content hash; repeating that name in the temporary file can cross the
    # traditional Windows 260-character path boundary even when the committed
    # object itself is valid.
    temporary = path.with_name(f".{uuid4().hex}.tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


@dataclass(frozen=True)
class CacheEntry:
    content_hash: str
    raw_size: int
    stored_size: int
    last_access_ns: int
    pinned: bool


class ContentAddressedCache:
    """Persistent compressed chunks with corruption quarantine and LRU bounds."""

    def __init__(self, root: str | Path, compression_level: int = 7) -> None:
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.quarantine = self.root / "quarantine"
        self.db_path = self.root / "cache.sqlite3"
        self.compressor = zstd.ZstdCompressor(level=compression_level, write_checksum=True)
        self.decompressor = zstd.ZstdDecompressor()
        self.root.mkdir(parents=True, exist_ok=True)
        self.objects.mkdir(exist_ok=True)
        self.quarantine.mkdir(exist_ok=True)
        self._initialize_index()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize_index(self) -> None:
        try:
            with self._connection() as connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS chunks (
                    content_hash TEXT PRIMARY KEY,
                    raw_size INTEGER NOT NULL,
                    stored_size INTEGER NOT NULL,
                    last_access_ns INTEGER NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0
                    )"""
                )
        except sqlite3.DatabaseError:
            damaged = self.db_path.with_name(f"cache.corrupt.{time.time_ns()}.sqlite3")
            if self.db_path.exists():
                self.db_path.replace(damaged)
            self._initialize_index()
            self.rebuild_index()

    def object_path(self, content_hash: str) -> Path:
        if len(content_hash) != 64 or any(char not in "0123456789abcdef" for char in content_hash):
            raise ValueError("Expected a lower-case SHA-256 hash")
        return self.objects / content_hash[:2] / f"{content_hash}.zst"

    def _pack_object(self, raw: bytes, content_hash: str) -> bytes:
        frame = self.compressor.compress(raw)
        header = canonical_json(
            {
                "content_hash": content_hash,
                "raw_size": len(raw),
                "frame_size": len(frame),
                "frame_sha256": sha256(frame).hexdigest(),
                "codec": "zstd-independent-frame",
            }
        )
        return OBJECT_MAGIC + UINT32.pack(len(header)) + header + frame

    def _unpack_object(self, data: bytes, expected_hash: str) -> bytes:
        if not data.startswith(OBJECT_MAGIC) or len(data) < len(OBJECT_MAGIC) + UINT32.size:
            raise CacheCorruptionError("Invalid cache-object header")
        header_length = UINT32.unpack_from(data, len(OBJECT_MAGIC))[0]
        start = len(OBJECT_MAGIC) + UINT32.size
        end = start + header_length
        if not header_length or end >= len(data):
            raise CacheCorruptionError("Invalid cache-object metadata length")

        def unique_fields(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate cache-object metadata field")
                result[key] = value
            return result

        try:
            header = json.loads(data[start:end], object_pairs_hook=unique_fields)
        except (ValueError, UnicodeError, RecursionError) as error:
            raise CacheCorruptionError("Invalid cache-object metadata") from error
        frame = data[end:]
        fields = {"content_hash", "raw_size", "frame_size", "frame_sha256", "codec"}
        if type(header) is not dict or set(header) != fields:
            raise CacheCorruptionError("Cache-object metadata fields mismatch")
        for name in ("content_hash", "frame_sha256"):
            value = header[name]
            if (not isinstance(value, str) or len(value) != 64
                    or any(char not in "0123456789abcdef" for char in value)):
                raise CacheCorruptionError("Invalid cache-object metadata digest")
        if (type(header["raw_size"]) is not int or not 0 <= header["raw_size"] <= sys.maxsize
                or type(header["frame_size"]) is not int or header["frame_size"] != len(frame)):
            raise CacheCorruptionError("Invalid cache-object metadata size")
        if header["codec"] != "zstd-independent-frame":
            raise CacheCorruptionError("Unsupported cache-object codec")
        if header["content_hash"] != expected_hash:
            raise CacheCorruptionError("Cache-object identity mismatch")
        if sha256(frame).hexdigest() != header["frame_sha256"]:
            raise CacheCorruptionError("Compressed-frame checksum mismatch")
        try:
            content_size = zstd.frame_content_size(frame)
            # frame_content_size exposes unknown size as -1; some bindings
            # also expose the underlying unsigned ZSTD_CONTENTSIZE_UNKNOWN.
            if content_size not in (header["raw_size"], -1, zstd.CONTENTSIZE_UNKNOWN):
                raise CacheCorruptionError("Zstd frame content-size mismatch")
            raw = self.decompressor.decompress(
                frame, max_output_size=header["raw_size"], allow_extra_data=False,
            )
        except zstd.ZstdError as error:
            raise CacheCorruptionError("Zstd frame is unreadable") from error
        if len(raw) != header["raw_size"] or sha256(raw).hexdigest() != expected_hash:
            raise CacheCorruptionError("Decompressed content failed identity verification")
        return raw

    def put(self, raw: bytes, *, pinned: bool = False) -> str:
        content_hash = sha256(raw).hexdigest()
        path = self.object_path(content_hash)
        if path.exists():
            try:
                self.get(content_hash)
                if pinned:
                    self.pin(content_hash, True)
                return content_hash
            except CacheCorruptionError:
                pass
        packed = self._pack_object(raw, content_hash)
        _atomic_bytes(path, packed)
        now = time.time_ns()
        with self._connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO chunks VALUES (?, ?, ?, ?, ?)",
                (content_hash, len(raw), len(packed), now, int(pinned)),
            )
        return content_hash

    def get(self, content_hash: str) -> bytes:
        path = self.object_path(content_hash)
        if not path.exists():
            raise KeyError(content_hash)
        try:
            raw = self._unpack_object(path.read_bytes(), content_hash)
        except CacheCorruptionError:
            quarantine_path = self.quarantine / f"{path.name}.{time.time_ns()}.corrupt"
            quarantine_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                path.replace(quarantine_path)
            finally:
                with self._connection() as connection:
                    connection.execute("DELETE FROM chunks WHERE content_hash = ?", (content_hash,))
            raise
        with self._connection() as connection:
            connection.execute(
                "UPDATE chunks SET last_access_ns = ? WHERE content_hash = ?",
                (time.time_ns(), content_hash),
            )
        return raw

    def has(self, content_hash: str, verify: bool = False) -> bool:
        path = self.object_path(content_hash)
        if not path.exists():
            return False
        if verify:
            try:
                self.get(content_hash)
            except (KeyError, CacheCorruptionError):
                return False
        return True

    def pin(self, content_hash: str, pinned: bool = True) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE chunks SET pinned = ? WHERE content_hash = ?", (int(pinned), content_hash)
            )

    def entries(self) -> list[CacheEntry]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT content_hash, raw_size, stored_size, last_access_ns, pinned FROM chunks ORDER BY content_hash"
            ).fetchall()
        return [CacheEntry(row[0], row[1], row[2], row[3], bool(row[4])) for row in rows]

    def maintenance(self, max_stored_bytes: int, verify: bool = False) -> dict[str, int]:
        """Verify optionally, then evict least-recently-used unpinned chunks."""

        corrupt = 0
        if verify:
            for entry in self.entries():
                try:
                    self.get(entry.content_hash)
                except (KeyError, CacheCorruptionError):
                    corrupt += 1
        entries = self.entries()
        total = sum(entry.stored_size for entry in entries)
        evicted = 0
        for entry in sorted(entries, key=lambda item: item.last_access_ns):
            if total <= max_stored_bytes:
                break
            if entry.pinned:
                continue
            path = self.object_path(entry.content_hash)
            try:
                path.unlink(missing_ok=True)
            finally:
                with self._connection() as connection:
                    connection.execute("DELETE FROM chunks WHERE content_hash = ?", (entry.content_hash,))
            total -= entry.stored_size
            evicted += 1
        return {"stored_bytes": total, "evicted": evicted, "corrupt": corrupt}

    def rebuild_index(self) -> dict[str, int]:
        """Recover access metadata from intact immutable object headers."""

        with self._connection() as connection:
            connection.execute("DELETE FROM chunks")
        recovered = corrupt = 0
        for path in self.objects.glob("*/*.zst"):
            content_hash = path.stem
            try:
                raw = self._unpack_object(path.read_bytes(), content_hash)
            except (CacheCorruptionError, ValueError):
                path.replace(self.quarantine / f"{path.name}.{time.time_ns()}.corrupt")
                corrupt += 1
                continue
            with self._connection() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO chunks VALUES (?, ?, ?, ?, 0)",
                    (content_hash, len(raw), path.stat().st_size, path.stat().st_mtime_ns),
                )
            recovered += 1
        return {"recovered": recovered, "corrupt": corrupt}


class TemplateRegistry:
    """De-duplicates literal metadata repeated by many tiles/packets."""

    def __init__(self) -> None:
        self.templates: dict[str, Mapping[str, Any]] = {}

    def register(self, template: Mapping[str, Any]) -> str:
        template_id = canonical_hash(template)
        self.templates.setdefault(template_id, dict(template))
        return template_id


@dataclass(frozen=True)
class Packet:
    sequence: int
    kind: PacketKind
    target_hash: str
    template_ref: str | None = None
    base_hash: str | None = None
    raw_size: int = 0
    payload: bytes = b""
    patch_codec: str | None = None
    artifact_path: str | None = None


def xor_patch(base: bytes, target: bytes) -> bytes:
    if len(base) != len(target):
        raise ValueError("XOR patch requires equal-sized base and target")
    return bytes(a ^ b for a, b in zip(base, target))


class PacketBatch:
    """Ordered FULL/REF/PATCH batch with one atomic protocol boundary."""

    def __init__(self) -> None:
        self.templates = TemplateRegistry()
        self._packets: list[Packet] = []

    def _next_sequence(self) -> int:
        return len(self._packets)

    def add_full(
        self,
        raw: bytes,
        template: Mapping[str, Any] | None = None,
        artifact_path: str | None = None,
    ) -> str:
        target_hash = sha256(raw).hexdigest()
        template_ref = self.templates.register(template) if template else None
        self._packets.append(
            Packet(
                self._next_sequence(),
                "full",
                target_hash,
                template_ref,
                raw_size=len(raw),
                payload=raw,
                artifact_path=artifact_path,
            )
        )
        return target_hash

    def add_ref(
        self,
        target_hash: str,
        template: Mapping[str, Any] | None = None,
        artifact_path: str | None = None,
    ) -> None:
        template_ref = self.templates.register(template) if template else None
        self._packets.append(
            Packet(
                self._next_sequence(),
                "ref",
                target_hash,
                template_ref,
                artifact_path=artifact_path,
            )
        )

    def add_patch(
        self,
        base: bytes,
        target: bytes,
        template: Mapping[str, Any] | None = None,
        artifact_path: str | None = None,
    ) -> str:
        patch = xor_patch(base, target)
        target_hash = sha256(target).hexdigest()
        template_ref = self.templates.register(template) if template else None
        self._packets.append(
            Packet(
                self._next_sequence(),
                "patch",
                target_hash,
                template_ref,
                base_hash=sha256(base).hexdigest(),
                raw_size=len(target),
                payload=patch,
                patch_codec="xor-v1",
                artifact_path=artifact_path,
            )
        )
        return target_hash

    def flush(self, path: str | Path, compression_level: int = 5) -> Path:
        target = Path(path)
        compressor = zstd.ZstdCompressor(level=compression_level, write_checksum=True)
        frames: list[bytes] = []
        descriptors: list[dict[str, Any]] = []
        cursor = 0
        for packet in self._packets:
            frame = compressor.compress(packet.payload) if packet.kind != "ref" else b""
            descriptor = asdict(packet)
            descriptor.pop("payload")
            descriptor.update(
                {
                    "frame_offset": cursor,
                    "frame_size": len(frame),
                    "frame_sha256": sha256(frame).hexdigest() if frame else None,
                }
            )
            frames.append(frame)
            descriptors.append(descriptor)
            cursor += len(frame)
        header = canonical_json(
            {
                "schema": "diadem.tile-packet-segment/0.1",
                "codec": "independent-zstd-frames",
                "packet_count": len(descriptors),
                "templates": self.templates.templates,
                "packets": descriptors,
                "protocol_boundary": "ATOMIC_SEGMENT",
            }
        )
        _atomic_bytes(target, SEGMENT_MAGIC + UINT32.pack(len(header)) + header + b"".join(frames))
        return target

    def flush_recovery_bundle(
        self,
        directory: str | Path,
        *,
        compression_level: int = 7,
        bundle_role: str = "AUTHORITATIVE_RELEASE_RECOVERY_MASTER",
    ) -> Path:
        """Write the default release format: manifest plus independent .zst frames."""

        target = Path(directory)
        if target.exists():
            raise FileExistsError(f"Immutable recovery bundle already exists: {target}")
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        frames_dir = temporary / "frames"
        frames_dir.mkdir(parents=True)
        compressor = zstd.ZstdCompressor(level=compression_level, write_checksum=True)
        descriptors: list[dict[str, Any]] = []
        for packet in self._packets:
            descriptor = asdict(packet)
            descriptor.pop("payload")
            if packet.kind == "ref":
                descriptor.update({"frame_path": None, "frame_size": 0, "frame_sha256": None})
            else:
                frame = compressor.compress(packet.payload)
                frame_name = f"{packet.sequence:06d}-{packet.target_hash[:16]}.zst"
                frame_path = frames_dir / frame_name
                with frame_path.open("wb") as handle:
                    handle.write(frame)
                    handle.flush()
                    os.fsync(handle.fileno())
                descriptor.update(
                    {
                        "frame_path": f"frames/{frame_name}",
                        "frame_size": len(frame),
                        "frame_sha256": sha256(frame).hexdigest(),
                    }
                )
            descriptors.append(descriptor)
        manifest_core = {
            "schema": "diadem.recoverable-zstd-bundle/0.1",
            "bundle_role": bundle_role,
            "authoritative_master": True,
            "codec": "independent-zstd-files",
            "packet_count": len(descriptors),
            "templates": self.templates.templates,
            "packets": descriptors,
            "protocol_boundary": "ATOMIC_DIRECTORY_RENAME",
            "self_contained": all(packet.kind == "full" for packet in self._packets),
            "legacy_zip_default": False,
        }
        manifest = dict(manifest_core)
        manifest["bundle_id"] = canonical_hash(manifest_core)
        manifest_bytes = canonical_json(manifest)
        (temporary / "manifest.json").write_bytes(manifest_bytes)
        (temporary / "manifest.sha256").write_text(
            f"{sha256(manifest_bytes).hexdigest()}  manifest.json\n", encoding="ascii"
        )
        _fsync_directory(frames_dir)
        _fsync_directory(temporary)
        os.replace(temporary, target)
        _fsync_directory(target.parent)
        return target


@dataclass
class SegmentIngestReport:
    applied_sequences: list[int]
    failed_sequences: dict[int, str]
    packet_count: int


def read_segment_header(path: str | Path) -> tuple[dict[str, Any], int]:
    data = Path(path).read_bytes()
    if not data.startswith(SEGMENT_MAGIC) or len(data) < len(SEGMENT_MAGIC) + UINT32.size:
        raise CacheCorruptionError("Invalid segment header")
    header_length = UINT32.unpack_from(data, len(SEGMENT_MAGIC))[0]
    start = len(SEGMENT_MAGIC) + UINT32.size
    end = start + header_length
    try:
        header = json.loads(data[start:end])
    except (ValueError, UnicodeDecodeError) as error:
        raise CacheCorruptionError("Invalid segment metadata") from error
    return header, end


def ingest_segment(
    path: str | Path, cache: ContentAddressedCache, *, recover_independent_frames: bool = True
) -> SegmentIngestReport:
    data = Path(path).read_bytes()
    header, payload_start = read_segment_header(path)
    decompressor = zstd.ZstdDecompressor()
    applied: list[int] = []
    failed: dict[int, str] = {}
    for descriptor in sorted(header["packets"], key=lambda item: item["sequence"]):
        sequence = int(descriptor["sequence"])
        try:
            kind = descriptor["kind"]
            target_hash = descriptor["target_hash"]
            if kind == "ref":
                if not cache.has(target_hash, verify=True):
                    raise KeyError(f"Missing referenced chunk {target_hash}")
                cache.get(target_hash)
            else:
                offset = payload_start + int(descriptor["frame_offset"])
                frame_size = int(descriptor["frame_size"])
                frame = data[offset : offset + frame_size]
                if len(frame) != frame_size:
                    raise CacheCorruptionError("Truncated independent frame")
                if sha256(frame).hexdigest() != descriptor["frame_sha256"]:
                    raise CacheCorruptionError("Independent frame checksum mismatch")
                payload = decompressor.decompress(frame)
                if kind == "full":
                    raw = payload
                elif kind == "patch":
                    if descriptor.get("patch_codec") != "xor-v1":
                        raise ValueError("Unsupported patch codec")
                    base = cache.get(descriptor["base_hash"])
                    raw = xor_patch(base, payload)
                else:
                    raise ValueError(f"Unknown packet kind {kind}")
                if len(raw) != int(descriptor["raw_size"]):
                    raise CacheCorruptionError("Packet raw-size mismatch")
                if sha256(raw).hexdigest() != target_hash:
                    raise CacheCorruptionError("Packet target identity mismatch")
                cache.put(raw)
            applied.append(sequence)
        except Exception as error:  # report isolated frame/protocol failure
            failed[sequence] = f"{type(error).__name__}: {error}"
            if not recover_independent_frames:
                raise
    return SegmentIngestReport(applied, failed, int(header["packet_count"]))


def read_recovery_manifest(directory: str | Path) -> dict[str, Any]:
    root = Path(directory)
    manifest_bytes = (root / "manifest.json").read_bytes()
    checksum_line = (root / "manifest.sha256").read_text("ascii").split()[0]
    if sha256(manifest_bytes).hexdigest() != checksum_line:
        raise CacheCorruptionError("Recovery-bundle manifest checksum mismatch")
    try:
        manifest = json.loads(manifest_bytes)
    except (ValueError, UnicodeDecodeError) as error:
        raise CacheCorruptionError("Recovery-bundle manifest is invalid") from error
    core = dict(manifest)
    bundle_id = core.pop("bundle_id", None)
    if canonical_hash(core) != bundle_id:
        raise CacheCorruptionError("Recovery-bundle identity mismatch")
    return manifest


def ingest_recovery_bundle(
    directory: str | Path,
    cache: ContentAddressedCache,
    *,
    recover_independent_frames: bool = True,
) -> SegmentIngestReport:
    root = Path(directory)
    manifest = read_recovery_manifest(root)
    decompressor = zstd.ZstdDecompressor()
    applied: list[int] = []
    failed: dict[int, str] = {}
    for descriptor in sorted(manifest["packets"], key=lambda item: item["sequence"]):
        sequence = int(descriptor["sequence"])
        try:
            kind = descriptor["kind"]
            target_hash = descriptor["target_hash"]
            if kind == "ref":
                if not cache.has(target_hash, verify=True):
                    raise KeyError(f"Missing referenced chunk {target_hash}")
                cache.get(target_hash)
            else:
                frame_path = root / descriptor["frame_path"]
                frame = frame_path.read_bytes()
                if len(frame) != int(descriptor["frame_size"]):
                    raise CacheCorruptionError("Independent frame size mismatch")
                if sha256(frame).hexdigest() != descriptor["frame_sha256"]:
                    raise CacheCorruptionError("Independent frame checksum mismatch")
                payload = decompressor.decompress(frame)
                if kind == "full":
                    raw = payload
                elif kind == "patch":
                    if descriptor.get("patch_codec") != "xor-v1":
                        raise ValueError("Unsupported patch codec")
                    raw = xor_patch(cache.get(descriptor["base_hash"]), payload)
                else:
                    raise ValueError(f"Unknown packet kind {kind}")
                if len(raw) != int(descriptor["raw_size"]):
                    raise CacheCorruptionError("Packet raw-size mismatch")
                if sha256(raw).hexdigest() != target_hash:
                    raise CacheCorruptionError("Packet target identity mismatch")
                cache.put(raw)
            applied.append(sequence)
        except Exception as error:
            failed[sequence] = f"{type(error).__name__}: {error}"
            if not recover_independent_frames:
                raise
    return SegmentIngestReport(applied, failed, int(manifest["packet_count"]))


def write_tile_recovery_bundle(
    tile: EvidenceTile,
    directory: str | Path,
    *,
    compact: bool = True,
    compression_level: int = 7,
) -> Path:
    """Default delivery path for a tile: one manifest-indexed Zstd bundle."""

    arrays = tile.encoded_arrays if compact else tile.arrays
    batch = PacketBatch()
    batch.add_full(
        canonical_json({**tile.metadata, "stored_arrays": sorted(arrays), "compact_storage": compact}),
        {"media_type": "application/json", "role": "tile_metadata"},
        artifact_path=f"{tile.spec.tile_id}/metadata.json",
    )
    for name in sorted(arrays):
        buffer = BytesIO()
        np.save(buffer, np.asarray(arrays[name]), allow_pickle=False)
        array = np.asarray(arrays[name])
        batch.add_full(
            buffer.getvalue(),
            {
                "media_type": "application/x-npy",
                "dtype": str(array.dtype),
                "shape": list(array.shape),
            },
            artifact_path=f"{tile.spec.tile_id}/arrays/{name}.npy",
        )
    return batch.flush_recovery_bundle(
        directory,
        compression_level=compression_level,
    )


def export_convenience_tar_zst(
    bundle_directory: str | Path, output_path: str | Path, compression_level: int = 7
) -> Path:
    """Optional single-file convenience export; never the recovery master."""

    source = Path(bundle_directory)
    output = Path(output_path)
    tar_buffer = BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as archive:
        archive.add(source, arcname=source.name)
    frame = zstd.ZstdCompressor(level=compression_level, write_checksum=True).compress(
        tar_buffer.getvalue()
    )
    _atomic_bytes(output, frame)
    return output


def read_legacy_zip_entries(path: str | Path) -> dict[str, bytes]:
    """Compatibility intake only; ZIP is not a generator release default."""

    with zipfile.ZipFile(path, "r") as archive:
        return {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}


class ActivityMode(str, Enum):
    ACTIVE = "active"
    LIGHT_IDLE = "light_idle"
    DEEP_IDLE = "deep_idle"


@dataclass(frozen=True)
class ViewerTrafficPolicy:
    """Optional network-viewer policy; unrelated to offline tile correctness."""

    mode: ActivityMode
    max_concurrent_fetches: int
    speculative_prefetch_tiles: int
    heartbeat_seconds: int | None
    automatic_flush: bool


class ActivityPolicyController:
    def __init__(self) -> None:
        self.mode = ActivityMode.ACTIVE

    def set_mode(self, mode: ActivityMode) -> ViewerTrafficPolicy:
        self.mode = mode
        if mode is ActivityMode.ACTIVE:
            return ViewerTrafficPolicy(mode, 8, 16, 30, True)
        if mode is ActivityMode.LIGHT_IDLE:
            return ViewerTrafficPolicy(mode, 2, 0, 180, True)
        return ViewerTrafficPolicy(mode, 0, 0, None, False)

    def restore_active(self) -> ViewerTrafficPolicy:
        return self.set_mode(ActivityMode.ACTIVE)


class CacheMaintenanceWorker:
    """Small stoppable background LRU/verification worker."""

    def __init__(
        self,
        cache: ContentAddressedCache,
        max_stored_bytes: int,
        interval_seconds: float = 300.0,
        deep_verify_every: int = 12,
    ) -> None:
        self.cache = cache
        self.max_stored_bytes = max_stored_bytes
        self.interval_seconds = interval_seconds
        self.deep_verify_every = max(1, deep_verify_every)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="diadem-cache-maintenance", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        cycle = 0
        while not self._stop.wait(self.interval_seconds):
            cycle += 1
            self.cache.maintenance(
                self.max_stored_bytes, verify=(cycle % self.deep_verify_every == 0)
            )

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
