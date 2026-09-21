# R4.4 dev40 bounded numerical and assessment evidence

21 September 2026. WORKING NON-CANON. Local review candidate based on
`7aacee7661a96ce35f78dfe61ec5228801ba44dc` (dev39).
**Full benchmark accepted: false. R4.4/R4: IN_PROGRESS.**

## Scope and provenance

New Windows experiments use Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1,
Numba 0.65.1 and single native threads. They are not bitwise reproductions of
the earlier Linux environment. The input endpoint archive SHA-256 is
`870fc3e46fb9d0b02fb50f239f686eb14190d671495da053152ee3951be169a1`.
Original runs and checkpoints are unchanged. Re-equilibration probes start new
declared states from the supplied temperature, not forged historical continuations.

Each retained local experiment declares its input, script and source hashes and
keeps state/balance evidence. Numerical probes preceded the final version and
assessment edits: their original source bindings have NOT been relabelled as
final dev40 continuation evidence. The final focused tests exercise the final
candidate. Large input/trajectory archives are not duplicated into this repository;
the local engineering handover identifies their locations. These digest references
identify evidence but do not claim the archives are distributed with this document.

## Frozen-field spatial isolation

A boundary-compatible sin(z)/cos(x) interpolant matches the original cell integrals,
then is integrated over 32, 64 and 128 cells per direction. It does not invent
resolved physical information. Mechanics and the registered nearest-row diagnostic
are otherwise unchanged. The probe does not evolve each mesh to its own equilibrium.

| Mesh | Domain RMS velocity | Surface RMS velocity | Maximum surface velocity |
| --- | ---: | ---: | ---: |
| 32 | 253.877702466415 | 2.007485658625 | 2.796617283948 |
| 64 | 251.185847863429 | 1.908572931401 | 2.659875304052 |
| 128 | 250.520551324295 | 1.884126374052 | 2.626114481682 |

All three velocity measures enter the existing reference bounds on the finer
meshes. This supports a spatial-error explanation, **not** full coupled acceptance:
the inherited fine-grid bottom heat flux is outside its reference bounds.
Quadratic free-slip surface reconstruction alone changes the 32-grid RMS from
2.007485658625 to 1.996201428832, insufficient to explain the discrepancy.

Original summary digest:
`a0bd553389c2b5eedf3df4423671d0363d443808161f735a5ceabf41727471de`.
Reported elapsed times 1.6703752, 0.2889686 and 0.5529345 s include preparation/
compilation as encountered and are NOT matched performance comparisons.

## Corrected wall reconstruction and timestep isolation

The former zero normal slope in wall-adjacent temperature cells gives a face error
of h/2 for a linear profile: 0.015625 on 32 cells. The reflected-wall, wall-capped
MC correction reproduces that linear profile exactly without changing the bound.
At the same new elapsed nondimensional time 0.001:

| Configuration | Domain RMS | Surface RMS | Bottom Nu |
| --- | ---: | ---: | ---: |
| Original 32, dt=1e-5 | 253.877881052771 | 2.007485426773 | 3.393288746740 |
| Corrected 32, dt=1e-5 | 250.669522765962 | 2.002951728230 | 3.286175683576 |
| Corrected 32, dt=5e-6 | 250.670105874154 | 2.002948305996 | 3.286182587133 |
| Corrected 32, dt=2.5e-6 | 250.670303053183 | 2.002947474114 | 3.286183091125 |
| Corrected 64, dt=5e-6 | 247.115670042032 | 1.904862181837 | 3.395080906712 |

Across the ten registered diagnostics, the largest full-to-quarter timestep change
is 0.0003112803%; half-to-quarter is 0.0000786607%. These are short-transient results,
not mature timestep adequacy. The 64-grid domain RMS remains below its reference
lower bound; the correction has not manufactured an all-diagnostic pass.

The original/corrected 32-grid dt=1e-5 probes stop cooperatively at their 180 s
limits, preserving 924/903 accepted steps. The finer-timestep probes complete
200 steps in 43.2806704 s and 400 in 83.5704772 s. The corrected 64-grid probe
completes 200 steps in 66.2303171 s. Independent probes overlapped; these times
are not a matched speed benchmark or a prediction of a mature campaign cost.

Retained result digests, in the table's configuration order:

