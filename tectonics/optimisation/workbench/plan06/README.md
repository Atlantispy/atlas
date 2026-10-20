# Plan 06: repaired exact wall arithmetic

WORKING NON-CANON. **Source snapshot; D5 is disabled. Collective review is deferred.**
The repaired implementation and private construction are complete. This directory
publishes their sources; it does not install an overlay into the main package or
supply a runnable scientific profile.

## Method and contracts

The three wall kernels can use GMP rational intermediates and return the same
Python integers/Fractions, values, types and required input/container identities
as their references. The existing provider selects the backend; a native
calculation failure propagates without retry on another backend.

The repaired route:

- creates retained-native accounting only after the first work call; mathematical
  order-zero branches read no resource property and make no reservation or revoker call;
- computes admission widths from reference-typed operands with `V._bits` and
  declines before reservation when a width exceeds the existing ceiling;
- closes native attachment permanently on a second module attachment and checks
  the reference functions, modules and Fraction constructors by object identity;
- provides `_work(bits, count, budget, *, pairs=0)` and `lease = _work`;
- preserves canonical new results and any input or container identity that the
  reference preserves, including noncanonical-input fallback and pickle memo relationships.

Ordinary reservations keep their amounts, categories and order. Policy A permits
only counted earlier refusals attributable to added `NATIVE_RETAINED` accounting;
later admission and numerical changes are prohibited. N9's separate zero-refusal
rule is not imported. The accepted D6 diagnostic exception is bounded by ordered
requests and overlapping live charges. Final peak-map inequalities alone are
insufficient; unexplained changes remain unresolved. See [DESIGN.md](DESIGN.md).

## Source layout and construction

| Location | Purpose |
|---|---|
| `src/` | Repaired shared primitive and three GMP wall twins. |
| `transforms/d5_wall_hooks.py` | Hook with explicit accepted input hashes. |
| `build_tree.py` | Existing test-tree construction route with exact input/output bindings. |
| `check.py`, `focused.py` | Captures, fuzz, mutants, provider and resource/identity checks. |
| `c6_build.py`, `c6.py`, `c6_diagnostics.py` | Available N9 seam and bounded diagnostic checks. |
| `d5_parity_r3.sh`, `parity_measurements.py` | Rebuilt replay and telemetry interpretation. |
| `measure.py` | Fresh-process ABBA captured-call comparison. |
| `integration/` | Actual additive `assemble_r3` route, staging/check sources and fixtures. |
| `queue-fix/` | Windows process-liveness safeguard and disposable fixture tests. |
| `SOURCE-MAP.json` | Full original/public digests and every export transformation. |

The historical refuted sources and unchanged r1 refuter remain in
[`pending/kernels/d5`](../../pending/kernels/d5/). The retained original refuter
reports failures in its output even when its process exits zero: its exit code
alone is not a verdict.

The builder depends on an exact private base test composition, runtime/provider
dependencies and the separately pinned environment. The replay needs private
captures and inputs; the assembler needs the selected staged generation and its
bound source roots. Those dependencies, generated 616-file compositions, profiles,
receipts, captures and logs are deliberately absent.

Local user paths are sanitised and exported text is LF. Original runtime,
composition, proof and environment pins remain original pins; they have not been
silently changed to make this export launch. The two public assembler fixture
tests have separately recorded public source bindings. Those bindings cover
synthetic tests only and do not authenticate a historical run.

The assembler adds the twins and hook only when an explicit SHA-pinned D5
contract is supplied. D5 remains unselected. The disabled route's synthetic pin
records match the original assembler byte for byte. The field name `reviewed`
in that existing assembler refers to expected-byte construction input and does
not assert collective review.

## Retained private validation

These are results of the original private bytes, not new public-clone receipts.
Full original source identities are recorded in `SOURCE-MAP.json`; private
evidence identities are listed in [RETAINED-RESULTS.json](RETAINED-RESULTS.json).

- 48,170 captured calls, 9,020 fuzz cases, all 16 mutants caught, 20,000 dyadic
  comparisons and all 12 focused groups passed.
