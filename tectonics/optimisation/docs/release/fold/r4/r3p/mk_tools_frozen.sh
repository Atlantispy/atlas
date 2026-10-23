#!/usr/bin/env bash
# Write r3p/tools-frozen.sha256 at staging: the sha256 of every tool and fixed input that prep_r3.sh and
# run_parity_r9.sh run or read. Refuses if the list exists or a file is missing.
#   bash r3p/mk_tools_frozen.sh WORKSPACE
set -eu
T="$1"
F="$T/rm/fold"
X="$F/r3p"
RR="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
OUT="$X/tools-frozen.sha256"
[ -e "$OUT" ] && { echo "$OUT exists"; exit 1; }
FILES=(
  "$RR/probes/step9/claude-20261016/heat_control_on_frozen.py"
  "$RR/compact-geometry-r1/step7_same_call_heat_control.py"
  "$F/fold_r5.py" "$F/v24/parity.py" "$F/v26/records.py" "$F/mutants_r4.py" "$F/trace_frozen.py"
  "$F/run_trace_r4.sh" "$F/hcf_prepare_r15.py" "$F/arms_r8.py" "$F/wobs2/sitecustomize.py"
  "$F/v27/bookings.py" "$F/v27/limbs_r3.py" "$F/v27/cells_keyed.py" "$F/v27/mpfr_same.py"
  "$F/v25/mk_manifest.py" "$F/v25/MANIFEST-r1.json"
  "$F/r2p/compare_comp.py" "$F/r2p/rows_equal.py" "$F/r2p/rekey_sites.py" "$F/r2p/private_literals.py"
  "$F/r2p/bis/t2s/arrays.json" "$F/r2p/bis/t2s/cell_keys.json" "$F/sites-r2.json" "$F/run_parity_r8.sh"
  "$F/fold_r2.py"
  "$X/prep_r3.sh" "$X/mk_r9.py" "$X/allowed-r3.txt" "$X/rekey-modules.txt" "$X/mk_declared_r12.py"
  "$X/declared-r12.json"
)
for path in "${FILES[@]}"; do
  [ -f "$path" ] || { echo "missing: $path"; exit 1; }
done
sha256sum -b "${FILES[@]}" > "$OUT"
wc -l < "$OUT"
sha256sum "$OUT"
