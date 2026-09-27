"""I01 constant-rigidity periodic 2D plate plus finite connected water.

WORKING NON-CANON. Static closure control, not regional/global integration.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
import argparse
from concurrent.futures import CancelledError
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import platform
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
POLICY = dict(max_axis=128, max_iterations=64, rms_error_m=1e-6,
              volume_relative_tolerance=1e-11, force_relative_tolerance=1e-7,
              refinement_relative_tolerance=.005, benchmark_repetitions=5)


def scalar(value, name, minimum=0.):
    if isinstance(value, (bool, str, bytes)):
        raise ValueError(name+" must be numeric")
    value = float(value)
    if not math.isfinite(value) or value < minimum:
        raise ValueError(name+" outside finite support")
    return value


def array(value, shape):
    a = np.asarray(value)
    if a.shape != shape or a.dtype.kind not in "fiu" or not np.all(np.isfinite(a)):
        raise ValueError("matching finite real grid required")
    return np.array(a, dtype=float, copy=True)


def _fill(bed, mean_depth, previous_wet=None):
    """Equal-area finite-volume projection; verify a reused wet set exactly."""
    if mean_depth == 0:
        return None, np.zeros_like(bed), np.zeros(bed.shape, dtype=bool), False
    base = float(np.min(bed))
    z = bed-base
    total = mean_depth*bed.size
    if previous_wet is not None and np.any(previous_wet):
        level = (total+float(np.sum(z[previous_wet])))/np.count_nonzero(previous_wet)
        if np.array_equal(z < level, previous_wet):
            return base+level, np.maximum(level-z, 0.), previous_wet, True
    ordered = np.sort(z.ravel())
    count = np.arange(1, bed.size+1)
    levels = (total+np.cumsum(ordered))/count
    candidates = np.flatnonzero(levels[:-1] <= ordered[1:])
    index = int(candidates[0]) if candidates.size else bed.size-1
    level = float(levels[index])
    return base+level, np.maximum(level-z, 0.), z < level, False


@dataclass(frozen=True)
class Plate:
    """Immutable constant-D FFT setup. Shape order is (ny,nx)."""
    shape: tuple[int, int]
    length_x_m: float
    length_y_m: float
    elastic_thickness_m: float
    young_pa: float = 70e9
    poisson: float = .25
    rho_m_kg_m3: float = 3300.
    rho_w_kg_m3: float = 1000.
    gravity_m_s2: float = 9.81
    _stiffness: np.ndarray = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if (type(self.shape) is not tuple or len(self.shape) != 2 or
            any(type(n) is not int or not 4 <= n <= POLICY["max_axis"] for n in self.shape)):
            raise ValueError("two grid axes of 4..128 cells required")
        for key in ("length_x_m", "length_y_m", "elastic_thickness_m", "young_pa",
                    "poisson", "rho_m_kg_m3", "rho_w_kg_m3", "gravity_m_s2"):
            object.__setattr__(self, key, scalar(getattr(self, key), key))
        if (min(self.length_x_m, self.length_y_m, self.young_pa, self.rho_m_kg_m3,
                self.rho_w_kg_m3, self.gravity_m_s2) <= 0 or not 0 <= self.poisson < .5
                or not self.rho_w_kg_m3 < self.rho_m_kg_m3):
            raise ValueError("positive scale/moduli and water less dense than mantle required")
        ny, nx = self.shape
        kx = 2*np.pi*np.fft.rfftfreq(nx, self.length_x_m/nx)
        ky = 2*np.pi*np.fft.fftfreq(ny, self.length_y_m/ny)
        stiffness = self.rigidity_n_m*(kx[None, :]**2+ky[:, None]**2)**2+self.dry_k
        if not np.all(np.isfinite(stiffness)) or np.any(stiffness <= 0):
            raise ValueError("unrepresentable flexural operator")
        # bytes-backed view cannot be made writable by a caller.
        object.__setattr__(self, "_stiffness", np.frombuffer(stiffness.tobytes(), dtype=float).reshape(stiffness.shape))

    @property
    def rigidity_n_m(self):
        return self.young_pa*self.elastic_thickness_m**3/(12*(1-self.poisson**2))

    @property
    def dry_k(self):
        return self.rho_m_kg_m3*self.gravity_m_s2

    @property
    def density_ratio(self):
        return self.rho_w_kg_m3/self.rho_m_kg_m3

    def _response(self, load):
        return np.fft.irfft2(np.fft.rfft2(load)/self._stiffness, s=self.shape)

    def equilibrium(self, unloaded_bed_m, volume_m3, *, geometry, connectivity,
                    initial_displacement_m=None, cancel=None, reuse_wet_set=True):
        """Total equilibrium relative to water-unloaded bed, never an increment.

        A changed volume may reuse setup and an initial guess; every result is
        solved again. No stored result/sea level is accepted merely by identity.
        """
        if geometry != "periodic_flat_plate" or connectivity != "one_communicating_reservoir":
            raise ValueError("only the explicit periodic/communicating-water contract is supported")
        if type(reuse_wet_set) is not bool:
            raise ValueError("reuse_wet_set must be boolean")
        z0 = array(unloaded_bed_m, self.shape)
        v = scalar(volume_m3, "volume")
        area = self.length_x_m*self.length_y_m
        mean = v/area
        if not math.isfinite(mean) or (v > 0 and mean <= 0):
            raise ValueError("unrepresentable water amount")
        w = np.zeros(self.shape) if initial_displacement_m is None else array(initial_displacement_m, self.shape)
        # Work relative to one datum to keep water filling insensitive to offset.
        datum = float(np.min(z0))
        z = z0-datum
        if not np.all(np.isfinite(z)):
            raise ValueError("unrepresentable bed differences")
        q = self.density_ratio
        wet, reused, fills = None, 0, 0
        for iteration in range(1, POLICY["max_iterations"]+1):
            if cancel is not None and cancel.is_set():
                raise CancelledError("water/flexure cancelled; no result published")
            _, depth, wet, hit = _fill(z-w, mean, wet if reuse_wet_set else None)
            reused += int(hit)
            fills += 1
            next_w = self._response(self.rho_w_kg_m3*self.gravity_m_s2*depth)
            change = float(np.sqrt(np.mean((next_w-w)**2)))
            bound = q/(1-q)*change  # Bound on NEW iterate in RMS norm.
            w = next_w
            if math.isfinite(bound) and bound <= POLICY["rms_error_m"]:
                break
        else:
            raise ValueError("coupled equilibrium iteration budget exhausted")
        level, depth, wet, hit = _fill(z-w, mean, wet if reuse_wet_set else None)
        reused += int(hit)
        fills += 1
        load = self.rho_w_kg_m3*self.gravity_m_s2*depth
        force = np.fft.irfft2(np.fft.rfft2(w)*self._stiffness, s=self.shape)
        force_error = float(np.linalg.norm(force-load)/max(1., np.linalg.norm(load)))
        residual_estimate = float(np.sqrt(np.mean((force-load)**2)))/(self.dry_k*(1-q))
        volume_error = abs(float(np.mean(depth))-mean)/mean if v else 0.
        mean_error = abs(float(np.mean(w))-q*mean)/max(1., q*mean)
        virtual_work = float(np.mean(w*load))*area
        stored_energy = .5*float(np.mean(w*force))*area
        if (not all(np.all(np.isfinite(a)) for a in (w, depth, force, load, z0-w))
                or force_error > POLICY["force_relative_tolerance"]
                or volume_error > POLICY["volume_relative_tolerance"]
                or mean_error > POLICY["volume_relative_tolerance"]):
            raise ValueError("returned water volume or coupled force residual failed")
        # Forebulge uplift (w<0) is physical, never clipped to positive values.
        return dict(displacement_m=w, bed_m=z0-w, depth_m=depth,
                    sea_level_m=None if level is None else datum+level,
                    iterations=iteration, wet_set_reuses=reused, water_fills=fills,
                    rms_iteration_error_estimate_m=bound,
                    rms_residual_error_estimate_m=residual_estimate,
                    mean_subsidence_relative_residual=mean_error,
                    volume_relative_residual=volume_error,
                    force_relative_residual=force_error,
                    plate_stored_energy_j=stored_energy,
                    load_displacement_product_j=virtual_work,
                    virtual_work_relative_residual=abs(2*stored_energy-virtual_work)/max(1., abs(virtual_work)))


ARGS = dict(geometry="periodic_flat_plate", connectivity="one_communicating_reservoir")


def fixture(n, spec):
    plate = Plate((n, n), **spec["plate"])
    x = 2*np.pi*np.arange(n)/n
    y = x[:, None]
    bed = 500*np.cos(x)[None, :]+300*np.cos(y)+80*np.sin(x[None, :]+y)
    return plate, bed, spec["mean_depth_m"]*plate.length_x_m*plate.length_y_m


def compact(result):
    return {k: v for k, v in result.items() if not isinstance(v, np.ndarray)} | dict(
        max_depth_m=float(result["depth_m"].max()),
        max_downward_displacement_m=float(result["displacement_m"].max()),
        min_downward_displacement_m=float(result["displacement_m"].min()),
        wet_fraction=float(np.mean(result["depth_m"] > 0)))


def campaign(spec):
    results, records = [], []
    for n in spec["grids"]:
        plate, bed, volume = fixture(n, spec)
        start = time.perf_counter()
        r = plate.equilibrium(bed, volume, **ARGS)
        records.append(dict(cells=n*n, seconds=time.perf_counter()-start, result=compact(r)))
        results.append(r)
    changes = [float(np.sqrt(np.mean((a["displacement_m"]-b["displacement_m"][::2, ::2])**2)))/spec["mean_depth_m"]
               for a, b in zip(results, results[1:])]
    plate, bed, volume = fixture(spec["grids"][-1], spec)
    # Same prepared operator, same problem and tolerances; compare only whether
    # a verified wet set avoids sorting again. Alternate order to reduce drift.
    timings = {"resort": [], "verified_reuse": []}
    answers = {}
    for i in range(POLICY["benchmark_repetitions"]):
        for label in (("resort", "verified_reuse") if i % 2 == 0 else ("verified_reuse", "resort")):
            start = time.perf_counter()
            answers[label] = plate.equilibrium(bed, volume, **ARGS, reuse_wet_set=label == "verified_reuse")
            timings[label].append(time.perf_counter()-start)
    old, new = (float(np.median(timings[k])) for k in ("resort", "verified_reuse"))
    parity = float(np.max(abs(answers["resort"]["displacement_m"]-answers["verified_reuse"]["displacement_m"])))
    return dict(passed=bool(changes[-1] < POLICY["refinement_relative_tolerance"] and parity < 1e-7),
                grids=records, displacement_rms_refinement_relative=changes,
                benchmark=dict(samples_seconds=timings, resort_median_seconds=old,
                    reuse_median_seconds=new, saved_seconds=old-new, saved_percent=100*(old-new)/old,
                    max_displacement_difference_m=parity,
                    scope="five interleaved small coupled solves per method, not generator-wide speedup"))


def bindings():
    names = ["tools/check_i01_water_flexure.py", "tests/test_i01_water_flexure.py",
             "cases/i01_water_flexure_v1.json", "docs/I01_WATER_FLEXURE.md"]
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        start = time.perf_counter()
        report = dict(schema="atlas.i01-water-flexure.v1", status="INCOMPLETE", scientific_acceptance=False,
                      runtime=dict(python=platform.python_version(), numpy=np.__version__, system=platform.system()))
        try:
            report["source_sha256"] = bindings()
            spec = json.loads((ROOT/"cases/i01_water_flexure_v1.json").read_text(encoding="utf-8"))
            if spec["policy"] != POLICY:
                raise ValueError("case policy differs from executable")
            report.update(campaign(spec))
            report["source_unchanged"] = report["source_sha256"] == bindings()
            report["status"] = "PASS_BOUNDED_CONTROLS_ONLY" if report["passed"] and report["source_unchanged"] else "FAIL"
        except Exception as exc:
            report.update(status="FAIL", error_type=type(exc).__name__, error=str(exc))
        report["elapsed_seconds"] = time.perf_counter()-start
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps({k: report[k] for k in ("status", "elapsed_seconds")}))
    return 0 if report["status"] == "PASS_BOUNDED_CONTROLS_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
