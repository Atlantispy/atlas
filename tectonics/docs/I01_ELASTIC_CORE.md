# I01 MC-07: one elastic core for stiffness and load transfer

**28 September 2026. WORKING NON-CANON. Bounded I01 material-closure step for closure-matrix item MC-07
(rows CM-04 and CM-15).** The [water-loaded GPE join](I01_WATER_GPE.md) left one material choice open. For
nonuniform finite rigidity it needs the depth `c` at which the plate's vertical shear hands a column's excess
weight to the uniform mantle pressure. This step supplies that depth from a declared material model: one
homogeneous elastic core whose position in the rock column fixes both the flexural rigidity `D` and the
transfer depth `c`.

It is not:

- a new integration stage;
- a temperature or strength (D2) producer;
- a variable-rigidity, multi-core or yielding law;
- a spherical calculation;
- proof that MC-07 or I01 is complete.

The retained join, dry-column and water/flexure helpers, their cases and their receipts are imported and read,
never edited.

## Decision

Contract `atlas.single-elastic-core.v1`:

- **One declared core.** The caller declares one homogeneous, isotropic, linear elastic core:
  - its top and bottom depths `a < b` below each column's rock surface;
  - Young's modulus `E` and Poisson's ratio `nu`;
  - a material identity;
  - a provenance or assumption basis.

  The branch is horizontally constant (scalar `a`, `b`, `E` and `nu`) and column-following.
- **Both quantities come from one interval.** With `h = b - a`:
  - the rigidity is `D = E h³/[12(1-nu²)]`;
  - the effective shear-transfer depth is `c = (a+b)/2`, the centroid of the core's Kirchhoff
    shear-divergence density (section 3).

  None of `D`, `Te` or `c` is accepted as an input.
- **The retained plate and the unchanged join.** The producer builds, or authenticates, the retained periodic
  `Plate` whose `Te`, `E` and `nu` are exactly the core's `b - a`, `E` and `nu`. It passes `c`, with the core's
  basis, to the unchanged `water_loaded_gpe`. The join's water accounting, classification and tolerances do not
  change.
- **Declared, not inferred.** The core is a declared material model. It is not inferred from `D` or `Te`, which
  cannot locate it (section 3.5), and not calibrated to terrain. A surface-starting core (`a = 0`) must be
  declared as such.
- **Zero rigidity is not a core.** A finite `E` and `h` cannot represent `D = 0`. A zero-rigidity plate is
  refused here; the join's zero-rigidity limit is used without a core.

The regime label is the join's own. A nonuniform finite-rigidity state is still
`FLEXURAL_CONDITIONAL_SHEAR_LEVEL`: its potential is conditional on the declared core, which now carries a
physical basis instead of a free depth.

## 1. What moves through this connection

Two retained consumers need the core:

- **The water/flexure solver** needs only `D`. The deflection `w`, water depth `d` and sea level do not depend on
  where the core sits.
- **The water/GPE join** needs the depth `c` of the plate's load transfer, and `d(delta V)/dc = B`.

Before this step, `c` was a free input. One declared interval now fixes both, so a caller can no longer pair a
rigidity from one layer with a transfer depth from another.

The producer takes the declared core, the retained dry-column inputs, a retained `Plate` and a supplied
water/flexure state. It then:

1. validates the core;
2. checks that the plate carries exactly this core's stiffness;
3. checks that the core lies inside every rock column;
4. hands `c` and the core's basis to the unchanged join.

It returns the join's result unchanged, with a record of the core added. It does not solve for water, change the
dry columns, re-float a column or add a second water load.

## 2. Inputs, units and guards

The declaration is a mapping or the frozen `ElasticCore`, with exactly these fields:

| Field | Meaning | Guard |
| --- | --- | --- |
| `material` | Material identity | Nonempty text |
| `basis` | Provenance or assumption basis | Nonempty text |
| `depth_reference` | Datum of the depths | Exactly `rock_surface` |
| `top_depth_m`, `bottom_depth_m` | `a` and `b` below each column's rock surface (m) | Finite real scalars; `0 <= a < b`; `b <= min H` over the represented columns |
| `young_pa` | `E` (Pa) | Finite and positive |
| `poisson` | `nu` | `-1 < nu < 1/2`, the isotropic stability range. The retained `Plate` also needs `nu >= 0` |

