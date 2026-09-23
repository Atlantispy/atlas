# W06 Step 2 — conservative birth/spreading evidence

22 September 2026. **WORKING NON-CANON; bounded prescribed-motion verification**.
Implementation: [model/API](../docs/W06_BIRTH.md),
[frozen case](../cases/w06_spreading.json),
[machine-readable timing and source hashes](w06-birth-timing.json).
The original Step-1 design remains unchanged and hash-bound.

## Outcome

Constant-velocity ridge accretion is implemented with continuous formation-age
histories, conservative cell means, distinct finite crust/mantle feeds, direct
boundary exports and immutable source-verified state. The selected initially
empty planar case passes its material/motion gates. This is Step 2, not complete
W06 acceptance, predicted breakup/melting or empirical terrain validation.

At 20 Myr the case creates 800 km of material per 1 m of strike: crust mass
1.624e13 kg and mantle mass 2.4552e14 kg. Both ledgers have zero residual for this
case. Remaining feed is 3.76e12 kg crust and 5.448e13 kg mantle. The smaller
200 km source window independently accounts for the material exported on both
sides; it does not discard that material or alter the common interior history.

## Focused verification

- 11 W06 tests pass across the original run and two corrected-assertion reruns.
  The original run took 25.069 s: nine passed, two failed in test normalisation,
  not production. The two corrected tests passed in 0.405 s. No full-suite rerun.
- Three grids (1,000/500/250 m), 0/5/10/20 Myr outputs and a partial-cell endpoint;
  nonuniform cells and a cell straddling the ridge; independent birth-time moments;
  finite-feed exhaustion and exact exhaustion endpoint; explicit exports and
  larger domain; constant asymmetry/migration and translated/moving-frame check.
- 32/64/128 requested partitions give bit-identical final geometry/accounts and
  identical full strips; parent/state identities still record the chosen sequence.
  Zero/repeated endpoints, the unchanged 256 interval ceiling, immutable views,
  cancellation, budget, closed/foreign state and live-source refusals pass.
- Nine shared execution-identity checks pass in 1.641 s. This covers the new
  module's integration with source/live-callable identity protection.
- Mandatory static safety: 13 source maps / 41 paths PASS; 30 tests PASS,
  one Windows symlink-creation skip (31 reported, 0.106 s). These are not physics
  tests or evidence of Linux execution.

The corrected assertions divide each independent birth moment by its own
occupied width, and compare signed near-zero balance residuals against the
established mass-scale roundoff allowance rather than relative to zero. The
original 1e-7 m geometry, 1 s age and W02 128-epsilon mass tolerances are unchanged.

## Measured performance

Windows 11, Python 3.12.14, NumPy 2.4.6; four outputs on 4,000 cells, two phases,
three repetitions, thread counts fixed to one. Import time is excluded. The
production path and independently implemented scalar reference return the same
width/youngest-age/oldest-age fields within the frozen gates.

| Scope | Median time | Saving |
| --- | ---: | ---: |
| Independent scalar geometry, four outputs | 0.017475400 s | baseline |
| Vectorised geometry, same four outputs | 0.000484100 s | 0.016991300 s / **97.23%** (36.10x) |
| Complete prepared sequence, including new plan/context, protected outputs, thickness projections and accounts | 0.459981000 s | no matched end-to-end baseline claimed |
| Repeated endpoint, including state/source validation | 0.021219200 s | in-memory reuse; no persistent-cache saving claimed |

Maximum differences from the independent reference: width 3.96199e-11 m and
age 0.0625 s over 20 Myr. These are numerical comparison errors, not real-world
geological accuracy. Accounted peak work reservation is 8,680,576 bytes, including
6,721,664 bytes of explicit caller allowance; final reservation is zero. This is
not measured process RAM. Required source validation dominates the protected
sequence at this small scale and has not been bypassed for a timing result.

The 97.23% is a **kernel comparison against a scalar reference**, not a measured
speedup over a previous production W06 implementation or the whole generator.
No reason to add disk caching/process parallelism to this sub-millisecond kernel.
Later recoverable workflow work can reuse protected complete results.

## Reproduce and continue

```powershell
$env:PYTHONPATH='tectonics/src;tectonics/tests'
python -B -m unittest test_w06_spreading -v
python -B -m unittest test_execution_reuse.IdentityTests -v
python -B tectonics/tools/benchmark_w06_spreading.py --output w06-birth-timing.json
python -B tools/check_coding_safety.py
python -B -m unittest discover -s tests -p test_coding_safety.py -v
```

Scientific-environment commands above were executed natively on Windows, with
the actual two failing-test reruns scoped to their method names. No Linux runtime,
full generator, whole-Diadem, R4.4, persistent W06 cache or thermal simulation was
run. Research/software checked are listed in [the implementation note](../docs/W06_BIRTH.md#researchsoftware-checked-for-this-implementation).
Next is Step 3 cooling and inherited passive-margin history; changing motion
and durable combined acceptance remain their subsequent planned steps.
