# Plan40A: lazy immutable chart and profile preparation

Historical source/prototype analysis. Current implementation selection, measurements and resource qualification are in [FINDINGS.md](FINDINGS.md) and [the receiving implementation](implementation/README.md). Statements below about proposed work or unproved production contracts describe this earlier evidence, not the current selection. This public copy removes local coordination and paths; it does not authenticate a rerun.

**Decision:** exact, bounded candidate worth retaining as a secondary complement to midpoint value-only evaluation. Synthetic AST feasibility passes. This is not a substantial measured IV gain, production integration, funded-lifetime proof or actual-capture replay. The cost saved is much smaller than removing repeated derivative jet arithmetic.

## Identity and result

- Current portable prototype: `chart_preparation_probe.py`, SHA256 `bcabef407a99aae01af82f9ec7d50d7d9378b1bce76a7885db89f4f0bcfbfa5a`.
- Retained arithmetic result: `chart-preparation-result.json`, original retained-byte SHA256 `a0d16defde061de921d9d83e37cdee2d6b4c56f2a8e1f7b85c39cd1c11beffd4`; tested adapter `04c72c14b1b3fe784fe18832ff5908485299f6e8c8f6b874edb4c37edfcebf30`. This result predates the portable CLI/strict decoder changes and must not be presented as their acceptance.
- Coupling: `tectonics/optimisation/pending/pressure/c/full3/src/atlas_tectonics/integration_pressure_coupling.py`, SHA256 `7c2c3b992d7e0267ed4da70dc5f6ba1bc557f3a2105369ca2b2abefa4e52d05e`.
- Vector definitions: `tectonics/optimisation/composed-r2/src/atlas_tectonics/integration_volume_overlap.py`, SHA256 `96f3921c2b7a8369f230dd362a28552d1f21179a5605fb183f01cfc075e68f48`, `_dot`/`_cross` lines32–37.

Run used bundled utility Python with `-B`; the probe AST-extracts only named definitions, imports no production modules, does not run stage/quadrature/admission, and makes no timings. The pre-3.12 `_over = Fraction` compatibility branch is reproduced when needed. No production source changed.

PASS for the retained arithmetic adapter: 216 chart comparisons, of which180 complete values and36 identical error type/message;108 midpoint and108 interval calls. Cases include coincident endpoints, origin crossing/touch, zero and nonzero normals, non-dyadic coefficients, large rational operands, and three precisions32/96/160. Each comparison includes every jet component **and the exact `_RadialJet.expression` witness**. Thirty-six profile primitive comparisons cover zero, signed and fractional coefficients and constant/nonconstant jets. Empty/reversed radial intervals do not prepare profile coefficients. Wrong integration binding refuses; an injected preparation failure is propagated and not cached. Corrupting only the radial expression witness is detected. Focused Ruff F821/F841/B905 and all behavioural controls passed for that adapter.

The current adapter requires explicit `--repo` and `--out`; it records relative source labels and hashes, no private source paths. It refuses `sys.flags.optimize != 0` before acceptance work. Capture decoding requires exact tagged fields/types, canonical decimal rational components, reduced positive denominators,4096-bit bounds, integer denominator1, and bounded structure; it never silently truncates an encoded integer fraction. Replay-only invocation skips the unchanged synthetic arithmetic suite. The pre-3.12 `_over = Fraction` fallback explicitly reproduces the selected module's original compatibility assignment; it is not a new numerical method.

The later portable-interface controls are **PASS**; they are separate from the original arithmetic result. `chart_preparation_control.py` SHA256 `089e47559a4db2a0bfa4f4a86502b71167ec6434e9ef16a3a5175d562437374c` exercised only the changed interface: two synthetic chart captures (one interval and one midpoint under one exact binding), complete expected-output/witness equality, preserved int/Fraction types, fourteen malformed decoder refusals, malformed-capture CLI exit1 without a success artifact, and `-O` exit1 before acceptance without a success artifact. Ordinary replay exited0. The frozen probe SHA remained `bcabef407a99aae01af82f9ec7d50d7d9378b1bce76a7885db89f4f0bcfbfa5a`; no probe repair was needed. Focused native Ruff F821/F841/B905 passed for probe and control. The216/36 unchanged arithmetic suite was not repeated; no production imports, science/stage, workers or timings were run.

Control evidence is `chart-cli-controls-r1/result.json`, original retained-byte SHA256 `b2010499a40beb711041104c31061d1b26d8c785e0ebdebf1c7f041226c7bcc1`. Synthetic replay output `chart-cli-controls-r1/synthetic-replay.json` original retained-byte SHA256 `6033adc5711a3a560bc1c24ab8094a812786eb4e8300694250c65dacd700a80e` explicitly retains `synthetic_fixture: true`. Input fixtures and subprocess logs are excluded from this public package; both expected negative exits are summarised in the retained control result. This validates capture transport and controls only; it supplies no actual workload capture or performance evidence.

The public JSON copies normalise CRLF to LF only; [PUBLICATION.json](PUBLICATION.json) maps the original digests above to their distinct public byte digests. Parsed records and embedded evidence identities are unchanged; this is not a rerun.

## Exactly what can share

`_radial_chart_jets` lines414–441 repeats six invariants for the same exact immutable three-vectors `(a,b,normal)`:

