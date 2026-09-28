# I01 MC-07: water-loaded, flexed columns to gravitational driving

**27 September 2026. WORKING NON-CANON. Bounded I01 choice and control for closure-matrix
item MC-07 (rows CM-04 and CM-15).** It joins the retained [dry column/GPE helper](I01_GPE.md)
to the retained [finite-water/flexure equilibrium](I01_WATER_FLEXURE.md) on their shared
planar periodic support. It is not I04 world sampling, I08 regional or global support, or a
spherical calculation. The retained helpers, their cases and their receipts are imported
and read, never edited.

## Decision

Contract `atlas.water-loaded-gpe.v1`:

- **Driving potential.** Water-loaded columns drive D1 through `V`, the depth integral of
  the *actual* vertical normal stress from the common compensation datum to the
  traction-free top: the sea surface where a cell is wet, the loaded bed where it is dry.
  The water column is inside that integral once. The column geometry is displaced by the
  retained total equilibrium deflection, never rebalanced by Airy isostasy a second time.
  D1 receives `t = -gamma grad V`, with the same common `gamma = L0/L` as dry columns and
  no separate ridge push or water push.
- **Selected and exact:** states in which the plate transfers no load between columns:
  zero water, zero rigidity (local Airy) and uniform loading. They are recognised
  structurally from the inputs (section 4), never because a residual or the plate support is
  small. There `V` is the integrated lithostatic pressure of the loaded column and needs no
  further input.
- **Conditional, not closed:** finite rigidity under nonuniform loading, however small the
  nonuniformity. The plate then carries part of each column's load sideways, so the pressure
  beneath its shear-carrying layer is not the weight of the material above. `V` depends on
  the depth `c` of that layer, with `dV/dc = B` below. The join runs only with an explicitly
  declared effective shear-transfer depth and its basis. **Choosing that depth is an
  unresolved material decision.** No default is supplied, and nothing here closes arbitrary
  flexural loading or all of MC-07.

## 1. What moves through this connection

The dry helper builds each rock column from layer thickness, density and temperature and
floats it on the mantle at a common pressure datum. That fixes its unloaded surface, its dry
gravitational potential energy (GPE) and its reference rock mass. The water helper takes
that same unloaded surface as its bed, adds a fixed volume of water and bends a
constant-rigidity plate until the bed, shoreline and water depth agree. It returns the total
downward deflection `w`, loaded bed, water depth `d` and one sea level.

This join lowers each column by exactly that `w` and puts exactly that water on top. It then
integrates the vertical stress of the loaded column to obtain the sideways gravitational
driving potential. It does not solve for water again, add water to the rock stack, or
re-float the loaded bed on the mantle.

A stiff plate spreads a narrow load. The mantle pressure beneath stays uniform even though
the weight of each column differs; the bending layer carries the difference. Above that
layer the pressure is the weight of the rock and water overhead. Below it the pressure is
the uniform mantle pressure. How deep the load transfer happens therefore changes the
sideways push, which is why finite rigidity needs the declared depth. Local compensation has
no transfer, so the depth does not matter there.

Outputs per column are the potential anomaly `delta V` (J/m²) and, on the plate grid, the
traction `-gamma grad V` (Pa). Diagnostics include:

- the basal overburden excess `B`;
- the structural limit, if any, that makes the state compensated (`no_transfer_limit`);
- the independently recomputed plate support `D biharmonic(w)` and its relative norm, which
  is reported but never used to classify;
- the unchanged reference rock mass and effective rock load;
- the water mass `rho_w d`;
- the displaced mantle fill;
- the equilibrium residuals used to authenticate the supplied state.

## 2. Conventions and inputs

- `z` increases upwards. Gravity `g` is constant. The datum is the retained `Datum`: a fixed
  compensation elevation `zc` with actual pressure `P`, in an inviscid mantle of density
  `rho_m`.
- The pure-mantle reference column rises to `Z_ref = zc + P/(g rho_m)`. Its integrated
  pressure is `U_ref = P²/(2 g rho_m)`, as in the dry helper.
