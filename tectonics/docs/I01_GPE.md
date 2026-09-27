# I01: dry columns to gravitational driving traction

Status: **WORKING NON-CANON**, bounded D1/D5 connection. The new helper calculates
support and gravitational potential energy (GPE) from the same material and
thermal columns, then supplies calculated traction to the retained D1 torque
solver. It is not an I04 world-evolution implementation.

## What happens, in ordinary language

Thicker, lighter or hotter rock changes how much mantle is needed underneath it
to balance the weight of neighbouring columns. That changes both surface height
and how high the column's weight sits. Differences between neighbouring columns
produce a sideways gravitational force. The force is calculated from the rock
columns, not added afterwards to make the motion look plausible.

The calculation keeps one shared depth and pressure reference. It distinguishes
the mass of prescribed material from its effective thermal buoyancy. Heating
changes buoyancy; it does not delete rock. The mantle needed for static support
is reported separately, not claimed to have been transported or conserved.

## Equations and conventions

Coordinates increase upwards from a common compensation elevation `zc`. Gravity
`g`, basal pressure `P`, reference mantle density `rm` and material reference
temperature `Tref` are spatially constant within one call. Surface pressure is
zero and there is no water load. Rock layers are ordered **bottom to top** and
have positive thickness, reference density and absolute temperature.

Within a layer temperature, and thus Boussinesq effective density, is linear:

```text
r_eff = r_ref [1 - alpha (T - Tref)]
m_j   = h_j (rb_j + rt_j) / 2
q_j   = h_j^2 (rb_j + 2 rt_j) / 6
```

Here `m_j` is effective buoyancy areal load, not reference material mass;
`q_j` is its first moment measured upwards from that layer's base. `rb` and `rt`
are effective bottom and top densities. Reference rock mass is separately
`sum(r_ref*h)`. The declared control refuses thermal density anomalies over 10%;
that is a support bound, not a calibrated law for arbitrary pressure/composition.

With `m=sum(m_j)`, `b_j=sum(h_k, k<j)` and `q=sum(b_j*m_j+q_j)`:

```text
Hm = (P/g - m) / rm
surface = zc + Hm + sum(h_j)
U = integral_zc^surface p_lith(z) dz
  = g integral_zc^surface r_eff(z) (z-zc) dz
Uref = P^2 / (2 g rm)                         [common pure-mantle column]
delta_U = U - Uref = g [q - m^2/(2 rm)]      [evaluated without large subtraction]
traction_GPE = -gamma grad_s(delta_U), gamma = L0/L
```

`U` has units J/m² = N/m; traction is Pa. Negative mantle fill is refused, not
clipped. `gamma` is an explicitly supplied common reduction factor, never a
varying local column-height normalisation. Pure datum translation leaves GPE
differences unchanged. Extending all columns down through identical mantle
with the matching pressure increment leaves surface elevations and `delta_U`
unchanged. Do not replace `U` with the different moment measured down from each
column's own surface.

Thermal and compositional GPE own their distributed driving contribution. There
is no additional ridge-push line force for the same contribution. Mechanically
resolved buoyancy must replace the corresponding reduced force, not add to it.
These are hydrostatic diagnostics, not a conserved full thermodynamic energy.

## Spherical connection and efficiency

An immutable stencil prepares two perpendicular tangent directions at each
supplied unit direction. Four neighbouring directions lie a declared angular
distance away along great circles. The caller samples supported physical
columns there; central differences give the surface gradient, dividing by
`2*radius*angular_step`. No longitude singularity or pole division occurs.
This second-order stencil assumes a smooth, resolved column field; discontinuous
interfaces require explicit interface treatment, not this fixture's smooth law.

The operator can be reused when geometry and angular step are unchanged. It does
not retain changing fields or unbounded history. Column moments are exact for
piecewise-linear density, vectorised over the batch, O(columns*layers) in time
and storage. The common reference is removed algebraically before gradients,
avoiding cancellation of large absolute energies. No numerical depth quadrature,
disk cache, dense spatial matrix or process workers are needed here.