1. `direction = _minus(b,a)`;
2. `dd = O._dot(direction,direction)`;
3. `ad = O._dot(a,direction)`;
4. `O._dot(a,a)` inside the radial expression witness;
5. `O._cross(normal,a)`;
6. `O._cross(normal,direction)`.

One integration-owned preparation may serve every interval and midpoint evaluation across all wedges/leaves and precision requests of that same integration. `_integrate_radial_shell` lines506–524 calls `_radial_slice` lines481–503, which calls the chart at487. `_integrate_radial_pressure` lines627–709 calls it at677. Both closures retain fixed `a,b,normal`; `_integrate_angular.add` lines547–566 evaluates the interval and, if fixed, the midpoint, then repeats on subdivision. `normal=O._cross(a,b)` is already computed once per integration and is not a saving claimed here.

Do not reuse across different integration owners merely because the vectors compare equal: capture replay groups equal bindings only to test arithmetic reuse, not to authorise a global cache. Do not reuse t-dependent radius extrema, square roots, derivatives, factors or edge clipping. In `_radial_interval_jets` lines444–479, edges/profiles vary and each invocation has its own branch decisions; this prototype changes none of it.

For each fixed profile row and gravity in `_integrate_radial_pressure.evaluate` lines682–690, the primitive contains `(ptop+gravity*rho*top)/3` and `-gravity*rho/4`. These two exact coefficients can share across upper/lower primitive endpoints, midpoints and interval/subdivision calls, independently per profile. `_positive_interval_primitive` lines601–610 skips both for equal/empty intervals. Retain that skip and the existing `exists` skip at684–685. This probe does not alter donor primitives, shell `rc**3`, row ordering, accumulation, branch decisions or any jet rounding.

## Order, refusal and arithmetic cost

The prototype replaces only the exact six chart expressions and two profile coefficient expressions with lazy `prep.get(key, lambda: ORIGINAL_EXPRESSION)` calls. An AST round-trip that removes these wrappers exactly reconstructs each original function/lambda, including expression order. Each cached value is an immutable Fraction/int/tuple; the owner-local dictionary is mutable metadata, not a claim of a fully immutable lazy holder. No original arithmetic is regrouped. Cached values are independent of precision and interval endpoints.

An eager complete chart preparation before the first evaluation would move `dot(a,a)` and the two cross products before the original origin check. The prototype deliberately avoids this: a first origin refusal computes only direction/dd/ad. Each later invariant is first evaluated at its original expression site, so earlier sqrt/division/jet refusals still precede it. Profile coefficients are similarly evaluated only when their original lambda reaches that operand, after its original preceding jet-power work. Refused expressions are never cached. Supported scope is exact immutable rational vectors/profile data; arbitrary side-effecting custom numeric objects are not covered.

For three-dimensional vectors, complete preparation costs:

| Component | Rational arithmetic |
| --- | --- |
| direction |3 subtracts |
| three dot products, including `sum(..., Fraction(0))` |9 multiplies +9 adds |
| two cross products |12 multiplies +6 subtracts |
| Total |21 multiplies +9 adds +9 subtracts |

For N successful full chart calls under one binding, original invariant work is N times that total; lazy preparation performs it once, saving `(N-1)` times the total. Primitive-operation break-even is the second call; first use saves zero, and dictionary/lambda/binding/lease overhead is additional and unmeasured. A mixed refused/successful sequence prepares only expressions actually reached; use per-key occurrence counts rather than the full-call formula. `_dot` allocation/comparison savings and Fraction internals are not included in these arithmetic counts.

The profile coefficient pair costs3 multiplies +1 add +2 divides +1 unary negation, once per profile actually reaching the primitive. With M actual primitive calls for that profile, save `(M-1)` times that total, starting with the second call. The original nonempty primitive normally evaluates upper and lower, so reuse can begin within its first accepted radial interval. No claim is made that these counts predict wall time.

## Funding and completion limits

The probe has no budget implementation and proves no admission or lifetime contract. Production preparation must remain per integration, on the existing arithmetic path, with retained derived coefficients funded for their complete lifetime and released on success/refusal/exception. `_integrate_angular.add` funds scratch arithmetic only inside `V._work` before reserving its leaf. Retaining prepared rationals across callbacks outlives that scope. Shell's earlier `V._work` covers wedge creation and ends before quadrature. Pressure's enclosing partition reservation/work scope lasts through quadrature, but its existence does not demonstrate that new retained cache values and object overhead are budgeted. Do not silently charge them to leaf leases or assume a fixed partition allowance suffices. A later integration needs exact size/accounting and failure-path checks; this prototype intentionally supplies none.

Optional source-bound actual replay is prepared but **not run**, because this task received no successful survey capture. Command: utility Python `-B chart_preparation_probe.py --repo SELECTED_REPO --captures SUCCESSFUL_SURVEY/survey.json --out FRESH_OWN_RESULT.json`. It requires survey verdict PASS, the selected coupling hash, bounded chart rows, original full-output agreement with each captured expected value, and then complete prepared-output agreement. Absence of chart captures fails. The transport passed synthetic controls but has not been exercised against a real report. A bounded sample proves only those captured calls, not full workload distribution or integration lifetime.

Recommendation: retain lazy chart/profile preparation for a later funded implementation alongside the stronger midpoint candidate. Use actual survey counts to determine recurrence opportunity. This unimplemented preparation candidate requires complete exact-output/refusal and funded-lifetime qualification before selection.
