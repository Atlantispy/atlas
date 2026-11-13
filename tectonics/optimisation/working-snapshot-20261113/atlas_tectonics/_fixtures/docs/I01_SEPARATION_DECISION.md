# I01: distinguish thinning, disconnection and a plate split

WORKING NON-CANON. **Selected diagnostic specification, not an implemented
separation law or passing simulation.** This completes NA-01's decision record.
The [case](../cases/i01_separation_decision_v1.json) is a design/test specification,
not runnable configuration or evidence. MC-01's physical mechanism stays open.

## 1. Four different records

Stretching rock can become extremely thin without breaking. Its upper crust can
also disconnect while deeper rock still transmits force. Finally, replacing a
weak belt by a simpler boundary can give acceptably similar motion without
proving that the rock has separated. Atlas must not substitute any one of these
observations for all the others.

| Record | Meaning | What it permits |
| --- | --- | --- |
| Crustal disconnection | An admitted change removes the last resolved crustal material connection between the declared sides | A named milestone only; no plate split, new basalt or resetting ages |
| Mantle-lithosphere connectivity | Whether tracked mantle-lithosphere material still joins those sides | A separate diagnostic, not an inference from crust thickness or a colour map |
| Mechanical handoff | The actual coupled and proposed replacement solutions satisfy the declared whole-window error allowance | Numerical replacement only within its supported law and interval; never a physical separation event by itself |
| Through-lithosphere separation | An admitted physical law produces a bracketed loss of the relevant material connection, with compatible network topology and transfers | A split proposal under the unchanged D6 contract; I02 still validates and commits it once |

Use `CONNECTED`, `DISCONNECTED` or `UNRESOLVED` for connectivity. A mixed cell,
insufficient resolution, ambiguous contact, incomplete exterior coverage or a
missing material classifier means `UNRESOLVED`, not `DISCONNECTED`. A disconnected
starting state is inherited, not a newly generated event.

## 2. Material and geometry, before a threshold

I05 supplies conservative current material supports, cohort identities, amounts,
composition, transported history and their uncertainty. Declare the two material
anchor regions and candidate separating footprint before comparing resolutions.
Track those anchors through the deformation; do not choose new ones after seeing
the result. A colour, original plate ID or majority-material cell is not support.

Crust and mantle lithosphere need explicit producer-owned classifications and
provenance. A thermal or compositional reclassification requires its admitted
law and transfer accounting; neither an isotherm chosen afterwards nor newly
arriving asthenosphere may silently erase the original bridge. Track their union
as well as each subset: individually disconnected subsets can still form a
connected crust-to-mantle-to-crust bridge.

Assess paths through reconstructed material in the declared domain, including
interfaces and possible paths round the candidate cut. No deletion of a positive
inventory, pixel erosion, cell-fraction cutoff or thickness floor is permitted.
Uncertain point contacts and sub-resolution bridges require refinement or an
admitted discontinuity representation. Their absence in a raster is not proof.
A two-dimensional section reports section connectivity only. I03/I07 must cover
the along-strike extent and exterior paths before a global plate split; both ends
of a new boundary must join the existing network.

Also report the weakened zone's surface-to-base connectivity separately from
the rock's side-to-side connectivity. The former uses D2's declared physical
state/law, not an invented history threshold, and supplies the diagnostic shared
with MC-02. A spanning weak zone is not automatically a material discontinuity.

## 3. Strength, force and width are separate quantities

For a declared section with horizontal direction n and vertical direction z,
record the stress-difference resultant
`S = integral (n.sigma.n - z.sigma.z) dz` in N/m, split by actual crust and
mantle supports. Report signed and absolute-integral values so cancellation is
visible. In the retained coaxial column this is `2*sign(a)*integral(s dz)`, not
`integral(s dz)`; see the [column convention](I01_COLUMN.md). Report the real
cut traction `integral sigma.n dl`, its direction and external pressure/load
terms separately. S is a section diagnostic, not a general reaction force or
universal rupture threshold. Oblique sections require the corresponding tensor
projection, not reuse of a scalar extension invariant.