- `f75cf8dffeb3e56413d88baaa0acf4d5d07f87a7a70c17df2c0b49b019a080e5`
- `2e452e547e6ee7949ba75f8d6562114754493be12011835217a43c998fedc659`
- `599185995998c0e57e62698051386edb6b43dce9acee5f3195cd2f95dc741a6d`
- `cecf47bc784c0a57bf88f580ab60c93e9213923ce7b4de0a4457289173a6e7d4`
- `1aafd2994f90acaa66e4d8c864d5f36a2b69d15b49333c5177d09d91e428749c`

## Algorithm candidate not promoted

A separate static experiment evaluates the same spectral temperature interpolant
at stress supports before forming viscosity. On 32/64/128 meshes, domain RMS is
251.708631771189 / 250.546940610935 / 250.357651884173 and surface RMS is
2.005969425524 / 1.908178033332 / 1.884027789365. Compared with the frozen-field
baseline, the 32-to-128 domain-RMS spread shrinks 59.76%, but the surface-RMS spread
shrinks only 1.15%. This is not a measured absolute-error reduction. It is insufficient
evidence to replace the general nonlinear constitutive route; production is unchanged.
Result digest: `deca8538290e32367cc359c5aee660c168543fb512841b5db8834378a253c545`.

## Focused verification and limits

The boundary implementation passed 47 distinct focused reconstruction, diffusion,
transport, conservation and independent ODE checks. Independent review found no
blocker in its boundedness/sign/unit argument. Four analytic frozen-field/surface
tests and existing quadrature checks also passed. These are component results,
not the historical 2,502-test suite being relabelled as a fresh full regression.

Final combined source checks passed 71 numerical/workflow tests: the new assessment,
schedule and probe modules; TemporalScreeningTests; AnalysisPolicyTests;
SuiteAcceptanceTests; FixedWallStep; and fresh-process driver recovery. The first
command used the wrong module name for SuiteAcceptanceTests: 65 actual tests passed
in 13.388 s plus one loader error. Running that class from its correct workflow
module passed its six tests in 0.088 s; no numerical test failed or was skipped.
After the reference narrative correction, the affected assessment, schedule,
analysis and suite-acceptance selection was rerun: 45 passed in 0.330 s. These
overlap the 71 above and must not be counted as additional distinct tests.

`tools/check_coding_safety.py` passed (13 selected maps, 41 required paths).
The prescribed `python -B -m unittest discover -s tests -p test_coding_safety.py -q`
passed 30 static checks in 0.116 s, with one Windows test-symlink creation skip.
An earlier unnecessary `-I` invocation could not import the repository's `tools`;
the documented non-isolated static command resolved that invocation error.
`git diff --check` passed. No mature coupled campaign, full regression or complete
visual acceptance was performed. No measured solver speed improvement is claimed.

## Reference context

[Tosi et al. (2015), original benchmark](https://www.ipgp.fr/~samuel/henriIPGP/Publications_files/Tosi_2015-1.pdf)
provides the comparison equations, numerical values and resolution context; the
published ranges are not statistical confidence intervals. Existing registered
acceptance tolerances remain unchanged. Known case-5 reference questions remain
explicit blockers rather than guessed targets.

The original PDF p.4, equations (20)-(21), distinguishes raw dissipation from
dissipation/Ra, but p.9 Table 2 omits `/Ra` from the case-5a extrema labels.
Whether those entries were divided by Ra=100 is still unresolved; magnitude alone
does not authenticate the interpretation. Case 5b requires both minimum and maximum
surface Nu averaged over ten cycles (or surface Nu for steady states), not only
mean peaks. The specification's narrative was corrected accordingly; computed
extrema and numerical thresholds already retain both channels. PDF p.17 section
5.4 points to supplementary Tables S14-S23 for exact reference values. The publisher
supplement was inaccessible (HTTP 403), so those targets remain null, not inferred
from the reported regime-transition ranges.

[SciPy 1.18 release notes](https://docs.scipy.org/doc/scipy/release/1.18.0-notes.html)
document the FFT backend change. The existing runtime authenticates pocketfft;
declaring SciPy `<1.18` avoids advertising an unsupported backend without bypassing
the binary checks. Isolated installation uses `--no-cache-dir` where the package
cache directory is not writable; no global runtime or user package was changed.
