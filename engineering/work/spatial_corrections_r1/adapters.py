"""Callable, source-pinned successors of the actual producers' spatial substages.

Only selected assignment statements are executed, not their top-level I/O or later
physical/political models. Pins protect source identity, not domain/canon acceptance.
No historical module import, monkey-patch, map write, or installed-runtime mutation.
"""
import ast
from dataclasses import dataclass
import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from .grid import Grid, SpatialError, categorical, intensive, sample_cells


WORKSPACE = Path(__file__).resolve().parents[2]
PINS = {
    "b1a3": {
        "path": WORKSPACE / "work/terrain_optimisation_r1/b1a3/candidate/build_r32d_b1a3_natural_basins.py",
        "sha256": "bfcf978a34353598b76941bcf2f34f853060f4f24f958b0a6bdfc32476061c47",
        "bytes": 45488,
    },
    "c1r7": {
        "path": WORKSPACE / "work/terrain_optimisation_r1/c1r7/candidate_parallel/build_clean.py",
        "sha256": "5f0cbc20febf7db5c3a00a9f38d84f2123aff759a824f493218c3d4114eb9a12",
        "bytes": 22635,
    },
    "political": {
        "path": Path("C:/Users/LOCAL_USER/Documents/Codex/2026-07-11/referenced-chatgpt-conversation-this-is-untrusted/work/political_borders/p4_contiguous_candidate/build_p4_candidate_f_natural_units.py"),
        "sha256": "ccd6939326ab6c27fc997daa2054aa4349c8158d320f2db958c49f4cbb09a2f3",
        "bytes": 13673,
    },
}


class SourcePinError(SpatialError):
    pass


@dataclass(frozen=True)
class PreparedFields:
    fields: dict[str, np.ndarray]
    grid: Grid
    receipt: dict


def _source(key):
    pin = PINS[key]
    raw = pin["path"].read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != pin["sha256"] or len(raw) != pin["bytes"]:
        raise SourcePinError(f"{key} source identity changed; explicit reviewed rebind required")
    return raw, {"source": str(pin["path"]), "sha256": digest, "bytes": len(raw)}


def verify_sources():
    return {key: _source(key)[1] for key in PINS}