The bounded campaign passes the computed traction through the unchanged
`drag_matrix` and `solve_torque` functions in `check_i01_closures.py`. It does
not supply a prescribed torque as a substitute. The retained helper is included
in the new receipt's source bindings; its previous evidence remains unchanged.

## How we check it

1. Constant-density crust over mantle has independent Airy formulae:
   `delta_surface=(1-rc/rm)*delta_h` and
   `delta_U=.5*g*rc*(1-rc/rm)*h^2` relative to pure mantle.
2. Independent Gauss quadrature verifies a linear thermal-density layer's
   moments. Splitting a layer preserves the answer; reversing its temperature
   gradient changes the first moment correctly. Heating preserves reference
   material mass while changing support and GPE.
3. Translating the datum and extending the shared mantle reference preserve
   their declared invariants. Invalid columns, densities, temperatures and
   insufficient compensation depth are refused.
4. Constant GPE yields zero traction. A degree-one spherical field checks sign,
   radius, reduction factor, poles, tangency and rotation covariance. The setup
   cannot be mutated into a stale cache.
5. The assembled control uses two hemispheres with
   `h(n)^2=h0^2+A*n_x`. Hence `delta_U=constant+B*n_x`, where
   `B=.5*g*rc*(1-rc/rm)*A`. Each hemisphere's exact torque is
   `-gamma*B*pi*R^2*(b cross ex)`, with `b` its pole, and its basal drag matrix is
   `(4*pi/3)*D*R^4*I`. Calculated rotation must approach this independent answer
   at second order. Opposite torques cancel and distributed traction work equals
   rotational work and drag dissipation.

The case declares orders 4/8/16 and an angular step `pi/(8*order)` before running.
The finest rotation error must be below 0.1%, refinement ratios between 3.8 and
4.2, and pressure/work/torque cancellation errors below 1e-11 relative. This is
a manufactured numerical connection test, not an observed Earth comparison.

The performance comparison uses five interleaved repetitions of scalar and
vectorised **identical exact moment formulae**, on 4,096 three-layer columns.
It excludes validation, stencil construction and torque solving in both arms.
Its measured savings describe this kernel, not a previous generator release or
whole-world speedup. Results are in the new source-bound receipt and current
evidence register; no old receipt is rewritten.

## Papers and software checked

- [Ghosh, Holt & Flesch (2009), equation 7 and reference-level discussion](https://ceas.iisc.ac.in/~aghosh/Ghosh_gji09.pdf):
  integrated lithostatic pressure, basal reference and the importance of
  compensation. Atlas's exact linear-layer formula is an algebraic derivation
  for the declared column representation, not copied solver code.
- [Clennett et al. (2023), equation 4](https://adamfholt.github.io/documents/papers/clennett_et_al_scirep2023.pdf):
  negative GPE-gradient traction with a declared reduction. The paper diagnoses
  reconstructed motion; Atlas's forward torque solution is a separate extension.
  Their [archived software](https://doi.org/10.5281/zenodo.7904975) was identified
  but not accessible in this review, so no implementation parity is claimed.
- Existing Atlas `check_i01_closures.py`: inspected and reused its symmetric
  positive drag matrix and torque solve, without editing it or importing native
  source-bound simulation code. No external solver was installed or executed.

## Remaining integration boundary

Inputs are prescribed dry, locally compensated columns and smooth sampling
geometry. The helper does not infer composition, ocean age, thermal history,
slab forces, water loading, deformation, topology, mantle exchange or a geoid.
Finite-water flexure is a separate closure; its loaded beds cannot be treated
as these dry columns without a new compatible pressure/load contract. World
sampling, regional reaction ownership and evolving global state remain later
integration work. Test constants are not universal planet defaults.
