# Plan40A: repeated point, square root and chart inverse

Historical source/prototype analysis. Current implementation selection, measurements and resource qualification are in [FINDINGS.md](FINDINGS.md) and [the receiving implementation](implementation/README.md). Statements below about proposed work or unproved production contracts describe this earlier evidence, not the current selection. This public copy removes local coordination and paths; it does not authenticate a rerun.

**Disposition: retain all three as exact local candidates.** Same-point and same-square reuse are particularly direct for midpoint evaluation and remain useful after derivative removal. Existing-inverse reuse additionally reduces the full-jet chart's nonconstant reciprocal path. Synthetic source-bound checks pass; no production implementation, measured IV gain or resource acceptance is claimed.

All files below are siblings in this public pressure package:

JSON digests in this historical table identify the original retained bytes. Public JSON copies have LF line endings and separate digests in [PUBLICATION.json](PUBLICATION.json); parsed records and embedded identities are unchanged. The Python probes remain byte-identical.

| File | Original retained SHA256 |
| --- | --- |
| `chart_point_probe.py` | `a5f6581e2dff3eff7a4d2ab7d3654414e84518cd7cd9bf1c4f49d1427566ea88` |
| `chart_point_result.json` | `15c31daad7b5db1c429329bb7cad02f4226c352aa4139e82b51419048a82d892` |
| `chart_point_reciprocal_probe.py` | `09e17ad0078215868836d770bf561a9c5b92b2c1f23cf64e7f1b70dbe198aff3` |
| `chart_point_reciprocal_result.json` | `8df8c96426e6ff42fa6f3ba928a13a9d364f06a3eb64e9a545997d382cfb6420` |

Both depend on the unchanged AST helper `chart_preparation_probe.py` (`bcabef407a99aae01af82f9ec7d50d7d9378b1bce76a7885db89f4f0bcfbfa5a`); they load its definitions, not its test suite. The selected coupling is `tectonics/optimisation/pending/pressure/c/full3/src/atlas_tectonics/integration_pressure_coupling.py`, SHA256 `7c2c3b992d7e0267ed4da70dc5f6ba1bc557f3a2105369ca2b2abefa4e52d05e`. Vector definitions are `tectonics/optimisation/composed-r2/src/atlas_tectonics/integration_volume_overlap.py`, SHA256 `96f3921c2b7a8369f230dd362a28552d1f21179a5605fb183f01cfc075e68f48`. Source identity was freshly checked. The retained original evidence identities remain unchanged; publication-only JSON line-ending changes have separate byte identities.

## Same point and squared radius

Coupling `_radial_chart_jets`, lines414–441, calculates `radius2(closest)`, then `radius2(left)`, then `radius2(right)`. Each builds the same exact affine point when its argument is identical. The source then computes `_sqrt(square[0],bits)[0]` followed by `_sqrt(square[1],bits)[1]`. Identical squared radii at the same bits produce the same complete square-root bound pair.

The prototype evaluates each expression on first encounter at its original source location and retains the immutable result only until this invocation ends. It keys by exact value and type, and includes bits for square roots. The first-occurrence expression and its evaluation order are unchanged. Removing the AST wrappers exactly restores the original function. Supported exact inputs are built-in int/Fraction; unsupported key types evaluate the original operation without reuse. Stateful/custom arithmetic is not an optimisation claim.

For three-dimensional vectors, each skipped `radius2` removes6 rational multiplications and6 additions:3 multiplications/additions constructing the point and3 multiplications/additions in the dot product, whose `sum` starts with `Fraction(0)`. Each skipped `_sqrt` removes one complete original exact bound construction, including its integer square root and associated integer/Fraction work; no timing conversion is inferred.

| Case | Actual radius evaluations | Actual sqrt evaluations | Saved arithmetic per call |
| --- | --- | --- | --- |
| Successful midpoint, all three t equal |3→1 |2→1 |12 rational multiplies +12 adds +1 exact sqrt-bound construction |
| Closest equals one boundary, distinct boundaries |3→2 |Usually2→2 |6 rational multiplies +6 adds |
| Interior closest, all t distinct |3→3 |Usually2→2 |None from point reuse |
| Stationary chart, distinct boundaries |3→2 |2→1 |6 rational multiplies +6 adds +1 sqrt-bound construction |

