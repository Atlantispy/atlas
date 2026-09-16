# Foundation case and numerical contract

**ATLAS-TECTONICS-FOUNDATIONS-001, revision 1, 16 September 2026.**
Scope: first implementation under ATLAS-TECTONICS-PLAN-1 revision 3. The controlling
plan's original Markdown SHA256 is recorded in `../cases/foundations.json`. The
plan is an attached review artefact, not claimed to be published in this repository.

## Equations and boundaries

1. **E01/E02 kinematics.** Rigid rotations are unit quaternions, with right-handed
   geocentric XYZ coordinates. `a.then(b)` applies a then b. Instantaneous velocity
   is `omega cross r`, in m/s with omega in rad/s. It is not a finite chord velocity.
   Boundary diagnostics use x east / y north and right normal `(t_y,-t_x)`;
   relative velocity is right minus left. Positive normal motion means opening
   only under correct declared side geometry. No automatic geological interpretation.
2. **N01 source-free transport.** Constant-density solid-equivalent thickness H
   satisfies `dH/dt + d(uH)/dx = 0` on a fixed periodic uniform grid. H is a cell
   average; u[i] is the velocity on cell i's right face. A shared upwind flux
   `F[i]=u[i]*(H[i] if u[i]>=0 else H[i+1])` yields
   `H_new[i]=H[i]-dt/dx*(F[i]-F[i-1])`. Indices wrap. The positivity requirement is
   `dt/dx*(max(u[i],0)+max(-u[i-1],0)) <= 1` in every cell. This bound matters for
   divergent velocities and is stronger than merely checking max(abs(u))*dt/dx.
   The implementation uses an equivalent positive-weight form, without clipping.
   The conserved quantity is sum(H)*dx in m2 (solid volume per fixed unit width),
   not an integrated three-dimensional mass or the legacy integer mass account.
3. **E04 cooling.** `T=Ts+(Tm-Ts)*erf(z/(2*sqrt(kappa*t)))`, z positive downwards,
   SI seconds/metres/Kelvin and constant positive diffusivity. At t=0, the positive
   depth interior is Tm; the prescribed surface is Ts. The corner follows the
   surface boundary. No hidden minimum age. This evaluates an analytical profile,
   not a conduction timestepping solver. Scalar math.erf is a transparent reference
   within a batch, not a claim of a fully SIMD/vectorised special-function kernel.
4. **E12/E13 flexure.** `D*w'''' + K*w = q` with positive-down deflection w (m),
   load q (Pa), `D=Y*Te^3/[12*(1-nu^2)]` (N m) and `K=delta_rho*g` (Pa/m).
   Flat uniform thin elastic plate; small deflections; no in-plane stress; periodic
   boundaries. The discrete centred fourth difference has modal eigenvalue
   `(2*sin(pi*k/N)/dx)^4`. FFT divides each load mode by D times that eigenvalue
   plus K. This is **not** using continuous k^4 then calling it finite differences.
   The spatial scheme is second order for smooth fields. Uniform load gives w=q/K;
   a continuous sinusoid gives amplitude q0/(D*k^4+K), approached under refinement.
   Total deflection is returned, not an increment to add repeatedly to terrain.

All real inputs must be finite and supported by the stated sign/shape conventions.
Values outside finite binary64 intermediate range are refused rather than clamped.
Input Booleans, strings and complex arrays are rejected. Profiles contain source
labels, units in field names and no omitted-value defaults. Raw IEEE arithmetic is
not exact geology; conservation residuals and discretisation errors remain visible.

## Predetermined verification

The original case sheet set 1e-12 relative/absolute comparison tolerances for these
synthetic order-one quantities before the test suite was run. Those values do not
become universal geological or production tolerances. Smooth transport order must
lie between 0.8 and 1.2; smooth flexure order between 1.8 and 2.2 over three grids.
The grids are at most 128 cells in the present tests, below the case's 256-cell
fixture budget. That is a test scope, not a new hard-coded global Atlas limit.

Independent checks include hand-evaluated rotations, a scalar flux-divergence loop,
a tabulated error-function value, and a dense real-space flexure operator assembled
without FFT coefficients. Mutation/refusal cases cover negative thickness, invalid
properties, Courant violation, incompatible dimensions, nonfinite arithmetic,
readonly results and changed parameter/operator identity. Repeated short transport
steps are mathematical convergence fixtures, not a world or geological simulation.

The verification command inventories source/test/fixture bytes before and after,
records interpreter and NumPy versions, and fails if there are skips, errors or
source changes. This is local test evidence, not a tamper-proof attestation, a
historical restart seal, physical acceptance or a performance benchmark.

## Performance and memory scope

Use contiguous NumPy arrays and bounded caller-owned batches. Each public kernel
validates and detaches caller data; this first implementation favours clear ownership
rather than claiming zero-copy performance. Returned bytes-backed arrays cannot
be made writeable. Caller controls workload size; APIs do not independently enforce
a process RSS or wall-time budget. Verification uses no additional worker pool;
native library thread settings are recorded, with one thread selected for delivery
checks. No parallel/distributed scalability is claimed.

`PeriodicFlexure` retains N//2+1 coefficients. `setup_bytes` reports only those
coefficients, excluding Python metadata, inputs, FFT workspace and output copies.
Different loads reuse them; different material/grid definitions create different
operators. There is no process-global or persistent scientific result cache.

## Method references (not integrated packages)

- pyGPlates rotation/velocity convention reference:
  https://www.gplates.org/docs/pygplates/generated/pygplates.calculate_velocities
  Its finite-rotation/time API is not asserted identical to this instantaneous API.
- Wickert (2016), gFlex methods and physical scope:
  https://gmd.copernicus.org/articles/9/997/2016/
  This is an independent restricted Fourier-diagonalised difference solver, not
  copied gFlex code or a claim about an existing stable gFlex FFT feature.
- NumPy real FFT conventions:
  https://numpy.org/doc/2.3/reference/generated/numpy.fft.rfft.html
- Atlas Reports 01–04 / P01, P03, P06 and N01 in Plan 05 revision 3 supply the
  reviewed scientific context. No external solver, code, calibration data or
  database was imported to implement the formulas.
