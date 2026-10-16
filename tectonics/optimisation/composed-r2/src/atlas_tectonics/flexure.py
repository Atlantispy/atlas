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

from ._validation import FloatArray, TectonicsError, read_array as array, frozen, input_shape
from .resources import elements, select_budget
from .parameters import FlexureParameters, PeriodicGrid1D, identity


DEFAULT_FLEXURE_BATCH_BYTES = 8 * 1024**2


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

    def _batch_loads(self, batch_loads: int | None) -> int:
        if batch_loads is None:
            # Amortise setup without creating a full-world spectrum. One row is a
            # coupled physical domain and must never be split to meet this target.
            return max(1, DEFAULT_FLEXURE_BATCH_BYTES // (8 * self.grid.cells))
        if type(batch_loads) is not int or batch_loads <= 0:
            raise TectonicsError("batch_loads must be a positive integer or None")
        return batch_loads

    def work_bytes(self, shape, *, batch_loads: int | None = None) -> int:
        """Bounded array-work estimate, not process RSS or retained operator bytes."""
        batch_loads = self._batch_loads(batch_loads)
        count = elements(shape)
        if not shape or shape[-1] != self.grid.cells or not count:
            raise TectonicsError("load must be nonempty with grid cells in its final dimension")
        rows = count // self.grid.cells
        return 32 * count + 64 * min(rows, batch_loads) * self.grid.cells + 8192

    def solve(self, downward_load_pa: Any, *, budget=None, batch_loads: int | None = None) -> FloatArray:
        """Solve independent loads in bounded row batches, using the same global FFT.

        A row always spans the full periodic domain: never split one coupled load
        into independent spatial tiles. All leading dimensions denote independent
        load cases. Full output is admitted and returned; use solve_batches for a
        stream of independently supplied case batches. The default groups up to
        8 MiB of real load data (at least one full domain); a fitting group keeps
        the previous lower-overhead FFT path. No worker pool is created.
        """
        shape = input_shape(downward_load_pa, "downward_load_pa")
        required = self.work_bytes(shape, batch_loads=batch_loads)
        batch_loads = self._batch_loads(batch_loads)
        with select_budget(budget).reserve(required):
            load = array(downward_load_pa, "downward_load_pa")
            if load.shape != shape:
                raise TectonicsError("input shape changed during capture")
            if load.size // self.grid.cells <= batch_loads:
                # Reuse the proven contiguous FFT path when a group fits. Forcing
                # tiny row groups added overhead without a demonstrated gain.
                with np.errstate(over="ignore", invalid="ignore"):
                    spectrum = np.fft.rfft(load, axis=-1)
                    del load
                    spectrum *= self._gain
                    result = np.fft.irfft(spectrum, n=self.grid.cells, axis=-1)
                    del spectrum
                return frozen(result)
            rows = load.reshape(-1, self.grid.cells)
            result = np.empty(load.shape, dtype=np.float64)
            output = result.reshape(-1, self.grid.cells)
            with np.errstate(over="ignore", invalid="ignore"):
                for start in range(0, rows.shape[0], batch_loads):
                    spectrum = np.fft.rfft(rows[start:start+batch_loads], axis=-1)
                    spectrum *= self._gain
                    np.fft.irfft(spectrum, n=self.grid.cells, axis=-1,
                                 out=output[start:start+batch_loads])
                    del spectrum
            del rows, output, load
            return frozen(result)

    def solve_batches(self, load_batches, *, budget=None, batch_loads: int | None = None):
        """Lazily yield complete, immutable independent case batches; no prefetch.

        The caller controls retained outputs and may stop/close at any yield.
        This is result streaming, not restart, asynchronous work or spatial tiling.
        """
        for loads in load_batches:
            yield self.solve(loads, budget=budget, batch_loads=batch_loads)
            del loads

    def __reduce__(self):
        # Rebuild from the typed definition, never deserialize mutable gain data.
        return (type(self), (self.grid, self.parameters))

    def __deepcopy__(self, memo):
        memo[id(self)] = self
        return self