Carry pressure, effective pressure, temperature, strain-rate, stress, raw history
and elastic-memory ranges against the coefficients' declared support over the
whole approach. Unsupported extrapolation makes the event unavailable.

Do not equate shear-zone width, geometric neck width and the physical D2 length
ell. For later comparisons use a fixed, declared transverse transect and a
nonnegative activity density p (plastic dissipation for the plastic zone):
`width_p = (integral p dx)^2 / integral p^2 dx`. Zero activity has undefined
width, not zero width. For a single resolved neck use the same participation
definition on `q=max(h_reference-h_material,0)`, with a predeclared material
thickness reference; report the thickness minimum separately. Multiple peaks
require separate zones or an explicit composite diagnostic. These are Atlas
reporting definitions, not constitutive lengths or event triggers.

## 4. Mechanical handoff: compare solutions over time

Keep the existing linear Pi rule restricted to its zero-intercept Newtonian
control. For a nonlinear, plastic or memory-bearing belt, solve/bound both the
coupled branch C and the proposed replacement R, from the same parent and under
the same forcing, source accounts and exterior conditions. A small derivative
alone proves nothing about the force carried by a yield plateau.

The selected comparison contract is:

- Declare a positive horizon H, physical comparison support A, common frame and
  material correspondence before running. The window is `[t0,t0+H]`, truncated
  only at a predeclared event/source-validity bound, never to hide a discrepancy.
  Missing supported H means no certificate. Revalidation is required on expiry.
- Remove only the same permitted rigid-frame gauge from each branch. On a sphere,
  use the same area-weighted rigid-rotation projection on the same physical
  support; do not fit separate regional frames that hide a plate's motion error.
  The difference of the projected fields is the error field. Preserve normal and
  tangential motion. The retained scalar control already fixes its far-field frame.
- Use the spatial maximum Euclidean velocity error and its supremum over the
  whole window, not just endpoint or mean errors. Fix the reference speed to the
  supremum of the replacement field's speed on the same support/window and gauge.
  Thus `E_v = sup_A,time |v_C-v_R| / V_ref`. For the constant scalar control this
  reduces to error relative to `v_inf`, as required by the transition contract.
  A proved V_ref and numerator bound are needed; sample maxima alone are not bounds.
  If V_ref is zero or cannot be established, this relative criterion is unavailable;
  no hidden speed floor is introduced.
- I02 supplies `eps_v`; this document selects no production tolerance. Admit the
  motion replacement only when the certified `E_v <= eps_v`. A matching-support
  time-integrated velocity-error bound is then at most `eps_v*V_ref*H`.
  This is not automatically a moving particle's trajectory bound: I05/I09 must
  include correspondence/advection error or a suitable flow-stability bound.
- Record actual external work, dissipation, stored elastic energy and heat for
  both branches over the same window. Preserve the transition energy accounts and
  any I02 work allowance independently; a velocity bound does not bound work by
  itself or authorise deleting stored stress/energy when removing a belt.

The norm/scale/window are selected specifications. Constructing a whole-window
bound for general evolving rheology remains I07/I09 implementation; the existing
scalar admission receipts do not certify this wider model.

## 5. Required refusal example and comparison plan

Retain the closure matrix's counterexample, with all lengths in a common physical
unit and c dimensionless:

```text
u_a = c*(H_c-a*w)
h(u) = H_c-u/c                         when u <= u_a
h(u) = a*w*exp(-(u-u_a)/(c*a*w))        otherwise
```

