"""Immutable SI parameters. Fixtures supply values; kernels invent no Earth profile."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import hashlib
import json

from ._validation import TectonicsError, scalar, text


def identity(record: object) -> str:
    """Parameter identity, separate from the execution/source identity in verify.py."""
    payload = {"schema": "atlas.tectonics.parameters.v1",
               "type": type(record).__name__, "values": asdict(record)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ThermalParameters:
    profile_id: str
    provenance: str
    surface_temperature_k: float
    mantle_temperature_k: float
    diffusivity_m2_s: float

    def __post_init__(self) -> None:
        text(self.profile_id, "profile_id")
        text(self.provenance, "provenance")
        for key in ("surface_temperature_k", "mantle_temperature_k"):
            object.__setattr__(self, key, scalar(getattr(self, key), key, nonnegative=True))
        object.__setattr__(self, "diffusivity_m2_s",
                           scalar(self.diffusivity_m2_s, "diffusivity_m2_s", positive=True))
        if self.mantle_temperature_k < self.surface_temperature_k:
            raise TectonicsError("half-space cooling requires mantle temperature >= surface")


@dataclass(frozen=True, slots=True)
class PlateCoolingParameters:
    """Constant-property conductive plate, not an empirical Earth calibration.

    thermal.mantle_temperature_k is the prescribed temperature AT the plate base,
    not mantle potential temperature. Conductivity/diffusivity fixes volumetric
    heat capacity consistently; no separate, possibly contradictory rho or Cp.
    """
    thermal: ThermalParameters
    thickness_m: float
    conductivity_w_m_k: float

    def __post_init__(self):
        if type(self.thermal) is not ThermalParameters:
            raise TectonicsError('explicit ThermalParameters required')
        for key in ('thickness_m', 'conductivity_w_m_k'):
            object.__setattr__(self, key, scalar(getattr(self, key), key, positive=True))
        scalar(self.volumetric_heat_capacity_j_m3_k, 'volumetric heat capacity', positive=True)

    @property
    def volumetric_heat_capacity_j_m3_k(self):
        return self.conductivity_w_m_k / self.thermal.diffusivity_m2_s


@dataclass(frozen=True, slots=True)
class FlexureParameters:
    profile_id: str
    provenance: str
    young_modulus_pa: float
    elastic_thickness_m: float
    poisson_ratio: float
    density_contrast_kg_m3: float
    gravity_m_s2: float

    def __post_init__(self) -> None:
        text(self.profile_id, "profile_id")
        text(self.provenance, "provenance")
        for field in fields(self):
            key = field.name
            if key not in ("profile_id", "provenance"):
                object.__setattr__(self, key, scalar(getattr(self, key), key,
                                   positive=key != "poisson_ratio"))
        if not -1 < self.poisson_ratio < 0.5:
            raise TectonicsError("isotropic elastic stability requires -1 < nu < 0.5")
        # Refuse numerical overflow/underflow; do not clamp material properties.
        try:
            scalar(self.rigidity_n_m, "derived rigidity", positive=True)
            scalar(self.restoring_pa_per_m, "derived restoring coefficient", positive=True)
        except OverflowError as exc:
            raise TectonicsError("elastic properties exceed numerical range") from exc

    @property
    def rigidity_n_m(self) -> float:
        return (self.young_modulus_pa * self.elastic_thickness_m**3 /
                (12 * (1 - self.poisson_ratio**2)))

    @property
    def restoring_pa_per_m(self) -> float:
        return self.density_contrast_kg_m3 * self.gravity_m_s2


@dataclass(frozen=True, slots=True)
class PeriodicGrid1D:
    """Uniform cell centres; face i is the right-hand face of cell i."""
    cells: int
    length_m: float

    def __post_init__(self) -> None:
        if type(self.cells) is not int or self.cells < 5:
            raise TectonicsError("at least five cells (integer) required")
        object.__setattr__(self, "length_m", scalar(self.length_m, "length_m", positive=True))
        scalar(self.spacing_m, "spacing_m", positive=True)

    @property
    def spacing_m(self) -> float:
        return self.length_m / self.cells
