# I01 MC-03: melt segregation by two-phase compaction (instantaneous one-dimensional closure)

**WORKING NON-CANON: an instantaneous closure candidate, not generated melt or calibrated ridge supply.**
Execution results and current MC-03/I01 status live in [CURRENT_STATE](../../docs/CURRENT_STATE.md); the method and synthetic
controls below do not establish physical acceptance. The closure-matrix decision and evidence receipts remain
separate from this document.

## 1. What this closes and what it does not

The [common-Gibbs provider](I01_THERMO_PROVIDER_CONTRACT.md) extracts a *supplied* fraction of liquid. It does
not say how fast liquid leaves a partially molten column. This closure determines the liquid flux relative to the
matrix from the liquid pressure, buoyancy **and** matrix compaction resistance, for **one fixed state**. The
equations are McKenzie's two-phase formulation reduced to one vertical column, with explicit phase and mixture
volume balances.

It is an **instantaneous fixed-state solve**. The liquid volume fraction, melting rate, temperature, composition
and domain do not evolve here. The solve reports the porosity tendencies that a transient model would integrate.
Transient inventory, thermochemical coupling, moving domains and two- and three-dimensional focusing remain
I05/I06 implementation work. The [selected melt route](I01_MELT_ROUTE.md) defines a computed thermal/permeability
barrier, not a universal `z_lid(rate)` prescription. Its spatial cooling and moving freezing front are not solved
here. `Gamma` must come from supported thermal/material evolution using the thermodynamic provider; an equilibrium
phase inventory is not a production rate.

Three shortcuts are deliberately excluded:

- **A Darcy velocity on an undeclared rigid matrix.** At a sealed base it violates mass balance (section 8).
- **A prescribed extracted fraction.** That is the provider's existing input, not a flux law.
- **Cumulative production relabelled as extraction.** At a fixed state, melting changes the flux only through its
  reaction volume. The rest is stored in place (section 7).

## 2. Governing equations, units and signs

Height `z` (m) points upward and gravity is `-g z` with `g > 0`. `phi` is the **liquid volume fraction** (porosity).
`W` is the matrix velocity and `w_f` the liquid velocity (m/s, upward positive). The Darcy segregation flux is
`q = phi (w_f - W)`. Its units are m/s, a liquid volume per unit area per second, measured relative to the matrix.
`Gamma` (kg m-3 s-1) is the mass rate at which solid becomes liquid per unit mixture volume; `Gamma < 0` freezes.

Spiegelman (1993) writes McKenzie's (1984) equations as phase mass balances (his eqs 1, 2), a Darcy law (eq. 3) and
a matrix force balance with the buoyancy `-(1 - phi) (rho_s - rho_f) g` (eq. 4). With constant, unequal phase
densities his eq. (13) gives the volume change on reaction. In one dimension:

```text
liquid volume    d(phi)/dt + d(phi w_f)/dz = Gamma/rho_f
solid volume     d(1 - phi)/dt + d((1 - phi) W)/dz = -Gamma/rho_s
mixture          d(W + q)/dz = R,      R = Gamma (1/rho_f - 1/rho_s)                  [1/s]
Darcy            q = -(K(phi)/mu) (dP_f/dz + rho_f g)
force balance    dP_f/dz = d/dz[(zeta + 4 eta/3) dW/dz] - rho_bar g,   rho_bar = phi rho_f + (1 - phi) rho_s
```

The 1D matrix stress is `(zeta + 4 eta/3) dW/dz`: Spiegelman's `eta (grad V + grad V^T) + (zeta - 2 eta/3) div V`,
and ASPECT's deviatoric term with compaction viscosity (its eqs 29 and 31), both reduce to it.

