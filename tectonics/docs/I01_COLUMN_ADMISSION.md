# I01: conservative motion admission from the actual layered column

27 September 2026. **WORKING NON-CANON.** This connects the actual mixed-creep
column to the existing exact motion-admission gate. It does not implement rupture.

## What happens and why

Before replacing a deforming rock belt by a simpler boundary, ask whether losing
its resistance would change motion too much. The earlier gate needed a supplied
single-exponent law; real layers use different exponents and simultaneous creep
mechanisms. This adapter does not fit those into a convenient curve. Instead it
derives an upper bound that the existing column cannot exceed, then checks the
worst-case motion error. A failure means **not certified by this bound**, not
proof that the actual error is excessive. No automatic boundary switch is made.

## Derivation and exact arithmetic

Use the retained model's positive extension, fixed drive F, disjoint drag D and
width w. The actual motion solves `F = D v + R(v)`; the belt-free value is `v0=F/D`.
Each point of its represented quadrature has positive depth weight q, raw history
kappa, stress invariant s and common strain rate `e=v/w`. Its constitutive law is

`e = sum(nonnegative creep rates) + max(s-Y,0)/(2 eta_p)`.

Every point must have positive finite plastic regularisation eta_p. Therefore
`s <= Y + 2 eta_p e`, independently of its creep exponents or temperature factors.
For extension the lithostatic closure gives `Pmean = reference_pressure - s`, so
`Pmean <= reference_pressure`; the supplied-mean closure satisfies the same bound.

Save each point's current raw history as a lower floor. With no healing, cohesion
and friction angle cannot exceed their values Cmax and phimax at that floor.
Using `cos(phi)<=1` and `sin(phi)<=min(1,phi)` for nonnegative phi,

```text
Ybar_j = Cmax_j + max(reference_pressure_j - pore_pressure_j, 0) min(1, phimax_j)
Ybar   = 2 sum(q_j Ybar_j)                        [N/m]
Abar   = (4/w) sum(q_j eta_p,j)                   [Pa s]
R(v) <= Ybar + Abar v
v >= max(0, (F-Ybar)/(D+Abar))
```

The linear bound is passed to the existing `Balance(..., exponent=1)` gate.
For a permitted error epsilon, admission checks the bound at `(1-epsilon)v0`.
This exponent belongs to the **upper bound**, not a replacement rock rheology.
The bound's apparent static plateau likewise is not the actual column response.

All coefficients, weakening factors and decisions are constructed with `Fraction`
from the represented input numbers; no trigonometric approximation, stress root
or sampled endpoint is asserted to be an outward enclosure. Display bounds round
outward through the existing gate. The certificate covers the **represented
Gauss-point model**, not an independently certified integral over a continuum.
Changing quadrature requires preparing a new bound; convergence of sample values
is not reinterpreted as interval arithmetic.

## Window, ownership and refusals

The caller supplies duration, existing accumulated axial strain, a relative speed
allowance and displacement allowance. With `0<=v<=v0`, total strain is bounded by
`used_strain + duration*v0/w <= 0.05`. This keeps the existing small-strain ceiling;
starting another call does not erase previous deformation. Over the same interval,
the gate bounds speed, displacement and supplied driving-force work error.

The preparation, law, drive, width, temperature and pore-pressure state are fixed;
raw history may only increase from its saved floors. The API rejects a different
preparation/drive/law, decreasing history, missing plastic branches, compression,
zero drive, expired deadline, cancellation and an exhausted strain allowance.
It borrows the retained immutable preparation and copies history into an immutable
tuple. It does not mutate or commit simulation state. A caller cannot interpret
this conditional fixed-column window as a guarantee for changed future forcing,
geometry, thermal fields, elasticity, healing or a finite-strain path.

`generated_separation_authorised` remains false. Material transfer, fault geometry,
through-thickness failure and the physics of rupture still belong to D2/D6. This
work touches neither Claude's finite-strain files nor the retained numerical kernels.

## Checks and efficiency

The case freezes controls before execution: actual inherited layered rheology at
three quadrature orders; an independently solvable homogeneous creep/plastic case;
mixed exponents 1 and 3.5 at the same point; exact threshold equality and a tighter
rational neighbour; and a short run of the existing history-to-motion connection.
Numerical actual responses are diagnostics of the analytical bound, not its proof.
The realistic inherited column is expected to remain uncertified at a 1% allowance;
no coefficient or tolerance is fitted to make it separable.

Focused tests also cover a high, nearly rate-independent resistance, fresh-state
guards, immutable histories, displacement limits, used strain and cancellation.
No full solver suite, world run or spatial plot is needed for this algebraic seam.

Preparation is linear in existing quadrature points. Repeated checks reuse the
bound; they neither rebuild coefficients nor solve the nested motion/stress roots.
The benchmark compares the same public admission calls with rebuilt versus reused
envelopes, reporting three interleaved batches of ten calls on the actual layered
case. State/history guards remain in both; unchanged mechanical preparation is
excluded in both. This is not a whole-simulation speed-up. No disk cache, parallel worker or growing
history log is added for such a small operation. The campaign has a 30 s ceiling.

Commands from the repository root:

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_column_admission.py
python -B tectonics/tools/check_i01_column_admission.py --output NEW_RECEIPT.json
```

The exclusive-create receipt binds new sources/case/tests/method, retained kernels
and reviewed prerequisite receipts before/after. Existing evidence is not rewritten.
Measured results belong in that receipt and CURRENT_STATE, not post-run edits of
this source-bound method.

## Research and existing software checked

- [Duretz et al. (2021), sections 4.2.2–4.2.3](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2021GC009675): regularised overstress and history-dependent softening. The bound keeps regularisation; it does not claim a numerical omission threshold supplies physical rupture.
- [ASPECT continental-extension input](https://raw.githubusercontent.com/geodynamics/aspect/main/cookbooks/continental_extension/continental_extension.prm): retained material-specific flow laws and plastic-history context. No new material coefficients or ASPECT execution are claimed.
- [SciPy bisection documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.bisect.html): numerical root tolerances do not turn a converged floating value into an exact threshold enclosure. The production decision instead reuses Atlas's rational comparison.

The inequality is derived from Atlas's existing summed-rate law here. It is not
attributed to these sources as a published fracture criterion or a novel result.