- Units are in the field names: metres and pascals, with `nu` dimensionless. Text such as `"70 GPa"` is refused.
- `h`, `D` and `c` are derived and must be finite and positive. None may be declared:
  - a `Te` or `D` field beside the placement is refused;
  - a declaration carrying `Te` or `D` without placement is refused as unplaced.
- A surface-starting core needs an explicit `top_depth_m = 0`. There is no default placement.
- One core per declaration. An array value (lateral variation), a list of cores, or a `layers` or `cores` field
  is refused as unsupported.
- `H` is each column's rock thickness, the sum of its layer thicknesses, from the same columns the join validates.

## 3. Derivation: from the core's bending stresses to the transfer depth

### 3.1 Conventions and boundary conditions

```text
z upward, g constant, tension positive
z_r = z0 - w                 loaded rock surface; w is the retained downward-positive total deflection
s = z_r - z                  depth below the rock surface, downward-positive
core: a <= s <= b,  h = b - a,  zeta = s - (a+b)/2        (distance from the core mid-surface)
p_o(z) = g integral_z^T rho dz'                            overburden of rock and water above z
Phi = sigma_zz + p_o                                       departure of the vertical stress from the overburden
S = d_x sigma_xz + d_y sigma_yz                            horizontal divergence of the vertical shear
```

Vertical equilibrium, `d_x sigma_xz + d_y sigma_yz + d_z sigma_zz = rho g`, gives `d_z Phi = -S`, that is
`dPhi/ds = S`. The boundary conditions are those of the join:

- **Top.** The sea surface, or the dry rock surface, is traction-free, so `Phi = 0` there.
- **Above the core.** Water and any rock above the core carry no shear on horizontal planes, so `Phi = 0` for
  `s <= a`.
- **Below the core.** Rock below the core and the inviscid mantle carry no shear, so `Phi` is constant for
  `s >= b`.
- **Datum.** The datum carries the uniform pressure `P`, `sigma_zz(zc) = -P`. Hence `Phi(s >= b) = p_o(zc) - P = B`.

So the core's shear carries exactly the column's excess weight over its uniform support:

```text
integral_a^b S ds = B = g (rho_w d - rho_m w) = D biharmonic(w)
```

The last equality is the retained plate equation.

### 3.2 The shear inside a homogeneous core

Kirchhoff plate theory makes three assumptions (Kelly §6.1.2 (i)–(iii); Wickert 2016, Appendix A1):

- the mid-plane of a homogeneous plate is its neutral plane, free of in-plane strain;
- normals remain normal;
- vertical strain is ignored.

The bending stresses are therefore linear in `zeta` (Kelly eq. 6.2.30). Over a symmetric section
`integral zeta dzeta = 0`, so bending adds no net in-plane force (Wierzbicki eq. 55). Gravity supplies no
horizontal body force. With shear-free top and bottom faces, horizontal equilibrium then fixes a parabolic
transverse shear stress (Kelly eqs 6.4.13–6.4.15):

```text
sigma_zx = -(3 V_x / 2h) [1 - (2 zeta / h)²],     V_x = D d_x laplacian(w)         (Kelly 6.4.12, his signs)
```

In Kelly's signs, with his upward `w`, the shear resultants have divergence `d_x V_x + d_y V_y = D biharmonic(w)`,
which equals `-q` (his eqs 6.4.3 and 6.4.10). The horizontal divergence of the shear stress therefore has the same
parabolic shape. Its magnitude and sign in the column follow from section 3.1:

```text
S(s) = B phi(s),     phi(s) = (3/2h) [1 - (2 zeta/h)²] = 6 (s - a)(b - s) / h³
```

The parabola's shape and normalisation do not depend on sign conventions. The sign of the transferred load
follows from `integral S ds = B`. Kelly's upward deflection and downward face pressure give the same magnitude.

