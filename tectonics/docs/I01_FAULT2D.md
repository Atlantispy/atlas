# I01 D2: bounded two-dimensional fault-law checks

WORKING NON-CANON. Numerical feasibility, not generated lithosphere acceptance.
This supplements rather than rewrites the source-bound I01 r1 contract.

## Equations and conventions

The periodic square is a small-strain, fixed-material-coordinate, isothermal
plane-strain experiment. Confining pressure is fixed in the initial strength;
dynamic pressure is the incompressibility multiplier, not a friction input.
It cannot yet establish the pressure-sensitive D2 law, transport or rupture.

With zero divergence, use engineering vector `g=(2 e_xx,2 e_xy)` and invariant
`q=|g|=2 epsilon_II`. The stress vector is `t=(tau_xx,tau_xy)=s g/q`, where
`q=s/eta_v+max(s-Y,0)/eta_p`. Thus `t.g=s q` is mechanical dissipation and
`kappa_dot=max(s-Y,0)/eta_p` matches engineering plastic shear in simple shear.
Strength uses the original linear saturated weakening of *filtered* accumulated
history; raw history is neither clipped nor overwritten by its filtered value.
The periodic Helmholtz law is `(1-ell^2 Laplacian) kappa_bar=kappa`.

Equilibrium is solved in two spatial dimensions, not by applying independent
one-dimensional strip solves. A periodic streamfunction represents both velocity
components. Parameterising it by `chi=-Laplacian(psi)` makes the Fourier strain
operator `A=(-2 kx ky/k^2,(kx^2-ky^2)/k^2)` satisfy `A* A=1` away from the fixed
zero mode. Newton/CG minimises the integrated, convex instantaneous dissipation
potential at each held strength. Every accepted solve checks projected force and
macro-work/local-dissipation balance. Odd grids avoid ambiguous Nyquist modes.
No numerical viscosity floor or cosmetic modification of the result is used.

The physical history advance is explicit and checked by timestep halving.
Temperature, geometry, pressure-sensitive friction, elastic stress transport and
finite deformation are not silently represented by this fixed-coordinate control.

## Predeclared tests and limits

The [versioned case](../cases/i01_fault2d_v1.json) fixes the parameters and gates
before collecting results. Values are authored numerical fixtures, not fitted
planetary material constants. The 100 km square has a 5 km nonlocal length and
two smooth circular inherited strength deficits with fixed physical coordinates.
The calculation uses 33/65/129 square grids, 128 steps, and a separate 256-step
comparison. Effective stress and plastic participation area must change by at
most 3% between the finest spatial levels and temporal pair. Participation area
is `area*mean(kappa)^2/mean(kappa^2)`, avoiding pixel thresholds or a chosen fault.

Four analytical laminates with equal wavelength at grid-aligned and oblique
orientations test both strain components against an independent uniform-stress
solution. These are orientation controls, **not 2D fault emergence**. Separately,
the two-seed genuinely 2D experiment tests right-angle covariance and uniform-state
invariance. A square periodic cell is not invariant under arbitrary rotation:
its periodic images also affect the solution. Arbitrary-angle fault nucleation
and geological boundary conditions remain open; these checks do not close them.

The runner refuses overwrite, binds these files before/after execution, records
failures, and caps the numerical campaign at 180 seconds with cooperative checks.
No full-world or native-package calculation is run. The old r1 evidence remains
unchanged. Run `python -B tectonics/tools/check_i01_fault2d.py --output NEW.json`
with the existing scientific environment.

## Efficiency and research consulted

Operators and the exact constant-coefficient Helmholtz inverse are prepared once
per grid. Current equilibrium provides the next solve's initial guess. Fourier
actions avoid a dense global matrix; storage is proportional to grid size and
actions cost O(N log N). Only current history and compact metrics are retained.
These are design choices, not a measured whole-generator speedup.

- [Duretz et al. (2023)](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2022GC010675),
  sections 2–5: regularisation choices, equilibrium, fixed physical seeds and
  refinement controls. Atlas's nonlocal weakening is not their gradient/Cosserat
  implementation. Their paper does not calibrate our selected length.
- [PTsolvers PlasticityRegularisations_G3](https://github.com/PTsolvers/PlasticityRegularisations_G3):
  software overview consulted; no installation, execution or copied implementation.
- [Magri et al. (2021)](https://arxiv.org/html/2103.04770v1), sections 2.2 and 3.2:
  periodic mechanical/Helmholtz coupling and Fourier solution. Their ductile-metal
  models and heterogeneous-length treatment are not transplanted to rock physics.
  This control uses a constant length and continuous spectral derivatives, not
  their rotated finite-difference operator or constitutive models.

These methods support a small discriminating experiment; only its actual recorded
results can justify a claim about its numerical behaviour.