- The plate and the datum must carry the **same** `rho_m` and `g`. Water density `rho_w` and
  plate rigidity `D = E Te³/[12(1-nu²)]` come from the retained `Plate`.
- Air density and sea-surface pressure are zero, and one communicating reservoir shares one
  level `S`.
- Rock layers are bottom to top with linear Boussinesq effective density, exactly as in the
  dry helper. Effective density sets load, support and moments. Reference rock mass is
  reported separately and never changed by heating or by water. Every effective rock density
  must exceed `rho_w`: water belongs to the finite reservoir, not the rock stack.
- For each column the retained helper gives effective load `m`, rock thickness `H`, dry fill
  `Hm = (P/g - m)/rho_m` and dry anomaly `delta U0 = g [q - m²/(2 rho_m)]`, where `q` is the
  first moment about the rock base.
- The dry surface is `z0 = zc + Hm + H`. Its height above the reference mantle top is
  `e0 = z0 - Z_ref = H - m/rho_m`, evaluated without large numbers.
- The water helper's `w` is downward-positive and a **total** equilibrium relative to `z0`.
  The loaded bed is `z = z0 - w`, the depth is `d = max(0, S - z)` and the top is `z + d`.
- Units: metres, pascals, kilograms and J/m² (= N/m). Traction is in Pa, and `gamma` is
  dimensionless.

## 3. Which integrated stress moment drives motion

Integrate horizontal equilibrium, `d_x sigma_xx + d_y sigma_xy + d_z sigma_xz = 0`, over a
column from `zc` to the traction-free top `T(x,y)`. The top condition `sigma . n = 0` cancels
the Leibniz boundary terms exactly, giving

```text
d_x integral sigma_xx dz + d_y integral sigma_xy dz = sigma_xz(zc)
```

Write `sigma_ab = tau_ab + sigma_zz delta_ab`, with `tau_ab = sigma_ab - sigma_zz delta_ab` for
horizontal `a, b`. This gives the thin-sheet balance

```text
d_b integral tau_ab dz = d_a V + sigma_az(zc),     V = - integral_zc^T sigma_zz dz
```

`V` is the gravitational driving potential: `-grad V` is the body-force equivalent that
deviatoric stress, basal drag and plate-boundary reactions must balance. This is Ghosh,
Holt and Flesch's (2009) balance, their equations 5–6, with their `sigma_zz` bar equal to
`-V`. They evaluate `sigma_zz` as the overburden (their equation 4) and state that the
balance neglects flexure. The derivation above does not need that approximation; the
choice of `sigma_zz` is where flexure enters.

**The water column belongs inside the integral.** Water carries no deviatoric stress, but
its weight is part of `sigma_zz`. The traction-free top is the sea surface. An integral over
rock only, with the water pressure `p_w = rho_w g d` as a boundary condition on the bed,
differs from `V` by `rho_w g d²/2`. The gradient of that difference is `-p_w grad z`: the
horizontal water pressure on a sloping bed. The full-column form therefore contains that
force once. The rock-only form would need it added as a separate traction, and it must never
be added to the full form.

**The vertical stress is not always the overburden.** Vertical equilibrium,
`d_x sigma_xz + d_y sigma_yz + d_z sigma_zz = rho g`, shows that `sigma_zz + p_o` changes only
where vertical shear stress has horizontal divergence. Here `p_o(z)` is the overburden:
rock and water weight between `z` and `T`. In the thin-plate reduction this happens only
inside the elastic layer that carries the bending shear. Above that layer the vertical
stress is the overburden. Below it, weak rock and the inviscid mantle are hydrostatic from
the uniform actual pressure `P` at `zc`. The jump across the layer is

```text
B = p_o(zc) - P = g (rho_w d - rho_m w) = D biharmonic(w)
```