The thickness integral of the stress form recovers the rigidity:

```text
integral_{-h/2}^{h/2} E/[2(1-nu²)] (h²/4 - zeta²) dzeta = E h³/[12(1-nu²)] = D
```

This is Kelly eq. 6.2.32, Wierzbicki eq. 40 and Wickert eq. A8.

The density has these properties:

```text
integral_a^b phi ds   = 1
integral_a^b s phi ds = (a+b)/2                          phi is symmetric about the mid-surface
G(s) = integral_a^s phi ds' = F(u) = 3u² - 2u³,  u = (s-a)/h;   F(0) = 0, F(1) = 1, F(1-u) = 1 - F(u)
```

So the vertical stress passes continuously through the core:

```text
-sigma_zz = p_o                s <= a         overburden
          = p_o - B F(u)       a <= s <= b    smooth transition carried by the core's shear
          = p_o - B            s >= b         hydrostatic from P at the datum
```

For a plate loaded by `q` above a free base, the same cubic joins the face values of Kelly's eq. 6.4.1. It
follows from integrating his third equilibrium equation (6.4.6) with 6.4.3 and 6.4.15. That integration is an
Atlas check: Kelly neglects `sigma_zz` in the plate law (p. 149). Here `sigma_zz` is recovered from
equilibrium, not from the constitutive law.

### 3.3 The transfer depth

`V = -integral_zc^T sigma_zz dz = U_o - integral_zc^T Phi dz`, with `U_o` the fixed-datum overburden integral of
the join. Since `integral_0^1 F du = 1/2`,

```text
integral_zc^T Phi dz = B (z_r - b - zc) + B h integral_0^1 F du = B (z_r - (a+b)/2 - zc)
```

so

```text
V = U_o - (z_s - zc) B,     z_s = z_r - c,     c = (a+b)/2
```

This is exactly the join's formula ([I01_WATER_GPE.md](I01_WATER_GPE.md), section 3), with its Kirchhoff step at
the core's mid-surface. The smooth profile and the step give the same potential.

This generalises to any normalised density `phi` on `[a, b]`: `integral_a^b G ds = b - integral s phi ds`, so
the effective depth is the centroid of the shear-divergence density. For a homogeneous core that centroid is the
mid-surface. The join's closed form is unchanged:

```text
delta V = delta U0 + c B + g rho_m w (e0 - w/2) + g rho_w d²/2,       c = (a+b)/2
```

### 3.4 What the derivation needs

1. **Homogeneous `E` and `nu` in the core.** If the moduli vary with depth, the neutral surface moves towards the
   stiffer rock and the shear density is no longer symmetric. Its centroid, and so `c`, then differs from
   `(a+b)/2`.
2. **Shear-free core faces.** A stiff layer welded to the core is part of it. The single-core branch declares
   everything outside `[a, b]` shear-free, as the join already assumed.
3. **A thin plate with small deflection and constant `D`.** This is the retained plate's scope (Kelly §6.1.2; the
   footnote to eq. 6.4.9 neglects the shear forces' effect on curvature).
4. **Bending stresses that carry `B` and nothing else.** Horizontal gradients of the lithostatic stress drive D1
   through `V`. Their deviatoric response and basal drag belong to the thin-sheet balance, which neglects their
   vertical shear in `sigma_zz` (Ghosh et al. 2009, as reused by the join). Only the bending shear enters
   `sigma_zz`, as in the join.

All four hold for this branch within the retained scope, so no obstruction was found. The candidate
`c = (a+b)/2` is derived here, not copied as authority, and the controls check it by independent quadrature
(section 8).

### 3.5 Rigidity does not locate the core

`D` depends only on `h`, `E` and `nu`. Shifting the core by `Delta`, from `(a, b)` to `(a+Delta, b+Delta)`:

- keeps `D`, `w`, `d` and `B`;
- moves `c` by `Delta`;
- changes the potential by `Delta B` and the traction by `-gamma Delta grad B`.

A `Te`, or a `D`, fixes neither the depth nor the number of competent layers:

- Burov and Watts (2006, p. 6) note that `Te` values exceeding the crustal thickness "do not indicate which layer,
  crust or mantle, is strong", citing Burov and Diament (1995).
- Bellas and Zhong (2021, eqs 1–3) define `Te` through bending moments about neutral planes. Their multilayer
  cubic rule holds only if every competent layer has the same curvature.

A single core is therefore a declared material choice, not an inference from `D` or `Te`.

## 4. What follows the column, and what does not

**Reference.** `a` and `b` are measured below each column's rock surface: the loaded bed `z0 - w`, the same
material surface as the unloaded dry surface, displaced with its column. The core's faces lie at `z0 - w - a` and
`z0 - w - b`.

**The core moves with:**

- the column's total deflection `w`;
- a translation of every elevation (datum, dry surfaces, bed and sea level) at fixed `P`;
- the relief of each column's rock surface, because the branch is column-following.

**The core does not move with:**

- sea level or water depth: the depths are below the rock, not the sea surface;
- a deeper compensation datum with its matching pressure;
- `Te` or `D` alone.

**Consequences:**

- A datum translation leaves `delta V` unchanged: bitwise for a closed-form state, and within the retained
  re-solve bound for a solved one.
- A deeper datum leaves `delta V` bitwise unchanged.
- A physical core shift keeps `D`, `w` and `d` and changes `delta V` by `Delta B`. It is a different declared
  placement of material, not a change of coordinates.

**Relief.** A horizontally constant, column-following core has the relief of the rock surface. The retained linear
plate uses a flat reference geometry and omits shell (membrane–bending) coupling from that relief, alongside the
join's `N d²w` omission. This is a declared retained approximation: small slope alone does not establish that
curved-reference membrane coupling is negligible. These controls do not certify arbitrary initial relief;
admission of a physical region needs its geometry/regime assessment in I08.

**Static producer.** The core is not transported or evolved; each call evaluates one state.

## 5. Structural limits

| State | With a declared core | Reason |
| --- | --- | --- |
| Zero water | Admitted: the join classes it `zero_water`, and `delta V` equals the dry helper's bitwise | `w = d = 0`, so `B = 0` exactly and `c` is immaterial |
| Uniform loading (an exactly flat dry surface) | Admitted: `uniform_load`; `delta V` equals the join without a level within the oracle tolerance | `B` vanishes apart from the admitted residual |
| Zero rigidity | **Refused as a core**, `REFUSED_ZERO_RIGIDITY_NOT_A_CORE` | A finite `E` and `h` give `D > 0`; the unchanged join takes the Airy limit without a core |
| Finite rigidity, nonuniform loading | Admitted: `FLEXURAL_CONDITIONAL_SHEAR_LEVEL`, with `c` from the core | Conditional on the declared core |

A very thin core has a small `D`, and its `B` shrinks with `D`. It still remains flexural: no threshold turns it
into the Airy class, consistent with the join's structural classification.

## 6. Producer and atomic refusal

The public functions in `tools/check_i01_elastic_core.py` are:

- `elastic_core(declaration)`: returns a validated `ElasticCore`.
- `core_plate(core, datum, shape, length_x_m, length_y_m, *, rho_w_kg_m3)`: the retained `Plate` whose stiffness
  is the core's. It takes `Te = b - a`, `E` and `nu` from the core, and `rho_m` and `g` from the datum.
- `core_shear_level(core)`: the join's declaration `{"depth_below_bed_m": c, "basis": ...}`, which quotes the
  core's own basis.
- `core_loaded_gpe(datum, thickness, density, alpha, T_bottom, T_top, core, plate, water_state, *, volume_m3,
  geometry, connectivity)`: the producer.

The producer's checks run in this order, each with its own code:

