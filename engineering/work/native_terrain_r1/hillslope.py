"""Native terrain R1 requested BULK hillslope fluxes; WORKING NON-CANON.

This successor reuses R7's face law and numerical primitives, never its driver.
It does not mutate terrain or convert bulk volume to constituent solid volume.
The caller selects exposed mobile layers, allocates all simultaneous demands,
and debits/deposits the exact native constituents. Returned source scales are
diagnostics; they are not an applied transaction.
"""
from __future__ import annotations

import math

from work.terrain_model_r7.hillslope_kernel import (
    CONTRACT, Grid, _harmonic_mean, _positive_product, field, gradients, number,
)


class HillslopeStepTooLarge(ValueError):
    """Valid hillside regime, but the explicit interval needs refinement."""


def _external_faces(grid, declarations, periodic_x):
    """Validate explicitly declared exterior faces; no implicit crop outlets."""
    if type(declarations) not in (tuple, list):
        raise ValueError("external_faces requires an explicit list or tuple")
    result = []
    ids, positions = set(), set()
    required = {"id", "cell", "elevation_m", "distance_m", "width_m", "axis", "evidence"}
    for supplied in declarations:
        if type(supplied) is not dict or set(supplied) != required:
            raise ValueError("external face requires exact geometry and evidence fields")
        face = dict(supplied)
        if not isinstance(face["id"], str) or not face["id"] or face["id"] in ids:
            raise ValueError("unique nonempty external face ID required")
        if not isinstance(face["evidence"], str) or not face["evidence"].strip():
            raise ValueError("external face evidence required")
        cell = face["cell"]
        if type(cell) is not int or not 0 <= cell < grid.size:
            raise ValueError("external face cell outside grid")
        row, col = divmod(cell, grid.cols)
        allowed = {"x-": col == 0 and not periodic_x,
                   "x+": col == grid.cols - 1 and not periodic_x,
                   "y-": row == 0, "y+": row == grid.rows - 1}
        axis = face["axis"]
        if not isinstance(axis, str) or not allowed.get(axis, False):
            raise ValueError("external face must be on a declared nonperiodic exterior")
        if (cell, axis) in positions:
            raise ValueError("duplicate external face geometry")
        face["elevation_m"] = number(face["elevation_m"], "boundary elevation")
        face["distance_m"] = number(face["distance_m"], "boundary distance", 0, True)
        face["width_m"] = number(face["width_m"], "boundary width", 0, True)
        full_width = grid.dy_m if axis[0] == "x" else grid.dx_m
        if face["width_m"] > full_width:
            raise ValueError("external face width exceeds the physical cell face")
        ids.add(face["id"])
        positions.add((cell, axis))
        result.append(face)
    return sorted(result, key=lambda item: item["id"])


