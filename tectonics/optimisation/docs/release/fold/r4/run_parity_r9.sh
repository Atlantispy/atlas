#!/usr/bin/env bash
# R3 parity run: run_parity_r8.sh on p20c-r4 and its fold out-c3 with arms r7 (hcf_prepare_r15, the gmpy2 build record, tight sizes, the cell-key save), bookings and limbs r3 (v27), a tool-pin check, an r2 reference arm and the keyed cell checks. Small lane,
# one arm at a time (per-arm tree peak 1.14 GiB on p6), so the lock is one arm's peak:
#   runq small --gib 2 -- bash run_parity_r9.sh WORKSPACE OUT
# The inputs are fixed and pinned; the run refuses before any arm if either pin differs:
#   ac/p20c-r4/composition.json  21e666b8  (the R3 target)
#   ac/p20c-r2/composition.json  5ff62b90  (the reference arm R: one child, for the keyed cell match only)
#   rm/fold/out-c3/MANIFEST.json  1d6f7ea3  (its fold; B's arm record pins the same manifest)
#   rm/fold/r3p/tools-frozen.sha256: every tool this script runs has its reviewed sha
# Arms: A, B, A' (a second child of the prepared A layout), then B' (a second child of the prepared B layout). The
# children only read their layout; each child checks that its layout and inputs are unchanged by the run.
# Checks, each logged to OUT/<name>.log, with a JSON report where the tool writes one:
#   overlay  v25/mk_manifest.py re-pins the overlay to this run's MANIFEST-h. The overlay is code constants, so it
#            must equal MANIFEST-r1 (built on smoke 7, selftested) apart from base_sha256; same-overlay checks that.
#   rec-ab, rec-a2b, rec-ab2  records.py check A vs B, A' vs B and A vs B'
#   noise-a, noise-b  records.py noise A vs A' and B vs B'
#   book-ab, book-a2b, book-ab2  v27/bookings.py A vs B, A' vs B and A vs B'; same-bookings: the three reports are
#            byte-identical (a repeat of either arm books exactly the same)
#   limbs  v27/limbs_r3.py: A vs A' and B vs B' with no size difference, A vs B within the one-sided net per-row cap
#   cells-ra  v27/cells_keyed.py R vs A: every cell matched by the mixed key (exterior logical_cell_id,
#            collar physical_cell_id) with its values bitwise, 172 exterior and 64 collar; the report
#            states the match count
#   cells-ab  v27/cells_keyed.py A vs B (the fold, one composition), the same counts
# Every child also saves its arrays and cell keys, with physical_cell_id, into OUT/<child>/save (arms_r8).
#   mpfr  v27/mpfr_same.py: one libmpfr in each child (R, A, A', B, B') at RF2's exec_prefix path, one file
#         everywhere; each worker with a snapshot at most one, the same file (RF2 condition c)
set -u
T="$1"
O="$2"
PY="$T/.r44-env/Scripts/python.exe"
RR="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
HCF="$RR/probes/step9/claude-20261016/heat_control_on_frozen.py"
CTL="$RR/compact-geometry-r1/step7_same_call_heat_control.py"
P="$T/ac/p20c-r4"
P2="$T/ac/p20c-r2"
F="$T/rm/fold"
V="$F/v25"
FOLD="$F/out-c3"
PIN_P="21e666b83bd213bb97878b32a69081887eaea0dbc305fe02b18f64cfe8cc0950"
PIN_P2="5ff62b90f38059a76323f4b7387774c96f602ec46a414bb091d212b428b5f0b1"
PIN_FOLD="1d6f7ea357fb6d705faf1d9eb4911f26fce70788a3dfff06665b895e0bb623a9"
export PYTHONHASHSEED=0
pin() {
  got=$(sha256sum "$1" | cut -c1-64)
  if [ "$got" != "$2" ]; then echo "pin differs: $1 is $got, expected $2"; exit 1; fi
}
pin "$P/composition.json" "$PIN_P"
pin "$P2/composition.json" "$PIN_P2"
pin "$FOLD/MANIFEST.json" "$PIN_FOLD"
sha256sum --strict --quiet -c "$F/r3p/tools-frozen.sha256" || { echo "a tool pin differs (r3p/tools-frozen.sha256)"; exit 1; }
echo "r9 $(sha256sum "$0" | cut -c1-64)"
mkdir "$O" || exit 1
set -e
echo "prepare-a $(date +%H:%M:%S)"
"$PY" -B "$F/arms_r8.py" prepare-a "$O/a" "$P" "$HCF" "$CTL" "$P/composition.json"
echo "prepare-b $(date +%H:%M:%S) from $FOLD"
"$PY" -B "$F/arms_r8.py" prepare-b "$O/b" "$FOLD" "$O/a"
echo "prepare-r $(date +%H:%M:%S) from p20c-r2"
"$PY" -B "$F/arms_r8.py" prepare-a "$O/r" "$P2" "$HCF" "$CTL" "$P2/composition.json"
set +e
for arm in "a oa" "b ob" "a oa2" "b ob2" "r or"; do
  set -- $arm
  echo "child $2 $(date +%H:%M:%S)"
  "$PY" -B "$F/arms_r8.py" child "$O/$1" "$O/$2" || echo "child $2 exit $?"