1. **Declaration.**
   - `REFUSED_CORE_PLACEMENT_ABSENT`: no top or bottom depth, including `Te`-only or `D`-only declarations.
   - `REFUSED_UNSUPPORTED_CORE`: several cores, layers, or array-valued fields.
   - `REFUSED_INVALID_CORE`, for any of:
     - wrong or extra fields;
     - non-finite, boolean or text numbers;
     - `a >= b`, `E <= 0`, or `nu` outside `(-1, 1/2)`;
     - empty or non-text material or basis;
     - any depth reference other than `rock_surface`;
     - an unrepresentable `D` or `c`.
   - `REFUSED_CORE_OUTSIDE_ROCK`: `a < 0`.
2. **Plate.**
   - `REFUSED_UNSUPPORTED_CONTRACT`: not the retained `Plate` type.
   - `REFUSED_ZERO_RIGIDITY_NOT_A_CORE`: zero rigidity.
   - `REFUSED_UNSUPPORTED_CORE`: `nu < 0`, which the retained `Plate` cannot represent.
   - `REFUSED_CORE_SOLVER_MISMATCH`: `Te`, `E` or `nu` not exactly the core's `b - a`, `E` and `nu`, or a
     different rigidity.
3. **Columns.**
   - `REFUSED_INVALID_COLUMNS`: invalid thicknesses.
   - `REFUSED_CORE_OUTSIDE_ROCK`: `b > min H`. A core may reach the thinnest rock base (`b = min H`), because the
     inviscid mantle below it is shear-free.
4. **The unchanged join**, given `c` and the core's basis. It applies its own checks in its own order:
   contract; datum and plate `rho_m` and `g`; columns and water in rock; water fields; reference; load;
   equilibrium; classification; geometry; representation. It returns `REFUSED_NOT_FLEXURAL_EQUILIBRIUM` for:
   - a state solved on another rigidity;
   - an Airy state on the core's plate;
   - a stale deflection.

Agreement is exact; no tolerance is applied:

- `core_plate` builds the matching plate. An independently built plate whose `Te` is bitwise the same `b - a`
  also matches.
- An interval whose `b - a` rounds to a different `Te` is refused, never snapped.
- A core with a different `E` and `h` but about the same `D` is a different declared material, and is refused.

Refusals raise before any result exists. The producer copies and modifies nothing; the join copies its own
inputs.

The result is the join's unchanged dictionary plus an `elastic_core` record containing:

- the contract, branch and derivation text;
- `material`, `basis` and `depth_reference`;
- `a`, `b`, `h`, `E`, `nu`, `D` and `c`;
- `thinnest_rock_m` and `rock_below_core_m`.

## 7. Validity and restrictions

- **Admitted scope.** One homogeneous, isotropic, linear elastic core, horizontally constant and
  column-following, inside every rock column. It sits on the retained planar, periodic, constant-`D`,
  small-deflection plate with one communicating reservoir.
- **Placement is declared, not inferred.** Nothing infers the core's location from temperature or strength (D2),
  `Te`, `D` or terrain. No Earth, Diadem or I08 core is selected here.
- **Not claimed:**
  - variable `D` or laterally varying cores;
  - multiple, decoupled or layered cores, which need a load-weighted centroid;
  - yielding cores or depth-varying moduli;
  - anisotropy;
  - time-dependent relaxation or decoupling;
  - thick-plate corrections.
- **Not modelled.** Finite regions and exterior loading; spherical sampling and support; the assembly of D1
  rigid-plate torques at weak or broken boundaries. These remain I04 and I08 work, as in the join.
- **No completeness proof.** Nothing here proves that MC-07 or I01 is complete. Closure is decided by review, the
  owner and the closure matrix.

## 8. Controls and what each establishes

The focused tests are in `tests/test_i01_elastic_core.py`. The bounded source-bound campaign is
`tools/check_i01_elastic_core.py --output NEW.json`. The case `cases/i01_elastic_core_v1.json` freezes tolerances,
inputs and a 60 s cooperative budget before execution.

- Every tolerance is copied from the retained join. The executable refuses a copied tolerance that differs from
  the join's.
- The case must reproduce the retained water/GPE declarations, including their 7.5 km control level.

Rows marked **P** use actual retained producer output: the retained `columns()`, `Plate.equilibrium`, the water
fixture and the unchanged join. The independent oracles integrate each column's own pressure profile by Gauss
quadrature. They never use `c B`, `(a+b)/2` or the join's algebra.

