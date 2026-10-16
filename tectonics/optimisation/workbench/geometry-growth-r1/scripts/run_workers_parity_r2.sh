#!/usr/bin/env bash
# Worker-cap lift parity r2: RC1's router with automatic workers at 1, 2, 4 and 6 on the candidate
# runtime + workers_six + workers_six_endpoint_clamp (gg/workers6-r4). Each set: a serial pass
# writes the timing store; each worker arm starts from its own copy. Records and streams must be
# byte-identical across serial, 1, 2, 4 and 6, AND the 4- and 6-worker arms must actually run more
# than two batch workers at once (read-only sampler in parallel_parity.py), or the arm fails.
#   IV1: all supports, minimum_seconds 1 (IV1 surfaces are cheap; this makes the batches engage).
#   IV2: candidate partition, supports with index % 20 == 0, default policy thresholds.
# One arm at a time. Memory (measured in r1 smoke): parent < 0.5 GB, a batch child about 0.2 GB, so
# 6 workers about 1.7 GB; the lock declares 4 GiB TOTAL. Before taking the lock, free memory must
# cover the 4 GiB total + the 1 GiB floor + 4 GiB headroom. PYTHONHASHSEED=0.
set -u
export PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
OUT="$G/evidence/workers-six-r2"
RT="test:$T/gg/workers6-r4"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
mkdir -p "$OUT"
cd "$G/scripts"
for attempt in $(seq 1 240); do
  if "$PY" -B -I -c "import psutil,sys; sys.exit(0 if psutil.virtual_memory().available >= 9*2**30 else 1)"; then
    HEAVY_LOCK_WINPID=$(cat /proc/$$/winpid) "$PY" -B heavy_lock.py acquire $$ 4.0 "geometry chat: worker-count parity r2, ONE arm at a time, parent + up to 6 workers (TOTAL)" > /dev/null && break
  fi
  [ $attempt = 240 ] && { echo "gave up waiting for the lock or free memory"; exit 3; }
  sleep 60
done
trap '"$PY" -B heavy_lock.py release $$' EXIT
echo "lock acquired after $attempt attempt(s) $(date +%H:%M:%S); available $("$PY" -B -I -c "import psutil; print(round(psutil.virtual_memory().available/2**30,1))") GiB"
run_set () {  # name supports grid interval width extra...
  local name=$1 sup=$2 grid=$3 iv=$4 w=$5; shift 5
  local common=(--runtime "$RT" --supports "$sup" --partition "$grid" --interval "$iv" --stream-width $w "$@")
  "$PY" -B parallel_parity.py "${common[@]}" --mode serial --workers 1 --profile-store "$OUT/$name-store" --output "$OUT/$name-serial.json" > "$OUT/$name-serial.log" 2>&1
  echo "done $name serial $(date +%H:%M:%S)"
  for n in 1 2 4 6; do
    cp -r "$OUT/$name-store" "$OUT/$name-store-w$n"
    "$PY" -B parallel_parity.py "${common[@]}" --mode auto --workers $n --profile-store "$OUT/$name-store-w$n" --output "$OUT/$name-w$n.json" > "$OUT/$name-w$n.log" 2>&1
    echo "done $name w$n $(date +%H:%M:%S)"
  done
}
run_set iv1 "$G/work/iv1-supports.jsonl.gz" "$G/work/next-iv1-rc1-r1.grid.json.gz" "$G/work/iv1-interval-r1.json.gz" "$W1" --minimum-seconds 1
run_set iv2 "$G/evidence/final-f2/iv2-supports.jsonl.gz" "$G/evidence/final-f1/iv2-partition.grid.json.gz" "$G/work/iv2-interval-only-r1.json.gz" "$W2" --shard 0 --shards 20
"$PY" -B -I summarise_workers_parity.py "$OUT" > "$OUT/summary.txt"; echo "summary exit $?"
cat "$OUT/summary.txt"
echo "end $(date +%H:%M:%S)"
