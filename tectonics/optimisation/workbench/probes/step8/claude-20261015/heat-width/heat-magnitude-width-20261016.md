# Heat-ledger exact magnitude width: source and growth (16 Oct 2026, Steps 8-9 chat)

Read-only paper analysis for the coordinator, with one micro-test. Nothing in the candidate changed.
Limit: `MAX_INTEGER_BYTES` = 1 MiB = 8,388,608 bits per integer (record_tables, mesh_tables).

Sources:
- the IV1 structural census `R/probes/structure-census-r3/structure-census.json`, sha256 02f0a05a…, through
  `census_widths.py` and `census_fields.py`; field names follow the canonical sorted-key order;
- storage's rational study (`claude-review-steps1-7-20261015/fixes/wp10-followups`, section (e));
- the code paths cited below, read in the unchanged I tree and H;
- `pose_width_steps.py`, which runs the runtime's own pose functions; output in `pose-width-steps.json`.

## (1) Where the widest values are (IV1, measured)

| record / field | values | widest (bits) | bytes | % of 1 MiB | root (IV0) |
|---|---:|---:|---:|---:|---:|
| heat `exact_cell_storage_residual_j` (per cell) | 855 | 2,054,539 | 256,818 | 24.5% | no heat at the root |
| heat `exact_corrected_enthalpy_j` | 855 | 1,724,160 | 215,520 | 20.6% | |
| heat `exact_stock_projection_residual_j` | 855 | 1,724,160 | 215,520 | 20.6% | |
| heat `exact_paired_face_energy_j` (per face) | 8,569 | 411,073 | 51,385 | 4.9% | |
| heat `exact_retained_solver_residual_j` | 855 | 334,758 | 41,845 | 4.0% | |
| mesh `geometry_volume_max_deviation_m3` (ONE sum over all cells) | 1 | 614,116 | 76,765 | 7.3% | 35,877 |
| mesh `cells` (per-element metric rationals) | 5,985 | 38,455 | 4,807 | 0.46% | 8,128 |
| mesh `faces` (per-element metric rationals) | 157,143 | 9,479 | 1,185 | 0.11% | 2,315 |
| transport (widest field) | 132 | 23,787 | 2,974 | 0.28% | |
| state (widest field) | 39,809 | 13,628 | 1,704 | 0.16% | |

The "614k bits" mesh figure is a single scalar: the sum of the per-cell volume deviations
(`integration_differential_mesh`, `total_error = sum(errors)`). It is not a coordinate. Mesh
per-element rationals are at most 38,455 bits.

## (2) What sets the width (from the code)

**Heat: one joined call per interval, on that interval's END mesh.**
- **Every input except the metric is re-rounded on each call.**
  - The old stocks are the binary64 projection of the transported exact stock
    (`private_heat_native_issuer_r12.bind_owner_call`: `_project(_q(exact_stocks...))`).
  - The capacities and the source are binary64.
  - The LOW and HIGH predictors are Decimal80.
  - The finish converts with `_q(float(v))`.
  - Nothing from an earlier call or interval enters, which confirms WP7 in code.
- **The metric is the one exact input.**
  - LOW face conductance is |n|^2/(d_i/k_i+d_j/k_j), from exact area vectors and centre-to-face distances
    (`private_heat_low_geometry_kernel_r1.prepare_geometry`).
  - LOW face energy is dt * conductance * (E_i/C_i - E_j/C_j) (`ledger`).
  - So a face's width is a fixed multiple of the metric's width.
- **The finish (FCT) multiplies by the stencil.**
  - A limited face is lo - alpha*delta, with alpha = min(1, (C*T_bound - E)/P), where P is the sum of the
    cell's positive corrections. So alpha is about as wide as the sum of that cell's face widths.
  - A corrected stock is low + sum(alpha_f*delta_f) over the cell's faces, a sum of terms with distinct
    denominators.
  - This is why the per-cell fields (2.05 Mbit) are about 5x the widest face (411 kbit).
  - The retained residual is the LOW ledger alone, with no alpha, so it is narrower (335 kbit).
  - The 64-bit theta contractions add at most 64 bits.
- **In short:** heat width = metric width x a fixed construction degree x the faces of one cell. Nothing
  accumulates over time steps or over intervals.

**Metric: one exact rotation step per interval.**
- **The end mesh of interval n poses the ORIGINAL geometry.**
  - The body-frame cones and radial layers come from the static initial partition
    (`prepare_differential_partition`, "INITIAL static"; the source charts keep `original_cone`).
  - They are posed through the full exact rotation history.
