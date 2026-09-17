"""E12/E13: uniform periodic 1D flexure, FFT-diagonalised finite differences.

The solved operator is D * (centred second difference)^2 + delta_rho*g,
NOT the continuous spectral k^4 operator. Its smooth-grid error is second order.
There is no variable rigidity, spherical shell, infinite plate or free-edge mode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import math

import numpy as np

from ._validation import FloatArray, TectonicsError, array, frozen, input_shape
from .resources import elements, select_budget
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
        n = self.grid.cells // 2 + 1
        with select_budget(None).reserve(96 * n):
            k = np.arange(n, dtype=np.float64)
            s = 2 * np.sin(np.pi * k / self.grid.cells)
            # Normal-range path retains the existing evaluation. A log-domain
            # path avoids losing D*c when c**4 underflows before multiplication.
            with np.errstate(all="ignore"):
                spatial_scale = s / self.grid.spacing_m
                bending = spatial_scale**4 * self.parameters.rigidity_n_m
                denom = bending + self.parameters.restoring_pa_per_m
                gain = 1 / denom
            risky = ((spatial_scale[1:] < np.finfo(float).tiny**0.25)
                     | (bending[1:] == 0) | ~np.isfinite(bending[1:]))
            if np.any(risky):
                logs = (math.log(self.parameters.rigidity_n_m)
                        + 4 * (np.log(s[1:]) - math.log(self.grid.spacing_m)))
                with np.errstate(all="ignore"):
                    gain[1:] = np.exp(-np.logaddexp(logs,
                                      math.log(self.parameters.restoring_pa_per_m)))
            if np.any(~np.isfinite(gain)) or np.any(gain <= 0):
                raise TectonicsError("flexure transfer outside numerical range")
            object.__setattr__(self, "_gain", frozen(gain))
        # Nested parameters, grid and method name all participate. This is not
        # a historical execution seal or an authentication of a saved result.
        object.__setattr__(self, "operator_id", identity(_OperatorDefinition(
            "periodic-centred-fourth-difference-scaled-binary64-v2", self.grid, self.parameters)))

    @property
    def setup_bytes(self) -> int:
        """Retained coefficient storage only; not total FFT/solver memory."""
        return self._gain.nbytes

    def solve(self, downward_load_pa: Any, *, budget=None) -> FloatArray:
        shape = input_shape(downward_load_pa, "downward_load_pa")
        if not shape or shape[-1] != self.grid.cells:
            raise TectonicsError("load final dimension must equal grid cells")
        with select_budget(budget).reserve(128 * elements(shape)):
            load = array(downward_load_pa, "downward_load_pa")
            if load.ndim < 1 or load.shape[-1] != self.grid.cells:
                raise TectonicsError("load final dimension must equal grid cells")
            with np.errstate(over="ignore", invalid="ignore"):
                return frozen(np.fft.irfft(np.fft.rfft(load, axis=-1) * self._gain,
                                           n=self.grid.cells, axis=-1))

    def __reduce__(self):
        # Rebuild from the typed definition, never deserialize mutable gain data.
        return (type(self), (self.grid, self.parameters))

    def __deepcopy__(self, memo):
        memo[id(self)] = self
        return self
