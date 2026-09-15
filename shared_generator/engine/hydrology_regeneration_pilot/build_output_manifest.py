"""Create an ingestion manifest without building a production delivery bundle."""

from __future__ import annotations

from hashlib import sha256
import json
import mimetypes
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "pilot_output"


ROLES = {
    "synthetic_regeneration_report.json": "analytical_report",
    "synthetic_regenerated_route.geojson": "analytical_vector",
    "pilot_run_summary.json": "run_summary",
    "synthetic_hydrology_regeneration_QA.png": "qa_visual_not_authority",
    "synthetic_visual_qa_metrics.json": "qa_metrics",
}


def digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def build() -> Path:
    entries = []
    for name, role in ROLES.items():
        path = OUTPUT / name
        if not path.is_file():
            raise RuntimeError(f"Missing pilot output for manifest: {name}")
        entries.append(
            {
                "logical_path": f"hydrology_regeneration_pilot/{name}",
                "source_path": str(path.relative_to(HERE)).replace("\\", "/"),
                "frame_role": role,
                "content_sha256": digest(path),
                "uncompressed_size_bytes": path.stat().st_size,
                "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "required": True,
            }
        )
    manifest = {
        "schema": "diadem-indexed-multiframe-ingest-manifest/1.0",
        "status": "WORKING PROPOSAL - REVIEW ONLY - NOT CANON",
        "bundle_created": False,
        "delivery_target": {
            "container": "recoverable_zstd_multiframe",
            "minimum_zstandard_version": "0.25.0",
            "content_addressed": True,
            "per_frame_sha256": True,
            "ordered_atomic_flush": True,
            "corruption_rebuild": True,
        },
        "frames": entries,
    }
    target = OUTPUT / "PILOT_OUTPUT_INGEST_MANIFEST.json"
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return target


if __name__ == "__main__":
    print(build())