The last equality is the retained plate equation `(D biharmonic + rho_m g) w = rho_w g d`.
`B` averages to zero over the periodic plate. Where `B > 0` the column is heavier than its
mantle support and the plate carries the excess sideways. For a homogeneous Kirchhoff layer
the shear stress is parabolic and symmetric about its mid-surface. The pressure change
through the layer then integrates exactly like a step at that mid-surface. Let that
effective shear-transfer level lie a depth `c` below the loaded bed, at `z_s = z - c`. Then

```text
V = U_o - (z_s - zc) B,      U_o = integral_zc^T p_o dz = g integral_zc^T rho(z) (z - zc) dz
```

`U_o` is the naive fixed-datum lithostatic integral, and `delta U_o = U_o - U_ref` is its
anomaly. Deepening the common mantle datum by `Delta`, with the matching pressure
`P + rho_m g Delta`, adds a mantle segment beneath every column:

- the reference column gains `P Delta + rho_m g Delta²/2`;
- the absolute `U_o` gains that same common term plus `Delta B`, because the overburden on
  the added segment starts from `P + B`, not `P`;
- the absolute `V` gains only the common term, because below `z_s` both the loaded and the
  reference columns are hydrostatic from the same `P`.

The common term cancels in every anomaly and gradient. The anomaly `delta U_o` therefore
changes by `Delta B`, so when `B` is nonuniform it depends on the arbitrary datum depth. This
is Ghosh et al.'s reference-level warning in their section 7. The anomaly `delta V`, and
hence the traction, is unchanged. Neither absolute integral is invariant, and neither is
claimed to be. The flexural term is the moment of an owned reaction at its physical level.
It is not subtracted merely to restore datum invariance: placing the level at `zc` would
recover `U_o`, which is Ghosh et al.'s case of radial traction applied at the reference
level.

## 4. Selected formula and its limits

Integrating the displaced column with a mantle fill of `Hm - w`, the unchanged rock stack
and the water layer, then subtracting `U_ref`, gives exactly:

```text
delta V = delta U0 + c B + g rho_m w (e0 - w/2) + g rho_w d²/2
```

This Atlas derivation is exact for the declared hydrostatic layers and the single declared
shear level. It contains no datum elevation or basal pressure, and it involves no
subtraction of two absolute energies. The special cases are:

| State | Structural requirement | Result |
| --- | --- | --- |
| Zero water | Zero volume: `d = 0`, `w = 0`, no sea level | `delta V = delta U0` bitwise: dry parity |
| Zero rigidity (Airy) | `D = 0` exactly: `w = (rho_w/rho_m) d`, `B = 0` | `delta U0 + g rho_w d (e0 - w/2 + d/2)`: the unchanged dry helper with water appended as a top layer |
| Uniform loading | An exactly flat dry surface, so a fully wet flat bed: only the zero Fourier mode, `B = 0` for every rigidity | Same as the Airy row; spatially constant water contribution, so the dry traction is unchanged. Total traction is zero only if the dry potential is also uniform |
| Finite rigidity, nonuniform loading | Every other state, however small `B = D biharmonic(w)` is | Needs a declared `c`; `d(delta V)/dc = B` |

**Admission and classification are separate steps.**

1. A supplied state is first *admitted* as the equilibrium of this dry surface, plate and
   volume, by its residuals at the retained tolerances (section 6).
2. It is then *classed* from independent inputs only: the volume, the plate's rigidity and
   the dry surface that the join builds itself. It is compensated only in the three
   structural limits above, where `B` vanishes identically in the exact equilibrium.
   - A flat dry surface counts only when every cell's elevation is exactly equal.
   - A surface that is flat only to rounding is treated as nonuniform and needs a level.

A small residual or a small support never makes a state compensated. The relative support
norm `||D biharmonic(w)|| / max(1, ||rho_w g d||)` falls as uniform water is added, while `B`,
and so the omitted `c B`, is unchanged. A threshold on that norm would therefore hide a
genuine flexural transfer; section 8's small-support control shows this. No omission bound
that could admit such states without `c` has been derived. The norm is reported as a
diagnostic only.

