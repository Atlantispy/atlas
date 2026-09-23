# W04 step 4: fixed spatially variable rigidity

22 September 2026. WORKING NON-CANON, local unreleased `remake` work.
Implemented and optimised for the stationary, planar **1D** W01-W03 support
projection. This extends [finite regions](W04_FINITE_REGIONS.md); it does not
change the existing fast uniform-rigidity routes. Subsequent [combined acceptance](W04_COMBINED_ACCEPTANCE.md)
passes the selected stationary 1D support workflow, not general terrain validation.

## Physical contract

`RigidityProfile1D` supplies source-linked E (Pa), effective elastic thickness Te
(m), and Poisson ratio nu for every ordered source/halo cell. Require E>0, Te>0,
and -1<nu<0.5. Rigidity is `D=E Te^3/[12(1-nu^2)]` in N m. E and Te are not
inferred from rock names, crustal thickness or the thermal-plate thickness.
Arrays are immutable snapshots; source, grid, frame, datum, epoch and explicit
exterior materials contribute to the profile identity.

Solve the conservative thin-plate/Winkler equation

`(D(x) w''(x))'' + K w(x) = q(x)`, `K=(rho_compensation-rho_void)g > 0`.

Displacement and pressure are positive down. D and q are piecewise constant in
the supplied cells; no averaging smears a stiffness jump. The weak form is
`integral(D w'' v'' + K w v) = integral(q v)`. It transmits displacement, slope,
bending moment and shear across an unloaded interface. Curvature itself may
jump. Multiplying the old uniform biharmonic stencil by local D is **not** this
equation and is not used.

The profile is fixed across the reference/current projection. The solver acts on
the change in load, so repeated calls give total displacement from that reference,
not accumulated increments. Time-dependent rigidity would require separate
reference/current absolute-load solutions; changing D is not supported here.
Local maximum strain uses each cell's own Te times absolute curvature / 2.

Boundary choices are explicit:

- `periodic`: identify displacement and slope at the seam. D may jump across it;
  the nonzero-mean load is retained because K is positive.
- Physical ends: homogeneous `free` or `clamped`, including mixed free/clamped
  ends, applied as natural weak conditions or constrained displacement/slope.
- Continuing plate: specify both far materials as `(E,Te,nu)` tuples and both
  exterior half-line pressures, with any represented halo cells in the profile.
  Exact constant-material decaying half-line solutions supply endpoint stiffness
  and forcing. The output crop is not a new plate edge.

For continuing support, **nonzero omitted-exterior pressure uncertainty is
refused**. The uniform Green-function tail bound is not valid through a variable-D
interior. Zero bounds declare exact prescribed exterior loads; they never mean
unknown data. Existing uniform support retains its previous uncertainty treatment.

This remains linear small-deflection, stationary 1D flexure with constant K.
Loading is invariant transverse to the transect; W03's inventory width does not
make it a finite-width 2D plate. No spherical geometry, yielding, viscoelasticity,
evolving rigidity, general end forces or feedback into W03 geometry/heat/water is
added. Effective elastic inputs still need source-specific scientific selection.

## Numerical accuracy and output

C1 cubic Hermite finite elements preserve the correct weak equation. Exact
element stiffness, consistent foundation and cell-load integrals are assembled
in scaled `[w,h*theta]` degrees of freedom. A diagonal equilibration precedes
SPD banded Cholesky. No artificial stiffness, matrix jitter, dense fallback or
changed physics is used on failure. A componentwise scaled equation residual is
checked after every solve.

`VariableFlexureAccuracy` requires a source, relative tolerance and separate
absolute tolerances for displacement, slope and curvature. Starting subcells
respect the smallest prescribed flexural length. At least two meshes are solved;
subdivision doubles until every cell's point/maxima change passes its selected
absolute tolerance plus relative tolerance times that field's domain maximum.
The returned answer is the finer computed solution, not an extrapolation.
Default maximum refinements is six, bounded to eight and an explicit element
ceiling (default 65,536). Budget or convergence failure refuses the answer.

