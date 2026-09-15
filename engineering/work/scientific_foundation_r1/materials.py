"""Finite persistent material columns; exact mass reference, not soil prediction.

Layers are bottom-to-top. Removing the surface exposes the next actual material;
deposition never changes the identity or porosity of buried material. Fractions
are bounded-reference arithmetic, not a proposed large-raster storage backend.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
import math


def exact(value, name, *, positive=False):
    if type(value) not in (int, float, Fraction):
        raise ValueError(name + " requires an explicit physical quantity")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(name + " must be finite")
    result = Fraction(value)
    if result <= 0 if positive else result < 0:
        raise ValueError(name + " outside supported range")
    return result


@dataclass(frozen=True)
class PhysicalProperty:
    name: str
    value: float | None
    unit: str
    evidence: str
    status: str

    def require(self, name, unit):
        if self.name != name or self.unit != unit:
            raise ValueError("property meaning/units mismatch; no ordinal-to-physical conversion")
        if self.status in {"UNKNOWN", "CONFLICT", "INCOMPLETE"} or self.value is None:
            raise ValueError("required physical property is unresolved")
        if self.status not in {"CANON", "WORKING NON-CANON", "SYNTHETIC TEST"} or not self.evidence:
            raise ValueError("physical property needs explicit source status and evidence")
        return exact(self.value, name)


@dataclass(frozen=True)
class Layer:
    material_id: str
    mass_kg: Fraction
    grain_density_kg_m3: Fraction
    porosity: Fraction
    phase: str
    evidence: str

    def __post_init__(self):
        if not isinstance(self.material_id, str) or not self.material_id.strip() or not isinstance(self.evidence, str) or not self.evidence.strip():
            raise ValueError("material identity and evidence required")
        if self.phase not in {"bedrock", "immobile_regolith", "mobile_sediment", "organic"}:
            raise ValueError("unknown material phase")
        for name in ("mass_kg", "grain_density_kg_m3", "porosity"):
            object.__setattr__(self, name, exact(getattr(self, name), name, positive=name != "porosity"))
        if self.porosity >= 1:
            raise ValueError("porosity must be below one")

    @property
    def bulk_volume_m3(self):
        return self.mass_kg / self.grain_density_kg_m3 / (1 - self.porosity)


@dataclass(frozen=True)
class Column:
    area_m2: Fraction
    basal_elevation_m: Fraction
    layers: tuple[Layer, ...]
    source_status: str

    def __post_init__(self):
        object.__setattr__(self, "area_m2", exact(self.area_m2, "area_m2", positive=True))
        if type(self.basal_elevation_m) not in (int, float, Fraction):
            raise ValueError("basal elevation must be explicit")
        object.__setattr__(self, "basal_elevation_m", Fraction(self.basal_elevation_m))
        if not isinstance(self.layers, tuple) or len(self.layers) > 4096 or any(not isinstance(x, Layer) for x in self.layers):
            raise ValueError("bounded immutable ordered layer tuple required")
        if self.source_status not in {"CANON", "WORKING NON-CANON", "SYNTHETIC TEST"}:
            raise ValueError("unresolved source cannot instantiate physical material stock")

    @property
    def surface_m(self):
        return self.basal_elevation_m + sum((x.bulk_volume_m3 for x in self.layers), Fraction()) / self.area_m2

    @property
    def mass_kg(self):
        return sum((x.mass_kg for x in self.layers), Fraction())

    @property
    def exposed(self):
        return self.layers[-1] if self.layers else None

    def deposit(self, layer):
        if not isinstance(layer, Layer):
            raise ValueError("a material-bearing deposit is required")
        return replace(self, layers=(*self.layers, layer))

    def strip_mass(self, requested_mass_kg):
        """Top-down physical removal, returning parcels in removal order.

        The demanded mass is supplied by a validated process, NOT predicted by
        this state container. Finite stock exhaustion leaves explicit unmet mass.
        No mixing or invented infinite underlying rock is introduced.
        """
        request = exact(requested_mass_kg, "requested_mass_kg")
        left = request
        layers = list(self.layers)
        removed = []
        while left and layers:
            layer = layers.pop()
            taken = min(left, layer.mass_kg)
            removed.append(replace(layer, mass_kg=taken))
            if taken < layer.mass_kg:
                layers.append(replace(layer, mass_kg=layer.mass_kg-taken))
            left -= taken
        after = replace(self, layers=tuple(layers))
        receipt = {"removed_layers": tuple(removed), "unmet_mass_kg": left,
                   "mass_residual_kg": self.mass_kg-after.mass_kg-sum((x.mass_kg for x in removed), Fraction()),
                   "surface_lowering_m": self.surface_m-after.surface_m}
        if receipt["mass_residual_kg"] != 0:
            raise ArithmeticError("column mass does not close")
        return after, receipt

    def as_dict(self):
        def pair(value):
            return [value.numerator, value.denominator]
        return {"schema": "diadem.material-column.r1", "area_m2": pair(self.area_m2),
                "basal_elevation_m": pair(self.basal_elevation_m), "source_status": self.source_status,
                "layers": [{**vars(x), **{k: pair(getattr(x, k)) for k in ("mass_kg", "grain_density_kg_m3", "porosity")}} for x in self.layers]}

    @classmethod
    def from_dict(cls, data):
        if set(data) != {"schema", "area_m2", "basal_elevation_m", "source_status", "layers"} or data["schema"] != "diadem.material-column.r1":
            raise ValueError("invalid material column schema")
        def unpack(value):
            if not isinstance(value, list) or len(value) != 2 or any(type(x) is not int for x in value) or value[1] <= 0:
                raise ValueError("exact numerator/positive denominator required")
            return Fraction(*value)
        layers = []
        for row in data["layers"]:
            values = dict(row)
            for key in ("mass_kg", "grain_density_kg_m3", "porosity"):
                values[key] = unpack(values[key])
            layers.append(Layer(**values))
        return cls(unpack(data["area_m2"]), unpack(data["basal_elevation_m"]), tuple(layers), data["source_status"])
