#!/usr/bin/env bash
# G-PY (T/ck/transforms/gpy_q2_jets.py) parity, mirroring G/scripts/run_jets_parity.sh (D-b: only
# source-digest fields may differ) and the CPU effect. Run via T/q/runq.py run qNN -- bash gpy_parity.sh TAG
# PYTHONHASHSEED=0. One arm at a time, 6 processes.
#  1. IV1 surfaces, all: jets-r1 (RC1 + q2fast + jetsfast) vs T/ck/gpy-jets (jets-r1 + gpy).
#  2. IV2 1-in-10 sample (cap 2 s): final-f2 vs T/ck/gpy-f2 (final-f2 + gpy), final-f1 inputs as jets-r1.
#  3. IV2 deep set (the 216 final-f1 capped-list interfaces, cap 120 s): the same two arms.
# r2 (16 Oct, review before queue): FAIL CLOSED. Every shard's exit code is kept (OUT/<stage>-<arm>-s<i>.exit)
# and each stage is judged by scripts/gpy_parity_check.py (runs geometry's pinned compare_surfaces.py on
# exactly the expected shards; also fails a missing/failed/timed-out/partial shard in EITHER arm, an arm
# that loaded the other's runtime, an all-capped or empty stage). Proven on planted mutants:
# scripts/gpy_parity_proof.py r2 -> T/ck/q11p3/proof.json. Scripts and the four runtimes are hashed at start
# and end; a change fails the run.
# Smoke (small lane, 1 core): bash gpy_parity.sh TAG smoke -- the same harness on one shard per stage
# (IV1 and IV2 sample 1/600, deep: the second capped-list interface, so the sample's capped row runs in 2b).
# r3 (16 Oct, refuter RISK: a row capped in either arm was compared nowhere): IV1 and deep allow no capped
# row (measured: 0 of 40,968 IV1 rows capped at 60 s; 216 of 216 deep rows met at 120 s, three runs).
# IV2-sample rows capped at 2 s in either arm are re-run at 120 s: on the deep lists by the deep stage,
# the rest (final-f2: 1 of 216) by stage 2b from OUT/iv2-sample-extra-list.jsonl, which allows no cap.
# r4 (16 Oct): every replay runs under scripts/run1.py (same 5400 s limit, exit 124) instead of GNU timeout:
# under Git Bash `timeout N cmd &` falls out of the Windows parent chain and runq's tree peak missed every
# shard (smokes s2/s3 recorded 0.03/0.02 GiB; ck/d5/tree-probe.txt).
# r5 (16 Oct, delta refuter RISK C): deferral is checked, not assumed: the sample check writes its deferred rows
# (OUT/iv2-sample-deferred-list.jsonl) and the deep check gets cover:<that list> (each must be replayed by both
# arms, none capped). The deep lists (or the smoke list) are hashed by frozen(); the sample's extra and deferred
# lists are hashed when written and re-checked at the end.
set -u
export PYTHONHASHSEED=0
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
CK="$T/ck"
F="$G/evidence/final-f1"
TAG="${1:?tag}"; MODE="${2:-full}"
OUT="$CK/gpy-parity-$TAG"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
case "$MODE" in
  full)  N1=6;   L1="0 1 2 3 4 5"; N2=60;  L2="0 10 20 30 40 50"; LD="0 1 2 3 4 5";;
  smoke) N1=600; L1="0";           N2=600; L2="0";                LD="0";;
  *) echo "mode must be full or smoke"; exit 2;;
