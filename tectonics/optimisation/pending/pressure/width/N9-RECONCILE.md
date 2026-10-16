# N9 pose width: what is rounded vs where it is integrated (16 Oct 2026, 17:52 BST)

DESIGN r2 (width/DESIGN.md f6e6dc64) is authoritative for WHAT is rounded; the geometry handoff note
(R/geometry-growth-r1/HANDOFF.md, the pose-width bullet naming wall_measures, current_geometry_from_interval and
differential_mesh) is authoritative for WHERE and WHEN it is integrated. The file sets differ in one name:

| design r2 (rounded) | geometry note | resolution |
|---|---|---|
| W integration_wall_measures `_pose_vector` (b-ray) | integration_wall_measures | same file |
| E integration_exterior_mesh `_representative_pose` (b-quat) | current_geometry_from_interval (DG) | E, not DG (below) |
| M integration_differential_mesh, both builders (c) | integration_differential_mesh | same file |

Why E and not DG.current_geometry_from_interval:
- current_geometry_from_interval (DG l.390) never builds a pose. It appends the accepted step (rate, duration) to the
  exact symbolic prior_rotations history and stores a zero rate. That history stays exact; nothing in it is rounded.
- The rounding happens where a pose is evaluated from that history: E._representative_pose. Its callers in the
  composed runtime are DG.posed_boundary (l.772), E.build_exterior_mesh (l.662), E._build_exterior_mesh_record
  (l.870) and current_force_pose (no caller in full6). All of them get the rounded pose; DESIGN r2 covers each.
- DG is byte-identical before and after: c/full6 and c/wr1 integration_differential_geometry.py are both ee930406.

Built test-only composition (frozen:c/full6 + b + c -> c/wr1, WIDTH_COMPOSITION.json 0a0fc87f):

| file | transform (sha) | input pin | output |
|---|---|---|---|
| W | width_pose_round.py 1daa946e | d6b7d472 | a7a7dc43 |
| E | width_pose_round.py 1daa946e | d338238e | 524622bf |
| M | width_deviation_bound.py 4749c003 | ab0f31f8 | bfe89a0e |

Integration notes for the geometry side:
- W: (b-ray) is text-disjoint from D5 T1 (C6); either order, one parity. The W pin d6b7d472 must be re-pinned if D5
  lands first (new pin = D5's W output; the anchors are unchanged), never bypassed.
- E: single owner of `_representative_pose` (C7); the QUAT anchor ends inside the `with V._work` block, so the
  block's tail is covered by the input pin only.
- M: anchor count 2 (one comparison per builder, C8).
- Identity successor: pose-derived exact values change (quaternion, pose error, posed rays, stored deviation).
  Fresh runs use the rounded build from IV1; never mix rounded and unrounded intervals.
- Evidence: route parity (route-parity-wr1b, 0 mismatches), proof (proof-quanta.log), unit + 13/13 mutants
  (unit-wr1f), mpmath enclosure (check-round-mpmath-wr1f). Still owed: the IV1 replay ticket (condition 4).
