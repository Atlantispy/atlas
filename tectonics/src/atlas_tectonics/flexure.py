"""E12/E13: uniform periodic 1D flexure, FFT-diagonalised finite differences.

The solved operator is D * (centred second difference)^2 + delta_rho*g,
NOT the continuous spectral k^4 operator. Its smooth-grid error is second order.
There is no variable rigidity, spherical shell, infinite plate or free-edge mode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ._validation import FloatArray, TectonicsError, array, frozen
from .parameters import FlexureParameters, PeriodicGrid1D, identity


@dataclass(frozen=True, slots=True)
class _OperatorDefinition:
    method: str
    grid: PeriodicGrid1D
    parameters: FlexureParameters


@dataclass(frozen=True, slots=True)
class PeriodicFlexure:
    """Reusable immutable operator: load changes reuse setup, material/grid do not.

    No process-global result cache, ownership race or retained input array. A caller
    owns this object's lifetime and storage. solve accepts (...,cells) load batches.
    """
    grid: PeriodicGrid1D
    parameters: FlexureParameters
    _gain: FloatArray = field(init=False, repr=False, compare=False)
    operator_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.grid, PeriodicGrid1D) or not isinstance(self.parameters, FlexureParameters):
            raise TectonicsError("explicit grid and flexure parameters required")
        try:
            with np.errstate(over="raise", divide="raise", invalid="raise", under="ignore"):
                k = np.arange(self.grid.cells // 2 + 1, dtype=np.float64)
                fourth_difference_eigenvalue = (2 * np.sin(np.pi * k / self.grid.cells)
                                                / self.grid.spacing_m)**4
                denominator = (self.parameters.rigidity_n_m * fourth_difference_eigenvalue
                               + self.parameters.restoring_pa_per_m)
                gain = 1 / denominator
                if np.any(gain <= 0):
                    raise TectonicsError("flexure transfer underflow")
        except FloatingPointError as exc:
            raise TectonicsError("flexure operator outside numerical range") from exc
        object.__setattr__(self, "_gain", frozen(gain))
        # Nested parameters, grid and method name all participate. This is not
        # a historical execution seal or an authentication of a saved result.
        object.__setattr__(self, "operator_id", identity(_OperatorDefinition(
            "periodic-centred-fourth-difference-binary64-v1", self.grid, self.parameters)))

    @property
    def setup_bytes(self) -> int:
        """Retained coefficient storage only; not total FFT/solver memory."""
        return self._gain.nbytes

    def solve(self, downward_load_pa: Any) -> FloatArray:
        load = array(downward_load_pa, "downward_load_pa")
        if load.ndim < 1 or load.shape[-1] != self.grid.cells:
            raise TectonicsError("load final dimension must equal grid cells")
        with np.errstate(over="ignore", invalid="ignore"):
            return frozen(np.fft.irfft(np.fft.rfft(load, axis=-1) * self._gain,
                                       n=self.grid.cells, axis=-1))