In a compensated state the formula is evaluated with the declared `c`, or `c = 0` if none is
declared. `B` is then zero apart from the admitted residual, so a declared `c` is
immaterial. The join also reports `max(H |B|)`, a bound on the effect of any admissible `c`.

**Datum statements.** These are statements about anomalies. Absolute integrals gain the
common reference term of section 3 and are never compared.

- Translating every elevation (`zc`, surfaces, bed and sea level) at fixed `P` leaves
  `delta V` unchanged.
- Deepening the common datum by `Delta` with the matching mantle pressure leaves `delta V`
  bitwise unchanged in the join, because the retained `delta U0`, `e0`, `w`, `d` and `B` are
  unchanged. The independent quadrature's `delta V` agrees within its tolerance.
- The same extension changes the naive anomaly `delta U_o` by `Delta B`. That is shown, not
  hidden.

**Refused shortcuts:**

- adding the water depth or weight again;
- re-floating the loaded bed through the dry helper when `D > 0`;
- adding successive total deflections;
- using `(rho_m - rho_w) g` with the full water load;
- a ridge-push or water-push line force alongside `V`.

## 5. Ownership: the driver and the separately owned reactions

| Contribution | Owner | How it enters |
| --- | --- | --- |
| Rock weight and thermal buoyancy | Dry columns (retained helper) | Inside `delta U0`, `m` and `e0`; the reference mass is reported separately and unchanged |
| Water weight and pressure on a sloping bed | Finite reservoir (retained water helper) | Inside `V` once, through `d`; no separate term |
| Flexural deflection | D5 plate (retained water helper) | Total `w` translates the column once |
| Bending moments, vertical shear and the nonuniform overburden excess `B` | D5 plate | Only as `c B`, the moment of the transfer at its level; no extra force |
| Uniform datum pressure `P` | D5 datum | No traction |
| Basal drag, slab pull and interface reactions | D1 (and I07) | Unchanged separate terms |
| Membrane forces modifying flexure (`N d²w`, buckling) | Not modelled | Linear-plate omission |
| Mantle-volume closure, self-gravity, geoid, rotation | Not modelled | Explicit omissions, as in D5 |

## 6. Producer compatibility and atomic refusal

`water_loaded_gpe(...)` builds the dry state itself, by calling the retained `columns()`. It
authenticates a supplied water/flexure result by that result's own equilibrium conditions.
Status strings and law names are ignored. Checks are evaluated in this order, each with its
own refusal code:

1. **Contract** (`REFUSED_UNSUPPORTED_CONTRACT`): `periodic_flat_plate` geometry,
   `one_communicating_reservoir` connectivity, and the retained `Datum` and `Plate` types.
2. **Material** (`REFUSED_MATERIAL_MISMATCH`): the same `rho_m` and `g` on the datum and the
   plate.
3. **Shear-level declaration, if supplied** (`REFUSED_INVALID_INPUT`): exactly
   `{"depth_below_bed_m": c, "basis": text}`, with a finite real `c` and a nonempty basis.
4. **Columns** (`REFUSED_INVALID_COLUMNS`, `REFUSED_SHAPE_SUPPORT_MISMATCH`,
   `REFUSED_WATER_IN_ROCK_COLUMN`):
   - the retained column guards;
   - one column per plate cell, in row-major `(ny, nx)` order;
   - every effective rock density above `rho_w`.
5. **Water fields** (`REFUSED_SHAPE_SUPPORT_MISMATCH`, `REFUSED_NONFINITE`,
   `REFUSED_NEGATIVE_WATER_DEPTH`, `REFUSED_INVALID_INPUT`):
   - finite displacement, bed and depth grids of the plate shape;
   - a nonnegative depth in every cell, checked before any load, volume or mass account is
     formed. A negative depth is refused however small; it is never clipped or rebalanced.
     The geometric and force tolerances do not license negative water. A signed zero is zero
     water;
   - a finite nonnegative volume.
6. **Reference** (`REFUSED_REFERENCE_MISMATCH`): `bed + w` equals this dry surface within
   1e-6 m, the retained RMS solve target. A solve made on another unloaded bed, another
   datum or a reordered column set is refused.