Define the **overpressure** `Sigma = (zeta + 4 eta/3) dW/dz = P_f - P_total`. Here `P_total` is the total vertical
compressive load, not the mean aggregate pressure, with `dP_total/dz = -rho_bar g`. Positive `Sigma` means liquid pressure above the total load, so the
matrix dilates. In Terzaghi's terms, `Sigma` is the tension-positive effective vertical stress. The compaction rate
is `C = dW/dz = Sigma/xi`, where `xi = zeta + 4 eta/3`.

This `Sigma` is **not** the route's ASPECT-convention compaction pressure `p_c = -zeta C`. In wet cells,
`Sigma = -(xi/zeta) p_c`: the sign and shear contribution both matter. With that convention the mean aggregate
pressure is `P_f + p_c = P_total + (4 eta/3) C`. A physical pressure datum and an explicit choice of the pressure
used for thermodynamics are required before connection to G25; the solver's relative pressures are not direct
provider inputs. Eliminating `P_f` gives:

```text
q = -k (dSigma/dz - beta),      k = K/mu [m2 Pa-1 s-1],      beta = (1 - phi)(rho_s - rho_f) g [Pa/m]
Sigma/xi + dq/dz = R     =>     -d/dz[k (dSigma/dz - beta)] + Sigma/xi = R
```

This is an elliptic equation with compaction length `delta = sqrt(k xi)` (Spiegelman eq. 14). Without compaction
gradients, `q -> k beta`: the rigid-matrix Darcy flux, which is a limit, not the closure. The phase balances in the
matrix frame give two expressions for the porosity tendency, which must agree:

```text
D(phi)/Dt|W = Gamma/rho_f - phi C - dq/dz  (liquid)  =  (1 - phi) C + Gamma/rho_s  (solid)
```

Their difference equals the mixture balance. Spiegelman's eq. (9) is the solid form.

### Declared constitutive forms

- **Permeability:** `K(phi) = K_r (phi/phi_K)^n` with `n > 0`, so `K(0) = 0` exactly. This is the power-law form
  of Spiegelman eq. (5) and Keller & Katz (2016) Table 1.
- **Bulk viscosity:** `zeta(phi) = zeta_r (phi/phi_z)^(-m)` with `m >= 0`. Keller & Katz use `m = 1` (their
  `p`).
- **Viscosities:** `eta` and `mu` are constants.

This is the selected route's fixed-grain-size, constant-shear-viscosity slice: their fixed factors can be absorbed
in the declared reference coefficients. The route selects `m > 0`; this tool also admits `m = 0` as an analytical
constant-bulk-viscosity control, not as the selected route's near-dry law.

Not implemented: the `(1 - phi)` prefactors and `exp(-alpha phi)` melt weakening of Keller & Katz (2016) and
ASPECT; ASPECT `melt_global`'s `k0 phi^3 (1 - phi)^2`; percolation thresholds; anisotropic permeability. Every
coefficient is an explicit input with provenance. None has a default.

## 3. Approximations stated explicitly

**Compressibility.**

- Each phase is individually incompressible with one declared constant density over the column. `rho_s` and
  `rho_f` may differ.
- The matrix changes volume only by porosity change: `dW/dz` is nonzero.
- Pressure, temperature and composition dependence of phase volume is not represented in this solve. The provider
  supplies thermodynamic phase volumes through `V`, which need not agree with constant transport densities across
  an evolving state. The integrating case must declare reference densities, the admitted state interval and an
  assessed volume/density error bound, as required by the selected route. Failure of that bound requires a
  variable-density extension, not silently feeding per-cell provider densities to this closure.
- ASPECT's eq. (30) shows the density-gradient terms that a compressible extension would add.
- Per-cell densities are refused as unsupported.

**Reaction volume.** `R = Gamma (1/rho_f - 1/rho_s)` is retained exactly. It agrees with Spiegelman eq. (13),
written `Gamma Delta rho/(rho_s rho_f)`, with ASPECT methods eq. (30), and with ASPECT `melt.cc`'s
`melting_rate * (1.0/fluid_density - 1.0/solid_density)`.

