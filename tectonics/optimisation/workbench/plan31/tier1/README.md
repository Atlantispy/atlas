# Completed-query hit reporting

This source constructor integrates the corrected Tier 1 counters into the existing
endpoint owner and both interval runners. If any open contributes a truncated hit
split, its stage remains `TRUNCATED` after later complete opens. A new stage has
its own completeness. Ordinary hit totals continue counting after truncation.

From the repository root, using standard-library Python 3.11 or newer:

```text
python -B tectonics/optimisation/workbench/plan31/tier1/build_candidate.py --repo . --output NEW_DIRECTORY
python -B -m unittest discover -s tectonics/optimisation/workbench/plan31/tier1 -p test_tier1.py -v
```

The builder authenticates and constructs the complete
[Plan30 S1A selection](../../plan30/s1a/README.md), which retains the Plan39 source
and release hooks. It transforms only the endpoint owner and the fresh/restart
runners, producing 694 source members with `src`, `helpers` and a new
`SOURCE-MANIFEST.json`. Occupied or linked outputs and changed input, transform,
map or output pins refuse. No scientific source is imported during construction.

The public restart predecessor lacked per-stage completed-query reporting.
`query_store_prerequisite.py` applies the retained query-store wiring from the
runner successor: declared-store admission, the fresh runner's actual query
definitions, flush-before-recording and the workload's observer calls. The public
profile schema, historical-root handling and timing remain unchanged. The Tier 1
edit then applies identically to both runners. The map records public input/output
identities separately from the private corrected successors; public bytes do not
authenticate historical private results.

`apply_t1.py` also supplies the exact private derivation via explicit
`--owner-base`, `--fresh-base` and `--restart-base` paths. Each input and output is
pinned; `--check` writes nothing and `--output` requires a new directory. Its
optional `--restart-crosscheck` accepts only the pinned earlier restart base.
The private owner is unchanged by the review repair; the repaired fresh and
restart outputs are `8efc3a8c` and `051008ad` respectively.

The owner keeps at most `min(max_entries, 2**18)` key prefixes per open, classifies
restart/after-write/warm hits, drops its map after truncation and clears it on
close. Observation changes do not enter cache keys or results. Legacy owners
retain null split fields. Final runtime profiles must book **21 MiB per open
owner** for this observation map; the existing route opens one owner at a time.
This source constructor neither supplies nor confirms that runtime booking.
Ten bounded public checks cover completeness in both
orders, stage reset, real generated flush/error reporting, actual restart wiring,
and input/output/reapplication refusal. The private successors passed four
regression cases across both runners and reproduce the reviewed output bytes.

Status: **WORKING NON-CANON; integrated source component, not a qualified final
generation.** This route grants no runtime admission, interval execution, default
selection or scientific acceptance. It does not construct the held final n12f
generation, run a timing or parity campaign, or update an installed package.
