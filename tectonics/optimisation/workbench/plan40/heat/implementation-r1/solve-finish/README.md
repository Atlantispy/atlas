# Plan40B solve/finish implementation r1

**Current actual-source result:** the later [complete owning-receiver comparison](../MEASUREMENTS.md) saves 1.339% (~0.060 ms/call), with all three paired batches favourable. This replaces the prototype 5.244% as the performance description of the implemented receiver; no current runtime or whole-IV gain is claimed.

C8 is implemented as an additive complete assembler, derived inventory and owning assessment receiver. The new receiver is wired and locally qualified with the actual selected WorkBudget/workspace. It is not selected by the frozen source closure, enabled in production or scientifically accepted. All selected sources, measured scripts/results and interval/worker holds remain unchanged.

## Measured decision

The successful q76 run `364b539f-74df-4ee4-83ce-f4f1cb2370f8` supplied the retained samples. `MEASURED-DECISIONS.json` preserves every raw batch sample, exact measurement hash, median calculation and candidate disposition. Each batch contains three complete component calls; lower is better. Positive reduction means faster.

| Candidate | Baseline median batch, microseconds | Candidate median batch, microseconds | Median reduction | Faster paired batches |
|---|---:|---:|---:|---:|
| C6 | 763.7 | 776.3 | -1.650% | 1/3 |
| C7 | 125.6 | 130.4 | -3.822% | 0/3 |
| C8 | 7072.9 | 6702.0 | +5.244% | 2/3 |
| C9 | 313.1 | 319.1 | -1.916% | 2/3 |
| C10 | 4851.2 | 4773.6 | +1.600% | 2/3 |
| C18 | 298.5 | 287.0 | +3.853% | 3/3 |
| C19 | 9160.7 | 9205.0 | -0.484% | 1/3 |
| C20 | 1552.3 | 1744.9 | -12.407% | 0/3 |

C8 has a modest observed benefit with overlapping samples. This supports a small, direct exact-arithmetic change; it does not establish statistical significance or a whole-heat improvement. C18 improved in all three pairs but introduces a retained Fraction vector whose native lifetime/custody remains unqualified. C10's small benefit likewise does not qualify its cache/issuer seam. C6, C7, C9, C19 and C20 regressed on median time; C20's large first candidate sample is retained, not discarded.

## Implemented source and exactness

`private_heat_interval_assembly_kernel_plan40b_c8_r1.py` is a complete additive successor of selected `private_heat_interval_assembly_kernel_r2.py` (SHA256 `6ac42cb45074daee24a74a04b0dec1d0a99a9c1e79f6c138bf6695bd264ebb7e`). Its only executable change is the validated cell-owner expression. A +1 owner reuses the immutable GMP rational endpoint tuple; a -1 owner uses `(-hi, -lo)`. The preceding validation permits only exact integer +1/-1 and `_q` already converts endpoints to exact GMP rationals. There is no rounded multiplication reassociation or Decimal sign shortcut.

Physical face/owner/key order, every original check, exact additions, wall/power conversion/scaling, zero handling, contributor records, refinement selection and Decimal rounding remain unchanged. No extra retained vector/cache, optional admission or new lifetime is introduced. Existing conservative inventory and owner behaviour are unchanged; this implementation does not lower their declared storage or certify a previously unproved inventory. Reused endpoints are immutable and remain within the existing result/input lifetime.

## Focused validation

`check_c8_successor.py` loads the actual complete successor and predecessor modules, selected converter and actual selected GMP backend. The test package namespace avoids importing unrelated package entry points; numerical functions are not AST-extracted, rewritten or stubbed. Exact source guards bind the source map, selected dependencies and successor. A whole-module AST comparison proves every executable statement outside the one expression is unchanged, including both public wrappers and their admission/cleanup code.

`C8-CONTROLS.json` records 24 passing comparisons: collect and fail-fast modes; both owner signs; exact zero; 512/2048-bit denominator cases; aggregate ambiguity and complete contribution/refinement outputs; invalid integer/bool/same-sign/duplicate owners; reversed bounds; three cancellation points; and an injected failure in the unchanged add operation. Full canonical outputs, Decimal flags, exception type/message and checkpoint/add counts agree. In the ordinary fixture, calls to `_scale` fall from six to one: all five eligible cell-owner calls disappear, while boundary scaling remains. Those correctness controls collected no arm timings; the later actual-receiver timing is separate. Ruff `F821,F841,B905` returned `[]` for predecessor, successor and control.