- No Boussinesq substitution sets `R = 0` while keeping unequal densities in the buoyancy.
- Declaring equal densities removes the reaction volume and the buoyancy together.
- A closed rigid box with unequal densities and melting is refused (section 4).
- As I read the Keller & Katz (2016) author-manuscript copy consulted, its eq. (20b) combined with its printed
  `Delta(1/rho) = 1/rho_s - 1/rho_l` gives contraction on melting when `rho_l < rho_s`. That is the opposite sign
  from the phase balances.
- Its three-field sign conventions were therefore not used. The published version was not checked.

**Momentum.** The closure assumes creeping flow and a single liquid pressure, following Spiegelman's discussion of
eqs (3) and (4). It has no surface tension and no disequilibrium pressure. There is no shear, corner flow or
focusing in one dimension.

## 4. Supported boundary data

Each end declares one melt condition. The kinds follow Spiegelman (1993) section 3.2:

| Kind | Condition | Discrete form | Correspondence |
| --- | --- | --- | --- |
| `flux` (value `q`, m/s) | Upward component of matrix-relative Darcy flux; `0` seals relative segregation | Face flux prescribed exactly | Relative impermeability; ASPECT's prescribed `dp_f/dn` fixes a normal Darcy flux after conversion to the outward-normal sign |
| `rigid` | `C = 0`, so `Sigma = 0` | Half-cell to `Sigma = 0` | Spiegelman's rigid boundary |
| `free_flux` | `dSigma/dz = 0`: no compaction resistance to the normal flux | `q = k beta` with the boundary cell's values | Spiegelman's free-flux `grad C . dS = 0` (equal for constant `xi`); ASPECT's `average density` fluid-pressure gradient `rho_bar g.n` gives the same flux |

Both boundary `q` values use upward-positive coordinates: outward relative flux is `-q_bottom` at the base and
`q_top` at the top. A zero `q` does not by itself prevent liquid carried with the matrix from crossing a fixed
receiver. The matrix velocity `W` is declared at one end, for example an upwelling rate at the base.

**Two matrix velocities.** These are admitted only when neither end is `rigid`. Both boundary fluxes are then
known, and the mixture balance

```text
W_top + q_top - W_bottom - q_bottom = sum(R h)
```

must close within `1e-12` of the exactly rounded term sum. Otherwise the declaration is refused as
`REFUSED_INCOMPATIBLE_BOUNDARY`. A closed rigid box with melting and unequal densities is therefore refused. The same
box without reaction, or with equal densities, is admitted.

**Other boundary refusals** (`REFUSED_BOUNDARY_DECLARATION`, or `REFUSED_UNSUPPORTED_INPUT` for a varying flux):

- no matrix velocity;
- two velocities with a `rigid` end;
- a missing or superfluous flux value;
- an unknown kind or field;
- non-finite values.

**Physical choice of the top.** Each case must declare its extraction-boundary condition; there is no default.
The selected route supplies the thermal/permeability-barrier model choice, not a universal boundary value.
Spiegelman notes that an impermeable cap disaggregates unless freezing balances the impinging flux
(Sparks & Parmentier 1991). Spatial implementation and a supported moving freezing front remain I05/I06 work.

## 5. Dry and disconnected states, without floors

`phi = 0` exactly means no liquid, no liquid pressure and no pores:

- `K = 0` exactly, from the power law. No floor is added.
- The cell is rigid in compaction: a pore-free cell cannot compact. This is a declared rule for every `m`. For
  `m > 0`, `zeta` also diverges as `phi -> 0`.
- `Sigma`, `P_f` and `delta` are reported as undefined (NaN). `C` is exactly zero.

**Interfaces with wet cells.** A face with a dry side has conductance and buoyancy flux exactly zero. It is
therefore impermeable, with a continuous matrix velocity. This is Spiegelman's solid/two-phase interface: no slip
for the matrix, impermeable for the melt.