The stationary case deliberately does not recognise distinct t with equal positions; that would be a further transformation. Squared-radius equality can still share its sqrt. At midpoint the original clamp makes `closest==left==right`, regardless of dd, so successful exact-rational midpoint calls have this opportunity. At an origin midpoint,3→1 radius calculations still preserve the original refusal, and neither version reaches sqrt.

The immutable results have no cross-call lifetime. The generic test memo holds at most3 radius results and2 complete sqrt result pairs, plus keys; this is a fixed count, not a fixed byte bound for arbitrarily wide rationals. Production should favour simple call-local slots/branches if their overhead is lower; that engineering choice is unmeasured. First evaluation pays unchanged arithmetic, and reuse breaks even in primitive counts on the second matching expression within the same call. Key comparisons, slots, closures/dictionaries and extra temporary references have overhead. No global or integration-wide cache is proposed.

## Existing inverse pair

At line428 the chart obtains `inv_s = _divide(_ONE,s)`. It constructs `s_jet` with exactly `s` as component0, then calls `_jet_reciprocal(s_jet)` at433. In `_jet_reciprocal` beginning at374, the nonconstant branch at377 repeats `_divide(_ONE,a[0])`: same numerator, same exact interval. Reusing `inv_s` at that one chart call removes one `_divide`, hence2 rational endpoint divisions, interval-zero checking and min/max selection. All subsequent reciprocal derivative operations and rounding retain their original order and inputs.

The companion transforms only this chart call to a chart-local reciprocal helper with supplied `inv_s`, and only that helper's nonconstant division expression to the supplied pair. Reversible AST checks preserve the rest of both functions. The constant fast branch stays first and ignores the supplied pair entirely; its original `1/a[0][0]` remains. Therefore constant exact charts save0 extra divisions, not2. Origin refusal and the first `_divide` refusal remain at their original sites. This is not permission to let general `_jet_reciprocal` callers supply arbitrary inverses, skip zero guards globally, or pass a rounded/changed interval.

This reuse aliases an already-live immutable pair within the same chart; it creates no new retained rational values. It chiefly benefits the full-jet path. A value-only midpoint implementation may already have eliminated the duplicate reciprocal through derivative removal, so do not add this saving twice when combining candidates.

## Checks and limits

`chart_point_probe.py` passed18 complete chart comparisons (14 values,4 identical refusals) and18 comparisons of the unchanged radius-bound prefix required by a value-only chart (14 values,4 identical refusals). Inputs cover midpoint, boundary/interior closest, stationary exact/nonexact radii, non-dyadic and128-bit-scale rational values, origin crossing/point refusal, at32/96 bits. Complete full-jet outputs include the `_RadialJet.expression` witness. Controls verify fresh per-call memo, origin refusal before sqrt, uncached first sqrt failure, precision separation and detection of an intentionally corrupted reused sqrt pair. The prefix test supports applicability after derivative removal; it is not a combined midpoint candidate integration proof.

`chart_point_reciprocal_probe.py` passed10 full-output comparisons (8 values,2 identical origin refusals), at32/96 bits. Nonconstant midpoint/interval/stationary-irrational charts showed `_divide` calls2→1. Constant-exact charts remained1→1 and refused charts0→0. Separate controls confirmed that the constant branch ignores an unusable supplied object and an injected original first-division failure remains identical. Result: `chart_point_reciprocal_result.json`. Native Ruff F821/F841/B905 passed both new helpers.

These were bounded local synthetic arithmetic controls using the utility interpreter, with source functions extracted by AST. No production imports, pressure stage, workers, timing or actual-capture replay occurred. The prior216/36 invariant suite was not rerun. Exceptions during original arithmetic propagate; the local memo dies with the invocation, and no failed result is stored. The production caller's existing `V._work` spans callback arithmetic, but changed scratch bounds still require review for wide operands; temporal locality alone is not a resource-accounting proof.

Recommendation: combine same-point/same-square reuse with the value-only midpoint work after source integration and exact-output checks; consider local inverse reuse separately for remaining full-jet calls. Actual survey counts can establish affected call distribution. Keep IV timing claims withheld until a correctly admitted measured comparison exists.
