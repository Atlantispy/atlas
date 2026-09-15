"""A NEW public integer oracle using the unchanged R12 executor/cache and R11 graph.

No scientific bundle is replaced or spoofed. The R12 executor has an explicit
snapshot-module interface; this development route supplies the original standalone
R11 graph contract, a source-bound synthetic producer and a dedicated namespace.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from typing import Any

from . import SCOPE
from . import core


FIXTURE_SCHEMA = "atlas.public-development.integer-graph.v1"


def load_fixture(root: Path = core.ROOT) -> dict[str, Any]:
    data = core.parse(core.read(root / "development/fixtures/runtime_graph.json"))
    required = {"schema", "fixture_id", "scope", "evidence", "nodes", "expected"}
    if (type(data) is not dict or set(data) != required or data["schema"] != FIXTURE_SCHEMA
            or data["scope"] != SCOPE or not isinstance(data["evidence"], str)
            or not data["evidence"].strip() or type(data["fixture_id"]) is not str
            or not data["fixture_id"].strip()):
        raise core.DevelopmentError("explicit public synthetic fixture required")
    nodes = data["nodes"]
    if type(nodes) is not list or not 1 <= len(nodes) <= 16:
        raise core.DevelopmentError("public fixture must have 1..16 integer nodes")
    seen: set[str] = set()
    for node in nodes:
        if (type(node) is not dict or set(node) != {"id", "base", "parents"}
                or type(node["id"]) is not str or not node["id"].isidentifier()
                or node["id"] in seen or type(node["base"]) is not int
                or not -1000000 <= node["base"] <= 1000000
                or type(node["parents"]) is not list
                or any(type(p) is not str or p not in seen for p in node["parents"])
                or len(node["parents"]) != len(set(node["parents"]))):
            raise core.DevelopmentError("unique ordered bounded integer fixture nodes required")
        seen.add(node["id"])
    if (type(data["expected"]) is not dict or set(data["expected"]) != seen
            or any(type(value) is not int for value in data["expected"].values())):
        raise core.DevelopmentError("independent integer expectations required for every node")
    return data


def snapshot(root: Path = core.ROOT):
    from work.generator_runtime_r12 import _CapturedLoader
    path = root / "engineering/work/generator_upgrade_r11/snapshot.py"
    spec = importlib.util.spec_from_file_location("_atlas_public_dev_snapshot_v1", path,
                                                loader=_CapturedLoader(path))
    if spec is None or spec.loader is None:
        raise core.DevelopmentError("cannot load the public graph contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def smoke(binding: dict[str, Any], root: Path = core.ROOT) -> dict[str, Any]:
    identity = core.verify(binding, root)
    data = load_fixture(root)
    from work.generator_runtime_r12 import executor, store
    s = snapshot(root)
    port = {"quantity": "SYNTHETIC_INTEGER", "unit": "count", "support_id": "PUBLIC_FIXTURE",
            "temporal_support": "NO_PHYSICAL_TIME"}
    context = {
        "world_id": "PUBLIC_SYNTHETIC_NOT_DIADEM", "snapshot_id": data["fixture_id"],
        "calendar_id": "NO_PHYSICAL_CALENDAR", "spatial_frame_id": "NO_GEOGRAPHY",
        "vertical_reference": "NO_ELEVATION", "scenario_id": identity,
    }
    producer_id = core.digest(core.canonical({"public_binding": identity,
                    "fixture": data, "producer": "integer-base-plus-parents-v1"}))

    def check() -> None:
        core.verify(binding, root)
        for module in (executor, store, s):
            path = Path(module.__file__)
            if getattr(module, "_R12_EXECUTED_SHA256", None) != core.digest(core.read(path)):
                raise core.DevelopmentError("actually executed public component differs")

    def producer(ctx, inputs, incoming):
        check()
        return s.emission(ctx, {"value": port},
                          {"value": inputs["base"] + sum(incoming.values())},
                          evidence=data["evidence"], source_status="SYNTHETIC TEST", status="MODELLED")

    registry = {"public_integer_sum": {"sha256": producer_id, "run": producer, "verify": check}}
    stages = []
    for node in data["nodes"]:
        stages.append({
            "stage_id": node["id"], "category": "geology", "producer_id": "public_integer_sum",
            "producer_sha256": producer_id, "inputs": {"base": node["base"]},
            "dependencies": {p: {"stage_id": p, "output": "value", "port": deepcopy(port)}
                             for p in node["parents"]},
            "outputs": {"value": deepcopy(port)}, "missing_inputs": [], "mode": "GENERATED",
            "acceptance": {"status": "PENDING", "evidence": "Integer test only; no domain acceptance"},
        })
    recipe = {"schema": "diadem.snapshot-graph-recipe.r11", "context": context,
              "stages": stages, "required_categories": ["geology"], "evidence": data["evidence"]}
    cache_root = core.safe(root / ".atlas-dev/cache" / identity)
    cache = store.Store(cache_root, producer_id, max_bytes=8 * 1024 * 1024)
    first_stats: dict[str, Any] = {}
    warm_stats: dict[str, Any] = {}
    first = executor.run(s, recipe, registry, store=cache, stats=first_stats)
    warm = executor.run(s, recipe, registry, store=cache, stats=warm_stats)
    oracle = s.run(recipe, registry)
    values = {key: row["product"]["values"]["value"] for key, row in warm["state"]["rows"].items()}
    if (any(type(value) is not int for value in values.values())
            or values != data["expected"] or first != warm or warm != oracle):
        raise core.DevelopmentError("public graph differs from independent expectations or retained oracle")
    if warm_stats["computed_stage_ids"] or len(warm_stats["reused_stage_ids"]) != len(stages):
        raise core.DevelopmentError("warm fixture unexpectedly recomputed a stage")
    if warm["production_authorised"] or warm["canon_changed"] or any(
            row["domain_acceptance_declared"] for row in warm["category_closure"].values()):
        raise core.DevelopmentError("synthetic fixture must never claim physical authority")
    check()
    return {
        "schema": "atlas.public-development.result.v1", "scope": SCOPE,
        "binding_sha256": identity, "fixture_id": data["fixture_id"],
        "fixture_sha256": core.digest(core.canonical(data)), "values": values,
        "first_computed": first_stats["computed_stage_ids"],
        "warm_computed": warm_stats["computed_stage_ids"],
        "warm_reused": warm_stats["reused_stage_ids"],
        "retained_graph_oracle_equal": True, "physical_acceptance": False,
        "historical_checkpoint_compatibility": False, "status": "PASS",
    }