**Disconnected wet segments.** Wet cells enclosed by dry cells are solved as sealed columns. Each segment's net
dilation equals its reaction volume.

**Refusals.**

- **Dry boundary cell:** it admits only a zero `flux` condition. A `rigid` or `free_flux` condition is refused
  (`REFUSED_DRY_BOUNDARY_CONDITION`). A nonzero flux is `REFUSED_INCOMPATIBLE_BOUNDARY`.
- **Freezing in a dry cell:** refused (`REFUSED_DRY_REACTION`).
- **Melting in a dry cell with unequal densities:** refused (`REFUSED_DRY_REACTION`). The volume change would have to
  open pores, which the rigid dry cell cannot do. The onset needs a resolved transient in I05/I06.
- **Melting in a dry cell with equal densities:** has zero reaction volume and is admitted. The liquid is stored in
  place.

**Numerical limits.**

- Positive but unrepresentable porosities, where `K` underflows or `zeta` overflows, are refused
  (`REFUSED_NUMERIC_RANGE`). They are never floored.
- A wet cell coarser than `delta/4` is refused (`REFUSED_UNRESOLVED_COMPACTION_LENGTH`). For `n > m`, `delta`
  shrinks as `phi -> 0`, so a near-solidus state needs a finer grid.

**Contrast with ASPECT.** ASPECT's `melt.cc` switches melt transport off in cells whose Darcy coefficient is below
a threshold times a reference value. Its `p_c_scale` limits the scaling the same way. This closure has no such
switch.

## 6. Discretisation, solve and reuse

**Grid and conductances.** The grid is cell-centred finite volumes on any strictly increasing faces:

- `Sigma` lives at cell centres. `q` and `W` live on faces.
- An interior face between wet cells has the series conductance of its two half cells,
  `G = 1/(h_below/(2 k_below) + h_above/(2 k_above))`: a harmonic mean.
- Its buoyancy uses the half-cell mean `phi_face = (phi_below h_below + phi_above h_above)/(h_below + h_above)`.
  The face flux is then `q = G (Sigma_below - Sigma_above) + G d (1 - phi_face)(rho_s - rho_f) g`, where `d` is the
  distance between centres.
- A rigid boundary uses the half cell to `Sigma = 0`.

**Boundary-face accuracy.**

- Given fluxes are exact.
- At a rigid face, the boundary cell's `k` gives an O(h) flux truncation. The strong half-cell coupling absorbs
  it, so the fields stay second order.
- A `free_flux` face takes `k beta` from the boundary cell's centre. With varying coefficients that face value is
  only first order. With uniform coefficients, as in the closed-form controls, it is exact.
- No prepared accuracy check uses `free_flux` with varying coefficients. The balance control does, but it checks
  balances only.

**Cell rows.** Each wet cell's row is its mixture balance with `W` eliminated by `dW = Sigma h/xi`. The result is a
symmetric positive-definite tridiagonal system in the wet cells, with coupling zero across dry gaps. The system is
factorised once with `scipy.linalg.cholesky_banded` and solved with `cho_solve_banded`.

**Recovered fields.**

- `W` is accumulated from its single datum.
- `P_total` is integrated from the top face with piecewise-constant `rho_bar`, and `P_f = P_total + Sigma`.
  Pressures are reported relative to the top face's total vertical compressive load. The absolute datum and
  thermodynamic-pressure mapping belong to the integrating model (section 2); neither is supplied by this solve.
- These choices make the reported `P_f` reproduce every interior Darcy flux exactly, liquid weight `rho_f g`
  included.

**Reuse.** The operator depends only on the grid, `phi`, the transport law (`K`, `mu`, `eta`, `zeta`) and the two
kinds. Densities, gravity, melting rate, boundary values and the matrix velocity are loads.

