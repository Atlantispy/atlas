#!/usr/bin/env bash
# Worker-cap lift parity r2, IV2 set only (rerun). The first r2 run's IV2 arms all stopped in the
# HARNESS: Streams used repr(), and IV2's exact rationals exceed Python's 4,300-digit decimal
# conversion limit (serial included; runtime not involved). parallel_parity.py now encodes stream
# values exactly in hex. IV1 (passed: serial/1/2/4/6 identical, peak live 4 and 5 at w4/w6) is not
# rerun. Same runtime (gg/workers6-r4), same policy, one arm at a time, lock declares 4 GiB TOTAL
# after a free-memory check (total + 1 GiB floor + 4 GiB headroom). PYTHONHASHSEED=0.
set -u
export PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
OUT="$G/evidence/workers-six-r2"
RT="test:$T/gg/workers6-r4"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
cd "$G/scripts"
mkdir -p "$OUT/iv2-first-attempt-harness-repr"
for f in "$OUT"/iv2-*; do [ -f "$f" ] && mv "$f" "$OUT/iv2-first-attempt-harness-repr/"; done
for attempt in $(seq 1 240); do
  if "$PY" -B -I -c "import psutil,sys; sys.exit(0 if psutil.virtual_memory().available >= 9*2**30 else 1)"; then
    HEAVY_LOCK_WINPID=$(cat /proc/$$/winpid) "$PY" -B heavy_lock.py acquire $$ 4.0 "geometry chat: worker-count parity r2 IV2 rerun, ONE arm at a time, parent + up to 6 workers (TOTAL)" > /dev/null && break
  fi
  [ $attempt = 240 ] && { echo "gave up waiting for the lock or free memory"; exit 3; }
  sleep 60
done
trap '"$PY" -B heavy_lock.py release $$' EXIT
echo "lock acquired after $attempt attempt(s) $(date +%H:%M:%S); available $("$PY" -B -I -c "import psutil; print(round(psutil.virtual_memory().available/2**30,1))") GiB"
common=(--runtime "$RT" --supports "$G/evidence/final-f2/iv2-supports.jsonl.gz" --partition "$G/evidence/final-f1/iv2-partition.grid.json.gz" --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --shard 0 --shards 20)
"$PY" -B parallel_parity.py "${common[@]}" --mode serial --workers 1 --profile-store "$OUT/iv2-store" --output "$OUT/iv2-serial.json" > "$OUT/iv2-serial.log" 2>&1
echo "done iv2 serial $(date +%H:%M:%S)"
for n in 1 2 4 6; do
  cp -r "$OUT/iv2-store" "$OUT/iv2-store-w$n"
  "$PY" -B parallel_parity.py "${common[@]}" --mode auto --workers $n --profile-store "$OUT/iv2-store-w$n" --output "$OUT/iv2-w$n.json" > "$OUT/iv2-w$n.log" 2>&1
  echo "done iv2 w$n $(date +%H:%M:%S)"
done
"$PY" -B -I summarise_workers_parity.py "$OUT" > "$OUT/summary.txt"; echo "summary exit $?"
cat "$OUT/summary.txt"
echo "end $(date +%H:%M:%S)"
