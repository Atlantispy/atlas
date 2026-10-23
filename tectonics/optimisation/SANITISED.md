# Sanitised files

Plans19–20 have explicit original/public digest maps in
[Plan19](workbench/plan19/SOURCE-MAP.json), [Plan20](workbench/plan20/SOURCE-MAP.json)
and the [combined selection](workbench/plans19-20/SOURCE-MAP.json).
The two geometry modules are unchanged exports of accepted bytes. Capture exports
redact private prose and substitute an explicit unavailable native-library path;
the library hash stays unchanged and no binary is included. Existing guards are
not repinned. These are new publication identities, not a runnable historical
profile or evidence of the pending package fold.

The Plan02 map in
[workbench/plan02/SOURCE-MAP.json](workbench/plan02/SOURCE-MAP.json) preserves all
25 logical members and their original/public digests. Nine exact duplicate exports
now reference existing driver bytes through repository-relative `public_path`
values; no source bytes or identity hashes changed. The local `start_gate.py`
copy remains because retained Plan02 modules import it as a sibling.

Plans13–14 have a complete original/public digest trail in
[workbench/plans13-14/SOURCE-MAP.json](workbench/plans13-14/SOURCE-MAP.json).
Existing exact public files are referenced. New files redact private home paths,
room references and the retained owner-name constant, use LF and remove trailing
empty lines. Scientific literals and historical identity pins are unchanged;
public bytes do not authenticate private execution. Retained results are a new
summary, not a modified execution receipt.

The Plans10–12 complete selected source map and original/public digest trail are in
[workbench/plans10-12/SOURCE-MAP.json](workbench/plans10-12/SOURCE-MAP.json).
Existing identical public bytes are referenced, preserving one-copy source storage.
The new result summary is not an execution receipt; historical runtime pins remain unchanged.

The Plan05 export has its complete original/public digest trail in
[workbench/plan05/SOURCE-MAP.json](workbench/plan05/SOURCE-MAP.json).
Only the declared source/publication transformations are applied; original
execution pins and private evidence are unchanged. New public summaries are
labelled summaries, not sanitised execution receipts.

The Plan04 successor export has its complete original/public digest and
transformation trail in [workbench/plan04/SOURCE-MAP.json](workbench/plan04/SOURCE-MAP.json).
It additionally replaces the private owner-name constant with `OWNER` and
removes private room references. The 371-file table below describes the
earlier snapshot only; original execution pins remain unchanged.

Local user-profile paths had the user segment replaced with `LOCAL_USER`, and a contact email address was replaced
with `<owner-email>`. Nothing else was changed. These files no longer match the hashes pinned in
`composed-r2/composition.json` or in run records, so a pinned identity check refuses them without the private
originals. Sanitised bytes do not authenticate historical runs.

371 files.

