"""Bounded SPACE mixed-bed algebra; not terrain generation or time integration.

Only m=.5, n=1, zero porosity/fines/thresholds and positive mixed-regime
parameters are supported. The geometric surface is bedrock plus alluvium, NOT
water level. Fluxes are solid volumes, not kilograms or chemical mass.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType


BENCHMARK_SHA256 = "bd25104047eeb0579b99f29e31d6acce58463fb9ac23804fe2f1e3e8d37ee35d"
BENCHMARK_PATH = Path(__file__).with_name("space_benchmark.json")
IMPORTED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def load_benchmark(path=BENCHMARK_PATH):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != BENCHMARK_SHA256:
        raise ValueError("frozen SPACE numerical contract changed")
    return json.loads(data)


def _number(value, name, *, positive=False, nonnegative=False):
    if type(value) not in (int, float):
        raise ValueError(name + " must be a finite real number, not a Boolean")
    try:
        value = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(name + " cannot be represented in binary64") from exc
    if not math.isfinite(value):
        raise ValueError(name + " must be finite")
    if positive and value <= 0 or nonnegative and value < 0:
        raise ValueError(name + " outside supported range")
    return float(value)


def _text(value, name):
    if type(value) is not str or not value.strip():
        raise ValueError(name + " must be nonblank text")
    return value


def _finite(**values):
    for name, value in values.items():
        if not math.isfinite(value):
            raise ValueError("nonfinite derived " + name)


@dataclass(frozen=True)
class Parameters:
    sediment_erodibility: float
    bedrock_erodibility: float
    area_exponent: float
    slope_exponent: float
    uplift_m_per_year: float
    cover_scale_m: float
    settling_m_per_year: float
    runoff_m_per_year: float
    porosity: float
    fines_fraction: float
    sediment_threshold_m_per_year: float
    bedrock_threshold_m_per_year: float
    forcing_basis: str
    erodibility_units: str

    def __post_init__(self):
        for name in ("sediment_erodibility", "bedrock_erodibility", "uplift_m_per_year",
                     "cover_scale_m", "settling_m_per_year", "runoff_m_per_year"):
            object.__setattr__(self, name, _number(getattr(self, name), name, positive=True))
        supported = {"area_exponent": .5, "slope_exponent": 1., "porosity": 0.,
                     "fines_fraction": 0., "sediment_threshold_m_per_year": 0.,
                     "bedrock_threshold_m_per_year": 0.}
        for name, expected in supported.items():
            value = _number(getattr(self, name), name)
            if value != expected:
                raise ValueError("unsupported SPACE setting: " + name)
            object.__setattr__(self, name, value)
        if self.forcing_basis != "drainage_area_m2" or self.erodibility_units != "1/year":
            raise ValueError("only drainage-area forcing with m=.5 and K in1/year is supported")


_CONTRACT = load_benchmark()
PUBLISHED_PARAMETERS = Parameters(**_CONTRACT["parameters"])
# The immutable tolerances come from the pre-test frozen contract, not copies.
TOLERANCES = MappingProxyType({name: (value["atol"], value["rtol"])
                              for name, value in _CONTRACT["tolerances"].items()
                              if isinstance(value, dict)})


def _close(actual, expected, kind, *, scale=None):
    atol, rtol = TOLERANCES[kind]
    scale = max(abs(actual), abs(expected)) if scale is None else scale
    return (math.isfinite(actual) and math.isfinite(expected) and
            math.isfinite(scale) and scale >= 0 and
            abs(actual - expected) <= atol + rtol * scale)


@dataclass(frozen=True)
class CellState:
    id: str
    x_m: float
    y_m: float
    width_m: float
    contributing_area_m2: float
    incoming_sediment_m3_per_year: float
    bedrock_m: float
    cover_m: float
    surface_m: float
    receiver_x_m: float
    receiver_y_m: float
    receiver_surface_m: float
    length_units: str = "m"
    area_units: str = "m2"
    sediment_flux_units: str = "m3_solid/year"
    vertical_datum: str = "synthetic_relative_m"
    receiver_vertical_datum: str = "synthetic_relative_m"

    def __post_init__(self):
        _text(self.id, "cell id")
        for name in ("x_m", "y_m", "bedrock_m", "surface_m", "receiver_x_m",
                     "receiver_y_m", "receiver_surface_m"):
            object.__setattr__(self, name, _number(getattr(self, name), name))
        for name in ("width_m", "contributing_area_m2"):
            object.__setattr__(self, name, _number(getattr(self, name), name, positive=True))
        for name in ("cover_m", "incoming_sediment_m3_per_year"):
            object.__setattr__(self, name, _number(getattr(self, name), name, nonnegative=True))
        if (self.length_units, self.area_units, self.sediment_flux_units) != ("m", "m2", "m3_solid/year"):
            raise ValueError("incompatible cell units")
        if _text(self.vertical_datum, "datum") != _text(self.receiver_vertical_datum, "receiver datum"):
            raise ValueError("incompatible vertical datums")
        if not _close(self.surface_m, self.bedrock_m + self.cover_m, "state_m"):
            raise ValueError("surface is not bedrock plus cover")
        area = self.width_m * self.width_m
        distance = math.hypot(self.x_m - self.receiver_x_m, self.y_m - self.receiver_y_m)
        drop = self.surface_m - self.receiver_surface_m
        _finite(cell_area=area, receiver_distance=distance, surface_drop=drop)
        if area <= 0 or distance == 0 or self.contributing_area_m2 < area or drop < 0:
            raise ValueError("invalid receiver geometry or contributing area")

    @property
    def cell_area_m2(self):
        return self.width_m * self.width_m

    @property
    def slope(self):
        return ((self.surface_m - self.receiver_surface_m) /
                math.hypot(self.x_m - self.receiver_x_m, self.y_m - self.receiver_y_m))


def equilibrium_predictions(contributing_area_m2, parameters=PUBLISHED_PARAMETERS):
    """Continuous analytical oracle, not a claim that a landscape converged."""
    if not isinstance(parameters, Parameters):
        raise TypeError("validated Parameters required")
    area = _number(contributing_area_m2, "area", positive=True)
    p = parameters
    denominator = p.runoff_m_per_year * p.sediment_erodibility
    _finite(denominator=denominator)
    if denominator <= 0:
        raise ValueError("mixed-regime denominator underflow")
    ratio = p.settling_m_per_year * p.bedrock_erodibility / denominator
    slope = (p.uplift_m_per_year * p.settling_m_per_year /
             (p.sediment_erodibility * p.runoff_m_per_year) +
             p.uplift_m_per_year / p.bedrock_erodibility) / math.sqrt(area)
    cover = p.cover_scale_m * math.log1p(ratio)
    flux = p.uplift_m_per_year * area
    _finite(ratio=ratio, slope=slope, cover=cover, sediment_flux=flux)
    if min(ratio, slope, cover, flux) <= 0:
        raise ValueError("positive mixed-regime equilibrium underflow")
    return {"slope": slope, "cover_m": cover, "sediment_m3_per_year": flux}


def local_rates(state, parameters=PUBLISHED_PARAMETERS):
    """Instantaneous local rates with steady water-column sediment balance.

    No state is advanced. In particular, multiplying off-equilibrium rates by
    a long interval is NOT an implemented SPACE time integrator.
    """
    if not isinstance(state, CellState) or not isinstance(parameters, Parameters):
        raise TypeError("validated CellState and Parameters required")
    p = parameters
    area = state.cell_area_m2
    water = p.runoff_m_per_year * state.contributing_area_m2
    cover_ratio = state.cover_m / p.cover_scale_m
    slope = state.slope
    area_slope = math.sqrt(state.contributing_area_m2) * slope
    _finite(water_discharge=water, cover_ratio=cover_ratio, area_slope=area_slope)
    if water <= 0:
        raise ValueError("water discharge underflow")
    exposed = math.exp(-cover_ratio)
    covered = -math.expm1(-cover_ratio)
    entrainment = p.sediment_erodibility * area_slope * covered
    erosion = p.bedrock_erodibility * area_slope * exposed
    denominator = 1. + p.settling_m_per_year * area / water
    outgoing = (state.incoming_sediment_m3_per_year + area * (entrainment + erosion)) / denominator
    deposition = p.settling_m_per_year * outgoing / water
    cover_change = deposition - entrainment
    bedrock_change = p.uplift_m_per_year - erosion
    mobile_volume_change = area * cover_change
    rock_supply = area * erosion
    # Bedrock lowering debits source material; uplift is NOT a second input.
    residual = mobile_volume_change - (state.incoming_sediment_m3_per_year + rock_supply - outgoing)
    result = {"id": state.id, "slope": slope, "water_m3_per_year": water,
              "entrainment_m_per_year": entrainment, "erosion_m_per_year": erosion,
              "deposition_m_per_year": deposition, "cover_change_m_per_year": cover_change,
              "bedrock_change_m_per_year": bedrock_change,
              "surface_change_m_per_year": cover_change + bedrock_change,
              "outgoing_sediment_m3_per_year": outgoing,
              "mobile_change_m3_per_year": mobile_volume_change,
              "bedrock_supply_m3_per_year": rock_supply,
              "solid_volume_residual_m3_per_year": residual}
    _finite(denominator=denominator, **{k: v for k, v in result.items() if k != "id"})
    return result


def evaluate_network(network, parameters=PUBLISHED_PARAMETERS):
    """At most16 synthetic square cells, single receivers, one external outlet.

    Areas and incoming sediment are calculated from donor links, not supplied
    independently. This is a tiny confluence ledger, not a routing algorithm.
    """
    if type(network) is not dict or set(network) != {"frame", "vertical_datum", "cover_m", "width_m", "outlet", "nodes"}:
        raise ValueError("unsupported network schema")
    if network["frame"] != "synthetic_local_m_x_east_y_south":
        raise ValueError("unsupported synthetic frame")
    _text(network["vertical_datum"], "network datum")
    width = _number(network["width_m"], "width", positive=True)
    cover = _number(network["cover_m"], "cover", nonnegative=True)
    outlet = network["outlet"]
    if type(outlet) is not dict or set(outlet) != {"id", "x_m", "y_m", "surface_m", "status"}:
        raise ValueError("unsupported outlet schema")
    _text(outlet["id"], "outlet id")
    for field in ("x_m", "y_m", "surface_m"):
        _number(outlet[field], "outlet " + field)
    if outlet["status"] != "SYNTHETIC_FIXED_TERRAIN_SURFACE_NOT_HYDRAULIC_STAGE":
        raise ValueError("outlet is not the declared synthetic terrain control")
    nodes = network["nodes"]
    if type(nodes) is not list or not 1 <= len(nodes) <= 16:
        raise ValueError("network requires1..16 synthetic cells")
    by_id = {}
    for node in nodes:
        if type(node) is not dict or set(node) != {"id", "x_m", "y_m", "surface_m", "receiver"}:
            raise ValueError("unsupported node schema")
        name = _text(node["id"], "node id")
        _text(node["receiver"], "receiver id")
        for field in ("x_m", "y_m", "surface_m"):
            _number(node[field], "node " + field)
        if name in by_id or name == outlet["id"]:
            raise ValueError("duplicate cell/outlet id")
        # Each axis-aligned square contributes its area once. Different IDs do
        # not licence overlapping material/water-supply footprints.
        for previous in by_id.values():
            if (abs(node["x_m"] - previous["x_m"]) < width and
                    abs(node["y_m"] - previous["y_m"]) < width):
                raise ValueError("overlapping synthetic square cells")
        by_id[name] = node
    for node in nodes:
        if node["receiver"] not in by_id and node["receiver"] != outlet["id"]:
            raise ValueError("unknown receiver")
    pending = list(by_id)
    completed = {}
    while pending:
        progress = False
        for name in pending[:]:
            donors = [key for key, node in by_id.items() if node["receiver"] == name]
            if any(key not in completed for key in donors):
                continue
            node = by_id[name]
            receiver = outlet if node["receiver"] == outlet["id"] else by_id[node["receiver"]]
            area = math.fsum([width * width] + [completed[key]["contributing_area_m2"] for key in donors])
            incoming = math.fsum(completed[key]["outgoing_sediment_m3_per_year"] for key in donors)
            state = CellState(id=name, x_m=node["x_m"], y_m=node["y_m"], width_m=width,
                              contributing_area_m2=area, incoming_sediment_m3_per_year=incoming,
                              bedrock_m=node["surface_m"] - cover, cover_m=cover, surface_m=node["surface_m"],
                              receiver_x_m=receiver["x_m"], receiver_y_m=receiver["y_m"],
                              receiver_surface_m=receiver["surface_m"], vertical_datum=network["vertical_datum"],
                              receiver_vertical_datum=network["vertical_datum"])
            result = local_rates(state, parameters)
            completed[name] = {**result, "contributing_area_m2": area,
                               "incoming_sediment_m3_per_year": incoming, "receiver": node["receiver"]}
            pending.remove(name); progress = True
        if not progress:
            raise ValueError("nonterminal cycle in synthetic network")
    exports = [completed[name] for name, node in by_id.items() if node["receiver"] == outlet["id"]]
    sediment_export = math.fsum(node["outgoing_sediment_m3_per_year"] for node in exports)
    water_export = math.fsum(node["water_m3_per_year"] for node in exports)
    supply = math.fsum(node["bedrock_supply_m3_per_year"] for node in completed.values())
    mobile = math.fsum(node["mobile_change_m3_per_year"] for node in completed.values())
    return {"nodes": [completed[name] for name in by_id], "external_sediment_m3_per_year": sediment_export,
            "external_water_m3_per_year": water_export, "total_bedrock_supply_m3_per_year": supply,
            "total_mobile_change_m3_per_year": mobile,
            "solid_volume_residual_m3_per_year": mobile - (supply - sediment_export)}


def run_benchmark():
    source_before = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if source_before != IMPORTED_SOURCE_SHA256:
        raise ValueError("SPACE implementation changed since import")
    recipe = load_benchmark()
    p = Parameters(**recipe["parameters"])
    expected = recipe["expected"]
    single_spec = recipe["single_cell"]
    state = CellState(**single_spec, bedrock_m=single_spec["surface_m"] - single_spec["cover_m"])
    single = local_rates(state, p)
    network = evaluate_network(recipe["network"], p)
    checks = {}
    for node in [single] + network["nodes"]:
        for field, key in (("erosion_m_per_year", "erosion_m_per_year"),
                           ("entrainment_m_per_year", "entrainment_m_per_year"),
                           ("deposition_m_per_year", "deposition_m_per_year"),
                           ("cover_change_m_per_year", "cover_change_m_per_year"),
                           ("bedrock_change_m_per_year", "bedrock_elevation_change_m_per_year")):
            checks[node["id"] + "." + field] = _close(node[field], expected[key], "rate_m_per_year")
        checks[node["id"] + ".solid_volume_balance"] = _close(
            node["solid_volume_residual_m3_per_year"], 0., "flux_m3_per_year",
            scale=max(abs(node["outgoing_sediment_m3_per_year"]), abs(node["bedrock_supply_m3_per_year"]),
                      abs(node["mobile_change_m3_per_year"]), abs(node.get("incoming_sediment_m3_per_year", 0.))))
    checks["single.slope"] = _close(single["slope"], expected["single_cell_slope"], "slope")
    # The independent head-cell oracle has the same area as the single cell.
    checks["single.outgoing"] = _close(single["outgoing_sediment_m3_per_year"],
                                      expected["network_outgoing_sediment_m3_per_year"][0], "flux_m3_per_year")
    analytical = equilibrium_predictions(state.contributing_area_m2, p)
    checks["analytical.cover"] = _close(analytical["cover_m"], expected["cover_m"], "state_m")
    checks["analytical.slope"] = _close(analytical["slope"], expected["single_cell_slope"], "slope")
    checks["single.cover"] = _close(state.cover_m, expected["cover_m"], "state_m")
    checks["network.ids"] = [n["id"] for n in network["nodes"]] == expected["network_ids"]
    # Defined square areas and their integer sums are exactly representable.
    checks["network.contributing_area_m2"] = [n["contributing_area_m2"] for n in network["nodes"]] == expected["network_area_m2"]
    for field, key in (("incoming_sediment_m3_per_year", "network_incoming_sediment_m3_per_year"),
                       ("outgoing_sediment_m3_per_year", "network_outgoing_sediment_m3_per_year")):
        checks["network." + field] = all(_close(node[field], value, "flux_m3_per_year")
                                         for node, value in zip(network["nodes"], expected[key], strict=True))
    for field in ("external_water_m3_per_year", "external_sediment_m3_per_year",
                  "total_bedrock_supply_m3_per_year", "total_mobile_change_m3_per_year"):
        checks[field] = _close(network[field], expected[field], "flux_m3_per_year")
    checks["network.solid_volume_balance"] = _close(
        network["solid_volume_residual_m3_per_year"], 0., "flux_m3_per_year",
        scale=max(abs(network["total_mobile_change_m3_per_year"]),
                  network["total_bedrock_supply_m3_per_year"], network["external_sediment_m3_per_year"]))
    load_benchmark()  # Recheck contract bytes before returning any successful result.
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != source_before:
        raise ValueError("SPACE implementation changed during evaluation")
    return {"status": "PASS_ANALYTICAL_REFERENCE" if all(checks.values()) else "FAIL_ANALYTICAL_REFERENCE",
            "contract_sha256": BENCHMARK_SHA256, "implementation_sha256": source_before,
            "single_cell": single, "analytical": analytical, "network": network,
            "checks": checks, "tolerances": recipe["tolerances"], "terrain_generated": False,
            "time_integration_performed": False, "physical_acceptance": False,
            "production_authorized": False, "diadem_canon_changed": False}


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), sort_keys=True, indent=2, allow_nan=False))
