# Plan40A: repeated-operand products and exact negation

Historical source/prototype analysis. Current implementation selection, measurements and resource qualification are in [FINDINGS.md](FINDINGS.md) and [the receiving implementation](implementation/README.md). Statements below about proposed work or unproved production contracts describe this earlier evidence, not the current selection. This public copy removes local coordination and paths; it does not authenticate a rerun.

Working examination evidence, not a production patch or measured speedup.

## Result and disposition

**Useful secondary arithmetic batch, ready for a precisely scoped implementation.** A nonconstant jet multiplied by itself computes two pairs of identical interval products in the first and second derivatives. Reusing each first product removes two of the six interval multiplications (33.3%) for that eligible jet operation. The original additions, scaling and final outward rounding remain in their original association. Eligibility is operand identity plus the exact built-in rational domain, not an equality scan or an inference from equal interval endpoints.

The selected chart explicitly evaluates `inverse * inverse`; the shell primitive evaluates `r * r` and `square_jet * square_jet`; nonconstant left-fold powers reach a repeated operand at their first multiplication. This is therefore source-reachable. Constant jets keep both original constant tests and return precedence. Distinct but equal jets, mixed endpoints and unsupported containers retain the reference route.

An additional exact `_scale(pair, -1)` case uses `(-hi, -lo)` for ordered built-in Fraction pairs. This replaces two Fraction multiplications/normalisations with two negations. Floats (including signed zeros), subclasses, reversed intervals and other iterables retain the original function. Full `_jet_outward` calls remain: sign reversal is not permission to skip rounding.

## Evidence

`self_product_probe.py` loads complete selected AST definitions through the hash-bound `arithmetic_probe.py` helper; neither imports the scientific package nor runs a stage. Source hashes are recorded in `self-product-result-r2.json`. The result binds the exact probe and helper bytes.

| Workload | Reference | Candidate | Change | Evidence status |
|---|---:|---:|---:|---|
| 36 synthetic chart/shell calls, interval multiplications | 2,160 | 2,064 | -96 (-4.44%) | Operation count, exact complete-output parity |
| Same calls, general interval scale calls | 753 | 555 plus 198 exact negations | -198 general scales (-26.29%); 396 rational multiplications replaced by negation | Operation count, not elapsed time |
| Same calls, interval additions | 882 | 882 | 0 | Original association retained |
| Same calls, outward-rounded pairs | 1,161 | 1,161 | 0 | Original rounding retained |

The 36 consumer calls cover 9 full charts and 27 shells at 32/96/160 bits, including intervals, midpoints, clamped and empty shells. Complete jet tuples, radial expression metadata and fixed flags match. Primitive controls cover 220 same-operand cases, 220 distinct-equal cases, 660 power calls, 220 reciprocal/refusal calls and 18 scale-domain cases, with precisions 8/32/96/160. Deliberately substituting the wrong final second-derivative term fails with exit1 and creates no success artifact (private negative-control log omitted). Optimised Python invocation is refused before work/output; native Ruff on the final probe found no selected-rule findings.

An important rejected shortcut is retained: the reference interval product `[-1,1]*[-1,1]` is `[-1,1]`. Replacing it with the tighter mathematical square `[0,1]` changes the numerical record. The prototype retains the general interval product, including this dependency overestimate.

## Integration obligations and limits

No cache crosses an invocation. Drop the first-derivative temporary after its original addition; keep the second-derivative reuse local to its expression. Existing callback admission must remain active. The prototype is not a proof of production scratch bounds, cancellation, accounting or exception-lifetime behaviour; qualify the exact implementation at those boundaries. In particular, fewer allocations do not justify removing an existing admission check. Generic fallback in this prototype repeats the constant predicates, so branch/guard costs must be measured before selection.

The observed 4.44% multiplication reduction in this deliberately small consumer set is a secondary opportunity, not evidence for a large pressure-stage improvement. It overlaps the midpoint value-only and power-prefix candidates: those remove some operations on which this shortcut would act. Apply it to the remaining arithmetic and measure the combination; do not add the percentages. No actual stage applicability fraction, timing, production memory reduction or whole-IV saving is established here.

The unversioned predecessor result and negative-control log are retained privately and omitted from this package. Revision2 shortens an unnecessary first-derivative temporary lifetime and avoids retaining the middle term in a local; only the affected small probe and deliberate wrong-term control were rerun.