| File | Original SHA-256 | Staged SHA-256 | Replacements |
|---|---|---|---|
| `composed-r2/composition.json` | `cec91b9332b6aa4a…` | `5d10c1e06c6f16a2…` | 1 |
| `composed-r2/helpers/private_heat_decimal_inventory_r1.py` | `ded95d895acd84dc…` | `395c9346cb4924bd…` | 1 |
| `composed-r2/helpers/private_heat_geometry_inventory_r1.py` | `55216dd545f51bc6…` | `bfeba9cad3656543…` | 1 |
| `composed-r2/helpers/private_heat_interval_inventory_r4.py` | `cc755dabf6ac9c6b…` | `fd8950872e1ce4d0…` | 1 |
| `composed-r2/helpers/private_heat_low_solver_kernel_r2.py` | `23395a2e31d25699…` | `dc3d12cef22885e6…` | 1 |
| `composed-r2/helpers/private_heat_low_solver_kernel_r5.py` | `8dd668fe93c80abf…` | `87c82197ac5f845d…` | 1 |
| `composed-r2/helpers/private_heat_original_continuation_r1.py` | `8b1b96badcd5e624…` | `3c9be487d8a41915…` | 1 |
| `composed-r2/helpers/private_heat_original_joined_r5.py` | `4d9b3c074305172e…` | `aae2faf34c70bfca…` | 2 |
| `composed-r2/helpers/private_heat_original_joined_r6.py` | `3e734cfda4f18b37…` | `33c4dcaaf85e44d4…` | 2 |
| `composed-r2/helpers/private_heat_original_joined_r7.py` | `d1bac8825c17e056…` | `074345bca0bf52af…` | 2 |
| `composed-r2/helpers/private_heat_original_joined_r8.py` | `e71837492f547794…` | `73d68106318ff04e…` | 2 |
| `composed-r2/helpers/private_heat_original_spatial_r1.py` | `abae4503f52e29a4…` | `159132a58ed74761…` | 1 |
| `composed-r2/helpers/step7_same_call_heat_control.py` | `91db76106dd18758…` | `5a242f6150cf229c…` | 1 |
| `composed-r2/helpers/test_cold_archive.py` | `e1a151ea666518ec…` | `8f45fc2fff6c9436…` | 2 |
| `composed-r2/helpers/test_r1a_export_booking.py` | `937811a9887da8ec…` | `ebb931776952fb41…` | 1 |
| `composed-r2/helpers/test_raw_sidecar_store.py` | `62c080d131922a01…` | `e45733bd6a3d3612…` | 2 |
| `composed-r2/helpers/test_storage_codec_patch.py` | `5529eb9cfd33c224…` | `84987a52816645bd…` | 2 |
| `docs/COMPACT_EVERYWHERE_PLAN.md` | `ea56c417fb48b269…` | `6d3c2ea592130577…` | 1 |
| `docs/release/LANGUAGES.md` | `3bb306283aae0476…` | `c65be163d8fedf25…` | 1 |
| `docs/release/RECONCILE.md` | `169dc2684c844935…` | `5a2095402b5091af…` | 1 |
| `docs/release/fold/refute/r05_bookings_userpaths.py` | `2c170116f17f8291…` | `9412000c535579fa…` | 3 |
| `docs/release/fold/refute/r30_held.py` | `408c175561c56606…` | `be2a45d12d311571…` | 3 |
| `docs/release/fold/run_trace.sh` | `0a4d0a2a1a9b7792…` | `f94ed7ae126894f3…` | 1 |
| `docs/release/fold/selftest.py` | `2710c4d3eac1a109…` | `028a6a0f8d62fbc4…` | 2 |
| `docs/release/reconcile/closure.py` | `c3c9903f22c8c4d0…` | `b737eed00a7efebb…` | 1 |
| `docs/release/reconcile/scan.py` | `7c59d3393a769844…` | `cf11c5fc46ca7bf0…` | 1 |
| `docs/release/reconcile/three.py` | `efb5f06558acf3f3…` | `3341866760ff2659…` | 2 |
| `docs/release/reconcile/trees.py` | `49566bbca3b0bba3…` | `4616095d77acb49c…` | 2 |
| `pending/geometry/ipw6-r1/INITPAR_MANIFEST.json` | `48c10f0dce167f14…` | `72849022ff1ef65f…` | 3 |
| `pending/heat/lf/helpers/private_heat_geometry_inventory_r1.py` | `864d6a8d0e3def07…` | `94d613cfa8114abd…` | 1 |
| `pending/heat/lf3/helpers/private_heat_geometry_inventory_r1.py` | `43d680cfa8cb0c38…` | `641161ebd51f137d…` | 1 |
| `pending/heat/rf-s1/rf_common.py` | `c3cd246d95fcda19…` | `3913b1b3b6df6954…` | 1 |
| `pending/heat/rf-s1/rf_variants.py` | `b423e149f0f7d85d…` | `18ba235e2525deb5…` | 1 |
| `pending/heat/scripts/heavy_lock.py` | `ff4b5586d566ac33…` | `872cbd6860428270…` | 1 |
| `pending/heat/scripts/job_h12.sh` | `99cc230e5b8c14c6…` | `3c6a1da8b89f21d9…` | 1 |
| `pending/heat/scripts/job_h1a.sh` | `4954d2db7f45752b…` | `1f46b54314dd7b14…` | 1 |
| `pending/heat/scripts/job_h1c.sh` | `2c9d616d6ebbd4c1…` | `125223fd2eb5a5b4…` | 1 |
| `pending/heat/scripts/job_h1c_r2.sh` | `05447d78a851b2c3…` | `da94ac307dfec217…` | 1 |
| `pending/heat/scripts/job_h1c_r3.sh` | `c702346033ed6718…` | `1e532628b2d5c858…` | 1 |
| `pending/heat/scripts/job_h1c_r4a.sh` | `c0ffada40a4099d0…` | `54c46bfbc15042e9…` | 1 |
| `pending/heat/scripts/job_h1c_r4b.sh` | `c133576264dce444…` | `6eb8739588e0b6b5…` | 1 |
| `pending/heat/scripts/job_h1c_r4c.sh` | `5101699619aa95ab…` | `2ed37e167703cd82…` | 1 |
| `pending/heat/scripts/job_h1c_r4c_r2.sh` | `12fa7955e8fd9926…` | `98ca48fd6e831af9…` | 1 |
| `pending/heat/scripts/job_h2.sh` | `465afe1803efadae…` | `041717ccd9e8e7df…` | 1 |
| `pending/heat/scripts/prep_lf.sh` | `3fc19f6ea260ad74…` | `46aa36d2a06bde8d…` | 1 |
| `pending/heat/scripts/prep_r2.sh` | `860530dfadbd61ae…` | `65e4f093d9f56ad5…` | 1 |
| `pending/heat/scripts/prep_r3.sh` | `7c9910cb7ac74a4f…` | `00be8dd8a9327859…` | 1 |
| `pending/heat/scripts/redo_l1_r2.sh` | `b620f05bb7f6599f…` | `dcf7e55c0caf2cd4…` | 1 |
| `pending/heat/scripts/run_locked.sh` | `24386e28f24491d0…` | `92b3b4a6a9a441b3…` | 1 |
| `pending/heat/scripts/run_r6_h5a_checks.sh` | `6452a4063ceb5c6d…` | `7f5e66dada2053ea…` | 1 |
| `pending/heat/scripts/run_r7_checks.sh` | `00c17b9676e9bf37…` | `12a51545fb08d394…` | 1 |
| `pending/heat/scripts/run_r7_r2_checks.sh` | `14d18f286f869940…` | `3a7f0373ac4352d0…` | 1 |
| `pending/heat/scripts/smoke_launch_r3.sh` | `875188df3e94fe25…` | `6e09348552b48c4c…` | 1 |
| `pending/heat/scripts/smoke_r2.sh` | `936e6db09529c1f7…` | `ed3c42f2bb55be0f…` | 1 |
| `pending/heat/scripts/smoke_r3.sh` | `de6e40891b8e9395…` | `ab0d3332e9da1ef3…` | 1 |
| `pending/heat/scripts/smoke_r4.sh` | `51ae79fb66f00298…` | `6c31ec99f49b2061…` | 1 |
| `pending/kernels/d5/bench.py` | `f06fe1c9a361f694…` | `fedbcbfdeab082b1…` | 1 |
| `pending/kernels/d5/capture.py` | `ca43e39e8750b612…` | `de1c8e871d2e6266…` | 1 |
| `pending/kernels/gpy-f2/TEST_COMPOSITION.json` | `c113dc830ed7d877…` | `6c9d51c64c9fec8c…` | 1 |
| `pending/kernels/gpy-jets/TEST_COMPOSITION.json` | `fdeb49a799932b85…` | `a784c71dc20df769…` | 1 |
| `pending/kernels/gpy-r1-backup/gpy-f2.TEST_COMPOSITION.json` | `be4bede55c43c7a2…` | `e9e90c3ffb9cd0ee…` | 1 |
| `pending/kernels/gpy-r1-backup/gpy-jets.TEST_COMPOSITION.json` | `7f90be08050a8e67…` | `e8ee8e8e28d1e3fc…` | 1 |
| `pending/kernels/gpy-r2-backup/gpy-f2.TEST_COMPOSITION.json` | `40b72659fe30405d…` | `c4d6f1e212dc8f98…` | 1 |
| `pending/kernels/gpy-r2-backup/gpy-jets.TEST_COMPOSITION.json` | `9ebca3ac9f3de0e1…` | `26c395f60936a978…` | 1 |
| `pending/kernels/gpy-r2-check/run.sh` | `ad7fa116506c58fc…` | `699dc77b3dd900b5…` | 1 |
| `pending/kernels/gpy-r3-check/run.sh` | `d1d8650ff350c0e0…` | `dcd82e1e57195bdd…` | 1 |
| `pending/kernels/h3/refute-r3/report.md` | `1b8a5b445e4e4998…` | `885f9238eb3f4920…` | 1 |
| `pending/kernels/initpar/ip8_r1_close_retry.py` | `a81dc5b2d709faa0…` | `d37444f30b7a30bd…` | 1 |
| `pending/kernels/initpar/ip8_r2_enclose_unfinished.py` | `92b542669a5bd8b5…` | `2a4cc90e69613326…` | 1 |
| `pending/kernels/ip2/INITPAR_MANIFEST.json` | `60813db7a1fa0cfa…` | `17efc87e104e4b21…` | 3 |
| `pending/kernels/ip3/INITPAR_MANIFEST.json` | `693b423484b8b94a…` | `4b3291a20dfee696…` | 3 |
| `pending/kernels/ip4/INITPAR_MANIFEST.json` | `47aa82d75beefc79…` | `b5adee892bff2a24…` | 3 |
| `pending/kernels/ip5/INITPAR_MANIFEST.json` | `b373d2a81013adcb…` | `255776f713a7e550…` | 3 |
| `pending/kernels/ip6/INITPAR_MANIFEST.json` | `c44eb4546252cc10…` | `b43cf290ae6cb497…` | 3 |
| `pending/kernels/ip7/INITPAR_MANIFEST.json` | `294900e5a18b49fc…` | `35b4ed6771bc6e6b…` | 3 |
| `pending/kernels/ip8/INITPAR_MANIFEST.json` | `4df2297923db448b…` | `daf8056af49b058f…` | 3 |
| `pending/kernels/ip9/INITPAR_MANIFEST.json` | `f53a01e091b6b249…` | `b80f6747e4859260…` | 3 |
| `pending/kernels/refuter-gpy/r2/sim_lists.py` | `c63a895ddfbe1a42…` | `0cb37ee40b7bc565…` | 1 |
| `pending/kernels/refuter-i19/r1_close_retry.py` | `d5a5193f85082c8f…` | `7d4a42080c0d2db5…` | 1 |
| `pending/kernels/refuter-i19/r2_enclose_unfinished.py` | `8fbc88509a07498c…` | `a9fb7a6eefaf16c5…` | 1 |
| `pending/kernels/refuter-i19/r3_requests.py` | `09c349964fa9aa0d…` | `18d0b657a2b323e1…` | 1 |
| `pending/kernels/refuter-r2/cancel_h3.py` | `013167fa057482d0…` | `ddefa943fb92b7bb…` | 3 |
| `pending/kernels/refuter-r2/fuzz_gram.py` | `2d9f12a3b76c8200…` | `cb154e4480181942…` | 1 |
| `pending/kernels/refuter-r2/fuzz_h3.py` | `f148152412776ed4…` | `14a7f41eb1191815…` | 3 |
| `pending/kernels/refuter/cancel_h3.py` | `3df7b4bbbb5dade2…` | `5ac7f4ab4052ff70…` | 3 |
| `pending/kernels/refuter/fuzz_gram.py` | `7dac355182266ae5…` | `32fa07f07715082d…` | 1 |
| `pending/kernels/refuter/fuzz_h3.py` | `d81f926b1d34ab12…` | `5e287b813ec348b0…` | 3 |
| `pending/kernels/refuter/imports_probe.py` | `19f331060096af1b…` | `298421ee1016cf41…` | 2 |
| `pending/kernels/refuter/latency_h3.py` | `4f5170d3aeb02d0f…` | `7888e8b407f91fe3…` | 2 |
| `pending/kernels/refuter/mem_h3.py` | `e2104a21e5136f21…` | `c6cc73157488ba78…` | 2 |
| `pending/kernels/refuter/mem_h3b.py` | `2d732322ed5327d6…` | `e888f80e42c07e86…` | 1 |
| `pending/kernels/refuter/mem_h3c.py` | `3af6fbe5db837e60…` | `c71cad99471cbf9b…` | 3 |
| `pending/kernels/refuter/probe_env.py` | `c59a8f78d263f575…` | `72d051ba7e5bcdeb…` | 1 |
| `pending/kernels/refuter/range_probe.py` | `08217654ecd3af1c…` | `78d6dc43b0d8d240…` | 2 |
| `pending/kernels/scripts/gpy_parity.sh` | `2a159f129a8df550…` | `3956b8a48c0060b6…` | 1 |
| `pending/kernels/scripts/gpy_parity_check.py` | `fc65d66ba24877da…` | `876617204ae7a990…` | 1 |
| `pending/kernels/scripts/gpy_parity_proof.py` | `d93938812acc9023…` | `c02793bccb320e9a…` | 1 |
| `pending/kernels/scripts/gpy_peak.sh` | `5671cf292a0dee73…` | `4864180e510ad161…` | 13 |
| `pending/kernels/scripts/gpy_rebuild_r2.py` | `c256f4a5f25ce729…` | `8c795d9fd21e4d06…` | 1 |
| `pending/kernels/scripts/gpy_rebuild_r3.py` | `53ed537e4c390b53…` | `862f9d99a0d164c5…` | 1 |
| `pending/kernels/scripts/heavy_lock.py` | `0c69c863f8680c79…` | `f377ef536f3fdc9b…` | 1 |
| `pending/kernels/scripts/job_h3.sh` | `6bee20dda56a02af…` | `24d40037b2acb2a8…` | 1 |
| `pending/kernels/scripts/job_h3r2.sh` | `c476046b4c2ea9bd…` | `2dd85cb8e5441f6c…` | 2 |
| `pending/kernels/scripts/job_initpar.sh` | `2283e332e9921e34…` | `f27df867ba959975…` | 1 |
| `pending/kernels/scripts/run_geo_profile.sh` | `5d57d787c1c6296f…` | `6d29cb6ea7edd779…` | 1 |
| `pending/kernels/scripts/run_locked.sh` | `8e2ea1892e9eac71…` | `cdc788a421f93fcb…` | 1 |
| `pending/kernels/scripts/run_w4_capture.sh` | `f904bffe405018bf…` | `e5756572a711a70a…` | 2 |
| `pending/pressure/c/full/PS_COMPOSITION.json` | `5c1e0745844976cb…` | `3450b36a3c1d7412…` | 1 |
| `pending/pressure/c/full2/PS_COMPOSITION.json` | `a494330c17bd62a5…` | `b4c6d4a57247c061…` | 1 |
| `pending/pressure/c/full3/PS_COMPOSITION.json` | `f46407debea146a3…` | `38ab48806bb633a8…` | 1 |
| `pending/pressure/c/full4/PS_COMPOSITION.json` | `7d3b3cedc3dd4217…` | `c9a75424a2fe1901…` | 1 |
| `pending/pressure/c/full5/PS_COMPOSITION.json` | `9403a3436efb24c0…` | `7c9d5ca49b364e8e…` | 1 |
| `pending/pressure/c/full6/PS_COMPOSITION.json` | `d61bde240c42989f…` | `88650949b4d0b521…` | 1 |
| `pending/pressure/c/null/PS_COMPOSITION.json` | `3ff69ddcf5aee322…` | `955f5d61be267e3c…` | 1 |
| `pending/pressure/c/p21/PS_COMPOSITION.json` | `120cab5a3c1e831b…` | `4aa9917d54610a45…` | 1 |
| `pending/pressure/c/w6f2/TEST_COMPOSITION.json` | `3b67574d03aabe05…` | `b81022fbb441cb25…` | 1 |
| `pending/pressure/c/w6f3/TEST_COMPOSITION.json` | `7acd9ce0813a5462…` | `de10f40b82cc803a…` | 1 |
| `pending/pressure/c/w6f4/TEST_COMPOSITION.json` | `a0e5fb4bc1f72e6f…` | `ce3af2f8518fcca7…` | 1 |
| `pending/pressure/c/w6f5/TEST_COMPOSITION.json` | `0c2e91764ca4efd9…` | `64a502b59319c0b4…` | 1 |
| `pending/pressure/c/w6full/TEST_COMPOSITION.json` | `4a1f68d8662b6959…` | `87e2bccaeadb4697…` | 1 |
| `pending/pressure/refute/p1/transport_equiv.py` | `c81101a21111eafc…` | `3a3d6b5110464f92…` | 1 |
| `pending/pressure/refute/p1d/r1_transport_gate.py` | `0b51b460826749e0…` | `6dbc61f39c34c3ad…` | 1 |
| `pending/pressure/refute/p1d/r2_ownership.py` | `5110acf9d6184a4e…` | `e4131f04da0c354b…` | 1 |
| `pending/pressure/refute/p1d/r3_r5_costs.py` | `353be2e45ed4fc9f…` | `1c87594418dfb5cb…` | 1 |
| `pending/pressure/refute/p2/p2_equiv.py` | `3d76db976ed8b9be…` | `cf93a4bbd9efc011…` | 1 |
| `pending/pressure/refute/p3/e2e.py` | `a477fe33fa34431d…` | `dd4f28bbbd71e028…` | 1 |
| `pending/pressure/refute/p3/micro.py` | `548dda36549b73bc…` | `a8250a6958779d39…` | 1 |
| `pending/pressure/refute/p3/sens.py` | `6022bbb83c4554c4…` | `b58ef53a9995d131…` | 1 |
| `pending/pressure/scripts/ab_pressure.py` | `2ce49c2067769a6e…` | `8fde32bd92c62747…` | 1 |
| `pending/pressure/scripts/ab_pressure_r2.py` | `d64f408920b7865e…` | `8d06a637a29848db…` | 1 |
| `pending/pressure/scripts/ab_pressure_r3.py` | `e68befaad4e80dee…` | `7e845759052f9bfb…` | 1 |
| `pending/pressure/scripts/ab_pressure_r4.py` | `2e6aa2f5e93cfc27…` | `fbdeff7f15164083…` | 1 |
| `pending/pressure/scripts/heavy_lock.py` | `e158c07e3df28351…` | `1e23a6a32e74f0ea…` | 1 |
| `pending/pressure/scripts/profile_pressure_stage.py` | `aa5891ac11bf0c05…` | `1b8737e20c170b05…` | 1 |
| `pending/pressure/scripts/rc1_env.py` | `274d33e7feb91061…` | `0b722e279d0c1b60…` | 1 |
| `pending/pressure/scripts/run_locked.sh` | `0f973f319795181e…` | `0b7dce0373ff3422…` | 1 |
| `pending/storage/refute/s1/base/test_run_fresh_interval.py` | `543e5608f4b7f5db…` | `7202011e16524423…` | 1 |
| `pending/storage/refute/s1/delta-r2/run_delta.sh` | `99b7b4cce1df046f…` | `e64c25cb24c7093d…` | 2 |
| `pending/storage/refute/s1/delta-r3/run_delta_r3.sh` | `bba69fa5683b2b2a…` | `41fffd732c196c39…` | 1 |
| `pending/storage/refute/s1/delta-r4/run_delta_r4.sh` | `63cead32feb74277…` | `3cf0739ec89d105a…` | 1 |
| `pending/storage/refute/s1/run_refute.sh` | `193d3c9892dc1d0a…` | `03e2bffabdb73454…` | 1 |
| `pending/storage/refute/s2/delta-r5/probe_r5.py` | `630d27d0630d530e…` | `6cb9b74413590e2b…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/b1_block_1p5_mib/compact_restart_patch.py` | `301845b1a6000907…` | `7baf7727319375be…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/b1_block_1p5_mib/ledger_fresh_interval.py` | `a2d7569d8712b936…` | `c2f7c0f394a2449a…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/b2_block_2_mib/ledger_fresh_interval.py` | `e67cb0618d9004e3…` | `be742a62523a1ad4…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/d1_no_midloop_size_check/ledger_fresh_interval.py` | `b01441729a17383d…` | `89832b37a6e0c971…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/d2_no_final_size_check/ledger_fresh_interval.py` | `4a4e9486d1160b58…` | `f8a1926fe7e4132a…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/d3_no_size_checks/ledger_fresh_interval.py` | `6010dda1ba0dc1d3…` | `66da534ae3966f67…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/w1_lstrip_whitespace/ledger_fresh_interval.py` | `bec3306dae57a78a…` | `938e3524d34bc3a9…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/w2_lstrip_nul_and_space/ledger_fresh_interval.py` | `64c63571e0626a09…` | `c4a666184c7e5d0c…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/x1_max_length_no_remaining/ledger_fresh_interval.py` | `679689a2a5550082…` | `0e6fcee1c008b160…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/x2_eof_check_skipped_on_block_end/ledger_fresh_interval.py` | `96f987d74ef3169c…` | `861dfc510221a5c8…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/x3_ended_not_set_on_eof_with_unused/ledger_fresh_interval.py` | `0eca76e51815b84e…` | `c97ab165e1733cc8…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/x4_raw_exact_off_by_one/ledger_fresh_interval.py` | `f5d0a74c56b8420b…` | `c3e5c68dabea8a35…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/x5_exceeds_gt_to_ge/ledger_fresh_interval.py` | `3f32063ed90024f3…` | `6405947a6f16e696…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/x6_padding_allows_leading_zero_when_empty_out/ledger_fresh_interval.py` | `c04682ff79432073…` | `cc281d5fcb199e1c…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/y1_padding_end_not_handled/ledger_fresh_interval.py` | `6ea6799ab8c31050…` | `34c0c7744baa9342…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/y4_read_count_wrong/ledger_fresh_interval.py` | `1d09154dc5f3dc31…` | `2917ef0866faba1c…` | 1 |
| `pending/storage/refute/s2/delta-r8/m/y6_accept_zlib_format/ledger_fresh_interval.py` | `29de37d9b04ee246…` | `7dcc17848ae88a0e…` | 1 |
| `pending/storage/refute/s2/probe_delta.py` | `1fba052bfddeadb1…` | `13d9b60d65ac6b97…` | 1 |
| `pending/storage/refute/s2/probe_import.py` | `4fbf32b886f2547e…` | `55686c37cebe99ae…` | 2 |
| `pending/storage/refute/s2/probe_mixed.py` | `9ea4d2bcf09bd275…` | `3c470b93fb2efa2a…` | 1 |
| `pending/storage/refute/s4/probe.py` | `bb90a7bb23d929e3…` | `a585a7f4a55eb5ab…` | 1 |
| `pending/storage/refute/s8/probe_s8.py` | `69a057f63b380010…` | `7ea79f1eb708ffc8…` | 1 |
| `pending/storage/refute/s9/make_mutants.py` | `ef8cde799e03040c…` | `40297161deb57a17…` | 2 |
| `pending/storage/refute/s9/probe_backing.py` | `3f60d872251b8226…` | `9f853c4c0cf52cee…` | 1 |
| `pending/storage/refute/s9/run_all_mutants.sh` | `3a92d72078a7ab00…` | `a12cff0e80d00180…` | 6 |
| `pending/storage/refute/s9/run_mutant.py` | `343ec269a6597c5a…` | `199d542ea708bf76…` | 2 |
| `pending/storage/s1/r2/run_all_tests_r2.sh` | `84aa0e12149c079a…` | `f1e988e91adf351b…` | 1 |
| `pending/storage/s1/r3-tools/run_all_tests_r3.sh` | `6764fa0329f3748d…` | `61a734f2afc23878…` | 1 |
| `pending/storage/s1/r4-tools/run_all_tests_r4.sh` | `a2e901b45f9c9927…` | `4ff503718dbf6609…` | 1 |
| `pending/storage/s1/relocate_s1.py` | `0e7ff34cdffcf575…` | `be5d1c8901d625c8…` | 1 |
| `pending/storage/s1/run_all_tests.sh` | `9a22d75e55a177a9…` | `b75bfd14aebf4ad5…` | 1 |
| `pending/storage/s2/build_measure_r2.py` | `8e77db9dafb3f31e…` | `91062f1c6d63fcc9…` | 2 |
| `pending/storage/s2/compact_restart_patch.py` | `e28331f2cbce4885…` | `6095d5827c81462f…` | 1 |
| `pending/storage/s2/ledger_fresh_interval.py` | `17162d30d771edc1…` | `e3ada690c549d4cb…` | 1 |
| `pending/storage/s2/measure_s2.py` | `895c687d9c37e02a…` | `9f3ad34157e59ea4…` | 2 |
| `pending/storage/s2/r5-check/mutants/c1_find_spec_only/compact_restart_patch.py` | `67c83bc988c0dbae…` | `a91409b755b3ec23…` | 1 |
| `pending/storage/s2/r5-check/mutants/c2_checks_every_store/compact_restart_patch.py` | `a6c7c4a327c77635…` | `ef739cb39a6afa74…` | 1 |
| `pending/storage/s2/r5-check/mutants/c3_no_library_load/compact_restart_patch.py` | `1d5f70a063aaa27a…` | `dca1b69454bd5c08…` | 1 |
| `pending/storage/s2/r5-check/mutants/c4_import_time_capture/compact_restart_patch.py` | `20f13067c64b94b3…` | `bf1f6aebc6a8693c…` | 1 |
| `pending/storage/s2/r5-check/mutants/c5_subclass_accepted/compact_restart_patch.py` | `73c5fbcaf3441d6b…` | `32922649f890dd51…` | 1 |
| `pending/storage/s2/r5-check/mutants/c6_route_error_swallowed/compact_restart_patch.py` | `77f120aba3e3c84f…` | `ce80104c603e45a0…` | 1 |
| `pending/storage/s2/r5-check/mutants/l1_no_raw_ceiling/ledger_fresh_interval.py` | `f81039e2da7a0079…` | `64caba3f40d2c1a1…` | 1 |
| `pending/storage/s2/r5-check/mutants/l2_no_stored_ceiling/ledger_fresh_interval.py` | `38fb047d75cabd38…` | `0cd032026066230f…` | 1 |
| `pending/storage/s2/r5-check/mutants/l3_no_container_form/ledger_fresh_interval.py` | `28af770472a1d3de…` | `86a00ea4ebdc1f3b…` | 1 |
| `pending/storage/s2/r5-check/mutants/l4_no_size_equality/ledger_fresh_interval.py` | `69753dab401cb2f6…` | `d4f57d1a2b832208…` | 1 |
| `pending/storage/s2/r5-check/mutants/l5_allocate_first/ledger_fresh_interval.py` | `d8de733f004e8875…` | `71d73441e41e828f…` | 1 |
| `pending/storage/s2/r5-check/mutants/l6_legacy_eof_uncaught/ledger_fresh_interval.py` | `a238c05d31764cbf…` | `64e892320c2b802e…` | 1 |
| `pending/storage/s2/r5-check/mutants/l7_legacy_zlib_uncaught/ledger_fresh_interval.py` | `62e75ec01618f081…` | `3b25c3e45f81bcb7…` | 1 |
| `pending/storage/s2/r5-check/mutants/l8_hex_any_case/ledger_fresh_interval.py` | `89f60922f5017334…` | `a6e40843a4093f49…` | 1 |
| `pending/storage/s2/r5-check/patch_drivers.py` | `5f65ab26e418850b…` | `ccd4a66f847e1714…` | 1 |
| `pending/storage/s2/r5-check/run_all_r5.sh` | `b42e6e7e8a4aa642…` | `b5c862bee6712272…` | 1 |
| `pending/storage/s2/r5-check/run_tests_r5.py` | `7b2a044230d8247c…` | `b961a6c30f2ef77a…` | 1 |
| `pending/storage/s2/r5-check/why_errors.sh` | `6875eb2b086ffb05…` | `c3337074b2e462e2…` | 3 |
| `pending/storage/s2/r5/compact_restart_patch.py` | `1a1088d9da175e33…` | `c806c3ad40b13228…` | 1 |
| `pending/storage/s2/r5/ledger_fresh_interval.py` | `775bb0a469aef427…` | `4f8cb58ffe2aec9b…` | 1 |
| `pending/storage/s2/r6-check/drv/drivers_r6.py` | `2dbe080c10a6a752…` | `def1422228c54e32…` | 1 |
| `pending/storage/s2/r6-check/mutants/c1_find_spec_only/compact_restart_patch.py` | `25780729990da440…` | `4af72198578c00d6…` | 1 |
| `pending/storage/s2/r6-check/mutants/c2_checks_every_store/compact_restart_patch.py` | `6437315afcdbfb99…` | `33538e1c271a31d1…` | 1 |
| `pending/storage/s2/r6-check/mutants/c3_no_library_load/compact_restart_patch.py` | `732da7c363fe6e24…` | `bc6c63061205e3b0…` | 1 |
| `pending/storage/s2/r6-check/mutants/c4_import_time_capture/compact_restart_patch.py` | `bc48780f0ae305fd…` | `56ba7002b5689a27…` | 1 |
| `pending/storage/s2/r6-check/mutants/c5_subclass_accepted/compact_restart_patch.py` | `ecb88b876bd9d486…` | `b90776d21d703723…` | 1 |
| `pending/storage/s2/r6-check/mutants/c6_route_error_swallowed/compact_restart_patch.py` | `eeff06675b6669ab…` | `87945f178ddf945e…` | 1 |
| `pending/storage/s2/r6-check/mutants/c7_route_imports_store/compact_restart_patch.py` | `b033bddda51e45be…` | `4b47be39d8b8994f…` | 1 |
| `pending/storage/s2/r6-check/mutants/l10_no_footer_check/ledger_fresh_interval.py` | `1fc7cf5be9da7a29…` | `50c79ea39f73fd3e…` | 1 |
| `pending/storage/s2/r6-check/mutants/l11_path_not_contained/ledger_fresh_interval.py` | `6078b1b32ef57237…` | `1a7d31e34e3f54d7…` | 1 |
| `pending/storage/s2/r6-check/mutants/l12_legacy_unbounded/ledger_fresh_interval.py` | `e85b1feee215f4b4…` | `c9fc2c806a8aaa2c…` | 1 |
| `pending/storage/s2/r6-check/mutants/l13_gzip_bytes_unchecked/ledger_fresh_interval.py` | `e21e950a5430e32f…` | `b0402f9a7c8f2135…` | 1 |
| `pending/storage/s2/r6-check/mutants/l14_legacy_raw_unchecked/ledger_fresh_interval.py` | `5e4c00d312d5bf5d…` | `0608b35b5a4e5523…` | 1 |
| `pending/storage/s2/r6-check/mutants/l15_no_container_compare/ledger_fresh_interval.py` | `c1e8563c543042c2…` | `f85f661af4955fe2…` | 1 |
| `pending/storage/s2/r6-check/mutants/l16_no_format_minimum/ledger_fresh_interval.py` | `00568c6ce1b853ef…` | `87e7b54899da4a0a…` | 1 |
| `pending/storage/s2/r6-check/mutants/l17_no_legacy_file_ceiling/ledger_fresh_interval.py` | `0a46172a41c1a118…` | `30315c34e8908e7a…` | 1 |
| `pending/storage/s2/r6-check/mutants/l18_dotdot_name/ledger_fresh_interval.py` | `3148d04917fbc8dd…` | `2c6efbc5caa1bbf7…` | 1 |
| `pending/storage/s2/r6-check/mutants/l1_no_raw_ceiling/ledger_fresh_interval.py` | `d9967caf9db1e34c…` | `35d5364e29d5ad12…` | 1 |
| `pending/storage/s2/r6-check/mutants/l2_no_stored_ceiling/ledger_fresh_interval.py` | `397e44e600e662bc…` | `ec617fdab60073ad…` | 1 |
| `pending/storage/s2/r6-check/mutants/l3_no_container_form/ledger_fresh_interval.py` | `1793102b52d44955…` | `92b57591c882ee4d…` | 1 |
| `pending/storage/s2/r6-check/mutants/l4_no_size_equality/ledger_fresh_interval.py` | `d0c63a98b080008b…` | `01a598da513e6e17…` | 1 |
| `pending/storage/s2/r6-check/mutants/l5_allocate_first/ledger_fresh_interval.py` | `5873c62d8fe0e1b6…` | `5dc500b2ca89a1ae…` | 1 |
| `pending/storage/s2/r6-check/mutants/l6_legacy_eof_unchecked/ledger_fresh_interval.py` | `385b9b3a2348c5e2…` | `666053857da37332…` | 1 |
| `pending/storage/s2/r6-check/mutants/l7_legacy_zlib_uncaught/ledger_fresh_interval.py` | `73c01e7ab70949ab…` | `2e7365ead170a12e…` | 1 |
| `pending/storage/s2/r6-check/mutants/l8_hex_any_case/ledger_fresh_interval.py` | `8a51cbb4e7a5abcd…` | `ba244a7910830150…` | 1 |
| `pending/storage/s2/r6-check/mutants/l9_allocate_before_hash/ledger_fresh_interval.py` | `b63d28828dacd345…` | `57f5acf37c5b2fc5…` | 1 |
| `pending/storage/s2/r6-check/run_all_r6.sh` | `3cd6793782cfd3fe…` | `18dae1916c497f89…` | 1 |
| `pending/storage/s2/r6-check/run_tests_r6.py` | `f1564a4e516444ce…` | `2117f2a201c9d004…` | 1 |
| `pending/storage/s2/r6/ledger_fresh_interval.py` | `f303d4024a92f677…` | `18b0c1b485733bf8…` | 1 |
| `pending/storage/s2/r7-check/drv/drivers_r7.py` | `9bfe61f963ec7aa8…` | `3b1fe9d79d4303f6…` | 1 |
| `pending/storage/s2/r7-check/run_all_r7.sh` | `6d7d8fe45d05ba09…` | `936ff74db1e98234…` | 1 |
| `pending/storage/s2/r7-check/run_tests_r7.py` | `d7c7faebc1d7371f…` | `26082a4c15112032…` | 1 |
| `pending/storage/s2/r8-check/mutants/l10_no_footer_check/ledger_fresh_interval.py` | `7d5e59e0c35f1445…` | `4963cdee901e989b…` | 1 |
| `pending/storage/s2/r8-check/mutants/l11_path_not_contained/ledger_fresh_interval.py` | `133a2387a6dc36af…` | `a80dbb4d63921b66…` | 1 |
| `pending/storage/s2/r8-check/mutants/l12_legacy_unbounded/ledger_fresh_interval.py` | `c9ad259001173267…` | `552f9ba27f5746e6…` | 1 |
| `pending/storage/s2/r8-check/mutants/l13_gzip_bytes_unchecked/ledger_fresh_interval.py` | `c1e1e5a29f2ed6b5…` | `9be653b522736d19…` | 1 |
| `pending/storage/s2/r8-check/mutants/l14_legacy_raw_unchecked/ledger_fresh_interval.py` | `752ec011af78b66b…` | `bbf354b137686553…` | 1 |
| `pending/storage/s2/r8-check/mutants/l15_no_container_compare/ledger_fresh_interval.py` | `f221b9a4800fe109…` | `84f5fa19895e9d74…` | 1 |
| `pending/storage/s2/r8-check/mutants/l16_no_format_minimum/ledger_fresh_interval.py` | `96db435024af2c28…` | `5d54cdb17a97a9e1…` | 1 |
| `pending/storage/s2/r8-check/mutants/l17_no_legacy_file_ceiling/ledger_fresh_interval.py` | `4199421d5776462b…` | `9e6b43e765c068ca…` | 1 |
| `pending/storage/s2/r8-check/mutants/l18_dotdot_name/ledger_fresh_interval.py` | `6f904ca3ac313daf…` | `04982d7c5fdd57e9…` | 1 |
| `pending/storage/s2/r8-check/mutants/l19_legacy_whole_file_read/ledger_fresh_interval.py` | `3535b2c4c9fafc1b…` | `10b32d4bed854840…` | 1 |
| `pending/storage/s2/r8-check/mutants/l1_no_raw_ceiling/ledger_fresh_interval.py` | `d187db147d15a5d8…` | `8a4e6bfd28cef259…` | 1 |
| `pending/storage/s2/r8-check/mutants/l20_legacy_leading_zeros/ledger_fresh_interval.py` | `4e802aab32f3d957…` | `2a1afd1a19bfed0a…` | 1 |
| `pending/storage/s2/r8-check/mutants/l21_footer_tail_last_block_only/ledger_fresh_interval.py` | `18d2e438c17fbefd…` | `b2addccd5d59fd28…` | 1 |
| `pending/storage/s2/r8-check/mutants/l22_legacy_stops_at_first_member/ledger_fresh_interval.py` | `82c55cb63f61f369…` | `9ef176da4b92ac4b…` | 1 |
| `pending/storage/s2/r8-check/mutants/l23_legacy_padding_kept/ledger_fresh_interval.py` | `c9028a607dc50c40…` | `dc4336288e776945…` | 1 |
| `pending/storage/s2/r8-check/mutants/l2_no_stored_ceiling/ledger_fresh_interval.py` | `cf2375f821263484…` | `1129685667dd64ad…` | 1 |
| `pending/storage/s2/r8-check/mutants/l3_no_container_form/ledger_fresh_interval.py` | `c24dcc153c5b43b3…` | `4524d29adfeb355a…` | 1 |
| `pending/storage/s2/r8-check/mutants/l4_no_size_equality/ledger_fresh_interval.py` | `5bfdcd13df1bff4f…` | `ce10af2da271bcf2…` | 1 |
| `pending/storage/s2/r8-check/mutants/l5_allocate_first/ledger_fresh_interval.py` | `de123daef9fd92d2…` | `bff1aca4a71c196f…` | 1 |
| `pending/storage/s2/r8-check/mutants/l6_legacy_eof_unchecked/ledger_fresh_interval.py` | `9fbb3e5d0d25557b…` | `f2b240d62de81376…` | 1 |
| `pending/storage/s2/r8-check/mutants/l7_legacy_zlib_uncaught/ledger_fresh_interval.py` | `aa9803111a717733…` | `47d18cc673e2e7db…` | 1 |
| `pending/storage/s2/r8-check/mutants/l8_hex_any_case/ledger_fresh_interval.py` | `002c0a19d2cebaa7…` | `a3f93d8d2f0e0605…` | 1 |
| `pending/storage/s2/r8-check/mutants/l9_allocate_before_hash/ledger_fresh_interval.py` | `ee06642bd9bb2a32…` | `8e6b3bf664047bef…` | 1 |
| `pending/storage/s2/r8/ledger_fresh_interval.py` | `7d8a0c91ce56f2b3…` | `92d8143fa6176413…` | 1 |
| `pending/storage/s2/r9-check/mutants/c1_find_spec_only/compact_restart_patch.py` | `51b91244c1d517f2…` | `18131662be176d41…` | 1 |
| `pending/storage/s2/r9-check/mutants/c2_checks_every_store/compact_restart_patch.py` | `358a1aa674e3be27…` | `7ce66acebcdc271f…` | 1 |
| `pending/storage/s2/r9-check/mutants/c3_no_library_load/compact_restart_patch.py` | `341e54b56fea6b88…` | `354405f26b614800…` | 1 |
| `pending/storage/s2/r9-check/mutants/c4_import_time_capture/compact_restart_patch.py` | `3775ff6bb52eb964…` | `9cd070c497395b95…` | 1 |
| `pending/storage/s2/r9-check/mutants/c5_subclass_accepted/compact_restart_patch.py` | `04f32559e27f91be…` | `ddabf9fe0b9f765a…` | 1 |
| `pending/storage/s2/r9-check/mutants/c6_route_error_swallowed/compact_restart_patch.py` | `38e51341a0f10705…` | `dc3c0cbc82a6663e…` | 1 |
| `pending/storage/s2/r9-check/mutants/c7_route_imports_store/compact_restart_patch.py` | `5162e1e7d6856ffc…` | `266d34d5a3e6cd1a…` | 1 |
| `pending/storage/s2/r9-check/mutants/l10_no_footer_check/ledger_fresh_interval.py` | `fb6bf8eb90e56616…` | `452181cf35c96cfd…` | 1 |
| `pending/storage/s2/r9-check/mutants/l11_path_not_contained/ledger_fresh_interval.py` | `8d0ec2c1ff1ac6d7…` | `9019939e03c4f4af…` | 1 |
| `pending/storage/s2/r9-check/mutants/l12_legacy_unbounded/ledger_fresh_interval.py` | `a2cce99724472020…` | `49dba7a535596058…` | 1 |
| `pending/storage/s2/r9-check/mutants/l13_gzip_bytes_unchecked/ledger_fresh_interval.py` | `e86f94a999e89655…` | `08a85c28f40a0c82…` | 1 |
| `pending/storage/s2/r9-check/mutants/l14_legacy_raw_unchecked/ledger_fresh_interval.py` | `de2ab7e7518d152b…` | `25eb1cbb2e086758…` | 1 |
| `pending/storage/s2/r9-check/mutants/l15_no_container_compare/ledger_fresh_interval.py` | `6c1896e32e57a657…` | `eef43b71072d9bc5…` | 1 |
| `pending/storage/s2/r9-check/mutants/l16_no_format_minimum/ledger_fresh_interval.py` | `959130653788149a…` | `5efcc3867ca6cf3c…` | 1 |
| `pending/storage/s2/r9-check/mutants/l17_no_legacy_file_ceiling/ledger_fresh_interval.py` | `700c84235235bdcf…` | `bb225cd63b2a9ec4…` | 1 |
| `pending/storage/s2/r9-check/mutants/l18_dotdot_name/ledger_fresh_interval.py` | `fb212d118f7a6377…` | `c66b925a608e7dd9…` | 1 |
| `pending/storage/s2/r9-check/mutants/l19_legacy_whole_file_read/ledger_fresh_interval.py` | `f444d11fb954a613…` | `c055fe0dd52ff6f6…` | 1 |
| `pending/storage/s2/r9-check/mutants/l1_no_raw_ceiling/ledger_fresh_interval.py` | `0d829c392ca9e7c9…` | `014ea09c405aa955…` | 1 |
| `pending/storage/s2/r9-check/mutants/l20_legacy_leading_zeros/ledger_fresh_interval.py` | `97772a52f4fc0fc9…` | `42fccf282386d0ad…` | 1 |
| `pending/storage/s2/r9-check/mutants/l21_footer_tail_last_block_only/ledger_fresh_interval.py` | `93861f310a9d7202…` | `7690f1fba9a686b8…` | 1 |
| `pending/storage/s2/r9-check/mutants/l22_legacy_stops_at_first_member/ledger_fresh_interval.py` | `a44ed68518840728…` | `5ab746f6ec48a0b7…` | 1 |
| `pending/storage/s2/r9-check/mutants/l23_legacy_padding_kept/ledger_fresh_interval.py` | `4837d49e77a0c763…` | `b2807f6c8a24299c…` | 1 |
| `pending/storage/s2/r9-check/mutants/l24_no_midloop_size_check/ledger_fresh_interval.py` | `0a996c376ae8a895…` | `f7006a15af84457f…` | 1 |
| `pending/storage/s2/r9-check/mutants/l25_no_final_size_check/ledger_fresh_interval.py` | `f3a25e71947b2e1f…` | `f8776b03b118c352…` | 1 |
| `pending/storage/s2/r9-check/mutants/l26_zlib_format_accepted/ledger_fresh_interval.py` | `430743e88b9489fc…` | `6dc19bffa946d8aa…` | 1 |
| `pending/storage/s2/r9-check/mutants/l27_whitespace_padding/ledger_fresh_interval.py` | `af48d770ffd59ad3…` | `432c6e1d8b21ffa6…` | 1 |
| `pending/storage/s2/r9-check/mutants/l28_truncated_before_output/ledger_fresh_interval.py` | `e762710e1c84a550…` | `837b387f8551e105…` | 1 |
| `pending/storage/s2/r9-check/mutants/l29_blocks_kept/ledger_fresh_interval.py` | `0cafebf3aa5fc9f1…` | `f01458d8a45cc299…` | 1 |
| `pending/storage/s2/r9-check/mutants/l2_no_stored_ceiling/ledger_fresh_interval.py` | `c1d05e64528ff62a…` | `62670a6fdba49a90…` | 1 |
| `pending/storage/s2/r9-check/mutants/l30_block_one_and_a_half_mib/ledger_fresh_interval.py` | `48d8d014cb9bef12…` | `1b5b2515dc97734b…` | 1 |
| `pending/storage/s2/r9-check/mutants/l3_no_container_form/ledger_fresh_interval.py` | `083dd3060e79d262…` | `744c90651ce933a7…` | 1 |
| `pending/storage/s2/r9-check/mutants/l4_no_size_equality/ledger_fresh_interval.py` | `25d9db146d0b1123…` | `c72705a114b2525d…` | 1 |
| `pending/storage/s2/r9-check/mutants/l5_allocate_first/ledger_fresh_interval.py` | `27a77232eba60b6f…` | `ed59151bce1aa1b3…` | 1 |
| `pending/storage/s2/r9-check/mutants/l6_legacy_eof_unchecked/ledger_fresh_interval.py` | `80a8f2a36a5eea51…` | `ef3d1a154372c5ca…` | 1 |
| `pending/storage/s2/r9-check/mutants/l7_legacy_zlib_uncaught/ledger_fresh_interval.py` | `d8cb4ea4bf3bdbaa…` | `f1949f90eeaba015…` | 1 |
| `pending/storage/s2/r9-check/mutants/l8_hex_any_case/ledger_fresh_interval.py` | `b26fbdd01e2a7311…` | `ffa3e03fb1efd8b2…` | 1 |
| `pending/storage/s2/r9-check/mutants/l9_allocate_before_hash/ledger_fresh_interval.py` | `eac3e670e32002f9…` | `ad34549e613d8e61…` | 1 |
| `pending/storage/s2/r9/compact_restart_patch.py` | `7afe82bfc2240309…` | `257f036ace286cfb…` | 1 |
| `pending/storage/s2/r9/ledger_fresh_interval.py` | `06040fd28c42f062…` | `d8a5bcae583021a0…` | 1 |
| `pending/storage/s2/run_all_tests.sh` | `01359504ff1c5f6c…` | `4851f077eab00518…` | 1 |
| `pending/storage/s2/run_tests.py` | `f9384a5e21761415…` | `b1f19e15773560ef…` | 1 |
| `pending/storage/s4/run_tests.sh` | `17b5fa9dca798f8a…` | `71632308a0961f7c…` | 1 |
| `pending/storage/s7/scan_guard.py` | `538f7394799e53ba…` | `025d1a23671c993b…` | 2 |
| `pending/storage/s8/run_all_tests.sh` | `e55f2603ae6fc302…` | `563eb58f3a17aa4d…` | 1 |
| `pending/storage/s8/run_all_tests_r2.sh` | `fed4aa3c248fbf05…` | `abf08e6fae5e6e3c…` | 1 |
| `pending/storage/s8/run_tests.py` | `2499a03ccbec339e…` | `08ce711fce7be917…` | 1 |
| `pending/storage/s8/run_tests_r2.py` | `3deaa20addf3af37…` | `da8df4140e550f27…` | 1 |
| `pending/storage/s8/test_reopen_fresh_restart.py` | `c60d38f8c7d14f7b…` | `31d36040936db05a…` | 1 |
| `pending/storage/s9/probe/frozen_probe.py` | `73304ccf3ed94227…` | `b68ccbcf733a4507…` | 2 |
| `pending/storage/s9/run_all_tests.sh` | `f0be3d07c3c0d855…` | `556d0070642d21ee…` | 1 |
| `pending/storage/s9/run_tests.py` | `aa5ca57a5112acad…` | `b60af056e200110a…` | 1 |
| `pending/storage/s9/w4/mutants_summary.py` | `69bbbb961b6b5619…` | `0f44c5bee722a5b5…` | 1 |
| `pending/storage/s9/w4/run_s9_w4.sh` | `36e8d447a3ed7ef1…` | `1097d5bf85cad0aa…` | 1 |
| `workbench/compact-geometry-r1/native/build_manifest.json` | `2eb285fe170fefa2…` | `3bfb75116b7050a0…` | 252 |
| `workbench/composed-checks/assemble_r2.py` | `b1069d77e1c9a784…` | `c2aa80eab6c14dce…` | 1 |
| `workbench/composed-checks/d2-TEST_COMPOSITION.json` | `604c7feba285ba8e…` | `53d651781ca8f7e0…` | 202 |
| `workbench/composed-checks/run_source_handles_on_composed.py` | `270cd4f4bb93674f…` | `a82d0e5acfe5d8df…` | 1 |
| `workbench/geometry-growth-r1/scripts/heavy_lock.py` | `4cac12988f0686cc…` | `6e96e02135ca8b18…` | 1 |
| `workbench/geometry-growth-r1/scripts/measure_stage_memory.sh` | `1b917b3dd4fcce0d…` | `838025a4232ef9bb…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_after_r2.sh` | `85e60b93fb70337a…` | `6d403922f5a78d0a…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_cpcut2_parity.sh` | `cf2846ff3f6739c3…` | `8e2391ab2e18213d…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_cpcut_parity.sh` | `7199bcffe627b986…` | `8bc663d71f3482b9…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_d12_parity.sh` | `42076bdbde7b8ebd…` | `f607377d6f89000e…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_deep_profile.sh` | `9baf4f6895ebcad4…` | `c4767eee1f2cd369…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_dj_rearm.sh` | `24f3eb16249f2a76…` | `9c6849cb104d8109…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_final_f2.sh` | `fe148f9a38e560dd…` | `dd45b6c12bff3d26…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_final_f2_wait.sh` | `6c283a3c028aa6cb…` | `8ac9d8562e77b532…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_final_parity.sh` | `b0f19a00631cf894…` | `dff3333a96078401…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_final_parity_locked.sh` | `f662ef467feca964…` | `1b42cc214234f53f…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_final_parity_q.sh` | `d720314d5dcd2ac4…` | `9caf35ca481bcae4…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_growth_parity.sh` | `4709a42c50426904…` | `a5595d11f5757b13…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_iv1_arms.sh` | `f9e67266eaed27c1…` | `e90872724b14dfbd…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_iv2_triage.sh` | `e630e2d5b8e535da…` | `b3265ec68822b6e5…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_jets_parity.sh` | `d8210a89ec0ffd44…` | `d954fa9a5039dcc6…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_locked.sh` | `d75b9ce7c624209d…` | `d479c502d842f413…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_progress_parity.sh` | `6396305f621998fd…` | `3287f0acf3590829…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_r3_confirm.sh` | `0eba558ee17d61e6…` | `bac706b9bdb6c3b7…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_replay_set.sh` | `c3c2588fe641ff9a…` | `f2df8b24727df48d…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_surfaces_iv2.sh` | `894a49b0f4a8366f…` | `1f6f75664d1752a3…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_surfaces_sample.sh` | `d9d361e80437ae2e…` | `61e90ea22d603313…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_width_sensitivity.sh` | `86c737b4b48cb870…` | `0edeefa6253b5de3…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_workers_parity.sh` | `d2565699a5ed2a71…` | `67eee7294530bff1…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_workers_parity_dj.sh` | `53863ea802648200…` | `9cf01af3d11fff3c…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_workers_parity_r2.sh` | `930fdb280a056733…` | `3dc4c6b88383ab09…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_workers_parity_r2_iv2.sh` | `31cce2db97ea3489…` | `1630e9e0ee41ec27…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_workers_parity_r3.sh` | `11c97cfc550ce87a…` | `3422b0517efcb80f…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_wp18_parity.sh` | `cb7cc706f0dc6c38…` | `6fce0399207824c9…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_wp20r3_chain.sh` | `a7fcc424fd0690d8…` | `9a42fafd1434e4c0…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_wp23_parity.sh` | `d0b39636daaa51ed…` | `c15570604c12e55c…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_wp23_parity_seed0.sh` | `4e78060dd7a1f6f9…` | `4a5ea929c7515d32…` | 1 |
| `workbench/geometry-growth-r1/scripts/surfaces_stage_check_proof.py` | `7a85ecab3d452077…` | `75884cffd2335543…` | 1 |
| `workbench/probes/step8/claude-20261015/decision-06-plan-order.md` | `abfefd3a2f4ca7dc…` | `7cc814501fab855e…` | 1 |
| `workbench/probes/step8/claude-20261015/owner-s0-before/composition.json` | `9ad7cf281fc41788…` | `bc7280c9d2e6c8dd…` | 8 |
| `workbench/probes/step8/claude-20261015/owner-s1-after/composition.json` | `6c9d829c9047814f…` | `1cd36e90461dec53…` | 8 |
| `workbench/probes/step8/claude-20261015/parity-small64k/composition.json` | `62f178a95466a7ac…` | `e80d22f544081cc1…` | 8 |
| `workbench/probes/step8/claude-20261015/ruff_compare.py` | `2860a2857cd6dad8…` | `c7af55dbb5e8de23…` | 1 |
| `workbench/probes/step8/claude-20261015/run_gen1_suites.sh` | `2678ffd81d699544…` | `a95e0f017d879f06…` | 1 |
| `workbench/probes/step8/claude-20261015/run_r1gen_suites.sh` | `6e39185d72975548…` | `3af0010b1f88e0f3…` | 1 |
| `workbench/probes/step8/claude-20261015/run_r2mesh_suites.sh` | `d77405cb532023c0…` | `af613a2536829a11…` | 1 |
| `workbench/probes/step8/claude-20261015/run_x2_suites.sh` | `11c628fc6a8720f7…` | `36dbf7a0b3c553fd…` | 1 |
| `workbench/probes/step8/claude-20261015/scouting/baseline-tests.md` | `efd2bf8e9a68ce0c…` | `c09d823d0bb32265…` | 2 |
| `workbench/probes/step8/claude-20261015/scouting/builder.md` | `5c38c49993a974e9…` | `386acb6a8ab11a70…` | 1 |
| `workbench/probes/step8/claude-20261015/scouting/exchange-facts.md` | `92e57dd9e06a7e8a…` | `2bb3b6641dfd749d…` | 3 |
| `workbench/probes/step8/claude-20261015/scouting/harness.md` | `59f67ad522caaf64…` | `37d26fe6646afde2…` | 1 |
| `workbench/probes/step9/claude-20261016/run_adm_bisect.sh` | `320532ce4228dc59…` | `ed0d90d453adf1a8…` | 1 |
| `workbench/probes/step9/claude-20261016/run_adm_samples.sh` | `ced57db96960e941…` | `f28ff56cfe5041d3…` | 1 |
| `workbench/probes/step9/claude-20261016/run_b17_merge_tests.sh` | `5144804f01e506a0…` | `018a28de3102f2c4…` | 1 |
| `workbench/probes/step9/claude-20261016/run_cell_keys.sh` | `ea47a4f297680562…` | `2c26b6e360a5a18c…` | 1 |
| `workbench/probes/step9/claude-20261016/run_frozen_smoke.sh` | `c6a5408dbd5dbfb7…` | `50f9e68d1ff36189…` | 1 |
| `workbench/probes/step9/claude-20261016/run_item11_tests.sh` | `a58717803f7d6e63…` | `0f8fcf48b29a7799…` | 1 |
| `workbench/probes/step9/claude-20261016/run_item21_tests.sh` | `9fdeb7e9ef261437…` | `7bc1796ef54ab601…` | 1 |
| `workbench/probes/step9/claude-20261016/run_item7_arms.sh` | `3b01b9e9eca257d1…` | `a7139cae857352ee…` | 1 |
| `workbench/probes/step9/claude-20261016/run_item7_tests.sh` | `dab18f1233f0bb5b…` | `3adbe155f67cd136…` | 1 |
| `workbench/probes/step9/claude-20261016/run_r2_arrays_then_h4.sh` | `a1a74c7d0a2574d9…` | `36cb0d5d38120c17…` | 1 |
| `workbench/probes/step9/claude-20261016/run_s8_tests.sh` | `c8ae6986c5c6c011…` | `9c0d13fff0807ebb…` | 1 |
| `workbench/probes/step9/claude-20261016/run_when_lock_free.sh` | `dd85c6e8369158b9…` | `036aba68ebd22718…` | 1 |
| `workbench/geometry-growth-r1/scripts/run_dj_rearm_r5.sh` | `329b0b3c76b55e473cc525fa267077cc92c8474f0fab1e200f0844bd8ea7a571` | `90b720f3729cf3f60ca6b41113049d2230f81abaf2335ce0c9cd02d229dd7f76` | 1 |
| `workbench/geometry-growth-r1/scripts/test_summarise_dj_r5.py` | `2eb6dd0bdedfc525772e256e16272fa340ffcb2a3c11537c39cc675df27fa990` | `0a5fa81679f57b87ad74eb0bfbd67499a600788bc76f523be1666583aa1b14b1` | 1 |

## Plans15/17 source publication

The additive [Plan15](workbench/plan15/SOURCE-MAP.json) and
[Plan17](workbench/plan17/SOURCE-MAP.json) maps record exact original/public
digests and publication transformations. Personal home names become LOCAL_USER,
including embedded source strings. The driver test's source lookup alone is
adapted to this public layout. Private requests, queue state, profiles, run logs,
runtime assets and science inputs are excluded. Summaries are not execution receipts.
Sanitised dispatcher/native-binding files retain original private hash guards and
are source for inspection, not a runnable native installation or permission to run.

## Plan17 operational r7 source integration

The Plan17 source map retains every r3 entry and adds nine r4/r7 source files.
Only the admission source, launcher and overrun worker require publication changes:
personal home paths become LOCAL_USER and the launcher's two actual coordination
recipients become invalid named placeholders. Original/private guards remain
literal; no executable request or recipient binding is created. Synthetic test
identifiers remain unchanged. All other bytes are preserved, with original/public
digests and transformation counts in the source map. Private requests, fixtures,
profiles, runtimes, queue state and the external completion launcher/CLI are excluded.
The completed proof summaries describe retained private runs, not new public runs.