These are **mesh-change estimates, not rigorous continuum-error bounds**. Exact
element integration does not make the FE response exact, nor does a small backward
residual prove a small forward error for every extreme stiffness/mesh condition.
The independent controls include an exact two-material continuum solution and
uniform-rigidity analytical Green response; broad geological calibration remains
separate. An insufficient mesh ceiling is not repaired by loosening a tolerance.

The low-level immutable result has shape `(N,5,4)`:

| Row | Meaning |
| --- | --- |
| 0 / 1 / 2 | Left face / centre / right face: w, w', w'', w''' |
| 3 | FE-polynomial maxima in the source cell: abs(w), abs(slope), abs(curvature), strain |
| 4 | Mesh-change estimates for w, slope, curvature; accepted subdivisions |

True source/material faces remain one-sided. A centre falling on an artificial
internal FE face averages its two traces, making sampling reflection-consistent
without smoothing a material interface. Displacement/slope extrema include roots
inside each cubic, not merely centre/face samples. The third derivative is a
diagnostic FE derivative, **not** certified by the first-three-field mesh gate.
The bridge adds mesh-change estimates to its displacement, slope and strain
validity assessment; that remains a conditional engineering screen, not a proof
of all continuum subcell extrema or of realistic terrain.

## Integration, reuse and bounded resources

Supply `rigidity=profile, accuracy=accuracy` to `PreparedW04Support` or
`project_w04_support`. The full profile grid, actual W01 source frame and W03
datum/epoch must match. Existing thermal ownership, physical load construction,
reference surfaces and exterior state binding still apply. E/Te/nu in the profile
are authoritative for bending; `policy.elastic` continues to supply K and gravity.

All elements remain in one coupled solve. Finite bandwidth is three; folding the
periodic ring keeps bandwidth at most five, so factorisation/storage are linear
in the number of internal elements. Factors for visited meshes are retained once
per prepared profile, not rebuilt per load or stored as a growing load history.
Each new load still passes the same refinement gate; previous loads do not select
a different answer. Short kernels remain serial; this does not need worker startup.

`cached_variable_flexure` uses the existing cache, source/runtime identities,
single-flight and cheap-work bypass. The key includes exact pressure bytes,
profile, operator and accuracy, with SciPy/LAPACK execution identity. Cache and
fresh routes return identical response and convergence metadata. W03 restore plus
the same explicitly reconstructed profile/surface/exterior inputs reproduces IDs;
old source seals are not repinned. Profiles are not silently recovered from results.

Factor construction, retained ownership and response workspace use shared byte
admission, composing explicit per-call budgets. `close()` releases factors. Crops
are detached from halo buffers. Cancellation is checked between bounded mesh
operations, not by interrupting a native Cholesky call. Accounted bytes are not a
process RSS limit. See [focused checks and measured savings](../evidence/w04-variable-rigidity.md).

## Papers and software reviewed before selection

- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/),
  full-text section 2.2, equation 9 and boundary discussion: selected the
  conservative variable-rigidity equation and explicit boundary meaning.
- [TU Delft, Euler-Bernoulli beam](https://interactivetextbooks.citg.tudelft.nl/computational-modelling/structural_linear/euler_bernouilli.html),
  weak/discrete form, equations 4.14-4.43: selected C1 Hermite interpolation and
  source-aligned material stiffness rather than differentiating noisy D arrays.
- [Wieckowski and Swiatkiewicz (2021), Materials 14, 460](https://mdpi-res.com/d_attachment/materials/materials-14-00460/article_deploy/materials-14-00460.pdf),
  independent review of section 2.1 and the section 6 opening: cross-checked the
  Winkler foundation and four-degree-of-freedom Hermite formulation.
- SciPy's [banded Cholesky](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.cholesky_banded.html)
  and [factor reuse](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.cho_solve_banded.html)
  documentation: selected compact SPD factorisation/repeated solves over dense
  matrices or a generic sparse solve per snapshot.

These are paper/documentation reviews, not external gFlex execution, external
source-code audits or measured superiority to another terrain generator.