- Actual `_Arena`, near-full budgets, order-zero and real over-ceiling paths,
  second module copies, namespace mutations, noncanonical Fractions, exact
  types/aliases/containers, pickle protocols 2–5, provider failure without backend
  retry, and ordered work/reservation traces were covered.
- Fifteen earlier refusals were attributed to the added native-retained charge;
  no later admission was found.
- The unchanged r1 probes P1–P5 agree with reference behaviour; P6 closes native
  use on second attachment. Its subsequent P7–P9 therefore do not themselves
  prove resident-native behaviour; separate focused checks do.
- Rebuilt smoke passed. Full IV1 gave 40,968 exact matches. IV2 sample gave 894
  completed matches and seven capped rows; 216 deep matches covered all seven.
  Scripts, runtime sources, inputs and generated lists were unchanged.
- D6 interpretation passed 16 corresponding completed shard histories. Two
  CPU-capped sample histories remain explicitly incomparable; their numerical
  rows were covered by deep completion. No blanket diagnostic waiver is claimed.
- Available N9 test-only wall composition passed 324 pose cases and 536 rounding
  calls. This is not the final selected Plan31/N9 composition.
- The actual retained-baseline `assemble_r3` check/pin/compose route passed:
  616 files matched; only wall measures changed and two twins were added.
  Fifteen fixtures, 14 output checks and actual native import/dispatch passed.

## Measured disposition

**Justified-disabled.** The exclusive comparison used the same 4,096 captured
calls per kernel, three repetitions, and two fresh processes per arm in A–B–B–A
order. Input setup, validation and warm-up were outside timing. The tree peak
was 0.30 GiB, with zero concurrent small jobs.

| Kernel | Base median seconds | D5 median seconds | Change |
|---|---:|---:|---:|
| `_clip2` | 0.946220 | 1.052334 | +11.21% |
| `_rotated_normal` | 0.804318 | 0.847730 | +5.40% |
| `_line` | 0.392885 | 0.599002 | +52.46% |

Maximum process lifetime working set was 282,750,976 bytes base and 282,673,152
bytes D5 (about 270 MiB each). Package logical bytes increased from 7,276,852 to
7,292,711: +15,859 bytes. These are original captured leaf calls and a matching
no-op work arena, not post-N9 narrowed interval inputs. Actual resource behaviour
was checked separately. Lifetime memory includes imports/capture loading and
does not isolate native allocation; disk figures are logical bytes.

The complete kernel paths were slower. Conversion, canonicality/identity checks
and native accounting add work around the arithmetic. Their individual costs
were not profiled, so no dominant-cause or arithmetic-only speed claim is made.
No whole-interval gain or useful RAM reduction has been demonstrated.

The full replay's initial IV1 timing was affected by short concurrent work after
a Windows permission-limited liveness probe incorrectly reaped a live elevated
runner. Its numerical proof remains source-bound, but that timing is not an
isolated comparison. The included queue repair treats access denial as possibly
alive, confirms a genuinely absent PID and fails closed on unexpected errors.
The final exclusive ABBA comparison above had no such overlap.

## Public checks and remaining boundary

From the repository root, with the existing Windows test environment and `psutil`:

```text
python -B -m unittest discover -s tectonics/tests -p test_plan06_publication.py -v
```

This checks exported hashes, source hygiene, synthetic assembler guards and
disabled equivalence, process-liveness fixtures and the runtime entry environment.
It does not import the scientific runtime or run a simulation. Do not run the
private replay/measurement commands merely to test publication.

The missing integration input is the actual selected Plan31 source/profile/N9
generation. It must use the current Plan02 helper/profile, bind the selected
wall-measure bytes, derive successor identities from emitted bytes and pass the
affected C6 composed parity and useful-benefit comparison. The retained-baseline
construction is not silently promoted to that selection.

Pressure P4 and T3 restructuring remain separate. Scientific intervals, N9
scientific replay and individual held jobs remain held. Publication does not
record collective review, scientific acceptance or permission to launch them.