def face_requests(grid, surface_m, available_bulk_m3, diffusivity_m2_year,
                  dt_years, critical_gradient=None, *, periodic_x=False,
                  receiving_expansion_max=1.0, external_faces=()):
    """Return synchronous, unallocated, downhill bulk-volume requests in m3.

    K is m2/year; dt is years. ``receiving_expansion_max`` is the caller's
    declared worst receiver-bulk/donor-bulk ratio (at least one), including
    all possible material/packing changes. No global density is assumed.

    Each external face is an outward numerical port with explicit ID, cell,
    elevation_m, distance_m, width_m, axis (x-/x+/y-/y+), and evidence. A fixed
    toe located at a cell face uses half-cell distance. Uphill boundary import
    is rejected because no external finite source has been declared. Closed
    faces are omitted. External requests are not a completed export ledger.

    Nonlinear applicability uses the full normal and transverse face slope.
    Bare donor stock or zero K disables its law, including on bare cliffs.
    The R7 conservative maximum-diffusivity CFL is retained, strengthened by
    an actual face-conductance bound for explicit short boundary distances.
    """
    if not isinstance(grid, Grid):
        raise ValueError("validated Grid required")
    if type(periodic_x) is not bool:
        raise ValueError("periodic_x must be Boolean")
    n = grid.size
    z = field(surface_m, n, "surface_m")
    available = field(available_bulk_m3, n, "available_bulk_m3", 0)
    k = field(diffusivity_m2_year, n, "diffusivity", 0)
    dt = number(dt_years, "dt_years", 0, True)
    expansion = number(receiving_expansion_max, "receiving_expansion_max", 1)
    critical = None if critical_gradient is None else field(
        critical_gradient, n, "critical gradient", 0)
    boundaries = _external_faces(grid, external_faces, periodic_x)
    gradient = gradients(grid, z, periodic_x=periodic_x)
    faces = []
    conductance = [[] for _ in range(n)]
    maximum_d = 0.0

    def request(identifier, donor, receiver, normal, tangent, coefficient,
                critical_value, distance, width, axis, boundary=None):
        nonlocal maximum_d
        if normal == 0 or available[donor] == 0:
            return
        normal = number(normal, "face normal gradient", 0, True)
        norm = number(math.hypot(normal, tangent), "full face gradient", 0)
        ratio = 0.0
        if critical_value is not None:
            if critical_value <= 0 or norm >= critical_value:
                raise ValueError("soil transport outside declared critical-gradient regime")
            ratio = (norm / critical_value) ** 2
            if ratio >= 1:
                raise ValueError("critical-gradient margin is not representable")
        effective = _positive_product(
            (coefficient, (1 + ratio) / (1 - ratio) ** 2, expansion),
            "effective face diffusivity")
        maximum_d = max(maximum_d, effective)
        diagonal_rate = _positive_product(
            (effective, width, 1 / distance, 1 / grid.area_m2),
            "face response rate")
        conductance[donor].append(diagonal_rate)
        if receiver is not None:
            conductance[receiver].append(diagonal_rate)
        amount = _positive_product(
            (coefficient, normal, 1 / (1 - ratio), width, dt),
            "requested face bulk volume")
        record = {"id": identifier, "donor": donor, "receiver": receiver,
                  "axis": axis, "distance_m": distance, "width_m": width,
                  "requested_bulk_m3": amount,
                  "face_gradient_m_per_m": norm,
                  "effective_diffusivity_m2_year": effective,
                  "boundary_id": None, "evidence": None}
        if boundary is not None:
            record.update(boundary_id=boundary["id"], evidence=boundary["evidence"],
                          boundary_elevation_m=boundary["elevation_m"])
        faces.append(record)

    for i in range(n):
        row, col = divmod(i, grid.cols)
        right = i + 1 if col + 1 < grid.cols else (row * grid.cols if periodic_x else n)
        for j, distance, width, tangent, axis in (
                (right, grid.dx_m, grid.dy_m, "dz_dy", "x"),
                (i + grid.cols, grid.dy_m, grid.dx_m, "dz_dx", "y")):
            if j >= n or k[i] == 0 or k[j] == 0:
                continue
            normal = (z[i] - z[j]) / distance
            if normal == 0:
                continue
            donor, receiver = (i, j) if normal > 0 else (j, i)
            if available[donor] == 0:
                continue
            sc = None if critical is None else min(critical[i], critical[j])
            request(f"internal:{axis}:{i}:{j}", donor, receiver, abs(normal),
                    (gradient[tangent][i] + gradient[tangent][j]) * .5,
                    _harmonic_mean(k[i], k[j]), sc, distance, width, axis)

    for boundary in boundaries:
        i = boundary["cell"]
        if k[i] == 0:
            continue
        normal = (z[i] - boundary["elevation_m"]) / boundary["distance_m"]
        if normal < 0:
            raise ValueError("outward numerical boundary would import undeclared material")
        tangent = "dz_dy" if boundary["axis"][0] == "x" else "dz_dx"
        request("boundary:" + boundary["id"], i, None, normal, gradient[tangent][i],
                k[i], None if critical is None else critical[i],
                boundary["distance_m"], boundary["width_m"], boundary["axis"], boundary)

    if maximum_d:
        x_cfl = _positive_product((maximum_d, dt, 1 / grid.dx_m, 1 / grid.dx_m), "x CFL")
        y_cfl = _positive_product((maximum_d, dt, 1 / grid.dy_m, 1 / grid.dy_m), "y CFL")
        legacy_cfl = number(x_cfl + y_cfl, "R7 conservative CFL", 0)
        boundary_cfl = number(.5 * dt * max(map(math.fsum, conductance)), "face CFL", 0)
    else:
        legacy_cfl = boundary_cfl = 0.0
    cfl = max(legacy_cfl, boundary_cfl)
    if cfl > CONTRACT["explicit_diffusion_cfl"]:
        raise HillslopeStepTooLarge("timestep violates explicit diffusion stability bound")

    faces.sort(key=lambda item: item["id"])
    by_source = [[] for _ in range(n)]
    for face in faces:
        by_source[face["donor"]].append(face["requested_bulk_m3"])
    requested = [math.fsum(values) for values in by_source]
    scales = [min(1.0, stock / demand) if demand else 1.0
              for stock, demand in zip(available, requested, strict=True)]
    boundary_ledger = [{"boundary_id": boundary["id"], "cell": boundary["cell"],
                        "evidence": boundary["evidence"],
                        "requested_outward_bulk_m3": math.fsum(
                            face["requested_bulk_m3"] for face in faces
                            if face["boundary_id"] == boundary["id"])}
                       for boundary in boundaries]
    return {"schema": "diadem.native-terrain.r1.hillslope-face-requests.v1",
            "process": "hillslope_transport", "transfer_basis": "donor_bulk_m3",
            "faces": faces, "requested_bulk_m3_by_source": requested,
            "available_bulk_m3_by_source": list(available),
            "source_scale_factors": scales,
            "limited_source_cells": sum(scale < 1 for scale in scales),
            "explicit_cfl": cfl, "r7_conservative_cfl": legacy_cfl,
            "face_conductance_cfl": boundary_cfl,
            "explicit_cfl_limit": CONTRACT["explicit_diffusion_cfl"],
            "receiving_expansion_max": expansion, "dt_years": dt,
            "boundary": "periodic x / closed y" if periodic_x else "closed except declared outward faces",
            "boundary_requests": boundary_ledger, "state_applied": False}
