# Route (1) step 4 design: the interval-1 difference ledger (16 Oct 2026, ~07:10)

Paper design plus code reading; nothing has run. Read-only throughout: r9's run, artifacts and database stay untouched.

## The rule it implements

From the plan-order review, section 7b item 6 (amended ~04:15; items 11 and 15 OFF at ~05:45). The rerun does not have to equal r9; the ledger must show:

1. every difference is attributed to a named, approved RC1 change (today only **cube-witness stopping**);
2. both bounds of every differing query are certified, meet the requested width and overlap;
3. every downstream heat or transport difference is quantified and traced to those bounds;
4. anything unattributed fails.

## What makes the trace exact (CODE)

- Both runs save the same three pre-advance heat inputs, with raw SHA-256:
  - r9: `heat-original-connected-20261013-r9.artifacts/preadvance-{bounds,closed_graph,mesh}.json.gz`, recorded in `preadvance_operands`.
  - The rerun: `compact_restart_patch.inspect_compact_preadvance` writes the same three files into run B's output and records `preadvance_operands`.
- The bounds capture lists every cell (6,260 in r9) with its exact `start_volume_bounds_m3` and `end_volume_bounds_m3`, plus face intervals (1,014) and finite exchange intervals (140).
- Heat and transport for the interval are deterministic functions of these inputs and the heat method. The same-call re-proofs (g11, g12) prove the method gives identical certified records on identical inputs.
- So:
  - **identical inputs** → every endpoint array must be identical, and any difference fails;
  - **inputs that differ only in attributed cells** → every endpoint difference is traced to those bounds, and is quantified per array.

## Levels

1. **Identity (recorded, never a failure on its own).** Execution provenance, runtime source digest, plan and result IDs. They differ by construction when the composition changes.
2. **Start state.** The rerun root's logical fields against r9's `completed_endpoint.root_metadata`. Root-metadata references are resolved to their descriptors before comparing. Expected: identical. No approved change touches the start.
3. **Heat inputs (the query level).**
   - Bounds cells are matched by `cell_id` and endpoint (start or end), never by run IDs.
   - Each differing bound must be:
     - in the approved set, which is computed from the geometry chat's replay rows (`R/geometry-growth-r1/evidence/abl-iv1-*.jsonl`): the queries that differ from r7 with cube stop on and items 11 and 15 off;
     - exactly equal to the replayed cube-on value;
     - certified, within the requested width, and overlapping r9's.
   - Face and finite-exchange intervals and the closed graph may differ only through attributed cells. The mesh must be identical.
4. **Endpoint arrays.** The six groups, by name and SHA-256, from both receipts. For each differing array, the values are read from both stores: count of differing elements, maximum absolute and relative difference, sign changes and non-finite values.
5. **Exact widths.** `width_gate.compare` between r9's census widths and the rerun's recorded widths. Every difference is listed for the ledger to explain.

**Verdict:** PASS only if nothing at levels 2-5 is unattributed. FAIL blocks interval 2, by design.

## Three facts to confirm before the attribution code is final

These go to the geometry chat (the query-row owner):

1. Is the row `full_cell` the same identifier as the capture's `cell_id`? Is `endpoint` 'start'/'end' the same as `start_`/`end_volume_bounds_m3`?
2. Is the row's `exact` field `[lower, upper, witness]`, in m^3, as the capture?
3. Where is the requested width per query? Is the row's `status: met` the only width criterion, or is there a numeric bound (for example `max_stream_error_m3`)?

## Build order

- **Now:** levels 1, 2 (inline fields), 3 (cell matching, overlap and exact equality with the replay, once the three facts are confirmed), 4 (SHA level) and 5. All are store-free except the root references.
- **Next:** level 4 values (read-only store reads in a guarded process, like the reader) and level 2 references.

## Later-step impact

Interval 2 runs only on a PASS ledger. The same comparator compares the interval-2 rerun only if one is ever needed.

## Interval 3

No change.
