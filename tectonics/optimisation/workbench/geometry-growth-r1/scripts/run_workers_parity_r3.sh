#!/usr/bin/env bash
# D-j proof: workers_six + workers_six_rolling_interfaces (+ endpoint clamp), runtime gg/workers6-r5.
# Arms w4 and w6 on the IV2 1-in-20 sample (the case where r2's selection gave the interface pass to
# the single-contact route) and on IV1. Baselines are r2's serial passes (gg/workers6-r4; the serial
# arm never opens a worker route, so its records are the reference for both runtimes), copied in
# with their timing stores; each arm starts from its own store copy. Gate (summarise_workers_parity):
# byte-identical records and streams AND more than two live batch workers at w4/w6.
# The lock declares 4 GiB TOTAL after a free-memory check. PYTHONHASHSEED=0.
set -u
export PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
OUT="$G/evidence/workers-six-r3"
R2="$G/evidence/workers-six-r2"
RT="test:$T/gg/workers6-r5"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
mkdir -p "$OUT"
cd "$G/scripts"
for f in iv1-serial.json iv1-serial.log iv2-serial.json iv2-serial.log iv1-store iv2-store; do cp -p "$R2/$f" "$OUT/$f"; done
for attempt in $(seq 1 480); do
  if "$PY" -B -I -c "import psutil,sys; sys.exit(0 if psutil.virtual_memory().available >= 9*2**30 else 1)"; then
    HEAVY_LOCK_WINPID=$(cat /proc/$$/winpid) "$PY" -B heavy_lock.py acquire $$ 4.0 "geometry chat: D-j rolling-interfaces parity, ONE arm at a time, parent + up to 6 workers (TOTAL)" > /dev/null && break
  fi
  [ $attempt = 480 ] && { echo "gave up waiting for the lock or free memory"; exit 3; }
  sleep 30
done
trap '"$PY" -B heavy_lock.py release $$' EXIT
echo "lock acquired after $attempt attempt(s) $(date +%H:%M:%S)"
iv2=(--supports "$G/evidence/final-f2/iv2-supports.jsonl.gz" --partition "$G/evidence/final-f1/iv2-partition.grid.json.gz" --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --shard 0 --shards 20)
iv1=(--supports "$G/work/iv1-supports.jsonl.gz" --partition "$G/work/next-iv1-rc1-r1.grid.json.gz" --interval "$G/work/iv1-interval-r1.json.gz" --stream-width $W1 --minimum-seconds 1)
for set in iv2 iv1; do
  for n in 4 6; do
    cp -r "$OUT/$set-store" "$OUT/$set-store-w$n"
    if [ $set = iv2 ]; then args=("${iv2[@]}"); else args=("${iv1[@]}"); fi
    "$PY" -B parallel_parity.py --runtime "$RT" "${args[@]}" --mode auto --workers $n --profile-store "$OUT/$set-store-w$n" --output "$OUT/$set-w$n.json" > "$OUT/$set-w$n.log" 2>&1
    echo "done $set w$n $(date +%H:%M:%S)"
  done
done
"$PY" -B -I summarise_workers_parity.py "$OUT" > "$OUT/summary.txt"; echo "summary exit $?"
cat "$OUT/summary.txt"
echo "end $(date +%H:%M:%S)"
