# I01: locating contact between moving junctions

Status: **bounded numerical prerequisite implemented; generated junction
reorganisation remains OPEN (MC-05).** No generated world or physical event is
accepted by this helper. It does not alter a plate graph or call the current
junction solver. Later I03/I09 integration must supply admissible trajectories.

## 1. Why a junction residual is not enough

The existing [transition method](I01_TRANSITIONS.md), section 5, asks whether
three boundary-motion constraints permit one junction velocity. Incompatibility
means the assumed geometry cannot continue as declared; its least-squares
residual supplies neither an instability growth rate nor a replacement boundary.

A different event occurs when **two individually compatible junctions meet**.
Their endpoint velocities can remain compatible throughout the approach. If the
connecting edge is a straight segment, its length reaches zero. A residual-only
trigger misses this event. Endpoint coincidence alone does not prove that an
arbitrary curved edge has zero length: loops and spherical paths need their own
geometry and event certificates.

## 2. Exact calculation within a declared model

This implementation accepts planar positions in metres, constant velocities in
metres per second, a shared parent epoch, a named edge and a positive validity
horizon. The caller explicitly declares `affine_planar_junction_paths_v1`.
For offsets from that epoch:

```
d(t) = (x_right - x_left) + (v_right - v_left) * t = d0 + w*t
```

When a component of `w` is nonzero, solve its linear equation for `t`, then
require **every component** of `d0+w*t` to be exactly zero. This is equivalent
to testing the closest-approach time `-dot(d0,w)/dot(w,w)` and requiring zero
remaining separation, but avoids unnecessary products. A positive closest
distance, however small, is a miss on these declared trajectories.

The manufactured control has `d(t)=(12-3t,0)`: contact is exactly at 4 seconds.
Squared length is 144 square metres at both ends of the 0-to-8-second interval.
It touches zero without changing sign, so a sign-change-only event search would
miss it. This calculation is Atlas's elementary derivation, not an equation
attributed to the cited plate-tectonics papers.

Arithmetic uses exact fractions of the **supplied values**. Integer and finite
binary-float inputs are accepted; bounded `Fraction` inputs allow a returned
non-binary event time to be queried again without rounding. Converting before
subtraction avoids overflow and underflow changing the classification. This
does not recover information lost before input, validate a trajectory's physics,
or turn rounded solver output into exact physical geometry. An intended contact
perturbed by input rounding remains a miss in this representation: a future
uncertainty-aware caller must handle that explicitly, not snap it to zero.

## 3. Results and guards

Queries require `0 <= start < end <= validity`. The window includes both ends:

- `COLLISION_CANDIDATE_NOT_REORGANISED`: isolated contact later in the window.
- `CONTACT_AT_WINDOW_START`: contact is already present at the start.
- `COINCIDENT_INTERVAL_NOT_ISOLATED_EVENT`: identical positions and velocities;
  not a newly isolated collision.
- `NO_CONTACT_ON_DECLARED_PATH`: no exact contact inside this window.

The exact event offset is serialised as numerator and denominator strings.
Negative/past roots are not returned in later windows. Adjacent windows may
report the same endpoint as an initial contact: this is **not** a once-only
transaction system. I02 owns deduplication and I03/I09 own simultaneous contacts,
state authentication, trajectory validity and candidate admission.

Inputs are copied into an immutable prepared object; IDs are bounded labels,
not authenticated digests. Invalid numbers, empty identities, unsupported models
and out-of-horizon queries are refused. Input integer size and exact arithmetic
size have explicit resource bounds; these are computation limits, never physical
contact tolerances. No NumPy/SciPy/native solver, thread pool or filesystem cache
is required. The helper stores a fixed number of coefficients and at most one
root, with no growing trajectory history.

## 4. What must happen after contact

The caller must stop the old proposed evolution at the event before continuing
past it. The helper itself only reports the candidate; it cannot stop an external
solver. For four distinct plates, a vanishing A-B edge between ABC and ABD
junctions makes a C-D edge between ACD and BCD a **possible** adjacency, not an
automatic perpendicular flip or a physical selection rule.

Any continuation must preserve cyclic order, ownership and shared edge identity;
solve the new junction constraints; have compatible separating endpoint motion
and positive forward edge length; avoid crossings/inverted regions; and account
for any finite material, heat and history transfer. A ridge additionally needs
admitted spreading/supply; a trench needs polarity and consumption; a transform
needs compatible normal motion. Even a unique kinematic candidate does not
supply a rupture, ridge-propagation or other boundary-birth mechanism.

Neither a shortest-edge threshold, minimum-dissipation guess, graphical repair,
nor prescribed graph edit closes MC-05. Spherical/time-dependent paths, uncertain
positions, multiple simultaneous contacts and actual graph changes are not
implemented by this bounded planar helper.

## 5. Verification and measured reuse

`tests/test_i01_junction_events.py` covers exact double roots, both coordinate
constraints, tiny near misses, rational event times, event ordering, stationary
and persistent contact, exact representable translation/common-velocity/rotation
controls, reversed endpoints, malformed inputs, extreme float magnitudes and
immutable ownership. These are numerical controls, not observational validation.

`cases/i01_junction_events_v1.json` fixes the manufactured example and benchmark
workload before running. The command below creates a new receipt exclusively,
binds this method, case, tool and tests, and checks source identity before/after:

```
python -B tools/check_i01_junction_events.py --output evidence/i01-junction-events-r1.json
```

Five interleaved batches compare 1,000 identical queries with a prepared object
against rebuilding that object each time, requiring exact output equality.
The recorded saving is **preparation reuse only**, not improvement over an
existing world solver, end-to-end speedup or evidence for parallel execution.
The campaign has a 10-second bound checked between fixed-size batches. Accepted
results are `PASS_BOUNDED_CONTROLS_ONLY`; `scientific_acceptance` and
`generated_reorganisation` remain false.

## 6. Research and existing software inspected

- [McKenzie & Morgan (1969), *Evolution of Triple Junctions*](https://www.nature.com/articles/224125a0):
  publisher abstract only; full text was inaccessible. It distinguishes stable
  geometry under plate motion. No unchecked original equation or figure is used.
- [Kleinrock & Phipps Morgan (1988), *Triple junction reorganization*, DOI
  10.1029/JB093iB04p02981](https://www.researchgate.net/publication/252480635_Triple_junction_reorganization):
  author-uploaded Introduction, hypotheses, local tensile-stress and
  minimum-dissipation sections inspected. More than one configuration can be
  kinematically stable; stress-controlled ridge propagation is a separate
  mechanism. Its idealised wedge analysis is not a general Atlas growth law;
  no OCR-derived stress equation was copied.
- [pyGPlates `resolve_topologies`](https://www.gplates.org/docs/pygplates/generated/pygplates.resolve_topologies.html)
  and [shared subsegments](https://www.gplates.org/docs/pygplates/generated/pygplates.ResolvedTopologicalSharedSubSegment.html):
  documentation inspected, software not executed. Supplied topology/rotations,
  common boundary ownership and explicit polarity are useful representation
  precedents. Reusing immutable inputs avoids repeated preparation. These APIs
  do not supply a physical reorganisation law; reconstruction rubber-banding is
  not adopted as a physical continuation.