Choose the exact illustrative values H_c=64, a=c=w=c_w=1 and admit only ladder
levels h_k=H_c/2^k >= c_w*w. The seven admitted thicknesses are
64,32,16,8,4,2,1 and openings 0,32,48,56,60,62,63. Their increment ratios are
all 1/2, yet at the extrapolated opening 64 the real bridge is **1/e > 0**.
Halving w and extending the ladder leaves the false limit at 64, with bridge
thickness **1/(2e) > 0** there. At every finite opening the material is connected.
No event or mechanical certificate follows. These are exact analytical expected
values, not a new simulation or evidence receipt.

The [case](../cases/i01_separation_decision_v1.json) also fixes expected outcomes
for disconnected crust over connected mantle, an alternating-material bridge,
an unresolved thin bridge, the yield-plateau velocity counterexample, an inherited
gap and a boundary whose tip ends inside a plate. Later tools must refuse the
invalid event using their actual admission logic, not merely print a warning.

I07 compares N and 2N at fixed ell, identical physical support and law, plus time
refinement and a separately labelled ell sensitivity. Predeclare tolerances before
those runs. Report the three diagnostics, union connectivity, both widths,
coefficient ranges and event brackets. Neither refinement nor a convergent ladder
selects a physical failure mechanism. Only an admitted singularity, state change
with its accounts, or discontinuity/failure law can supply that missing step.

## 6. Existing basal choice and ownership

Reuse [MC-04's selected basal specification](I01_BASAL_CLOSURE.md) and its
[bounded receipt](../evidence/i01-basal-closure-r1.json); do not reopen or rerun it
to write this record. Both consumers need the mechanical prescription, incoming
thermal/compositional state and moving-volume accounts. I05 transports cohorts;
I07 binds solved fluxes and source states to the same prescription, checks a
deeper-base sensitivity and declares its solver tolerances. I02 commits once.
Basal inflow equals side outflow only at constant domain volume. None of these
accounts proves separation or admits otherwise unsupported melting.

MC-04 and retention of elastic memory were already selected independently.
This document does not count them again or close MC-01, MC-02 or I01. It leaves
old source-bound methods, tools and receipts unchanged. The next separation work
is selection of an admissible mechanism and a genuinely resolved comparison,
not another manufactured certificate.

## 7. Research basis and checks

Sources inspected for this decision on 28 September 2026:

| Source and inspected part | Used here; limit |
| --- | --- |
| [Brune et al. (2014)](https://www.earthbyte.org/Resources/Pdf/Brune_etal_2014_Rift_migration.pdf), Results p. 2 and Fig. 2 caption p. 4 | Rift migration transfers material between eventual margins; crustal breakup/exhumation and evolving velocity/strength fields are distinct. No universal separation threshold or mechanical error allowance is supplied. Methods page-image retrieval failed; those pages are not counted as newly read. |
| [ASPECT continental-extension cookbook](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/continental_extension/doc/continental_extension.html), compositional fields and final breakup limitation; [strain-dependent source](https://raw.githubusercontent.com/geodynamics/aspect/main/source/material_model/rheology/strain_dependent.cc), `compute_strain_weakening_factors`, `calculate_plastic_weakening`, `fill_reaction_outputs` | Separate particle-carried crust, lithospheric mantle and histories. Local weakening is not rupture; the example itself lacks the basal/asthenosphere treatment for realistic breakup. Live latest/main, not a pinned release or an executed comparison. |
| [Audoly & Hutchinson (2019)](https://groups.seas.harvard.edu/hutchinson/papers/2019-1-Rate-DependentNecking.pdf), section 2 equations 2.1–2.12 and section 5.3 formulation | Material-coordinate area conservation and law-dependent necking. Its elasticity-free rate-dependent model is not a general lithospheric separation criterion. |

The reporting definitions, union-path requirement and handoff norm are explicit
Atlas design choices, not thresholds borrowed from these papers. The source
comparison was delegated read-only; no external software was installed or run.

For this documentation-only change: parse the case, check its exact analytical
values and local links, run the repository's coding-safety/public-path checks and
verify unchanged current evidence. No solver campaign, new numerical receipt,
calibration or generated-world acceptance is implied.
