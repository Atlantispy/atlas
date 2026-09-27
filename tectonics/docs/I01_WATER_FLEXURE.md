# I01: finite water and map-view flexure

Status: **WORKING NON-CANON; a coupled, bounded D5 closure control.** This does
not start I08 regional embedding or complete I01. Existing native and earlier
I01 sources/evidence stay unchanged; the parallel weakening work is independent.

## What happens, in plain language

Water weighs enough to depress the crust. The depression changes basin capacity,
which moves the water surface and shoreline, redistributing that same water.
This prototype solves those effects together until the bed, water depth and
elastic response agree. The user supplies a water-unloaded bed, a finite volume
and a constant elastic thickness. It never creates extra water to fill newly
formed space. A flexural forebulge can rise beside a load and is not clipped off.

The grid is a two-dimensional, periodic flat plate: opposite edges connect to
copies of the same domain. All admitted water communicates at one surface level.
This is a declared static experiment, not a claim that real disconnected lakes
communicate, a free-edge regional model or a spherical planet calculation.

## Equations, signs and reference

Let the unloaded bed `z0` and water level `S` be upward-positive. Deflection `w`
is downward-positive. Water depth is `d=max(0,S-z0+w)` and the loaded bed is
`z=z0-w`. Uniform cell area `a` gives the finite-volume constraint `a sum(d)=V`.
Air density is neglected; `rho_m > rho_w > 0`.

The constant-rigidity plate solves

`L w = rho_w g d`, with `L=D ∇^4 + K`, `K=rho_m g`,

