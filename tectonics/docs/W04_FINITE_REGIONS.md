# W04 step 3: finite regions without invented plate edges

22 September 2026. WORKING NON-CANON, local unreleased `remake` work.
Implemented for the current **uniform-rigidity, stationary planar 1D** W01-W03
workflow. This is a linear support projection, not material evolution or
whole-world terrain acceptance. [Step 2](W04_WORKFLOW.md) retains its explicitly
periodic centred-difference operator; this step does not change that equation.

## Physical alternatives

- `continuous-plate`: the output region is a window into a continuing plate with
  the same prescribed D and K. Adjacent load cells and exterior half-lines are
  explicit. No motion or traction is forced to zero at the crop edges.
  Computational FFT padding is not an extra geological load region.
- `physical-edges`: the region really terminates at both source-defined ends.
  Each end is explicitly `clamped` (w=w'=0) or `free` (w''=w'''=0). Mixed
  free/clamped ends work. These homogeneous conditions describe changes from the
  chosen reference. Exterior plate loads are refused in this mode.

`FlexureBoundary1D(left, right, source_id)` records the actual assumption.
`W04SupportPolicy` takes `region_boundary` and `max_omitted_deflection_m` alongside
its unchanged material, ownership and validity requirements. A physical end must
not be chosen merely because source data stop there. Neither a coastline nor a
closed W02 transport boundary automatically defines a plate edge.

The 1D solution represents loading invariant along the transverse direction.
W03's finite reference width converts inventories into pressures; it is **not**
a finite-width 2D plate-edge treatment. Variable rigidity, spherical geometry,
arbitrary end forces, mixed continuous/physical ends and general 2D regions remain
outside this increment.

## Explicit surrounding loads and uncertainty

`W04ExteriorLoads(state, left_pressure_pa, right_pressure_pa, *, far_left_pa,
far_right_pa, omitted_left_bound_pa, omitted_right_bound_pa, source_id)` binds one
exterior specification to the exact W03 state, time, grid, frame and datum.

Halo arrays contain total downward pressure in Pa on contiguous cells at the
source spacing. Left order is far-to-near; right is near-to-far. Empty arrays
explicitly mean no represented halo. Beyond each halo is a prescribed constant-
pressure half-line. These are total exterior loads, including any thermal,
geological, water or external components the source authorises; outside thermal
evolution is never inferred. Globally uniform cooling must be explicitly
continued outside to claim its uniform whole-line response. The closed W03
reservoir still closes on its own cells; it is not allocated outside again.

Supply reference exterior inputs through `PreparedW04Support(..., exterior=...)`
and current inputs through `.solve(..., exterior=...)`. Halos must have identical
geometry at both instants. Load changes are subtracted from that fixed reference;
previous displacement is never accumulated. Changed halo extent needs new
reference preparation, not a silent checkpoint repin.

Each omitted bound is an absolute pressure departure from the declared far-field
constant, valid everywhere beyond the represented halo. Reference/current bounds
add conservatively. Zero is an explicit exact-load assumption, not unknown data.
For nearest output-to-exterior distances dL,dR, define:

`S = QL exp(-dL/alpha) + QR exp(-dR/alpha)`.

Conservative error bounds are `S/(sqrt(2)*K)` for displacement, `S/(K*alpha)` for
slope, and `sqrt(2)*S/(K*alpha^2)` for curvature. The selected omitted-displacement
tolerance must pass. All three also augment the existing displacement, slope and
bending-strain checks. Padding unknown surroundings with zeros does not establish
that these bounds hold. Results retain the boundary source, full model grid,
crop, flexural length, both exterior IDs and conditional uncertainty assessment.

## Equation and numerical choice

Solve the continuous uniform thin-plate equation `D w'''' + K w = q`, with
`K=(rho_compensation-rho_void)g`, positive-down w, and `alpha=(4D/K)^(1/4)`.

`G(r) = exp(-abs(r)/alpha) [cos(abs(r)/alpha)+sin(abs(r)/alpha)] / (2 K alpha)`.

Each cell is constant pressure over its full width, not a point impulse.
Analytical cell integration supplies exact weights for that representation.
Stable complex exponential/expm1 expressions preserve narrow-cell and far-tail
differences. Signed forebulges are retained. Zero-padded **linear** convolution
has enough padding for the complete source/kernel convolution, with no periodic
images. The whole coupled array is solved together. Output is point response at
centres/faces, including three analytic derivatives, not output-cell-mean
displacement. Unresolved subcell pressure still has a constant-cell assumption.

Constant far-halfline pressures are integrated analytically. Physical ends use
a four-coefficient homogeneous correction with bounded end-localised decaying
sine/cosine modes. Derivative rows are scaled by alpha powers. The scaled 4x4
condition number must be at most 1e8, and reconstructed endpoint residuals pass a
512-epsilon scaled arithmetic check. Ill-conditioned very short physical plates
refuse: this is a limitation of the numerical basis, not a singular physical
problem. No FD fallback silently changes the method.

The new continuum response and earlier periodic **discrete** biharmonic response
need not agree at finite resolution. Source subdivision and zero-load crop/domain
enlargement are independently tested. Physical-end changes deliberately change
the problem. Oscillating load responses need not converge monotonically with
distance. Validity checks sample analytic derivatives at every centre and face,
including exterior uncertainty; they do not certify unsampled subcell extrema,
independently validate thin-plate assumptions or calibrate elastic thickness.

## Efficiency, provenance and recovery

Integrated kernel transforms and physical-end bases are prepared once. No dense
O(N-squared) matrix or growing history is kept. These short, globally coupled
kernels remain serial. Shared byte admission covers setup, retained coefficients,
full halo responses and compact interior output. A crop cannot retain its large
temporary halo buffer. Exterior hashing streams both payloads without making a
duplicate concatenation.

`cached_finite_flexure` uses the existing store, runtime/source checks and cheap-
work auto-bypass. Its identity is distinct from periodic flexure and includes
geometry, physical boundaries, materials and all load bytes, including far fields.
W04 additionally binds exterior sources and bounds. W03 restoration plus
reconstructed exterior inputs reproduces results and IDs. No old seal is repinned.
See [checks and timings](../evidence/w04-finite-regions.md).

## Papers and software checked before selection

- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/):
  full-text section 2.1, equations 1-4 and 7, Table 1 and section 2.3. Compared
  analytical superposition and finite differences; checked continuous, clamped,
  free and periodic meanings. This motivated exact cell integration for constant
  rigidity and explicit exterior treatment instead of a guessed clamp.
- [gFlex theory and numerics](https://gflex.readthedocs.io/en/latest/theory_and_numerics.html):
  independent reviewer checked governing equations, flexural length, SAS/SAS_NG,
  FD and FFT documentation. Atlas independently derives/tests positive-down
  pressure units; finite physical padding is not treated as exactly infinity.
- [SciPy FFT convolution documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.fftconvolve.html):
  checked full linear-convolution behaviour and size-dependent direct/FFT costs.
  Implementation uses existing NumPy FFTs; no dependency was installed.

Paper/documentation reviews only: no external gFlex execution or source-code
audit. Independent quadrature and closed-form controls provide numerical evidence,
not field calibration or full terrain realism acceptance.
