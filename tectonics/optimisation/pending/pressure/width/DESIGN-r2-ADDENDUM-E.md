# Pose width r2 addendum E: (c) also covers the exterior mesh deviation sum (16 Oct 2026)

DESIGN.md (f6e6dc64) and DESIGN-r2-KNOWN.md are unchanged. This addendum extends rule (c) from M
(integration_differential_mesh.py) to E (integration_exterior_mesh.py).

## Finding

E's two builders (the native `build_exterior_mesh` and `_build_exterior_mesh_record`) sum the exact per-cell
volume deviations into `total_error` (starts at `Q(0)`; each term is `max(|volume-lo|, |volume-hi|)` from exact
volumes) and store it in the mesh header as `geometry_volume_max_deviation_m3`. That header value has the same
width problem as M's: the census head mesh header field is 307,067 B (helpers/test_mesh_v3_header_column.py),
and it grows with the number of cells summed.

Grep scope: every `.py` module under `src/atlas_tectonics` and `helpers` of the base runtime (c/full6), searched
for `geometry_volume_max_deviation_m3`, `max_geometry_volume_error_m3` and `deviation` (27 modules mention
`deviation`), and `total_error` in E.

The four points that make the change safe (each HOLDS on that scope):

1. `total_error` has no other use after the check: in each builder the only later read is
   `geometry_volume_max_deviation_m3=_enc(total_error)` in the header (E l.739 and l.954 of the base).
2. The header field is only written by E and M, and round-tripped as storage by mesh_tables.py (and its
   w3ref/xmref copies): HEADER_FIELDS / CELL_FIELDS and the bit-width booking count it; nothing computes with it.
3. No reader re-derives it or compares it with the sum of the per-cell deviations; the tests that set it
   (test_mesh_tables, test_mesh_v3_header_column, test_w3_mesh_booking, test_xmb_mesh_booking) only store or
   book synthetic values.
4. The per-cell deviations (`geometry_volume_max_deviation_m3=_enc(error)` per cell, E l.699 and l.907) stay
   exact; only the header sum is replaced.

## Rule (ce)

In each E builder, after the unchanged exact comparison

    if total_error > width:
        raise V.VolumeError(...)

insert `total_error = _stored_deviation(total_error, width)`, the same helper as M:

    0                                                                     if total_error == 0
    min(round_up(total_error, 2**(floor_log2(total_error)-64)), width)    otherwise

so stored >= total (outward), stored - total < 2**-64 * total, stored <= width. Pass/fail cannot flip: the
comparison is taken on the exact sum before the insert. A non-Fraction or out-of-range total refuses
(VolumeError) instead of rounding.

## Built and proved

- Transform: width_deviation_bound_exterior.py, pinned on E after (b-quat) 524622bf, helper anchor count 1,
  comparison anchor count 2; output E 4b5b11c4.
- Composer: compose_width_r2.py (groups b, c, ce; ce needs b). Composition c/wr2 = c/full6 + b + c + ce,
  WIDTH_COMPOSITION.json ba2f30c6. c/wr1 and c/wr2 differ in E only.
- Unit: unit_width_e.py (299a9716) on c/wr2 vs c/wr1, unit-e-wr2b.json 714bb722: 75 checks, 0 failures,
  4/4 mutants caught (round-down, min dropped, rounding before the check in each builder). Per builder,
  removing the inserted line gives the before builder exactly (AST), the insert directly follows the exact
  check, and `total_error` is never assigned or read after it except as the stored header. All other
  top-level definitions of E are unchanged, so the (b-quat) evidence on c/wr1 (unit_width.py, route
  parity, mpmath enclosure) carries to c/wr2 unchanged.

## Record identity

The stored header deviation of every exterior mesh changes (part of the pose width identity successor).
Fresh runs use the rounded build from IV1; never mix rounded and unrounded intervals.
