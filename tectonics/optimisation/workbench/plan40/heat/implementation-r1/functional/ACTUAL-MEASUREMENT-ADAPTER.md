# Actual C13 component measurement adapter — completed

**Execution complete:** [actual-source results](../MEASUREMENTS.md) and sibling `ACTUAL-MEASUREMENTS-r1.json` now record the controlled run. The preparation details below describe the frozen adapter and its prior no-clock qualification; they are not a pending run or an adoption claim. C13 was slower and is not adopted.

The prototype's 1.42% median reduction does not establish a saving for the actual successor. `measure_actual_c13.py` now measures the unchanged imported predecessor and successor components, including the successor's extra source/callable checks. No implementation bytes or source fences were changed for this comparison. The controlled actual-component result was 6.001% slower, so the successor is not adopted.

Frozen adapter SHA256: `637e04c01d57faa50eacd6f725c86f56233a56a1f9ff8e3fa5332e903019efc5`. It pins the three successor modules, original M1/M4 and numerical predecessor, unchanged `check_functional.py`, original passing `RESULTS-r1.json` and frozen functional loader. The loader authenticates the selected SOURCE-MAP and all loaded selected sources. Source-relative bindings appear in the result; no private dependency root is required.

The adapter reuses only the pinned check's setup and four fixtures, ending before its `invoke` definition or any correctness execution. It imports the complete actual successor modules. It does not repeat the four-case/thirteen-fault proof. The explicit START component-fence injection is identical to that earlier proof and runs in both arms; it is not qualification of the original private runtime fence. Functional bounds/parallel import shells are unused. No worker, forward issuer, checkpoint or full runtime is qualified.

Each arm executes four native `second_moment` calls (triangle, rectangle, reversed rectangle, tiny tilted triangle far from the origin). Its total includes budget/poll construction; `M.admit`, the injected START checks and original full prospective plan; original or successor numerical work and source checks; native retained transfer; symmetric diagnostic export; owner close and zero-charge verification. Diagnostic export is included in both arms. Result hashing/comparison occurs outside each timed interval. One-time loading/fixture setup has a separate `component_load_setup_seconds` field only in benchmark mode. There is no fallback or cache in this stateless transform.

The fixed loop is three counterbalanced blocks: ABBA, BAAB, ABBA, producing six raw samples per arm. Four calls per sample means 48 sampled calls plus eight untimed preflight calls. Each result contains top-level `status`, `candidate`, `script_sha256`, `mode`, a candidate status, all raw samples, per-call plan/peak/retained bytes and poll counts, exact predecessor/successor/source pins, workload digest and stable result digests. Failures remain FAIL and return nonzero. Optimised Python refuses before source access. Benchmark mode additionally requires `--queue-go`; that flag is not authority.

One exact-loop no-clock smoke passed: `actual-c13-smoke-r1.json`, 12 samples, all matching preflight digest `60869ebbed11ec42fca3c8682ba2eb8af6ac68459ae2a1cc84a8ac203388b15f`. Workload SHA256: `1e0b74d2583a3f8feb7a32875a65a8bad4a8edca96d68ad64517a670baf6f034`. Performance-clock sentinels remained active; the result has no timing fields. Every arm executed four START component fences. Native peak charge was at most 9,229,868 bytes and every successful close released its charge. Both arms preserve exact values, full plan and polls; measured retained-byte diagnostics are reported as observed. Focused Ruff F821/F841/B905 is clean.

The smoke process completed in approximately 0.8 seconds as reported by the execution tool, without arm timings. Requested run bounds can conservatively be one core, under one minute and under 1 GiB; the peak native charge is not a process-memory measurement. No performance claim follows from smoke duration.

Portable command, using the selected Atlas interpreter and sibling implementation files:

```text
PYTHON -B measure_actual_c13.py --repo ABSOLUTE_CHECKOUT --testing FROZEN_FUNCTIONAL_TESTING_DIRECTORY --candidate C13 --smoke --output NEW_SMOKE.json
```

Only after the root's controlled queue GO:

```text
PYTHON -B measure_actual_c13.py --repo ABSOLUTE_CHECKOUT --testing FROZEN_FUNCTIONAL_TESTING_DIRECTORY --candidate C13 --benchmark --queue-go --output NEW_MEASUREMENT.json
```

This adapter and smoke do not enable C13, change H5a or clear any scientific, individual or full-interval hold. The previous positive prototype margin remains explicitly insufficient for adoption; the actual successor lost and is not adopted.