7. **Load** (`REFUSED_WATER_LOAD_MISMATCH`):
   - `d = max(0, S - bed)` within 1e-6 m;
   - `mean(d) x area = V` within 1e-11 relative;
   - zero water has no level and no depth.
8. **Equilibrium** (`REFUSED_NOT_FLEXURAL_EQUILIBRIUM`): recompute
   `(D biharmonic + rho_m g) w` from the plate's public rigidity and lengths and compare it
   with `rho_w g d` at the retained relative tolerance 1e-7. This refuses:
   - doubled water loads and double water feedback;
   - increments passed as totals;
   - an Airy-rebuilt deflection on a stiff plate;
   - dropped flexure.

   Because the coupled equilibrium is unique (retained method), a state that passes checks
   6–8 is that equilibrium to within tolerance.
9. **Classification and shear level** (`REFUSED_SHEAR_LEVEL_UNDECLARED`,
   `REFUSED_SHEAR_LEVEL_OUTSIDE_ROCK`):
   - the state is compensated only in a structural limit of section 4: zero volume, `D = 0`
     exactly, or an exactly flat dry surface. The limit is reported as `no_transfer_limit`;
   - every other state is flexural, however small its support, and needs a declared level;
   - a declared level must satisfy `0 < c < min(H)`.
10. **Geometry** (`REFUSED_BELOW_DATUM`): the displaced fill `Hm - w` must stay positive.
    Deepen the common datum rather than clip.
11. **Representation** (`REFUSED_NONFINITE`): non-finite outputs are refused.

Refusals raise before any result exists. Inputs are copied, never modified, so a refused
call leaves no partial state.

## 7. Validity and restrictions

- **Admitted scope.** The join is admitted only for:
  - a planar periodic plate with constant rigidity and small deflection;
  - one communicating reservoir;
  - hydrostatic layers outside one effective elastic shear layer;
  - an inviscid mantle below every displaced column base.
- **Later extension.** Spherical sampling, support and gradients of `V` (I04), and variable
  rigidity, finite regions, exterior loads and external water ports (I08), are outside that
  scope. A sphere needs its own compatible support; nothing here is a spherical calculation.
- **The Kirchhoff step.** It is exact for a homogeneous layer with symmetric shear. A
  layered or multi-core plate needs its load-weighted effective depth. Deriving that depth
  from a strength envelope is not done here. The effective shear-transfer depth itself
  remains an unresolved material choice (section 11).
- **The traction operator.** Traction uses second-order periodic central differences,
  matching the order of the retained spherical stencil. A shoreline is a gradient kink in
  `V`. It is treated without spectral ringing, but only at first order locally.
- **Order of accuracy.** Geometry is exact for the displaced hydrostatic column. The plate
  response is linear, so terms beyond first order in the flexural stresses are not claimed
  physically accurate.
- **Plate boundaries.** How D1 rigid-plate torques treat flexural stresses at weak or broken
  plate boundaries is not decided here. The periodic plate has no boundaries.

## 8. Controls and what each establishes

The fast focused tests are in `tests/test_i01_water_gpe.py`. The bounded source-bound
campaign is `tools/check_i01_water_gpe.py --output NEW.json`. The case
`cases/i01_water_gpe_v1.json` freezes tolerances, inputs and a 60 s cooperative budget
before execution.

Rows marked **P** exercise actual retained producer output: the retained `columns()` and
`Plate.equilibrium`, or the retained water fixture. Independent oracles are separate
algebra or quadrature, not the production formula rearranged.

