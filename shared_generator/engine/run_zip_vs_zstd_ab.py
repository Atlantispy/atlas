"""Compression-only ZIP/Deflate versus independent-frame Zstd A/B test.

The raw inputs are the exact packet payloads already used by the bounded Titan
tile recovery bundle.  Terrain generation is not run or timed here.
"""

from __future__ import annotations

import gc
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import statistics
import struct
import time
import tracemalloc
import zipfile

import zstandard as zstd


ROOT = Path(__file__).resolve().parent
SOURCE_BUNDLE = ROOT / "bounded_real_terrain_test_2026-08-28" / "tile.zstbundle"
OUT = ROOT / "bounded_zip_vs_zstd_ab_2026-08-28"
ZIP_LEVEL = 6
ZSTD_LEVEL = 7  # Current authoritative recovery-bundle level.
ZSTD_MAGIC = b"DIAZAB01"


def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_exact_payloads() -> tuple[list[tuple[str, bytes]], dict]:
    manifest = json.loads((SOURCE_BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    decompressor = zstd.ZstdDecompressor()
    payloads: list[tuple[str, bytes]] = []
    for descriptor in sorted(manifest["packets"], key=lambda item: item["sequence"]):
        if descriptor["kind"] == "ref":
            continue
        frame = (SOURCE_BUNDLE / descriptor["frame_path"]).read_bytes()
        raw = decompressor.decompress(frame)
        if sha256(raw).hexdigest() != descriptor["target_hash"]:
            raise RuntimeError(f"Source packet hash mismatch: {descriptor['artifact_path']}")
        payloads.append((descriptor["artifact_path"], raw))
    return payloads, manifest


def encode_zip(payloads: list[tuple[str, bytes]]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=ZIP_LEVEL,
        allowZip64=True,
    ) as archive:
        for name, raw in payloads:
            archive.writestr(name, raw)
    return output.getvalue()


def decode_zip(encoded: bytes) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(BytesIO(encoded), mode="r") as archive:
        return [(info.filename, archive.read(info)) for info in archive.infolist()]


def encode_zstd(payloads: list[tuple[str, bytes]]) -> bytes:
    compressor = zstd.ZstdCompressor(level=ZSTD_LEVEL, write_checksum=True)
    frames: list[bytes] = []
    descriptors: list[dict] = []
    offset = 0
    for sequence, (name, raw) in enumerate(payloads):
        frame = compressor.compress(raw)
        descriptors.append(
            {
                "sequence": sequence,
                "artifact_path": name,
                "raw_size": len(raw),
                "raw_sha256": sha256(raw).hexdigest(),
                "frame_offset": offset,
                "frame_size": len(frame),
            }
        )
        frames.append(frame)
        offset += len(frame)
    manifest = canonical_json(
        {
            "schema": "diadem.codec-ab-independent-zstd/0.1",
            "codec": "zstd-independent-frames",
            "compression_level": ZSTD_LEVEL,
            "packet_count": len(descriptors),
            "packets": descriptors,
        }
    )
    return ZSTD_MAGIC + struct.pack("<I", len(manifest)) + manifest + b"".join(frames)


def decode_zstd(encoded: bytes) -> list[tuple[str, bytes]]:
    if encoded[: len(ZSTD_MAGIC)] != ZSTD_MAGIC:
        raise RuntimeError("Zstd A/B container magic mismatch")
    manifest_size = struct.unpack(
        "<I", encoded[len(ZSTD_MAGIC) : len(ZSTD_MAGIC) + 4]
    )[0]
    manifest_start = len(ZSTD_MAGIC) + 4
    payload_start = manifest_start + manifest_size
    manifest = json.loads(encoded[manifest_start:payload_start])
    decompressor = zstd.ZstdDecompressor()
    output: list[tuple[str, bytes]] = []
    for descriptor in sorted(manifest["packets"], key=lambda item: item["sequence"]):
        start = payload_start + descriptor["frame_offset"]
        end = start + descriptor["frame_size"]
        raw = decompressor.decompress(encoded[start:end], max_output_size=descriptor["raw_size"])
        if sha256(raw).hexdigest() != descriptor["raw_sha256"]:
            raise RuntimeError(f"Zstd packet hash mismatch: {descriptor['artifact_path']}")
        output.append((descriptor["artifact_path"], raw))
    return output


def aggregate_digest(payloads: list[tuple[str, bytes]]) -> str:
    digest = sha256()
    for name, raw in payloads:
        digest.update(name.encode("utf-8"))
        digest.update(struct.pack("<Q", len(raw)))
        digest.update(raw)
    return digest.hexdigest()


def benchmark(function, repeats: int, warmups: int = 2) -> tuple[object, list[float]]:
    value = None
    for _ in range(warmups):
        value = function()
    timings: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        value = function()
        timings.append(time.perf_counter() - started)
    return value, timings


def tracked_peak(function) -> int:
    gc.collect()
    tracemalloc.start()
    value = function()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del value
    gc.collect()
    return int(peak)


def timing_metrics(values: list[float], raw_bytes: int) -> dict:
    ordered = sorted(values)
    median = float(statistics.median(ordered))
    p95_index = min(len(ordered) - 1, max(0, int(round(0.95 * len(ordered) + 0.5)) - 1))
    return {
        "repeats": len(ordered),
        "median_seconds": median,
        "minimum_seconds": float(ordered[0]),
        "p95_seconds": float(ordered[p95_index]),
        "throughput_mib_per_second": float((raw_bytes / (1024**2)) / median),
    }


def zip_payload_bytes(encoded: bytes) -> int:
    with zipfile.ZipFile(BytesIO(encoded), mode="r") as archive:
        return int(sum(info.compress_size for info in archive.infolist()))


def zstd_frame_bytes(encoded: bytes) -> int:
    manifest_size = struct.unpack(
        "<I", encoded[len(ZSTD_MAGIC) : len(ZSTD_MAGIC) + 4]
    )[0]
    manifest_start = len(ZSTD_MAGIC) + 4
    manifest = json.loads(encoded[manifest_start : manifest_start + manifest_size])
    return int(sum(item["frame_size"] for item in manifest["packets"]))


def main() -> int:
    payloads, source_manifest = load_exact_payloads()
    raw_bytes = int(sum(len(raw) for _, raw in payloads))
    expected_digest = aggregate_digest(payloads)

    zip_encoded, zip_encode_times = benchmark(lambda: encode_zip(payloads), repeats=25)
    zstd_encoded, zstd_encode_times = benchmark(lambda: encode_zstd(payloads), repeats=25)
    zip_decoded, zip_decode_times = benchmark(lambda: decode_zip(zip_encoded), repeats=50)
    zstd_decoded, zstd_decode_times = benchmark(lambda: decode_zstd(zstd_encoded), repeats=50)

    zip_digest = aggregate_digest(zip_decoded)
    zstd_digest = aggregate_digest(zstd_decoded)
    zip_encode_peak = tracked_peak(lambda: encode_zip(payloads))
    zstd_encode_peak = tracked_peak(lambda: encode_zstd(payloads))
    zip_decode_peak = tracked_peak(lambda: decode_zip(zip_encoded))
    zstd_decode_peak = tracked_peak(lambda: decode_zstd(zstd_encoded))

    zip_size = len(zip_encoded)
    zstd_size = len(zstd_encoded)
    zip_encode_median = statistics.median(zip_encode_times)
    zstd_encode_median = statistics.median(zstd_encode_times)
    zip_decode_median = statistics.median(zip_decode_times)
    zstd_decode_median = statistics.median(zstd_decode_times)
    status = "PASS" if zip_digest == zstd_digest == expected_digest else "FAIL"
    result = {
        "status": status,
        "scope": "COMPRESSION_ONLY_IDENTICAL_PAYLOAD_AB_NO_TERRAIN_GENERATION",
        "input": {
            "source_bundle": str(SOURCE_BUNDLE),
            "source_bundle_id": source_manifest["bundle_id"],
            "packet_count": len(payloads),
            "raw_payload_bytes": raw_bytes,
            "aggregate_payload_sha256": expected_digest,
            "location_unchanged": "TITAN-INTERIOR-REAL-TERRAIN-TEST-001",
        },
        "a_zip_deflate": {
            "codec": "ZIP_DEFLATED",
            "level": ZIP_LEVEL,
            "container_bytes": zip_size,
            "compressed_payload_bytes_excluding_container_overhead": zip_payload_bytes(zip_encoded),
            "reduction_from_raw_fraction": float(1.0 - zip_size / raw_bytes),
            "encode": timing_metrics(zip_encode_times, raw_bytes),
            "decode_and_verify": timing_metrics(zip_decode_times, raw_bytes),
            "encode_python_tracemalloc_peak_bytes": zip_encode_peak,
            "decode_python_tracemalloc_peak_bytes": zip_decode_peak,
            "exact_reconstruction": zip_digest == expected_digest,
        },
        "b_zstd_independent_frames": {
            "codec": "Zstd independent frames with checksums and manifest",
            "level": ZSTD_LEVEL,
            "container_bytes": zstd_size,
            "compressed_frame_bytes_excluding_manifest": zstd_frame_bytes(zstd_encoded),
            "reduction_from_raw_fraction": float(1.0 - zstd_size / raw_bytes),
            "encode": timing_metrics(zstd_encode_times, raw_bytes),
            "decode_and_verify": timing_metrics(zstd_decode_times, raw_bytes),
            "encode_python_tracemalloc_peak_bytes": zstd_encode_peak,
            "decode_python_tracemalloc_peak_bytes": zstd_decode_peak,
            "exact_reconstruction": zstd_digest == expected_digest,
        },
        "comparison": {
            "zstd_encode_speedup_vs_zip": float(zip_encode_median / zstd_encode_median),
            "zstd_decode_speedup_vs_zip": float(zip_decode_median / zstd_decode_median),
            "zstd_size_reduction_vs_zip_fraction": float(1.0 - zstd_size / zip_size),
            "zstd_encode_tracemalloc_ratio_vs_zip": float(zstd_encode_peak / zip_encode_peak),
            "zstd_decode_tracemalloc_ratio_vs_zip": float(zstd_decode_peak / zip_decode_peak),
            "winner_encode_speed": "ZSTD" if zstd_encode_median < zip_encode_median else "ZIP",
            "winner_decode_speed": "ZSTD" if zstd_decode_median < zip_decode_median else "ZIP",
            "winner_size": "ZSTD" if zstd_size < zip_size else "ZIP",
        },
        "measurement_limits": [
            "Timing and size compare byte-identical packet payloads; terrain generation is excluded.",
            "ZIP uses Deflate level 6; Zstd uses the current recovery-master level 7 and independent frames.",
            "Tracemalloc measures Python-tracked allocations and may not include every native codec allocation.",
            "This small tile is representative of the tested packet structure, not every future dataset.",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    output = OUT / "ZIP_VS_ZSTD_AB_METRICS.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
