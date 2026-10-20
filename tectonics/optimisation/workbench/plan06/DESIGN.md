# Plan 06 implemented exact wall twins, r3

WORKING NON-CANON. This revision implements the accepted DESIGN-r2 contracts and
the accepted 19 October D6 decision. This is an additive source snapshot.
Collective review is deferred. Technical validation and run safeguards remain.
Historical CK sources, r1 failures and smoke results are preserved.

## Arithmetic and return boundary

The provider selects the backend at import. The shared twin obtains that selection
through `X.library()`; it does not import gmpy2 directly or reselect per operation.
Python never imports the native module. Auto may decline provider eligibility
failures; explicit native requests fail closed. MemoryError and RecursionError
retain the provider's propagation. A native calculation failure is never retried
on another backend.

Only exact int and canonical Fraction operands enter the native path. Fraction
numerators/denominators must be Python ints, denominator positive and gcd one.
Malformed/noncanonical inputs decline to the reference without normalisation.
New results are distinct canonical Fractions of Python ints; kept input points,
the unchanged polygon and early-return normal preserve the reference identities.
Mathematical order zero returns the same new-container/original-entry relationship.
Pickle protocols 2–5 include the input/result memo relationships.

## Eligibility, attachment and instrumentation

The first attachment binds the three reference functions, W.Q, V._work, V._bits,
V.select_budget, O._dot, O._cross, W.V, W.O, V.Fraction and O.Fraction by object
identity. A second attachment permanently closes the twin through `_closed` and
keeps the original attachment; subsequent calls use the reference.

Instrumentation installed before a call causes entry decline. A change during
arena.work, resource access or reservation continues the current Taylor state
using the current reference objects. It does not restart the call, repeat work or
repeat an already entered reservation. Clip recursion remains observable.

## Work and retained accounting

`_work(bits, count, budget, *, pairs=0)` has `lease = _work`. It reserves precisely
`65536 + 128*bits + 256*count + 256*pairs` in `i03-physical-volume`.
Widths are computed with V._bits on reference-typed inputs. Later Taylor terms
are Fraction-equivalent natives whose numerator/denominator bit counts coincide.
The shared CEILING_BITS remains `1 << 27`, distinct from the 1 MiB integer bound.

The callers decline before reservation for over-ceiling entry/clip widths.
A Taylor step that later crosses the ceiling continues in the reference route
without replaying its event prefix. The primitive does not introduce a separate
post-reservation ceiling exception.

Retained is created only after the first arena.work. Actual mathematical
order-zero calls make no resource-property reads, reservations or revoker calls.
Nonzero steps preserve work-before-resource validation. Retained native values
use exact_gmp._settle and an added running-maximum NATIVE_RETAINED charge.
Release remains balanced, including exceptional unwind.

Policy A permits earlier refusal only attributable to that added accounting;
these cases are counted. It permits no later admission or numerical change.
Common ordinary-event prefixes, actual refusal requests and live retained charges
establish attribution; equality of final refusal counts is not required.
N9's separate zero-refusal-flip rule is not applied to D5.

## Accepted D6 diagnostics

The accepted source is
the retained private diagnostic disposition,
SHA `ff554325097fc813d242e6f90e70b653a3eac7486a1a26b0e7ee56a66d4b818c`.
Native current/peak entries, a retained zero-current key and solely resulting
folding into `other` under the unchanged cap are permitted. Ordered requested
categories, amounts and overlapping live intervals establish cause. Final maps
alone do not. Unexplained differences remain unresolved.

This does not waive a named consumer's category-identity contract or establish a
general full-payload persistence route. Known done-row statistics and exception
error strings remain distinct from exception-attached full payloads.

## Construction and integration

The r3 build_tree.py retains CK's test-composition construction route, verifies all
base manifest files and records exact source/output bindings. The SHA-guarded
transform accepts the original W and the explicitly inspected test-only N9 W.
The selected assemble_r3 successor registers the hook and both new modules through
its existing staged input, reviewed manifest and composition mechanism. Its
complete pre-D5 baseline comparison remains intact.

Text-disjoint N9 edits to _pose_vector still require composed parity. Local
N9-W tests cannot establish binding to an unavailable final Plan31/N9 candidate.
Required rebuilt smoke, IV1-all, IV2 sample and capped-to-deep proofs retain their
queue/ticket scope. Evidence and measurements belong to the owner plan and the
new r3 evidence files, never to rewritten historical receipts.

Pressure P4 and T3 restructuring are separate. The shared interface is available
without implementing those consumers or releasing any scientific/job hold.