| Control | Retained output? | Demonstrates |
| --- | --- | --- |
| Dry parity | P | Zero water through the retained solver is classed by the zero-water limit and gives `delta V` and traction bitwise equal to the dry helper; reference mass unchanged |
| Uniform load | P | Te 15 km and Te 0 are classed by the uniform-load and zero-rigidity limits and give identical, uniform `V` and zero traction. A declared level is accepted and immaterial. They match the **unchanged dry helper with water appended as a layer**, and the independent quadrature with the split at the datum or mid-crust; `w = (rho_w/rho_m) d`, not `rho_w d/(rho_m-rho_w)` |
| Zero rigidity | P | The partly wet retained fixture at Te 0 is classed by the zero-rigidity limit. It matches the water-appended dry helper, within a bound derived from the solve residual, and has the same top surface. Only here is re-floating valid |
| Finite-rigidity Fourier mode | P and independent | See the list below |
| Small nonuniform support | P (columns) and independent | See the list below |
| Retained fixture join | P | 32², 64² and 128² retained water fixture with the retained GPE datum and crust. Refusal without a declared level; authenticated residuals; water-mass conservation; 64 sampled columns against the quadrature; vertical translation re-solved by the retained helper; bitwise datum extension; naive anomaly `delta U_o` shifted by `Delta B`; the Airy re-float differs; shear-level sensitivity reported |
| Refusals | P | Doubled depth, extra local Airy, double water feedback, increment, Airy rebuild on a stiff plate, dropped flexure, shifted reference, reordered columns, density and gravity mismatch, column count, forged status, undeclared or invalid level, below datum, water in rock, geometry, foreign plate, non-finite depth, a -1e-7 m depth in one exactly dry cell, volume errors, invalid columns. Each gives its code, and the inputs are byte-identical afterwards |
| Timing | P | Raw medians only; there is no matched earlier baseline, so no saving is claimed |

The finite-rigidity Fourier control uses a fully wet oblique mode on a 16 by 16 grid with
Te 15 km:

- the retained solver agrees with the closed-form `w` and `d`, reused from the retained test;
- the closed-form `B = -g rho_w a D k⁴/(lambda - rho_w g) cos(theta)` matches the recomputed
  support;
- the join matches an **independent pressure-profile quadrature**, in which overburden lies
  above the split and datum-hydrostatic pressure below, for every column;
- solver and closed-form joins agree within the propagated solve tolerance;
- the quadrature at two depths shows `dV/dc = B`;
- the anomaly `delta V` is invariant when the datum is deepened, while the naive anomaly
  `delta U_o` shifts by `Delta B`;
- traction matches the operator applied to the quadrature field, with zero net force;
- the Airy-rebuilt field differs by more than 1000 times tolerance.

The small nonuniform support control is the reviewed reproducer. It uses the same mode and
plate with a 0.1 mm bed amplitude, and the exact closed-form state at 100, 1000 and 4000 m
of mean water. The closed-form `B` does not depend on the mean water, so every amount carries
the same nonuniform support: a peak of about 0.3 Pa, and a level term `c B` of about
2.2 kJ/m² at the control's `c` = 7.5 km, against an oracle tolerance of about 0.65 kJ/m².
The control checks that:

- the join's `B` equals that one closed form at every amount;
- the relative support norm falls with the added uniform water and crosses the retained
  force tolerance, so a residual-norm classification would flip from flexural to
  compensated;
- without a declared level, the join refuses at every amount;
- with the declared level it is flexural and matches the independent quadrature;
- the omitted level term would have exceeded the fixed oracle tolerance.

The tests add that the same bed on a zero-rigidity plate is the genuine Airy limit and needs
no level.

Tests also cover:

- layer splitting;
- heating, which changes `V` but not reference mass;
- that the quadrature oracle reproduces the retained dry anomaly;
- the pure-mode traction identity, its sign, units and reduction;
- invalid traction inputs;
- a negative depth at an exactly dry cell, refused down to the smallest subnormal and
  before classification, while a signed zero is accepted as zero water;
- case/policy parity with the retained tolerances and case values;
- bound files and imports;
- refusal to overwrite an existing receipt.

The campaign also requires that the retained tools and cases it runs are the bytes recorded
by their accepted receipts, `i01-gpe-r1` and `i01-water-flexure-r1`, and that imports
resolve to those paths. The receipts' method documents and tests are reported, not gated.
Sources are bound before and after the run. A deadline overrun, a non-finite value or an
unserialisable record fails closed.

