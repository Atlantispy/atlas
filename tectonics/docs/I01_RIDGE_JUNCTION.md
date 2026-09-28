# I01: testing a proposed ridge after junction contact

**WORKING NON-CANON. Local kinematic prerequisite implemented; physical
reorganisation selection remains OPEN (MC-05).** This is not a graph edit,
rupture law or generated-world acceptance. It follows the separate
[contact calculation](I01_JUNCTION_EVENTS.md) without changing its source.

## 1. Physical choice and research boundary

An AB edge can vanish between ABC and ABD junctions. A proposed CD edge would
then connect ACD and BCD. Exchanging these labels does not establish that the
new edge can grow or that rock will form that boundary. This implementation
checks the first question for a declared all-ridge planar candidate; it does not
answer the second. Supplied normals and velocities are hypotheses, not a
mechanism derived from the lithosphere.

The next physical route must use the local traction/stress, temperature,
composition and inherited weakness with an admitted localisation/rupture or
magmatic propagation mechanism. It must also supply melt and conserve material.
An isolated residual, unsigned edge length or minimum-dissipation guess cannot
replace that state. A unique surviving kinematic candidate would not exclude
distributed deformation or a different physical boundary geometry.

## 2. Equations and supported domain

Four distinct plates A,B,C,D have constant planar velocities in m/s. Five
constant nonzero normals are oriented A-to-C, A-to-D, B-to-C, B-to-D and C-to-D.
They need not have unit length. This branch admits **symmetric, positively
opening ridges only**. For each pair i,j:

```
b_ij = n_ij . (v_i + v_j)/2
n_ij . (v_j - v_i) > 0
```

The exterior pairs determine the proposed outgoing junction velocities:

```
n_AC . J_A = b_AC       n_AD . J_A = b_AD
n_BC . J_B = b_BC       n_BD . J_B = b_BD
```

Each 2-by-2 system must have full rank. Work in the A-plate frame before solving,
so adding a common observer velocity cannot change the classification. With
`w=J_B-J_A`, both endpoints must satisfy the same proposed CD ridge law:

```
n_CD . J_A = n_CD . J_B = b_CD
```

For a straight edge starting at zero length this enforces `n_CD.w=0`. In the
declared right-handed frame, the ownership-oriented tangent from ACD to BCD is
`t=(-n_CD.y,n_CD.x)`. Require `w.t>0`: an unsigned length can grow while the
endpoints exchange the wrong sides. If `w=0`, there is no first-order branch;
higher-order motion is unresolved, not automatically a stable quadruple junction.

For admitted *local kinematics*, squared length at elapsed time tau is
`tau**2 * dot(w,w)`. The supplied finite horizon bounds queries; it is not a
certificate that external conditions stay unchanged. Constant normals exclude
rotating boundaries, and no spherical continuation is implemented here.

These equations are derived directly from rigid kinematics and the retained
[symmetric ridge law](I01_TRANSITIONS.md), not transcribed from an inaccessible
paper. The contact time is an input to future assembly: this helper's time starts
at assumed coincidence and does not authenticate a contact receipt.

## 3. Outputs and necessary later checks

The result distinguishes incompatible CD motion, no first-order growth, reversed
oriented growth and `LOCALLY_FEASIBLE_NOT_GENERATED`. Malformed inputs, unsupported
models, non-opening ridges, rank deficiency and excessive arithmetic are refused.
Exact fractions preserve the supplied numbers and tiny mismatches; they do not
restore accuracy lost before input or certify physical geometry.

I03/I09 must still establish exterior cyclic order/outward rays, absence of
crossings and other contacts, shared ownership, trajectory validity and joint
event admission. I02 owns authenticated state and once-only transactions. The
helper never sets `topology_change_authorised`, `physical_birth_verified` or
`global_geometry_verified` true. No candidate is automatically selected or
committed. Trench/transform candidates require their own laws and are not silently
represented as ridges. MC-05 remains open.

## 4. Small controls and efficiency

For manufactured velocities A=(-2,0), B=(2,0), C=(0,1), D=(0,-1), exterior normals
(1,1),(1,-1),(-1,1),(-1,-1) and CD normal (0,-1), elementary substitution gives
laboratory-frame J_A=(-1/2,0), J_B=(1/2,0). Hence the squared separation after
3 s is 9 m2. These deliberately large velocities are numerical fixtures, not
tectonic parameter values. Incoming junctions at (0,2),(0,-2), moving at
(0,-1/2),(0,1/2), meet after 4 s under the retained contact helper.

Tests also cover both endpoint equations, reversed and stationary branches,
translation/rotation, positive normal and velocity scaling, exact tiny mismatch,
rank loss, domain/resource refusal and immutable ownership. The test connection
passes manufactured values between controls, not authenticated world state.

Preparation performs the constant-size rational solve once; repeated length
queries reuse immutable results. No history growth, disk cache, parallel pool or
new dependencies are needed. Five interleaved batches compare 300 prepared versus
rebuilt queries with exact parity. This measures preparation reuse only, never
end-to-end generator speedup. A bounded campaign creates a new receipt:

```
python -B tools/check_i01_ridge_junction.py --output evidence/i01-ridge-junction-r1.json
```

The receipt binds this method, tool, tests, case and imported exact-number/contact
helper. Existing source-bound contact/transition files and receipts stay unchanged.

## 5. Sources actually consulted

- [Gerya & Burov (2018), DOI 10.1016/j.tecto.2017.10.020](https://doi.org/10.1016/j.tecto.2017.10.020):
  publisher abstract and the author's [institutional seminar summary](https://www.ipgp.fr/actus-et-agenda/agenda/seminaires/nucleation-and-evolution-of-ridge-ridge-ridge-triple-junction-new-theory-and-magic-formula/)
  inspected. They describe quadruple rifting junctions becoming two oceanic
  triple junctions. The weighted ridge-lengthening theory concerns mature steady
  spreading, not an instantaneous general birth rule. Original derivation and
  calibration were inaccessible; that optimisation is **not implemented** here.
- [Koptev et al. (2018), Afar triple junction](https://doi.org/10.1038/s41598-018-33117-3):
  a bounded research worker inspected the original introduction, modelling,
  implications and methods. Its I3ELVIS experiments use thermal-rheological
  evolution and imposed forcing, not a post-hoc graph flip. This supports the
  distinction between kinematic feasibility and physically generated topology;
  its continental model is not validation of this oceanic candidate.
- Existing Atlas contact/transition methods retain the earlier McKenzie-Morgan,
  Kleinrock-Morgan and pyGPlates research. The software precedent concerns shared
  boundary representation, not boundary birth; no external software was run or
  newly benchmarked for this work.
