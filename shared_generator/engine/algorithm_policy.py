"""One explicit, inherited reference switch for exact-output algorithm paths.

Configure once before admitting work. The guarded launcher records the selected
mode; spawned processes inherit it. This is execution policy, not domain input.
Unknown algorithm names fail closed to their reference implementations.
"""
from __future__ import annotations

import os


ENVIRONMENT_KEY = "DIADEM_GENERATOR_ALGORITHM_MODE"
MODES = ("auto", "reference")
# Only acceptance-tested tags may remain here in an installed release.
ENABLED_ALGORITHMS = frozenset({
    "river_profile_sampling",
    "route_corridor_spans", "chamfer_wavefront", "terrain_quantization", "channel_proximity",
    "mfd_scenario_batch",
})
_mode = os.environ.get(ENVIRONMENT_KEY, "auto")
if _mode not in MODES:
    _mode = "reference"


def configure(mode: str) -> None:
    """Select before worker startup; no source/output access or new dependency."""
    if mode not in MODES:
        raise ValueError("algorithm mode must be auto or reference")
    global _mode
    _mode = mode
    os.environ[ENVIRONMENT_KEY] = mode


def use_optimized(name: str) -> bool:
    return _mode == "auto" and name in ENABLED_ALGORITHMS


def snapshot() -> dict[str, object]:
    return {"mode": _mode, "enabled_algorithms": sorted(ENABLED_ALGORITHMS) if _mode == "auto" else []}
