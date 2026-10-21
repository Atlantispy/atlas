# Plans 13–14: compiled heat certificates, finish reuse and observations

WORKING NON-CANON. Implementation and selected private integration are complete.
This additive snapshot extends [Plans 10–12](../plans10-12/README.md) on the
optimisation branch. It preserves 618 selected source members, changes 11 and adds
five: 239 native and 395 helper files in total, with no removed predecessor.
H3 remains a candidate; this source integration does not enable it by default.

## How the changes fit together

H3 batches directed MPFR interval dot products in compiled code for the heat
certificate: Gram matrices, inverse defects, residuals and physical bounds.
It preserves rounding direction, zero signs and ternary results. Unsupported
contexts or exceptional compiled results use the retained Python expressions.
The selected build uses `fastmath=false`; this is no change to the heat equation,
precision, acceptance tolerance or exact conservation accounts.

The H2 → L1 → H3 construction retains the physical scratch-order repair and
original public cell/face order. Heat S1 reuses the closed-guard endpoint
certificates through closed-owned r5 and finish r11. The current forward,
checkpoint, joined, restored, RAM and native cold-reader consumers bind this
same generation. Historical readers and receipts remain intact.

Projection numerics retain one actual peak-width witness, with deterministic
ties. This avoids constructing a fictitious witness from component maxima.
The arithmetic and resource policy are unchanged; N5 selects the new numeric
helper while historical N4 retains its old implementation.

Fresh and ordinary prepared drivers share six ordered ticks, an eleven-stage
heat prefix and 16 registered stages (15 without the optional R3 hook). Closure
probes resolve the unique loaded code object before admission. The exact
projection marker observes `NUMERICS.calculate` on N5 and `R.calculate` on N4;
decoding still uses `R.verified_private`. These observations do not change the
numerical kernel, and nested stage durations must not be added together.

## Source and earlier-plan integration

[SOURCE-MAP.json](SOURCE-MAP.json) maps the complete selected closure to exact
public bytes, reusing existing files where identical. It includes a bounded set
of constructor and control sources, including the shared profile builder and H3
transform previously absent from the exported maps. The witness control's r3
resource fixture is labelled under `controls/`; it is not selected production
source. Original/public digests and sanitising transformations are explicit.

The selected closure retains the earlier storage/admission/pressure/geometry
selections and Plans 10–12 reuse, reader scheduling and lf3 heat. The later Plan04
r24 comparator has separate source on this branch; its final producer/Heat
binding remains Plan31 work. This snapshot preserves its selected r21 ancestor
and does not silently repin that frozen composition or claim every pending
earlier-plan change has been folded.

Private paths use `LOCAL_USER`, coordination references are redacted and text
uses LF with one final newline. Numerical literals, tolerances and historical
pins are retained. These transformations change execution identities. Builders
and controls still require excluded private metadata, fixtures and runtime:
this is inspectable source, not a runnable public native installation.

## Review, retained checks and measurements

[RETAINED-RESULTS.json](RETAINED-RESULTS.json) is a new summary of private evidence,
not an execution receipt. Review of the actual compiled helper/fallback, resource
witness, consumer bindings, marker code and strict comparator found no material
code defect. Existing adequate runtime proof is reused without rerunning heat.

- q25 completed all four arms, exact comparison and explicit compiled-route checks.
- The strict saved-output proof passes all five arrays, four cell accounts, face
  account, three scalars and private records, with no unresolved differences.
- All 174 captured Heat source files match the final generation. Neither driver
  was captured; nine focused marker controls establish that binding separately.
- Earlier fresh/prepared marker checks passed 37/17 tests and caught five mutants.
  Six source-bound witness cases cover both cell orders and compact reopen/refusal.
- Native conversion-work amounts compare exactly, but their uncaptured ABI-dependent
  object-size preimage was not replayed. No tolerance or field exemption was added.

| Measurement | Reference | Candidate | Interpretation |
|---|---:|---:|---|
| H3 component wall time | 89.57 s | 84.95 s | 5.16% less; one unmirrored timing sample per side, including compilation/imports |
| Same component sampled tree RAM | 1,030 MiB | 1,376 MiB | 33.59% more; acceptable speed trade-off within existing memory limits |
| Combined heat CONTROL observation | 78.7677 s | 73.3181 s | 6.92% less; one base-then-joint pair, not a robust final-stack claim |
| Same combined stage sampled tree RAM | 1,144,270,848 B | 1,505,419,264 B | 31.56% more; samples, not a hard upper bound |
| H3 component logical source bytes | 9,816,635 B | 9,841,837 B | 25,202 B more; source layout, not interval storage |

The original q52 metadata-admission failure is preserved; a separate corrected
offline proof compared its saved numerical arms successfully. These observations
cannot be added to the earlier heat/ROOT improvements. Final interval time,
runtime disk, combined peak RAM and Release/Debug gains remain unmeasured.

## Remaining programme boundaries

H3 is candidate-only; H5a, D5 and P4 stay disabled. A new profile needs its own
eligible ROOT. Final assembly/fold, first IV1 marker observations, conditional
S2/S4 work, N9 replay, full-workflow recovery, final timing and enablement remain
later scoped work. The full-interval hold, numerical contracts, memory guards and
accepted-step ceiling remain. This branch integration establishes neither
scientific acceptance nor a commit/push.