done
run() {
  name="$1"; shift
  echo "$name $(date +%H:%M:%S)"
  "$PY" -B "$@" > "$O/$name.log" 2>&1 || echo "$name exit $?"
  tail -n 1 "$O/$name.log"
}
run overlay "$V/mk_manifest.py" "$O/b" "$O/oa" "$O/ob" "$O/MANIFEST-r7.json"
run same-overlay -c "import json, sys
a, b = (json.load(open(p, encoding='utf8')) for p in sys.argv[1:3])
pins = a.pop('base_sha256'), b.pop('base_sha256')
print(json.dumps(dict(same_apart_from_pin=a == b, pins=[x[:16] for x in pins])))
sys.exit(0 if a == b else 1)" "$V/MANIFEST-r1.json" "$O/MANIFEST-r7.json"
run rec-ab "$F/v26/records.py" check "$O/a" "$O/oa" "$O/b" "$O/ob" "$O/MANIFEST-r7.json" "$O/rec-ab.json"
run rec-a2b "$F/v26/records.py" check "$O/a" "$O/oa2" "$O/b" "$O/ob" "$O/MANIFEST-r7.json" "$O/rec-a2b.json"
run rec-ab2 "$F/v26/records.py" check "$O/a" "$O/oa" "$O/b" "$O/ob2" "$O/MANIFEST-r7.json" "$O/rec-ab2.json"
run noise-a "$F/v26/records.py" noise "$O/oa" "$O/oa2"
run noise-b "$F/v26/records.py" noise "$O/ob" "$O/ob2"
run book-ab "$F/v27/bookings.py" "$O/a" "$O/oa" "$O/b" "$O/ob" "$O/b/MANIFEST-h.json" "$O/book-ab.json"
run book-a2b "$F/v27/bookings.py" "$O/a" "$O/oa2" "$O/b" "$O/ob" "$O/b/MANIFEST-h.json" "$O/book-a2b.json"
run book-ab2 "$F/v27/bookings.py" "$O/a" "$O/oa" "$O/b" "$O/ob2" "$O/b/MANIFEST-h.json" "$O/book-ab2.json"
run same-bookings -c "import hashlib, json, sys
d = [hashlib.sha256(open(p, 'rb').read()).hexdigest() for p in sys.argv[1:]]
print(json.dumps(dict(identical=len(set(d)) == 1, sha256=[x[:16] for x in d])))
sys.exit(0 if len(set(d)) == 1 else 1)" "$O/book-ab.json" "$O/book-a2b.json" "$O/book-ab2.json"
run limbs "$F/v27/limbs_r3.py" "$F/v27" "$O/b/MANIFEST-h.json" "$O/limbs.json" "$O/a" "$O/oa" "$O/a" "$O/oa2" "$O/b" "$O/ob" \
  "$O/b" "$O/ob2"
run cells-ra "$F/v27/cells_keyed.py" "$O/or/save" "$O/oa/save" "$O/cells-ra.json" 172 64
run cells-ab "$F/v27/cells_keyed.py" "$O/oa/save" "$O/ob/save" "$O/cells-ab.json" 172 64
run mpfr "$F/v27/mpfr_same.py" "$O/mpfr.json" "$O/or" "$O/oa" "$O/oa2" "$O/ob" "$O/ob2"
echo "end $(date +%H:%M:%S)"
