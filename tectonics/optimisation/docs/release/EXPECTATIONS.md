# Changed test expectations between remake and composed-r2 (I03-I05)

16 Oct 2026, 17:40. Written for the coordinator to put to Michael, batched. This document is read-only: nothing was run or edited.

**Inputs**
- remake `tectonics/tests` at 1a58e0b.
- The heat-repair test tree, `F/heat-repair-20261007/source/tectonics/tests`. These are the tests that go with composed-r2.
- Codex's fidelity source, F0. This shows where each change entered.
- `T/rm/reconcile/expect.py`, which lists every removed or added assertion. Its output is `expect.json`.
- The coordinator's 4 Oct review of Codex's fixes. Its findings and their checks are in `.atlas-dev/review-probes/codex-fixes-20261004/wfB-results.json`; the relevant finding is MS-4.

## 0. Summary

**How many tests changed, and where.**
- 15 test files differ.
- 14 of them changed in Codex's fidelity source (4 Oct). The other one, `test_source_inventory`, changed in the heat repair and is an inventory test.
- 5 of the 15 only add assertions: `test_constitutive_r3`, `test_digest_line_endings`, `test_i03_bridges`, `test_i05_ledger` and `test_source_inventory`. These add obligations; none is removed.
- The other 10 change an existing expectation (§1).

**No tolerance or numerical bound was widened.**
- The coordinator's 4 Oct review found this (MS-4, CONFIRMED, "no tolerance changed").
- The script found the same today: no removed assertion carries a looser number.

**One change is stricter.** Two I03 equivalence tests that were marked as expected failures now pass, with the original bound and no extra slack (E3).

**The others are method changes from three repairs in Codex's fidelity source:**
- (A) supplied overlap rows are re-checked against the code that produced them;
- (B) material position records (support) and density provenance;
- (C) the stored per-column temperature and heat record (moving state v3).

Plus one approximation that is now opt-in (D). Each changes a refusal path, an identity, or how an exact quantity is represented. None changes a certified bound.

**What Michael is asked to accept.** These four method changes, A-D, as a batch. Three items deserve his eye: E4 (the merger tie-break), E6 (a declaration that is now refused) and E10 (the I04 feedback control now runs on the approximation).

**Effect on landing.**
- No current receipt is affected: none of the 37 current records covers I03, I04 or I05.
- States saved under remake will still open, as legacy records. Their state IDs differ from composed-r2's. A remake-made I05 moving state can be inspected but not continued, because it has no recorded per-column temperatures.
- This fits R2 (fresh runs).
- U2 cannot land until Michael accepts this batch.

**What "approved" means here.** All four changes entered in Codex's fidelity source on 4 Oct. The coordinator reviewed them that day (finding MS-4 and the I05 heat claim, both CONFIRMED, neither blocking promotion). They then travelled through heat-repair, composed-r1 and composed-r2 under Michael's programme. **I found no record of Michael accepting these particular method changes.** That is the purpose of this document.

## 1. Each changed expectation

Opt-in key: "No" means default behaviour; "Yes" means callers must ask for it.

### Group A: supplied overlap rows are re-checked against their producer

Overlap rows that come from a prepared map or from storage are now recomputed and must match exactly. Source: `integration_transfer.py` (S, about lines 3009-3018) and the I03_SPHERICAL_NETWORK.md paragraph beginning "The old numerical overlap rows remain candidate indices".

**E1. test_i03_transfer, PreparedMapTests (forged prepared rows)** (opt-in: No)
- Old expectation: refused with 'do not occupy' (the face-occupancy check), code UNRESOLVED_OVERLAP.
- New expectation: refused earlier with 'stored map rows do not reproduce their declared geometry producer', same code.
- Magnitude: no number changes.
  - A forged row is now refused before the face-occupancy check is reached.
  - That check is still tested at `test_i03_frames` 245/405 (MS-4).
  - Cost: replay and reuse now recompute the rows, which is bounded extra work at restart.

**E2. test_i03_thin_faces, sliver refusal** (opt-in: No)
- Old expectation: 'do not occupy'.
- New expectation: 'do not occupy' or the producer message.
- Magnitude: the refusal deadline (`refused_by_step`) is unchanged.

### Group B: material position records (support) and density provenance

**E3. test_i03_equivalence, two consumption tests** (opt-in: No)
- Old expectation: `@expectedFailure`. Observed differences reached up to 23.5 times the C7 bound (2.35e-11 relative), and the coordinator approved keeping them as known failures on 3 Oct.
- New expectation: both are normal tests and pass.
- Cause: exact rigid-sweep displacement (4 Oct).
- Magnitude: same bound, zero extra slack, so this is **stricter**.
  - With the precise map disabled, the tests fail (2,442,133,504 > 1,035,430,877.98 J; 25,438,453,760 > 2,070,861,755.93 J), so they still detect errors (MS-4).