and `D=E Te^3/[12(1-nu^2)]`. **K is the dry restoring coefficient.** Using
`(rho_m-rho_w)g` here as well as updating the full water load would double-count
the water feedback. This distinction follows the explicit iterative-infill
discussion in [Wickert (2016), section 2.1](https://gmd.copernicus.org/articles/9/997/2016/).
The paper's Table 1 identifies periodic boundaries as an infinitely repeated
domain, not an isolated regional footprint.

The fixed compensation-pressure reference retains the zero Fourier mode:
`mean(w)=(rho_w/rho_m) V/domain_area`. Removing that mode would suppress physical
mean subsidence. Adding a constant to the input elevation shifts `S` by the same
amount without changing depths or displacement.

The result is a **total equilibrium relative to z0**, not a displacement to keep
adding to the already loaded bed. For a later inventory, reuse the same unloaded
reference and apply the difference between the two equilibrium displacements.
No regional/coarse overlap mapping or whole-world datum registration is provided.

## Numerical method and why it converges

The model uses the continuous spectral symbol `D(kx^2+ky^2)^2+K` on the periodic
grid, not a squared finite-difference Laplacian. The prepared immutable plate
stores that diagonal only. Each solve needs Fourier transforms and linear-sized
arrays, not a dense matrix, factorisation or stored iteration history.

For a supplied bed, sorting its cells gives an exact piecewise-linear water-level
solution, apart from floating-point error. The last wet set may avoid a new sort
only when recomputing its candidate level proves **every wet/dry inequality** for
the current bed. Changed shorelines invalidate this shortcut; there is no stale
cached volume or result. Elevations are centred before volume arithmetic.

Water filling is projection onto `d>=0, sum(d)=V/a` in the equal-area Euclidean
norm. Projection is non-expansive. The norm of `L^-1` is `1/K`, so alternating
water filling and plate response contracts by at most `q=rho_w/rho_m<1`.
The new iterate's RMS error in exact arithmetic is bounded by
`q/(1-q) RMS(w_new-w_old)`. The stopping estimate is 1e-6 m. The returned water
is recomputed from the **new** bed before evaluating `r=Lw-rho_w g d`; this avoids
reporting only the trivial linear residual against yesterday's water distribution.
An independent residual-based estimate is `RMS(r)/(K-rho_w g)`.

These are mathematical bounds for the discretised fixed-point problem evaluated
in floating point, not interval-certified round-off bounds or bounds on geological
error. They are RMS estimates, not maximum point errors. The code also checks
volume, mean subsidence and the coupled force residual independently. Failure to
converge within 64 iterations refuses the result; no damping or loosened tolerance
hides a failure. Grid axes are bounded to 4–128 cells. Cancellation is checked
each iteration. Setup can be reused for unchanged grid/material properties;
changed water or a warm starting displacement still requires a new solve.

## What the work check means

At equilibrium the virtual-work identity is
`<w,Lw> = rho_w g <w,d>`, using area-weighted inner products. Half the left-hand
side is stored bending-plus-foundation energy. The reported load-displacement
product is not by itself the complete energy of the water/plate system.

For this reduced model the joint potential is
`E=.5<w,Lw> + rho_w g <z0-w,d> + .5 rho_w g <d,d>`, at fixed volume. It contains
the gravitational potential of water between the loaded bed and its surface.
Its quadratic variation is the sum of a nonnegative bending term,
`(K-rho_w g)||delta_w||^2`, and `rho_w g||delta_d-delta_w||^2`, giving a unique
stable equilibrium. This derivation supports the solver; it is not a dynamic
energy-conservation or viscoelastic relaxation-time claim.

## Controls and interpretation

Focused tests cover zero water/undefined level; exact finite fill and stale-wet-set
refusal; flat loaded equilibrium; a partly wet **zero-rigidity Airy limit**; a
fully wet, oblique 2D Fourier mode; datum shifts; transposition with exchanged
domain lengths; volume, mean subsidence and virtual work; unclipped forebulges;
warm/cold parity; immutable preparation; invalid inputs and iteration/cancellation
refusal. The Airy control is independent algebra, not another call to the solver.
For an all-wet mode `z0=a cos(k.x)`, mean depth `H` and
`lambda=D|k|^4+K`, the exact displacement is
`w=qH-rho_w g a/(lambda-rho_w g) cos(k.x)`.

The authored partly wet 600 by 400 km fixture is sampled at 32², 64² and 128²
cells. Its finest-pair RMS displacement change, divided by the prescribed 200 m
mean water depth, must be below 0.5%. The source-bound case fixes all numerical
gates before the run. A five-repeat, interleaved benchmark compares verified
wet-set reuse with re-sorting every iteration using the same operator, physics
and tolerances. It records seconds, percentages and output parity, not inferred
whole-generator savings. Sorting/reuse changes performance, not which cells flood.

## Sources and software actually checked

- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/): section 2.1, constant-rigidity equations, iterative water infill, and boundary-condition Table 1. PDF text inspected; the screenshot request timed out. No claim of visual figure review.
- [Current gFlex theory and FFT documentation](https://gflex.readthedocs.io/en/latest/theory_and_numerics.html): spectral transfer, uniform-rigidity restriction and periodic domains. FFT is documented in the later software, **not** an implementation in the 2016 release. Atlas uses explicitly downward-positive signs. No gFlex run or copied implementation.
- [Schachtschneider et al. (2022), Appendix B](https://npg.copernicus.org/articles/29/53/2022/): surface-minus-bed depth and moving ocean mask. Their gravitational/geoid model is not implemented here.
- Existing Atlas `flexure.py` and `w09_water.py` were inspected for boundaries. The former is **1D finite-difference** flexure and cannot supply this 2D spectral operator by tiling; the latter routes water on supplied drainage graphs, not this common-reservoir equilibrium.

The projection/contraction and energy derivations above are for the stated Atlas
reduction. No source is credited with validating this new implementation. The
model omits variable rigidity, finite-edge/exterior loads, self-gravity, geoid and
rotation changes, mantle-volume closure, isolated-basin routing, yielding and
time-dependent relaxation. Constant elastic thickness is supplied, not inferred
from the separate mechanical-strength calculation. Small-deflection thin-plate
validity and reservoir connectivity still require admission for real applications.

The CLI `python -B tectonics/tools/check_i01_water_flexure.py --output <new.json>`
exclusively creates a receipt binding the new tool, case, method and tests. No
old evidence is overwritten, no native execution identity changed, and no
existing world or desktop result regenerated.