- `prepare(...)` returns an immutable `Operator` whose arrays are backed by read-only bytes.
- `Operator.solve(...)` reuses its factor exactly for changed loads.
- If any operator input differs, even by one ulp, it is refused (`REFUSED_OPERATOR_MISMATCH`).
- Nothing accumulates between solves, and memory is `O(cells)` up to 65536 cells.

**Where reuse is real.** Reuse helps when the porosity is frozen while loads change, for example a
provider/segregation iteration on the melting rate within one I05/I06 step, or several density or boundary
scenarios. It does not help across time steps whose porosity changes. The prepared timing command records raw
matched samples only. No saving is claimed.

## 7. What the outputs mean

`Result.summary()` reports several quantities:

- `top_segregation_flux_m_s` and `top_relative_liquid_mass_flux_kg_m2_s`: the instantaneous liquid flux relative to the
  matrix through the **declared** top condition, `rho_f q_top` for the mass flux;
- column production `sum(Gamma h/rho_f)`;
- column reaction volume;
- balance residuals and compaction-length resolution.

These are not a steady-state extraction rate, a focused ridge supply or a time-integrated inventory.

**Receiver frame.** `Result.relative_liquid_mass_flux_kg_m2_s` likewise reports `rho_f q`, not absolute liquid
delivery. For a fixed face, the upward liquid mass flux is `rho_f (phi_face W + q)`. For a face moving upward at
`v_face`, it is `rho_f [phi_face (W - v_face) + q]`. Only a face moving with the matrix has delivery `rho_f q`.
`Result.liquid_mass_flux_at_faces(face_liquid_volume_fraction, face_velocity_m_s)` requires both the caller's
admitted liquid-fraction trace and face speed explicitly. It performs no hidden interpolation: the buoyancy
average in section 6 does not certify an advective face trace. Convert coordinate fluxes to outward signs before
forming transfers. Finite transfers additionally require face area, a supported time interval, donor availability
and the incoming liquid composition/enthalpy; this instantaneous solve supplies none of those accounts.

**Production is not flux.** At a fixed state, `q` responds to melting only through `R`. Produced liquid otherwise
raises the porosity tendency in place, which is the stock/rate distinction made in
[phase-aware delivery](I01_DELIVERY.md). The derivation control checks that the top flux and its response to doubled
melting differ from production and its increment.

**Volume fraction versus mass fraction.** The state takes `liquid_volume_fraction` only. A declaration carrying
`melt_fraction`, `liquid_mass_fraction`, `mass_melt_fraction` or `degree_of_melting` is refused.

The helpers convert the **local retained** liquid mass fraction `x`:

- `phi = (x/rho_f)/(x/rho_f + (1 - x)/rho_s)`, from Keller & Katz's `rho_bar f = rho_l phi` and
  `rho_bar (1 - f) = rho_s (1 - phi)`;
- its inverse;
- `phi = V_l/(V_l + V_s)` from extensive phase volumes, such as the provider's `V` accounts.

Scalar conversions form the ratio using exact `Fraction` arithmetic before conversion to a float. This avoids
intermediate overflow in a sum of large phase volumes and underflow in mass/density divisions; representable tiny
positive fractions are retained, and an unrepresentable positive result is refused, not rounded to a dry state.
The volume conversion is an algebraic basis conversion, not evidence that a provider state is consistent with the
declared constant transport densities.

A parcel's cumulative degree of melting is production history. It is not the liquid present after segregation.

## 8. Bounded checks and frozen allowances

The allowances were fixed in the executable `POLICY` and the case before candidate execution. Execution status
and evidence belong in [CURRENT_STATE](../../docs/CURRENT_STATE.md), not in the definitions below. The case uses synthetic
values, labelled synthetic:

- `rho_s = 3300` and `rho_f = 2800` kg/m3;
- `k = 1e-13` m2/(Pa s) at 1%, cubic;
- `zeta = 6e18` Pa s at 1%, `phi^-1`;
- `eta = 3e18` Pa s.

These give `delta = 1` km. The column is 4 km with `Gamma = 1e-9` kg m-3 s-1 and `W = 1e-9` m/s.

