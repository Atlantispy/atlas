#!/usr/bin/env bash
# Prepare the R1 fold on the staged composition (p20c-r4; written for p20c-r3, which was superseded before staging)
# up to the ticket. Every step must pass before the next; the first failure stops the script with its log tail. Run
# it as a normal queue ticket, sequentially (on r2: trace peak 0.32 GiB, fold 0.54 GiB, mutants 0.20 GiB, whole chain
# 0.94 GiB in 6 minutes):
#   runq run --strict-admission TICKET -- bash rm/fold/r3p/prep_r3.sh WORKSPACE COMPOSITION COMPOSITION_SHA256
#
# p20c-r4 = p20c-r2 + CRP/LG r12 (Plan 20) + RF2 and Plan 18 r5. RF2 rewrote FP's two embedded sources without
# their machine path, so its two R2 carries retire (r3p/mk_declared_r12.py). The names r3 and out-c3 below are the
# successor's slots. Four inputs are written at staging, from Plan 20's report and a dry run, and pinned in
# r3p/tools-frozen.sha256 with every tool below:
#   r3p/allowed-r3.txt     the files r3 may change against r2, one compare_comp ALLOWED entry per line
#   r3p/rekey-modules.txt  the changed modules whose decisions move along their line maps, one per line
#   r3p/mk_declared_r12.py, r3p/declared-r12.json  r12's site changes, read from r3's candidates, and the reviewed
#                          declaration they must reproduce byte for byte
#   hcf_prepare_r15.py     with p20c-r3's composition sha added
# Steps, each logged to r3p/<step>.log:
#   tools       every tool this script and r9 run has the reviewed sha (r3p/tools-frozen.sha256)
#   compare     the staged composition differs from p20c-r2 only in allowed-r3.txt
#   trace       one real heat call with a loaded-file trace (run_trace_r4: hcf_prepare_r15; rm/fold/t3, t3-out.json,
#               t3-trace.json)
#   save        HCF's child on t3, saving the five arrays and each cell's keys (rm/fold/t3s)
#   rows        every cell's numbers equal p20c-r2's bitwise: the same multiset of rows as r2p/bis/t2s, the r2 save.
#               Cell identities and order are reported, not gated. The multiset cannot see two cells with equal key
#               fields swapping values; the keyed match by physical_cell_id is r9's cells-ra.
#   candidates  fold_r5 candidates on r3 with r2's decisions (sites-r2.json)
#   declared    r12's site changes read from r3's candidates (r3p/declared-r3.json)
#   same-declared  ... byte-identical to r3p/declared-r12.json, the reviewed declaration
#   rekey       r2's decisions carried along each changed module's own line map (p20c-r2 -> r3), plus the declared
#               retire/add (sites-r3.json)
#   fold        fold_r5 fold -> rm/fold/out-c3 (gates ast, pins, scan, K3)
#   mutants     tree mutants_r4 on out-c3 (mt4): r3's set plus M12 (the sibling helpers/ layout refuses at preflight),
#               N3 and N4
#   literals    private workspace names in the folded tree (r3p/pl-c3.json; fails on any dated name; the two RF2
#               carries remain)
#   r9          run_parity_r9.sh from run_parity_r8.sh by r3p/mk_r9.py: only the declared lines differ
set -u
T="$1"
C="$2"
CS="$3"
PY="$T/.r44-env/Scripts/python.exe"
RR="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
HCF="$RR/probes/step9/claude-20261016/heat_control_on_frozen.py"
F="$T/rm/fold"
X="$F/r3p"
export PYTHONHASHSEED=0
step() {
  name="$1"; shift
  echo "$name $(date +%H:%M:%S)"
  if ! "$@" > "$X/$name.log" 2>&1; then
    echo "$name FAIL"
    tail -n 10 "$X/$name.log"
    exit 1
  fi
  tail -n 1 "$X/$name.log" | cut -c1-400
}
step tools sha256sum --strict -c "$X/tools-frozen.sha256"
mapfile -t ALLOWED < <(tr -d '\r' < "$X/allowed-r3.txt" | grep -v '^$')
mapfile -t MODULES < <(tr -d '\r' < "$X/rekey-modules.txt" | grep -v '^$')
if [ "${#ALLOWED[@]}" -eq 0 ] || [ "${#MODULES[@]}" -eq 0 ]; then
  echo "allowed-r3.txt or rekey-modules.txt is empty"
  exit 1
fi
step compare "$PY" -B "$F/r2p/compare_comp.py" "$T/ac/p20c-r2" "$T/ac/$C" "$CS" "$X/compare.json" "${ALLOWED[@]}"
step trace bash "$F/run_trace_r4.sh" "$T" "$C" t3
step save "$PY" -B "$HCF" child "$F/t3" "$F/t3s-out.json" - "$F/t3s"
step rows "$PY" -B "$F/r2p/rows_equal.py" "$F/r2p/bis/t2s" "$F/t3s"
step candidates "$PY" -B "$F/fold_r5.py" candidates "$T/ac/$C" "$X/cand.json" --trace "$F/t3-trace.json" \
  --sites "$F/sites-r2.json"
step declared "$PY" -B "$X/mk_declared_r12.py" "$T/ac/$C" "$X/cand.json" "$X/declared-r3.json"
step same-declared cmp "$X/declared-r12.json" "$X/declared-r3.json"
step rekey "$PY" -B "$F/r2p/rekey_sites.py" --roots "$T/ac/p20c-r2" "$T/ac/$C" --declared "$X/declared-r12.json" \
  "$F/sites-r2.json" "$X/cand.json" "ac/$C" "$CS" "$F/sites-r3.json" "${MODULES[@]}"
step fold "$PY" -B "$F/fold_r5.py" fold "$T/ac/$C" "$F/out-c3" --trace "$F/t3-trace.json" --sites "$F/sites-r3.json" \
  --data-root "$RR"
step mutants "$PY" -B "$F/mutants_r4.py" tree "$F/v24" "$T/ac/$C" "$F/out-c3" "$F/mt4"
step literals "$PY" -B "$F/r2p/private_literals.py" "$F/out-c3/folded" "$X/pl-c3.json"
MS=$(sha256sum "$F/out-c3/MANIFEST.json" | cut -c1-64)
step r9 "$PY" -B "$X/mk_r9.py" "$F/run_parity_r8.sh" "$F/run_parity_r9.sh" "$C" "$CS" out-c3 "$MS"
echo "manifest $MS"
echo "end $(date +%H:%M:%S)"