| Control | Retained output? | Demonstrates |
| --- | --- | --- |
| `derivation` | P (plate) and independent | See the list below |
| `smooth_profile_fourier` | P and independent | See the list below |
| `core_shift` | P and independent | See the list below |
| `limits` | P | Zero water is admitted and bitwise equal to the dry helper, for both potential and traction. The uniform load is admitted: the core depth is immaterial, the potential uniform and the traction zero. A zero-rigidity plate is refused as a core with its inputs unchanged, yet the unchanged join classes it `zero_rigidity` without one. Zero-modulus and zero-thickness declarations are refused |
| `refusals` | P | 36 forged, unplaced, unsupported, non-finite, unprovenanced or incompatible inputs, each refused with its code and with byte-identical inputs; a core reaching the thinnest rock base is admitted |
| `timing` | P | Raw interleaved medians of the unchanged join with the derived level and of the producer on identical inputs, at 32² and 128². No saving or cost is claimed |

The `derivation` control uses the declared core and checks that:

- the core-built plate equals the retained 15 km water-case plate and carries the core's `D`;
- `D` is recovered from the core's own shear stresses by quadrature;
- the density integrates to one, and its first moment is `(a+b)/2`;
- its running share is `3u² - 2u³` and symmetric about the mid-surface;
- the same `D` at another depth gives the same plate but a different `c`;
- the explicit surface core reproduces the retained 7.5 km level;
- a shift keeps `D` and moves `c` by `Delta`.

The `smooth_profile_fourier` control uses the retained oblique (2,1) mode: 16 by 16 cells, 1000 m of mean water,
a 10 m bed amplitude and the core's own 15 km plate, with the closed-form fully wet state. It checks that:

- the producer's result equals the unchanged join's with the derived level, field for field;
- the core's Kirchhoff shear equals the plate support. The shear is the rigidity recovered by quadrature from
  the core's stresses, times a spectral biharmonic that does not use the plate's rigidity. It also equals `B`
  within the retained force tolerance;
- **force balance:** the smooth profile's basal pressure is the uniform datum pressure in every column;
- the smooth through-core profile matches the producer's potential in columns with `B > 0` and with `B < 0`;
- a step at either core face does not: it differs by more than 1000 times the oracle tolerance;
- traction matches the operator applied to the smooth field, and the periodic net force is zero;
- the water mass equals `rho_w` times the finite volume, so water is counted once;
- the retained solver's state lies within the propagated closed-form bound;
- a deeper datum and a translated datum leave the potential bitwise unchanged, and the smooth oracle is invariant
  to the deeper datum;
- the explicit surface core equals the retained control level bitwise.

The `core_shift` control uses the partly wet retained 32 by 32 fixture on the core's plate. A 3 km shift keeps the
plate, water and deflection bitwise. It checks that:

- the potential changes by `Delta B`, within a rounding bound of `1e-12` times the largest potential;
- the traction changes by `-gamma Delta grad B`, with the retained operator;
- the change is nonuniform;
- sampled smooth oracles match both placements and shift by `Delta` times the column excess;
- deepening the datum by `Delta` leaves the potential bitwise unchanged;
- translating it by `Delta`, and re-solving with the retained solver, leaves the potential unchanged within the
  retained re-solve bound, and moves the loaded bed, and with it the core, by `Delta`.

The tests add:

- the declaration and mapping routes;
- the Gauss quadrature of the density at two orders;
- rigidity at three depths;
- a refusal table for declarations;
- a core crossing a heated layer interface, against the smooth oracle with linear effective densities;
- a core admitted at the thinnest rock base and refused 1 m below it;
- plate, state, material, column and datum refusals, all with unchanged inputs;
- case and policy parity, retained values, bound files and imports;
- all non-timing controls;
- refusal to overwrite an existing receipt.