| Control | Independent reference and criterion |
| --- | --- |
| `derivation` | Closed form `Sigma = xi R + a e^{-(z_t-z)/delta} + c e^{-(z-z_b)/delta}`, solved separately for six condition pairs. Error `<= 0.5 (h/min(delta, L))^2`. Sealed base: compaction (`C < 0`) and a flux at `delta/2` at least 25% from the rigid-matrix `k beta`. `W + q` uniform without reaction. A 100x stiffer matrix cuts the peak flux below 25%. Top flux and its increment differ from production by at least 25% |
| `refinement` | Constant coefficients (closed form) and manufactured variable coefficients (`phi` varying 20%, cosine `Sigma`, analytic `Gamma`, Gauss-Legendre `W`) on `h/delta = 1/8, 1/16, 1/32`. Observed order in `[1.8, 2.2]` for `Sigma`, `q` and `W`. Finest manufactured error `<= 1e-2` |
| `reversal` | Swapping the densities through one factor negates `Sigma`, `q` and `W` bitwise. An injected downward top flux (`-2 k beta`) reverses `q` against buoyancy with signs matching the closed form |
| `balances` | Graded grid, dry base, disconnected segment, melting and freezing, free-flux top, top datum. Per-cell mixture and phase residuals `<= 1e-12` of the balance scale; column total. Reported `P_f` reproduces Darcy fluxes (`1e-11`) with an independently recomputed face mobility. Exact zero flux on dry-sided faces; rigid translation through dry cells |
| `dry_limits` | Equal densities: exact zero `Sigma` and `q`, liquid stored in place. All dry: no solve, exact zero flux, undefined liquid pressure. A dry base and a disconnected segment match sealed closed forms. Five dry refusals, inputs unchanged |
| `boundaries` | Closed box refused with melting; admitted without reaction (`W + q = 0`) or with equal densities; compatible open column admitted. Eleven refusals, inputs unchanged: two volume-balance incompatibilities and nine malformed declarations |
| `porosity_basis` | Exact rational reference, round trip, equal-density identity, phase volumes, refused mass-fraction state |
| `reuse` | Four changed loads bitwise equal to fresh preparations. Operator fingerprint and size unchanged; arrays read-only. Seven operator-input changes refused, three of them one ulp (fraction, face, permeability) and one a changed melt-condition kind |
| `timing` | Raw interleaved samples, fresh against reused, at 256 and 4096 cells. Bitwise agreement only; no claim |

**Basis of the allowances.** The `0.5 (h/delta)^2` allowance is an a-priori bound with a safety factor. The
three-point scheme's decay-length error is about `(h/delta)^2/(24 e)`. The half-cell rigid boundary shifts the
boundary-layer amplitude by about `(h/delta)^2/8`, and flux boundaries are exact. The balance and pressure
tolerances are rounding bounds for the stated scales.

## 9. Sources actually consulted for this implementation

