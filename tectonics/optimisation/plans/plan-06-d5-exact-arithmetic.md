# Plan 06 — D5 exact arithmetic repair and shared primitives

**Status:** WORKING NON-CANON. Implementation, private construction and scoped
technical verification are complete. **D5 is justified-disabled** for measured
regressions. Collective review remains deferred.

The repaired sources, hook, build/check tools, assembly extension and run safeguard
are published additively in [workbench/plan06](../workbench/plan06/README.md).
This source snapshot does not overlay the main package or supply private profiles,
inputs, captures, stores, receipts or logs. Original/public byte identities and
export transformations are explicit.

## Implemented contracts

D1 defers `Retained` until after the first arena work call; mathematical order-zero
calls read no resource property and make no reservation/revoker call. D2 uses
`V._bits` on reference-typed operands and declines over-ceiling calls before
reservation at entry, both clipping paths and rotation. D4 closes native use on a
second attach and extends the identity binding to `W.V`, `W.O`, `V.Fraction` and
`O.Fraction`. D8 exposes `_work(bits, count, budget, *, pairs=0)` with `lease = _work`.

Provider failure does not cause a backend retry. New results remain canonical
Python Fractions; required input/container identities, aliases and pickle memo
relationships are preserved. Noncanonical inputs retain reference behaviour.
Mid-call identity changes and later ceiling crossings continue the reference
state without repeating earlier work or reservations.

Policy A requires exact results and no later admission. Earlier refusals are
permitted only when attributable to added `NATIVE_RETAINED` accounting and are
counted. N9's separate zero-refusal rule is not applied. The accepted D6 exception
requires causal accounting evidence; unexplained diagnostic changes remain open.
See the [implemented design](../workbench/plan06/DESIGN.md).

## Evidence and measured decision

The retained original failure evidence is preserved in the historical
[D5 sources](../pending/kernels/d5/). Old smoke results do not establish repair.
The repaired candidate passed captured/fuzz/mutant/focused checks, rebuilt smoke,
IV1-all (40,968 exact), IV2 sample (894 exact plus seven capped) and deep completion
(216 exact, covering all seven). Corresponding completed diagnostic histories
passed their bounded D6 interpretation. The original r1 script was interpreted
substantively rather than by its zero exit status.

Actual `assemble_r3` construction, output identities and native dispatch passed
against an explicitly retained baseline. Available N9 test-only wall composition
passed 324 pose cases and 536 rounding calls. These results do not substitute for
the final selected Plan31 composition.

The clean exclusive captured-call comparison measured D5 slower by 11.21%
for clipping, 5.40% for rotation and 52.46% for line construction. Lifetime process
peaks were about 270 MiB in both arms; logical package disk increased by 15,859
bytes. There is no useful measured benefit supporting enablement. Detailed scope,
full identities, interpretation and limitations are in the
[source and validation record](../workbench/plan06/README.md).

## Remaining integration boundary

The actual selected Plan31 source/profile/N9 generation is still required.
Bind its current Plan02 helper/profile and wall-measure bytes, derive all successor
identities from actual output, and complete affected C6 parity and useful-benefit
measurement there. The privately constructed retained baseline is not that
selection. No hand-off to a former implementation owner is required.

Pressure P4 and T3 remain separate work. Existing scientific and individual-job
holds remain intact. Collective review is deferred, not passed. Committing this
snapshot does not enable D5 or claim scientific acceptance.