**E4. test_i03_events, merger tie** (opt-in: No)
- Old expectation: the exact area account of the north plate exceeds the south plate's, and the merged plate takes north's rotation.
- New expectation: the exact accounts differ but their binary64 totals tie. The merged plate takes the rotation of whichever plate has the larger exact account (summed from the recorded piece areas).
- Magnitude: the original run's difference was +3/1024 m², below one unit in the last place (ulp) of the plate area. The measured areas still tie (p3).
- **For Michael:** this is a law choice for ties smaller than one ulp. It is deterministic and follows the recorded accounts.

**E5. test_i03_history_split, identities** (opt-in: No)
- Old expectation: motion, map and successor state IDs equal the 4 Oct baseline bit for bit.
- New expectation: the motion and map IDs are still equal. The state ID now differs, because the schema is `atlas.i03-sphere-material.v3`. A restore round trip keeps the ID.
- Magnitude: identity only; the numbers are unchanged.
  - MS-4 advised recording the new state ID as a successor rather than rewriting the old baseline. Recommend doing that at landing.

**E6. test_i03_network, declared pieces** (opt-in: No)
- Old expectation: rebuilding from the same pieces reproduces the material ID. Two cohorts sharing a face are accepted.
- New expectation, part 1: the stock arrays are identical. The ID matches only when the declared density is supplied; without it, the ID differs.
- New expectation, part 2: two cohorts sharing a face without explicit positions are refused with SupportError ('explicit material footprints'). A legacy restore still opens, with no position record.
- Magnitude: numbers identical; the identity changes and admission narrows.
- **For Michael:** an initial declaration that used to be accepted is now refused, rather than given invented positions.

**E7. test_i05_transport, balance** (opt-in: No)
- Old expectation: exact balance over the piece heat arrays. The relabelled split differs in 4 arrays.
- New expectation: exact balance over the patch heat. The rounding of the piece projection is its own exact residual (`_projection_rounding`). The split also differs in `sphere.material_support`.
- Magnitude: exact in both versions; no tolerance.

### Group C: moving state v3, stored per-column temperatures and heat

Source: I05_MOVING_STATE.md §15 (4 Oct).

**E8. test_i05_heat, `test_an_envelope_the_states_own_temperatures_refute_is_refused`** (opt-in: No)
- Old expectation: on the original warm/cold fixture, the end temperature contrast exceeds the start contrast for at least one contact. The envelope checks (start, end, nextafter, zero) refuse.
- New expectation: on the original fixture the contrast does not grow (asserted). A separate fixture, a warm column over a hot base (+50 K) beside a cold insulated column, now supplies the growth. The start/end/zero refusal checks and the passing case are byte-identical (wfB claim CONFIRMED).
- Magnitude: the old "growth" was rebuilding round-off of at most **9.09e-13 K** (§15), on a 175 K start contrast. The check bound is exact (nextafter), which is why round-off alone used to satisfy it.
- Evidence: `fidelity-20261004/i05-physical-r2/r3/r4.json` (r2 and r3 fail as expected on the old fixture; r4 PASS).

**E9. test_i05_properties, fixture and corrupt-density case** (opt-in: Yes for P1, No for the refusal)
- Old expectation: the fixture issues moving heat per piece. A corrupt 30-epsilon density state can be advanced.
- New expectation: the fixture writes patch heat explicitly. P1 asks for `allow_cell_mean=True`. The corrupt state is refused ('reference mass') when a physical field is supplied.
- Magnitude: refusal and opt-in changes only.

### Group D: the cell-mean approximation is now opt-in

**E10. test_i04_feedback, P1 columns** (opt-in: Yes)
- Old expectation: `moving_columns(...)` used the default route.
- New expectation: `moving_columns(..., allow_cell_mean=True)`, so the I04 feedback control exercises the labelled cell-mean approximation. The default route refuses it and is tested in `test_i05_material_trace`. Documented in I04_I05_PORTS.md (`allow_cell_mean`).
- Magnitude: no numbers change, but the control now runs on the approximation.
- **For Michael:** I04 coupled feedback is controlled on the approximation, not on the exact trace (MS-4 asked for this to be stated in the docs).

## 2. Recommendation

Accept A-D as one batch. Each is either stricter, a refusal that happens earlier, an identity that now records more, or an approximation that is now explicit, and none widens a bound.

Two conditions at landing:
- E5's new state ID is recorded as a successor observation; the old baseline is never edited.
- E10's approximation is stated where I04 feedback controls are described.

If Michael rejects E4 or E6, the fix belongs in Codex's fidelity line before U2. It cannot be done by editing the tests.

## 3. Decision

**Michael ACCEPTED batch A-D (E1-E10) on 16 Oct 2026 at about 17:53, "as long as it doesn't lose accuracy".** The coordinator
relayed it; recorded here at 17:53.

Landing conditions:
1. U2 re-runs `rm/reconcile/expect.py` at landing. It refuses to land if any assertion's bound is looser than remake's.
2. E5's new state ID is recorded as a successor observation. The old baseline is never edited.
3. E10's approximation is stated wherever the I04 feedback controls are described.

What this does and does not unblock:
- It unblocks U2 on the expectations side only.
- U1 and U2 still wait for X1 + R1 and for Michael's word on the merge itself.