esac
[ -e "$OUT" ] && { echo "$OUT exists"; exit 2; }
mkdir -p "$OUT"
RT1B="test:$T/gg/jets-r1";   RT1G="test:$CK/gpy-jets"
RT2B="test:$T/gg/final-f2";  RT2G="test:$CK/gpy-f2"
DEEP=()
for i in $LD; do DEEP+=("$F/capped-list-$i.jsonl"); done
# Smoke deep row: capped-list-0 line 2, not line 1. The 1/600 sample's only capped row (s2) is line 1's, so
# with line 2 it is off the deep list and goes through stage 2b: the smoke runs every stage.
if [ "$MODE" = smoke ]; then sed -n 2p "$F/capped-list-0.jsonl" > "$OUT/smoke-list-0.jsonl"; DEEP=("$OUT/smoke-list-0.jsonl"); fi
DEEPC=$(IFS=,; echo "${DEEP[*]}")
frozen () {
  sha256sum "$CK/scripts/gpy_parity.sh" "$CK/scripts/gpy_parity_check.py" "$CK/scripts/run1.py" \
    "$G/scripts/replay_surfaces.py" "$G/scripts/compare_surfaces.py" "${DEEP[@]}"
  for d in "$T/gg/jets-r1" "$CK/gpy-jets" "$T/gg/final-f2" "$CK/gpy-f2"; do
    (cd "$d" && find . -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sed "s|^|$d |")
  done
}
frozen > "$OUT/frozen-start.sha256"
cd "$G/scripts"
run6 () {  # tag runtime supports partition interval width cap shards shardlist... -- extra
  local tag=$1 rt=$2 sup=$3 part=$4 iv=$5 w=$6 cap=$7 n=$8; shift 8; local list=() extra=() seen=0
  for x in "$@"; do if [ "$x" = "--" ]; then seen=1; elif [ $seen = 0 ]; then list+=("$x"); else extra+=("$x"); fi; done
  local pids=() ids=() k
  for i in "${list[@]}"; do
    local more=()
    [ ${#extra[@]} -gt 0 ] && more=("${extra[@]//@I@/$i}")
    "$PY" -B -I "$CK/scripts/run1.py" 5400 "$PY" -B replay_surfaces.py --supports "$sup" --partition "$part" --interval "$iv" --stream-width $w \
      --runtime "$rt" --cap-cpu "$cap" --shard $i --shards "$n" --output "$OUT/$tag-s$i.jsonl" "${more[@]}" > "$OUT/$tag-s$i.log" 2>&1 &
    pids+=($!); ids+=($i)
  done
  for k in "${!pids[@]}"; do wait "${pids[$k]}"; echo $? > "$OUT/$tag-s${ids[$k]}.exit"; done
  echo "done $tag $(date +%H:%M:%S) exits $(for i in "${ids[@]}"; do cat "$OUT/$tag-s$i.exit"; done | paste -sd' ')"
}
check () {  # stage shardlist base_runtime gpy_runtime caps [rows]
  "$PY" -B -I "$CK/scripts/gpy_parity_check.py" "$OUT" "$1" "$(echo $2 | tr ' ' ',')" "$3" "$4" "${@:5}" || s=1
}
s=0
echo "start $(date +%H:%M:%S) mode $MODE"
for arm in base gpy; do
  rt=$RT1B; [ $arm = gpy ] && rt=$RT1G
  run6 iv1-surfaces-$arm "$rt" "$G/work/iv1-supports.jsonl.gz" "$G/work/next-iv1-rc1-r1.grid.json.gz" "$G/work/iv1-interval-r1.json.gz" "$W1" 60 $N1 $L1
done
check iv1-surfaces "$L1" "$RT1B" "$RT1G" none
for arm in base gpy; do
  rt=$RT2B; [ $arm = gpy ] && rt=$RT2G
  run6 iv2-sample-$arm "$rt" "$F/iv2-supports.jsonl.gz" "$F/iv2-partition.grid.json.gz" "$G/work/iv2-interval-only-r1.json.gz" "$W2" 2 $N2 $L2 -- --only-cells-from "$(ls "$F"/ref-iv2-surfaces-s*.jsonl | paste -sd, -)"
done
check iv2-sample "$L2" "$RT2B" "$RT2G" "defer:$DEEPC"
XL="$OUT/iv2-sample-extra-list.jsonl"; DL="$OUT/iv2-sample-deferred-list.jsonl"
sha256sum "$XL" "$DL" > "$OUT/lists.sha256" || { echo "FAIL: sample extra/deferred lists not written"; s=1; }
if [ ! -f "$XL" ]; then
  echo "FAIL: $XL not written"; s=1
elif [ -s "$XL" ]; then
  NX=$(wc -l < "$XL")
  for arm in base gpy; do
    rt=$RT2B; [ $arm = gpy ] && rt=$RT2G
    "$PY" -B -I "$CK/scripts/run1.py" 5400 "$PY" -B replay_surfaces.py --supports "$F/iv2-supports.jsonl.gz" --partition "$F/iv2-partition.grid.json.gz" \
      --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --runtime "$rt" --cap-cpu 120 \
      --only-list "$XL" --output "$OUT/iv2-extra-$arm-s0.jsonl" > "$OUT/iv2-extra-$arm-s0.log" 2>&1
    echo $? > "$OUT/iv2-extra-$arm-s0.exit"
  done
  check iv2-extra 0 "$RT2B" "$RT2G" none "$NX"
else
  echo "iv2-extra: every capped sample row is on the deep lists"
fi
for arm in base gpy; do
  rt=$RT2B; [ $arm = gpy ] && rt=$RT2G
  pids=(); ids=()
  for i in $LD; do
    list="$F/capped-list-$i.jsonl"; [ "$MODE" = smoke ] && list="$OUT/smoke-list-$i.jsonl"
    "$PY" -B -I "$CK/scripts/run1.py" 5400 "$PY" -B replay_surfaces.py --supports "$F/iv2-supports.jsonl.gz" --partition "$F/iv2-partition.grid.json.gz" \
      --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --runtime "$rt" --cap-cpu 120 --kinds interface \
      --only-list "$list" --output "$OUT/iv2-deep-$arm-s$i.jsonl" > "$OUT/iv2-deep-$arm-s$i.log" 2>&1 &
    pids+=($!); ids+=($i)
  done
  for k in "${!pids[@]}"; do wait "${pids[$k]}"; echo $? > "$OUT/iv2-deep-$arm-s${ids[$k]}.exit"; done
  echo "done iv2-deep-$arm $(date +%H:%M:%S)"
done
check iv2-deep "$LD" "$RT2B" "$RT2G" "cover:$DL"
frozen > "$OUT/frozen-end.sha256"
cmp -s "$OUT/frozen-start.sha256" "$OUT/frozen-end.sha256" || { echo "FAIL: scripts, lists or runtimes changed during the run"; s=1; }
sha256sum -c --quiet "$OUT/lists.sha256" || { echo "FAIL: sample extra/deferred lists changed during the run"; s=1; }
echo "end $(date +%H:%M:%S) exit $s"
exit $s