Portable command, using an already qualified environment with the selected GMP backend:

```text
python -B check_c8_successor.py --repo CHECKOUT --output NEW_RESULT.json
```

The control executes the complete changed assembler body. It does not newly qualify native owner/traceback accounting; unchanged public-owned wrappers are established as source-identical. Root owns shared source-only/public-path checks and implementation review/integration.

## Additive receiver wiring and new public identity

`private_heat_interval_inventory_plan40b_c8_r1.py` is the complete r4 inventory successor. It imports C8 and keeps every inventory formula, conservative allowance, retained-generation charge and admission. Its source guard checks the actual imported dependency files against explicit selected-public hashes. `private_heat_interval_assessment_plan40b_c8_r1.py` is the complete r5 owning wrapper successor, with the new assembler/inventory imports and exact inventory pin. Its executable receiver functions and classes are unchanged. There is no source alias or runtime monkeypatch activation.

This is an explicit new public binding. The selected public r5 wrapper still contains historical inventory pin `cc755dab...`, whereas its selected public inventory bytes hash `fd895087...`. That inventory retains a sanitised private absolute runtime path with historical hash `1cecc336...`; the selected public `integration_exact_gmp.py` hashes `5f3be654...`. The new route resolves actual imported files and pins their full public hashes instead. Original files and historical receipts remain untouched; this change does not authenticate a historical private run.

`check_c8_receiver.py` imports complete selected modules through a hash-checked loader, including the real native WorkBudget, OwnedWorkspace, exact backend and preserve-workspace machinery. `C8-RECEIVER-CONTROLS-r2.json` records seven passing receiver controls: result and rounded-system consumer; retained-generation charging and earlier-owner close; owned refinement refusing a numerical view; budget refusal; initial cancellation; escaped MemoryError with retained exception and traceback-only charge until final drop; and both inventory/kernel pin faults before admission. The combined first control includes the ordinary result and retained generation. All 71 imported selected source files are bound. AST checks establish unchanged inventory formulas and complete receiver functions; the earlier 24 assembler checks are reused unchanged.

Preparation failures are retained in the private evidence and final receipt: the first builder's mistyped map pin refused before writing; the first focused import loader omitted the selected top-level live helpers and refused; both were corrected without altering selected sources. Initial lint flagged a deliberately held traceback variable as unused; the control now explicitly checks that retained reference and drops it. Successor receiver controls were refreshed after that small test correction. Focused Ruff is clean for the new source/control/adapter files.

## Completed actual receiver comparison

`private_heat_interval_inventory_plan40b_reference_r1.py` and `private_heat_interval_assessment_plan40b_reference_r1.py` apply the same new portable public binding to the unchanged original r2 arithmetic. `measure_c8_receiver.py` compares these complete imported reference/C8 owning routes. Both arms include the same input construction/admission, source guards, inventory derivation, native WorkBudget/workspace, canonicalisation, owner close and fixture-input release. Each call uses a 64 MiB native accounting limit and a 1 MiB caller-input allowance. These are fixture accounting limits, not RSS measurements. Imports and outer source-pin scans are outside the sample.

The completed benchmark used three alternating samples per arm and three receiver calls per sample. It requires external queue admission; its environment check does not grant GO. `C8-RECEIVER-SMOKE.json` is one no-clock iteration of that same loop and has equal output digests. The subsequent controlled actual-receiver timing completed and is retained in `ACTUAL-MEASUREMENTS-r1.json`. In particular, the earlier 5.244% prototype median must not be assigned to these source-checking owning receivers.

```text
python -B check_c8_receiver.py --repo CHECKOUT --output NEW_RECEIVER_RESULT.json
python -B measure_c8_receiver.py --repo CHECKOUT --smoke --output NEW_SMOKE.json
# Only after exact external GO:
python -B measure_c8_receiver.py --repo CHECKOUT --benchmark --output NEW_MEASUREMENT.json
```

The actual additive receiver is complete, callable and integrated for its accepted source-only scope. Selecting it in the held full forward/issuer route, modifying the frozen source map/profile, worker dispatch, whole-programme integration and scientific acceptance remain separate authority/source gates. The original selected r5/r4 and their consumers still select the original r2.