**ASPECT documentation.** [Melt transport methods](https://aspect-documentation.readthedocs.io/en/latest/user/methods/melt-transport.html),
the latest page: equations 29–32, the definitions of `K_D` and `xi`, the treatment of solid compressibility, and the
approximate-Darcy section with its mass-conservation limitation.

**ASPECT source** (`main`, fetched 28 September 2026; no commit recorded):

- [`source/simulator/melt.cc`](https://github.com/geodynamics/aspect/blob/main/source/simulator/melt.cc), lines
  1–1000 of 2085: `p_c_scale` and the `K_D` threshold, the Stokes/melt assembly including the reaction-volume
  term, and the fluid-pressure boundary term.
- [`boundary_fluid_pressure/density.cc`](https://github.com/geodynamics/aspect/blob/main/source/boundary_fluid_pressure/density.cc):
  the solid, fluid and average density gradient options.
- [`material_model/melt_global.cc`](https://github.com/geodynamics/aspect/blob/main/source/material_model/melt_global.cc):
  the permeability, compaction viscosity and density laws. Its compaction viscosity is `xi_0 exp(-alpha phi)`, with
  no `1/phi`.

Nothing was installed or run.

**Spiegelman (1993),** J. Fluid Mech. 247, 17–38, from the
[author-hosted scan](https://www.ldeo.columbia.edu/~mspieg/FDPM1_S0022112093000369a.pdf), pages 17–28:

- eqs (1)–(14);
- section 3.2 on boundary conditions;
- sections 4.1–4.3.

**McKenzie (1984),** J. Petrol. 25, 713–765: the abstract only. The article was paywalled, and its equations were
used as written by Spiegelman.

**Keller & Katz (2016),** the [Glasgow eprint author manuscript](https://eprints.gla.ac.uk/195948/1/195948.pdf),
manuscript pages 7–16:

- sections 1–2.3;
- eqs (17)–(23);
- Tables 1–2;
- the mass- and volume-fraction relations.

**Not read.** Katz's lecture notes, whose URL returned 404, and Dannberg et al. (2019), seen only as a search
summary. Atlas's [delivery method](I01_DELIVERY.md), [provider contract](I01_THERMO_PROVIDER_CONTRACT.md) and closure
matrix row were read for scope only.

## 10. Input gaps, remaining work and the next integration boundary

**Input gaps (not guessed).**

- Calibrated permeability (`K_r`, `n`, grain size, geometry, possible thresholds).
- Bulk and shear viscosities and their melt, temperature and depletion dependence.
- Liquid viscosity and composition.
- Common reference phase densities and an assessed error bound against provider `V` over the admitted states.
- The case's physical top condition and its relation to the selected thermal/permeability barrier.
- Base inflow and upwelling rate provenance.

**Remaining work.**

- Transient porosity evolution: advection by `W`, porosity waves, time step.
- A production rate from supported thermal/material evolution using provider phase amounts and energy, with a
  declared time/path/depletion treatment; equilibrium phase amounts alone do not supply `Gamma`.
- Energy and composition carried by actual frame-correct liquid transfers.
- The compressible (variable-density) extension.
- The onset of melting at a dry boundary.
- Near-solidus resolution.
- Two- and three-dimensional focusing.
- Spatial cooling and the selected axial barrier, including a supported moving freezing front.
- Moving domains.

**Next integration boundary (I05/I06).** A transient column integrator would:

1. freeze the state;
2. obtain `Gamma` from supported evolution and declare constant reference densities within their assessed
   provider-volume error bound;
3. call this closure;
4. advance `phi` with the matrix-frame tendency plus advection by `W`;
5. integrate the frame-correct face liquid mass flux over the declared area and time interval, respecting donor
   availability, then form the provider's `extract` fraction and paired `TransferProposal` accounts with the
   appropriate incoming liquid composition and enthalpy;
6. deliver across the declared top under its admitted boundary and phase support.

No live G25-to-segregation-to-receiver evolution is established by this fixed-state closure. In particular, the
native G25 route currently refuses phase appearance/disappearance: transporting pre-existing liquid does not
establish generated ocean crust, a freezing lid or experimental calibration. Those physical-acceptance gates
remain downstream even if I01 selects the restricted law and its numerical feasibility is demonstrated.

I02 still owns the once-only commit. Codex decides whether the matrix records this closure as MC-03's selected
segregation law.

## 11. Commands and execution status

From the repository root; consult [CURRENT_STATE](../../docs/CURRENT_STATE.md) for recorded execution and results:

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_melt_segregation.py -v
python -B tectonics/tools/check_i01_melt_segregation.py --timing
python -B tectonics/tools/check_i01_melt_segregation.py --output NEW_PATH.json
```

The campaign binds this document, the tool, the case and the tests. It writes only a new, never-overwritten
receipt. Capture evidence only after review.