The campaign requires the retained tools and cases it runs to be the bytes recorded by the accepted receipts
`i01-water-gpe-r1`, `i01-gpe-r1` and `i01-water-flexure-r1`, and imports to resolve to those paths. The receipts'
method documents and tests are reported, not gated. Sources are bound before and after the run. A deadline
overrun, a non-finite value or an unserialisable record fails closed.

These are numerical and contract controls on manufactured fields. They are not Earth comparisons or scientific
acceptance.

## 9. Efficiency

- **Producer checks.** The declaration and plate checks are `O(1)`. The thinnest-column check is one `O(N L)` sum
  of the thicknesses the join also reads, with no copy for floating input.
- **The join.** Unchanged: `O(N L)` exact moments, one real FFT pair to authenticate the state, and `O(N)`
  algebra and differences.
- **Reuse.** The retained immutable `Plate` and its prepared spectral symbol are reused as supplied. Any core with
  the same `h`, `E` and `nu`, for example a shifted core, yields an equal plate.
- **No new structures.** No new cache, dense matrix, stored history or repeated array copy.
- **Oracles.** The column quadrature and the spectral biharmonic are control-only and never used by the producer.
- **Timing.** Timings are raw observations of this control, not generator speedups.

## 10. Sources

**Read for this decision**, as rendered pages on 28 September 2026:

- [Kelly, *Solid Mechanics Part II*, chapter 6, "Plate Theory"](https://pkel015.connect.amazon.auckland.ac.nz/SolidMechanicsBooks/Part_II/06_PlateTheory/06_PlateTheory_Complete.pdf)
  (University of Auckland open text), pp. 120–149:
  - §6.1.2, assumptions (i)–(iii): the mid-plane is the neutral plane; normals stay normal; vertical strain is
    ignored. Accurate for thin plates with small deflection.
  - §6.1.3, eqs 6.1.1–6.1.3: moments and shear forces as thickness integrals.
  - §6.2.4, eqs 6.2.30–6.2.33: linear bending stresses and `D = E h³/[12(1-nu²)]`.
  - §6.4.1: face loads (6.4.1); force and moment balance (6.4.3, 6.4.5); the three-dimensional equilibrium
    equations with shear-free faces (6.4.6–6.4.7); `biharmonic(w) = -q/D` (6.4.9–6.4.10); `V_x = D d_x
    laplacian(w)` (6.4.12). Also the footnote to 6.4.9 on neglecting the shear forces' effect on curvature.
  - §6.4.2, eqs 6.4.13–6.4.16: the parabolic transverse shear from equilibrium. P. 149: `sigma_zz` is neglected
    in the plate law.
- [Wierzbicki, MIT OpenCourseWare 2.081J *Plates and Shells*, Part I notes](https://ocw.mit.edu/courses/2-081j-plates-and-shells-spring-2007/1bd32d641a2b41ca518591d981405393_lecturenote.pdf)
  (CC BY-NC-SA 4.0):
  - §2.1, eqs 34–39: plane-stress law; strain linear about the middle surface; `M` and `N` as thickness
    integrals.
  - Eq. 40: `D`.
  - §2.3.1, eq. 55: the curvature term carries no membrane force.
  - §4.1.1, eqs 145–157: `M_ab,ab + q = 0` and `D biharmonic(w) = q`.
  - P. 9, eq. 32: transverse stresses are small beside in-plane stresses.
- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/), Geosci. Model Dev. 9, 997–1017:
  - pp. 998–999: the classical Kirchhoff–Love thin-plate basis, derived in Appendix A;
  - Appendix A, pp. 1011–1013, eqs A1–A8: the midpoint layer of a homogeneous plate, extending over `-Te/2` to
    `Te/2`, is the reference that neither extends nor shortens. `D` assumes uniform `E` and `nu`;
  - eqs A13–A17: vertical force balance with the shear force `V`, and `V = -dM/dx`.
- [gFlex source](https://github.com/awickert/gFlex), development master branch as retrieved on 28 September 2026.
  It was read through the web-fetch tool's quoted extraction, not a local checkout:
  - `gflex/f2d.py` (`F2D._solve_fft`, `F2D.elasprep`): `D = E Te³/[12(1-nu²)]`, and the FFT route requires a
    scalar `Te`;
  - `gflex/base.py`: configuration of elastic thickness, Young's modulus, Poisson's ratio, densities and boundary
    conditions.

  It has no input for the depth of the elastic plate and no through-thickness stress output. It was not run, and
  it is a comparison, not evidence for this implementation.
- [Bellas and Zhong (2021), J. Geophys. Res. Solid Earth 126, e2021JB022678, doi:10.1029/2021JB022678](https://ashleybellas.github.io/publications/BellasZhong_2021_JGRSE.pdf),
  pp. 1–2:
  - key points and abstract;
  - eq. 1: the moment about the neutral plane `z_n`;
  - eq. 2: `M0 = kappa E Te³/[12(1-nu²)]`;
  - eq. 3: the cubic rule, attributed to Burov and Diament (1995) and Burov (2015). It holds "if and only if
    curvature is constant across layers".

  Pages 3–6 (methods and first results) were viewed but not used.
- [Burov and Watts (2006), GSA Today 16(1), 4–10, doi:10.1130/1052-5173(2006)016<4:TLTSOC>2.0.CO;2](https://topex.ucsd.edu/geodynamics/BurovWatts2006.pdf),
  pp. 4–6:
  - Figure 1 caption: the short-term mechanical thickness `Hm` versus the long-term `Te`. Decoupled competent
    layers give a `Te` close to that of the most competent layer.
  - P. 6: `Te` values exceeding the crustal thickness "do not indicate which layer, crust or mantle, is strong".

**Suggested but not read:**

- Burov and Diament (1995), J. Geophys. Res. 100(B3), 3905–3927, doi:10.1029/94JB02770. The open-archive copy
  returned a bot-protection page at both HAL addresses, and the publisher PDF was refused. It is cited only as
  reported by Bellas and Zhong (2021) and Burov and Watts (2006).
- Timoshenko and Woinowsky-Krieger (1959) and Turcotte and Schubert (2002), cited by Wickert, were not consulted.

**Reused, not reread:** Ghosh, Holt and Flesch (2009), Clennett et al. (2023), and Wickert (2016) §2.1 and
Table 1, as recorded in the [water/GPE method](I01_WATER_GPE.md).

**Existing Atlas code, inspected and not rerun:**

- `check_i01_water_gpe.py`: join, oracles, controls and CLI pattern;
- `check_i01_water_flexure.py`: `Plate` and `fixture`;
- `check_i01_gpe.py`: `Datum` and `columns`;
- the water/GPE case and its receipt `i01-water-gpe-r1`;
- the closure matrix entry MC-07;
- the physical contract §7 (D5).

**Atlas derivations:** the column balance in section 3.1, the column integral and centroid in section 3.3, the
cubic `sigma_zz` check for Kelly's plate, and section 3.5.

No external software was installed or run, and no source is credited with validating this implementation.

## 11. Remaining work

- **Owner or I08.** Select an actual core, with placement, `E`, `nu` and a basis, for any Earth or Diadem use.
  This branch only admits a declared one.
- **D2.** A temperature- or strength-to-core producer. It must show that a single homogeneous core is admissible
  for its strength envelope, or deliver several cores.
- **Several, decoupled or yielding cores.** These need a load-weighted centroid of the combined shear density,
  with per-layer neutral surfaces and curvature. It is not derived here.
- **I08.** Laterally varying cores with the full map-view variable-rigidity operator, including its Poisson
  terms; finite regions and exterior loading.
- **I04.** Spherical sampling and support, and D1 torques at weak or broken plate boundaries.
- **I05 and I09.** Core transport and evolution.
- **MC-07 status.** Acceptance and remaining choices are recorded in the closure matrix,
  evidence register and current-state page; this method document does not certify the wider choice complete.

## 12. Commands (not run by this method document)

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_elastic_core.py -v
python -B tectonics/tools/check_i01_elastic_core.py --output NEW_PATH.json
```

The CLI creates only a new, exclusive receipt. Results belong in that receipt and the owner record, not in edits
to this source-bound method after the run.