These are numerical and contract controls on manufactured fields. They are not observed
Earth comparisons or scientific acceptance.

## 9. Efficiency

The join costs `O(N L)` for the retained exact layer moments, one real FFT pair for
authentication, and `O(N)` algebra and differences. Memory is `O(N L)`. It uses no depth
quadrature, dense matrix, cache or stored history. The retained immutable `Plate` is reused
as supplied; the authentication symbol is rebuilt from its public parameters. The
independent quadrature is a test oracle and is never used by the join. Timings are raw
observations for this control, not generator speedups.

## 10. Sources

**Read for this decision:**

- [Ghosh, Holt and Flesch (2009), Geophys. J. Int., doi:10.1111/j.1365-246X.2009.04326.x](https://ceas.iisc.ac.in/~aghosh/Ghosh_gji09.pdf),
  pages 1–15 as rendered PDF:
  - §2, equations 1–7: depth-integrated balance; thin-sheet overburden `sigma_zz`; "neglecting
    flexure";
  - §4: water and ice excluded from the integral but their pressure used as a boundary
    condition; equation 14 compensation;
  - §6, equation 17;
  - §7, equations 18–20: a base reference level; the choice matters when `sigma_zz(L)` varies.

  The rock-only versus full-column comparison in section 3 is an Atlas derivation. How
  their software applied the boundary pressure was not inspected.
- [Clennett et al. (2023)](https://adamfholt.github.io/documents/papers/clennett_et_al_scirep2023.pdf),
  pages 4–6, equations 1–8. Equation 4 gives `sigma_GPE = -(L0/L) grad U`. Equation 5
  integrates *isostatically balanced* columns. Equations 2–3 carry water depth into oceanic
  isostasy and ridge push. They do not treat flexure.
- [Wickert (2016)](https://gmd.copernicus.org/articles/9/997/2016/), pages 998–1001: Table 1
  (periodic boundary: infinite tiling) and §2.1, equations 1–2. `Delta rho = rho_m - rho_f`,
  and a shoreline with water onlap is solved iteratively with `rho_f = rho_air` and the load
  re-added each cycle. This is the retained dry restoring coefficient.

**Reused, not reread:** Schachtschneider et al. (2022) Appendix B and the current gFlex
theory pages, as recorded in the water/flexure method. The Clennett archived software was
recorded as inaccessible in the GPE method and was not retried. Existing Atlas code was
inspected, not rerun:

- `check_i01_gpe.py`;
- `check_i01_water_flexure.py` and its tests;
- the torque helpers in `check_i01_closures.py`, which are bound because the GPE helper
  imports them, but not called: a periodic plane has no rigid-plate torque;
- the closure matrix, physical contract D1/D5 and the plan's ownership table.

No external software was installed or run, and no source is credited with validating this
implementation.

## 11. Remaining work

- **Unresolved material choice (owner/I08).** Decide the effective shear-transfer depth for
  finite-rigidity joins. Options include deriving it from a D2 strength envelope or from a
  declared elastic-core position. The alternative is to restrict D1 driving to compensated
  states. Until then, finite-rigidity output is conditional.
- **No omission bound.** A small nonuniform support is never treated as compensated.
  Admitting such states without a level would need a separately derived, predeclared bound
  on `c B` that covers the claimed output. None is derived here.
- **I04:** sample loaded columns on the evolving sphere; decide how D1 rigid-plate torques
  receive `V` at weak or broken boundaries; spherical gradients of `V`.
- **I08:** variable rigidity, including the load-weighted shear level; finite regions and
  exterior loads; regional replacement from one datum; external water ports.

## 12. Commands (not run by this method document)

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_water_gpe.py -v
python -B tectonics/tools/check_i01_water_gpe.py --output NEW_PATH.json
```

The CLI creates only a new exclusive receipt. Results belong in that receipt and the owner
record, not in edits to this source-bound method after the run.