def _assignments(raw, key, ranges, expected):
    """Compile exact predecessor assignment ASTs, verified by source hash AND
    output target names. Never execute its imports/top-level loading/publication.
    compile(optimize=0) also avoids inheriting a caller's Python -O setting.
    """
    tree = ast.parse(raw.decode("utf-8-sig"), filename=str(PINS[key]["path"]))
    selected = sorted((node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                       and any(lo <= node.lineno <= hi for lo, hi in ranges)),
                      key=lambda n: (n.lineno, n.col_offset))
    names = []
    for node in selected:
        for target in node.targets:
            names.extend(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
    if names != list(expected):
        raise SourcePinError(f"{key} assignment shape no longer matches reviewed block")
    block = ast.Module(body=selected, type_ignores=[])
    return compile(block, str(PINS[key]["path"]), "exec", dont_inherit=True, optimize=0)


def _scope():
    return {"np": np, "__builtins__": {"bool": bool, "min": min, "max": max}}


def _check_grid(grid):
    if (grid.units != "km" or grid.origin_x != 0 or grid.origin_y != 0 or
            grid.step_x != 4 or grid.step_y != 4):
        raise SpatialError("retained producer requires corner origin (0,0), positive 4 km source cells")


def _check_fields(fields, keys, grid, binary=()):
    for key in keys:
        if key not in fields:
            raise SpatialError(f"missing producer input field: {key}")
        a = np.asarray(fields[key])
        if (a.shape != grid.shape or a.dtype.kind not in "buif" or
                not np.isfinite(a).all()):
            raise SpatialError(f"{key}: complete finite 2D values on the declared source grid required")
        if key in binary and not np.isin(a, [0, 1]).all():
            raise SpatialError(f"{key}: binary mask required; unknown cannot become True")


def _strict_shape(a, rows, cols):
    if a.shape != (rows, cols):
        raise SpatialError("resampling shape mismatch; historical crop/pad fallback is forbidden")
    return a


def _resample(a, source, target, order):
    result = (categorical(a, source, target) if order == 0 else
              intensive(a, source, target, order=order))
    if not result.valid.all():
        raise SpatialError("producer cannot consume unknown/out-of-frame resampled cells")
    return result.values


def prepare_b1a3_fields(a2, r11, r30, source_grid, target_grid):
    """Execute B1A3's actual 11 spatial preparation assignments with corrected
    centres/coverage, including the two later structural masks. Other terrain/model
    operations are deliberately NOT executed or claimed corrected.
    """
    _check_grid(source_grid)
    if (source_grid.units != target_grid.units or target_grid.step_x <= 0 or
            target_grid.step_y != target_grid.step_x or
            not np.allclose(source_grid.bounds, target_grid.bounds, rtol=0, atol=1e-10)):
        raise SpatialError("B1A3 target must be isotropic positive cells over exactly the same extent")
    a2_keys = ("predicted_conditioned_surface_m", "sea_mask", "inward_mask", "crown_mask")
    r11_keys = ("competence_prior", "erodibility_prior", "fracture_prior",
                "crown_support", "provisional_surface_m")
    r30_keys = ("crown_divide_mask_public", "actual_outlet_route_mask_public")
    _check_fields(a2, a2_keys, source_grid, a2_keys[1:])
    _check_fields(r11, r11_keys, source_grid)
    _check_fields(r30, r30_keys, source_grid, r30_keys)
    raw, receipt = _source("b1a3")
    scope = _scope()
    for fields, lines, names in (
        (a2, [(609, 612)], ("coarse_surface", "coarse_sea", "coarse_inward", "coarse_crown")),
        (r11, [(614, 618)], ("comp4", "erod4", "frac4", "crown_support4", "accepted_r11_surface4")),
        (r30, [(687, 688)], ("divide4", "outlet_route4")),
    ):
        scope["z"] = fields
        exec(_assignments(raw, "b1a3", lines, names), scope)
    factor = source_grid.step_x/target_grid.step_x

    def resize(a, requested_factor, order):
        if requested_factor != factor:
            raise SpatialError("unexpected producer scaling factor")
        return _resample(a, source_grid, target_grid, order)

    scope.update(resize=resize, exact_shape=_strict_shape, factor=factor,
                 rows=target_grid.shape[0], cols=target_grid.shape[1])
    names = ("surface", "sea", "inward", "crown", "comp", "erod", "frac",
             "crown_support", "accepted_r11_surface", "divide", "outlet_route")
    exec(_assignments(raw, "b1a3", [(624, 632), (689, 690)], names), scope)
    _source("b1a3")
    receipt.update(status="WORKING NON-CANON / REVIEW-ONLY SCIENTIFIC SUCCESSOR",
                   executed_assignments=[[609, 612], [614, 618], [624, 632], [687, 688], [689, 690]],
                   changed="cell-centred transform; containing-cell masks; reject crop/pad mismatch",
                   downstream_model_executed=False, exact_replay=False)
    return PreparedFields({name: scope[name] for name in names}, target_grid, receipt)


def prepare_c1r7_fields(r11, source_grid):
    """Execute C1R7's actual sea-crop and 4 km -> 500 m spatial preparation.
    Private ndimage facade replaces ONLY the five zoom expressions, never global
    scipy state. Cropped grid origin is preserved by the producer's own x/y lines.
    """
    _check_grid(source_grid)
    keys = ("provisional_surface_m", "derived_sea_mask", "competence_prior",
            "erodibility_prior", "fracture_prior")
    _check_fields(r11, keys, source_grid, ("derived_sea_mask",))
    if not np.asarray(r11["derived_sea_mask"]).any():
        raise SpatialError("C1R7 crop requires an explicit nonempty sea mask")
    raw, receipt = _source("c1r7")
    scope = _scope()
    grids = []

    def zoom(a, factor, order, mode=None):
        if factor != 8 or order not in (0, 1, 3) or mode not in (None, "nearest"):
            raise SpatialError("unexpected C1R7 spatial operation")
        cropped = source_grid.crop(scope["r4a"], scope["r4b"], scope["c4a"], scope["c4b"])
        target = Grid((cropped.shape[0]*8, cropped.shape[1]*8),
                      cropped.origin_x, cropped.origin_y, .5, .5)
        grids.append(target)
        return _resample(a, cropped, target, order)

    scope.update(z=r11, CELL=.5, ndimage=SimpleNamespace(zoom=zoom))
    names = ("surface4", "sea4", "inside4", "comp4", "erod4", "frac4", "rr", "cc",
             "r4a", "r4b", "c4a", "c4b", "zoom", "surface", "old", "comp", "erod",
             "frac", "r0", "c0", "rows", "cols", "x", "y", "yy", "xx")
    exec(_assignments(raw, "c1r7", [(81, 99)], names), scope)
    if len(grids) != 5 or any(g != grids[0] for g in grids):
        raise SpatialError("C1R7 fields did not use one shared spatial transform")
    x, y = grids[0].centres()
    if not np.array_equal(x, scope["x"]) or not np.array_equal(y, scope["y"]):
        raise SpatialError("C1R7 declared coordinates differ from actual remap coordinates")
    _source("c1r7")
    receipt.update(status="WORKING NON-CANON / REVIEW-ONLY SCIENTIFIC SUCCESSOR",
                   executed_assignments=[[81, 99]], crop_rows=[int(scope["r4a"]), int(scope["r4b"])],
                   crop_cols=[int(scope["c4a"]), int(scope["c4b"])],
                   changed="cell-centred transform and containing-cell sea mask",
                   downstream_model_executed=False, exact_replay=False,
                   physical_mouths="BLOCKED: native hydraulic contacts are not provided by this substage")
    fields = {name: scope[name] for name in ("surface", "old", "comp", "erod", "frac", "x", "y")}
    return PreparedFields(fields, grids[0], receipt)


def sample_political_evidence(evidence, x, y, grid):
    """Execute the political producer's eight actual evidence-sampling assignments.
    Inputs are already normalised/cache-aligned evidence; this does not endorse its
    normalisation, centroids, seed ownership, reach model, or categorical averaging.
    Every band uses the same explicit grid; missing/out-of-frame samples raise.
    """
    names = ("access", "barrier", "shore", "elev", "relief", "grass", "hs", "res")
    if any(name not in evidence for name in names):
        raise SpatialError("all eight political evidence fields are required")
    raw, receipt = _source("political")
    scope = _scope()

    def sample4(a, px, py):
        result = sample_cells(a, grid, px, py)
        if not result.valid.all():
            raise SpatialError("political evidence sample is unknown")
        return result.values

    scope.update({name: evidence[name] for name in names})
    scope.update(sample4=sample4, x=x, y=y)
    outnames = ("ua", "ub", "us", "ue", "ur", "ug", "uh", "ures")
    exec(_assignments(raw, "political", [(75, 76)], outnames), scope)
    _source("political")
    receipt.update(status="WORKING NON-CANON / REVIEW-ONLY SCIENTIFIC SUCCESSOR",
                   executed_assignments=[[75, 76]], changed="affine inverse containing-cell lookup",
                   political_assignment_executed=False, exact_replay=False)
    return PreparedFields({name: scope[name] for name in outnames}, grid, receipt)


def require_native_contacts(*, representation):
    """Explicit fail-closed boundary, NOT a native mouth generator or validator.
    Even a caller's 'native' label alone is insufficient hydraulic evidence.
    """
    raise SpatialError("native hydraulic contacts are not implemented in this package; "
                       f"{representation!r} cannot be used as a validated physical river mouth")
