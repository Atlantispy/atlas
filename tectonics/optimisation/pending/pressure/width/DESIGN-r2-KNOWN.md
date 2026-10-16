# Pose width r2: known limits (addendum to DESIGN.md f6e6dc64, 16 Oct 2026)

DESIGN.md r2 is unchanged. These are the limits the review of the built transforms found (none breaks the
design). Each line says what guards it and when it must be revisited.

| # | known limit | what guards it | revisit when |
|---|---|---|---|
| K1 | `_pose_round_axis` (E, b-quat) decodes all n segment rates into Fractions up front, outside the `V._work` lease: ~0.3 MB at n = 1,000 segments. | n is one segment per accepted interval; the encoded segments are already held in the record, so the decoded copy is the same order of size and far below the 256 MiB caps. | n reaches ~10^5, or a pose prefix cache keeps the decoded rates alive across calls. |
| K2 | The b-quat anchor ends inside the `with V._work` block of `E._representative_pose`; the rest of that block is covered by the input pin (d338238e) only, not by anchor text. | `_transform` refuses any input whose sha256 is not pinned unless `allow_unreviewed_input=True`; compose_width.py never passes it. | Any re-pin onto another E base (G-PY, D5 or a later E edit): re-read the block tail by hand and rerun unit_width.py before pinning. |
| K3 | The "no binary64" property holds for exact inputs only. | `_floor_log2` refuses any value that is not int or Fraction (VolumeError), so a float rate or time fails closed instead of rounding in binary64; `_pose_round_axis` treats a non-exact rate as "no axis"; record values reach W and E through `W._decode` (exact). unit_width.py checks the types and scans the inserted code for float use. | A caller starts passing in-memory float poses or rates. |
| K4 | `D._ray_component_boxes`, `D._rotation_boxes` (moving_face), `spatial_pressure._rotation_path`, interface_exclusion and rigid_intersection still compose the raw history (DESIGN section 6). | Their outputs are projected to binary64, so they never reach the 1 MiB width limit; only their cost grows with n. | The IV1/IV2 profiles show their cost growing past a few % of a stage. |
