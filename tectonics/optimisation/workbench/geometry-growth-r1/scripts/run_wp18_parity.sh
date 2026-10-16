#!/usr/bin/env bash
# WP18 part 1 proof (endpoint batching): byte-identical endpoint records, serial vs 2 automatic
# endpoint workers, on IV1 all and IV2 all, runtime gg/wp18-r2 (workers6-r6 + wp18 r2; only
# integration_component_volume_auto.py differs). For the coordinator's run queue:
#   runq.py run qNN -- <Git bash.exe> run_wp18_parity.sh <tag> [<shards>]
# <shards> (smoke only): every arm takes shard 0 of that many, same script, arguments and layout.
# No lock of its own (runq holds it). Arms, in order:
#   iv2-serial, iv2-w2            IV2 all; the policy's default 120 s threshold
#   iv1-serial, iv1-w2            IV1 all; default threshold (IV1's ~91 s stays serial: equality only)
#   iv1-w2-min30                  IV1 all at minimum_seconds 30, so IV1 batching is exercised too
# Before each worker arm it waits (at most about 2 min) for the CPU to go quiet, so the machine
# gate's decision is not made against a busy moment; the gate still decides and is reported.
# Outputs under evidence/<tag>/ (never rewritten). summary.txt (wp18_parity_summary.py) fails
# closed: a missing arm, key or error, a differing record hash, or a worker arm that never started
# workers is FAIL, and this script then exits non-zero.
set -u
export PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
QUIET=${QUIET:-3.0}
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
TAG=$1; SHARDS=${2:-}
OUT="$G/evidence/$TAG"
RT="test:$T/gg/wp18-r2"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
[ -e "$OUT" ] && { echo "exists: $OUT (never rewritten)"; exit 2; }
SHARD_ARGS=()
[ -n "$SHARDS" ] && SHARD_ARGS=(--shard 0 --shards "$SHARDS")
mkdir -p "$OUT"
cd "$G/scripts"
quiet() {
  for attempt in 1 2 3 4 5 6; do
    "$PY" -B -I -c "import psutil,sys; b=psutil.cpu_percent(interval=5)*psutil.cpu_count()/100; print('$(date +%H:%M:%S) busy logical CPUs %.1f (quiet <= $QUIET)' % b); sys.exit(0 if b <= $QUIET else 1)" && return
    sleep 15
  done
  echo "CPU not quiet: running anyway (the gate decides; the summary fails a worker arm that never started)"
}
arm() {   # name supports width mode [extra args]
  local name=$1 supports=$2 width=$3 mode=$4; shift 4
  [ "$mode" = auto ] && quiet
  echo "$(date +%H:%M:%S) start $name"
  "$PY" -B endpoint_parity.py --runtime "$RT" --supports "$supports" --stream-width $width --workers 2 \
    --mode "$mode" "${SHARD_ARGS[@]}" "$@" --output "$OUT/$name.json" > "$OUT/$name.log" 2>&1
  echo "$(date +%H:%M:%S) $name exit $?"
  tail -2 "$OUT/$name.log" | cut -c1-600
}
arm iv2-serial "$G/evidence/final-f2/iv2-supports.jsonl.gz" "$W2" serial
arm iv2-w2 "$G/evidence/final-f2/iv2-supports.jsonl.gz" "$W2" auto
arm iv1-serial "$G/work/iv1-supports.jsonl.gz" "$W1" serial
arm iv1-w2 "$G/work/iv1-supports.jsonl.gz" "$W1" auto
arm iv1-w2-min30 "$G/work/iv1-supports.jsonl.gz" "$W1" auto --minimum-seconds 30
"$PY" -B -I wp18_parity_summary.py "$OUT" > "$OUT/summary.txt"; status=$?
cat "$OUT/summary.txt"
echo "$(date +%H:%M:%S) end summary exit $status"
exit $status