- **Each interval appends ONE exact step** to every ray's symbolic history
  (`current_geometry_from_interval`: "append the accepted current ray step to its exact symbolic prefix").
  `integration_wall_measures._pose_vector` applies every prior step, and `_representative_pose` multiplies
  the step quaternions.
- **The clip and assembly depth is fixed** by the static partition. It does not deepen with intervals.

**Transport cannot compound either.** It re-projects concentrations to binary64 on every interval
(`integration_spatial_transport`: "One explicit binary projection bounds active-state rational width by
current geometry, not number of preceding intervals").

**The pose micro-test confirms the per-step increment is constant.** It used the runtime's own functions
with 1 to 6 identical coaxial steps (`pose-width-steps.json`):

| steps | quaternion bits | posed ray bits (level 0) | posed ray bits (level 24) |
|---:|---:|---:|---:|
| 1 | 834 | 602 | 1,345 |
| 2 | 1,667 | 1,149 | 2,636 |
| 3 | 2,501 | 1,696 | 3,927 |
| 6 | 5,000 | 3,337 | 7,799 |
| per step | +833 | +547 | +1,291 (constant) |

## (3) How the width grows

| grows with | answer |
|---|---|
| interval count | **Yes, linearly**: one pose step per interval. Not x4 per interval. |
| constraint nesting depth | It scales with the construction depth: clip planes, then vertices, area vectors, conductances and FCT sums. That depth is fixed by the static partition, so it does not grow with intervals. |
| not at all | No: the pose history grows. |
| exception | Whole-mesh SUMS (the deviation sum above and the cumulative projection accounts) scale with the number of contributing cells x the per-cell width. The deviation sum went from 35,877 to 614,116 bits (x17.1) from the root to IV1, while cells went from 547 to 855. |

## Projection (paper)

Linear law W(n) = W0 + n*(W1 - W0), with W0 the root (identity pose) and W1 IV1 (one step).
- **Lower bound:** uses the measured root-to-IV1 metric growth (cells x1.79 at IV2 and x2.58 at IV3;
  faces x1.76 and x2.51).
- **Upper bound:** assumes heat proportional to n (x2 and x3).

| quantity | IV1 measured | **IV2 line** | **IV3 line** | first refusal |
|---|---:|---:|---:|---|
| heat per-cell max (`exact_cell_storage_residual_j`) | 2,054,539 bits, 24.5% | 3.61-4.11 Mbit, **43-49%** | 5.16-6.16 Mbit, **62-73%** | about IV5 (IV4 80-98%) |
| heat per-face max | 411,073 bits, 4.9% | 8.6-9.8% | 12-15% | not soon |
| mesh per-element max | 38,455 bits, 0.46% | 0.8-0.9% | 1.2-1.4% | none |
| mesh deviation sum (one scalar) | 614,116 bits, 7.3% | 13-15% at a steady ~855 contributing cells | 18-22% at a steady count | scales with cell-count growth; measure |
| for comparison: x4 per interval | 24.5% | 98% | 392%, refuses | IV3 |

**Uncertainty.**
- The heat factor also depends on the faces per cell and on how many faces the FCT limits. Both depend on
  the data.
- The deviation sum depends on how many cells have a nonzero error.
- So the IV1-rerun gate should measure these, not assume them.

## Pre-interval-2 gate (proposal for the IV1 rerun: largest magnitude per step)

- **Record, for every record written:** the widest numerator and denominator bits and the value count of
  every exact field. This covers the 7 heat ledger fields, the mesh per-element fields and whole-mesh
  sums, transport, and the state accounts. Also record the end mesh's trajectory step count.
- **Exactness check:** the rerun must reproduce r9's widths exactly (heat 2,054,539 bits; deviation sum
  614,116 bits). The run is deterministic, so a difference is a defect.
- **Projection check:** project IV2 per field as W1 + (W1 - W0). The gate passes if every projected IV2
  width is at most 50% of 8,388,608 bits and the IV3 projection is at most 100%. Otherwise stop before IV2
  and route to Michael (D1).
- **During IV2:** add a cheap bit_length scan before the record build, so that any refusal comes early,
  not at the end of a long run.

## Options if the growth must go later

Each option changes output identities, so each is Michael's decision. None is proposed now.
- (a) For the coaxial family, sum the half-angle vectors and take ONE Taylor quaternion. The pose width
  then stays about constant per interval.
- (b) Round the pose to a bounded dyadic within the declared pose error budget.
- (c) Store the deviation sum as an outward-rounded bound. It is only compared with the declared budget.

Raising `MAX_INTEGER_BYTES` is not proposed.

- **Later-step impact:** the Step 10 composition gains the per-step width record. Nothing else changes.
- **Interval 3:** heat at 62-73% of the limit on paper, with no refusal; the first refusal is about IV5.
