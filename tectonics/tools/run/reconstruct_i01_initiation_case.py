"""Inspect one pinned Li-Gurnis archive row; never execute the archived solver.

SPDX-License-Identifier: AGPL-3.0-only
This is a source reconstruction, not a runnable case or a reference-curve admission.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

import numpy as np

FILES = {
    "README.docx": (21185, "d350bacfbf968668187481f04083afbb7c23e6ef73ddd45a67607d89944a3fbe"),
    "sbdt_init_sp3D.py": (69078, "6c83c43fe7a236aae26718fecd999b3a6e6a2e06aa06e965c1924959fc39d5ef"),
    "sup_data.npz": (21048, "3d7643775c5e0cf84519f97933bcccf7d9c790ea5ddbdd6dbc266d4a75693102"),
}
SECONDS_PER_YEAR = 365 * 24 * 3600
SECONDS_PER_MYR = 1000000 * SECONDS_PER_YEAR


def reconstruct_row(time_myr, signed_column_force, speed_m_s):
    """Retain every finite sample; refuse holes, unpaired padding or bad order."""
    t = np.asarray(time_myr)
    f = np.asarray(signed_column_force)
    if (t.dtype.kind != 'f' or f.dtype.kind != 'f' or t.ndim != 1 or
            t.shape != f.shape or not 2 <= len(t) <= 40):
        raise ValueError("bounded matching floating-point histories required")
    if isinstance(speed_m_s, (bool, np.bool_)) or not np.isfinite(speed_m_s) or speed_m_s <= 0:
        raise ValueError("positive finite speed required")
    valid = np.isfinite(t) & np.isfinite(f)
    n = int(valid.sum())
    if (n < 2 or not valid[:n].all() or valid[n:].any() or
            not np.isnan(t[n:]).all() or not np.isnan(f[n:]).all()):
        raise ValueError("only paired trailing NaNs may be omitted; missing rows refused")
    t, f = t[:n], f[:n]
    if t[0] < 0 or not (np.diff(t) > 0).all():
        raise ValueError("nonnegative strictly increasing time required")
    with np.errstate(over='ignore', invalid='ignore'):
        distance = t * SECONDS_PER_MYR * speed_m_s
    if not np.isfinite(distance).all() or not (np.diff(distance) > 0).all():
        raise ValueError("unrepresentable convergence")
    return {
        "sample_count": n,
        "omitted_trailing_nan_pairs": len(time_myr) - n,
        "time_Myr": t.tolist(),
        "speed_m_per_s": float(speed_m_s),
        "nominal_convergence_m": distance.tolist(),
        "raw_signed_column_force_N_per_m": f.tolist(),
        "compression_positive_column_force_N_per_m": (-f).tolist(),
    }


def reconstruct(folder):
    raw, identities = {}, {}
    for name, (size, expected) in FILES.items():
        with (Path(folder) / name).open('rb') as handle:
            data = handle.read(size + 1)
        if len(data) != size or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"changed or incompatible source: {name}")
        raw[name] = data
        identities[name] = {"bytes": size, "sha256": expected}
    # Only load the verified small data archive, never its Python code or pickles.
    with np.load(io.BytesIO(raw['sup_data.npz']), allow_pickle=False) as data:
        if (data['T1_rec'].shape != (16, 40) or data['F1_rec'].shape != (16, 40)
                or data['u'].shape != (16,)):
            raise ValueError("unexpected archive shape")
        row = reconstruct_row(data['T1_rec'][2], data['F1_rec'][2], data['u'][2])
    return {
        "schema": "atlas.i01-initiation-source-reconstruction.v1",
        "status": "PARTIAL_RECONSTRUCTION_NOT_ADMITTED",
        "scientific_acceptance": False,
        "runnable_configuration": False,
        "reference_curve_admitted": False,
        "source": "https://doi.org/10.1093/gji/ggac332",
        "archive": "https://doi.org/10.22002/D1.8958",
        "source_files": identities,
        "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "target": "4 cm/year imposed-velocity VEP published case; raw-row rheology unconfirmed",
        "published_target_parameters": {
            "basis": "PAPER_DESCRIPTION_NOT_AUTHENTICATED_ARCHIVE_INPUT_ROW",
            "locator": "paper section 3, Table 1 and Figure 4; archive README movie table",
            "overriding_age_Myr": 20,
            "subducting_age_Myr": 40,
            "overriding_granitic_crust_m": 25000,
            "subducting_basaltic_crust_m": 8000,
            "weak_zone_thickness_m": 20000,
            "weak_zone_dip_degrees": 45,
            "yield_cap_Pa": 150000000,
            "residual_strength_Pa": 3000000,
            "shear_modulus_Pa": 30000000000,
            "phase_density_reference": "https://doi.org/10.1029/2001JB001127",
            "phase_density_table_recovered": False,
            "figure_4_panels": {"a": "numerical VP", "b": "analytical", "c": "numerical VEP", "d": "VP solid and VEP dotted"},
        },
        "raw_row_zero_based": 2,
        "seconds_per_year": SECONDS_PER_YEAR,
        "diagnostic": row,
        "conventions": {
            "time": "README states Myr and u in m/s; nominal convergence uses seconds per Myr. Source input velocities instead use m/year.",
            "force": "Negate the stored integral of tau_xx-tau_zz for compression-positive COLUMN force. It is not automatically a boundary reaction or boundary-work observable.",
            "initial_zero": "Retained. The archived code initialises previousStress=0 and samples its projection before the first update; this explains that code's first zero, not the unprovided NPZ aggregation lineage.",
            "motion": "Speed times time is nominal convergence. The code imposes a depth-dependent tanh velocity profile, not a uniform right-wall velocity.",
        },
        "source_code_derivations": {
            "scope": "Exact pinned script, not proof of the settings that produced a published curve",
            "locator": "script lines 26-62, 143, 294-305, 495-502, 629-647, 828-846, 1424-1426",
            "box_m_xyz": [900000, 6000, 450000],
            "element_count_xyz": [256, 2, 128],
            "periodic_axis": "y",
            "mesh_deformation_applied": False,
            "reference_viscosity_Pa_s": 1e18,
            "force_scale_N_per_m": 1e18 * 1e-6 / 300000,
            "creep_reference_viscosity_Pa_s": 1e20,
            "temperature_offset_K": 273,
            "effective_activation_energy_J_per_mol": 540000 * 1400 / 1500,
            "activation_derivation": "With theta=T_C/1400 and viscT=273/1400, Q/(3*R*1500)*(1/(theta+viscT)-1/(1+viscT)) equals (Q*1400/1500)/(3*R)*(1/(T_C+273)-1/1673). Do not repair 1500 silently.",
            "required_missing_external_files": ["inputfile.txt", "morbphase.txt"],
            "morb_table": "Source maps 0-8 GPa and 100-1000 C to a density table using clamped indices. No density values are recoverable from those axis ranges alone.",
        },
        "remaining": [
            "Published panel/rheology and raw-row-to-run/aggregation provenance",
            "Complete case input row and MORB density table with source identity",
            "Reconcile archived geometry, thermal/rheology constants and diagnostics with paper",
            "Compatible initial/boundary profiles and numerical uncertainty/allowances",
            "Separate Atlas plastic-history, physical-length and true force-release controls",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive_folder', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = reconstruct(args.archive_folder)
    encoded = json.dumps(result, indent=2, allow_nan=False) + '\n'
    with args.output.open('x', encoding='utf-8', newline='\n') as output:
        output.write(encoded)
    print(f"PARTIAL_RECONSTRUCTION_NOT_ADMITTED: {result['diagnostic']['sample_count']} samples; no solver executed")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
