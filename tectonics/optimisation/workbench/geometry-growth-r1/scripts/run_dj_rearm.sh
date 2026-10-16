#!/usr/bin/env bash
# Re-run single D-j arms whose worker session the machine's CPU gate trimmed or refused (16 Oct:
# IV2 w6 found 1.66 free cores at session open and ran serial; its r2 rerun found 3.01 and ran two).
# For the coordinator's run queue:
#   runq.py run qNN -- <Git bash.exe> run_dj_rearm.sh <gen> iv2:6 [iv1:6 iv1:r4serial ...]
# <gen> is this rerun's generation, r2 or later (r2 was used at 13:5x; next is r3). Outputs are
# <set>-w<n>-<gen>.* and the merged summary folder is evidence/workers-dj-merged-<gen>; nothing that
# exists is ever rewritten (the script refuses instead).
# iv1:r4serial re-runs r2's IV1 serial pass (runtime gg/workers6-r4) with the current hex stream
# encoding. Whenever <set>-serial-r4enc.json exists, the merged r2view uses it as r2's serial.
# No lock of its own (runq holds it). Same runtime, inputs and arguments as
# run_workers_parity_dj.sh. Each arm starts from a fresh copy of its set's r6 serial store.
# Merged copy: each arm's newest rerun up to <gen> stands in for its first attempt (listed with
# shas in sources.txt); an arm named on this command line must have its <gen> output, or FAIL.
# Every attempt it replaced goes to <merged>/superseded and must be PASS or VOID there (round 3, P1).
# An attempt with no JSON (crashed or killed), a generation at or above <gen>, or an unknown attempt
# name refuses the start and FAILs the merge (round 3 re-review, P1).
# Before each arm it waits up to about 100 s (4 tries; the queue's rule for a harness's own wait is
# about 2 min) for a quiet CPU, at most QUIET busy logical CPUs over 5 s, then runs anyway: the gate
# decides, and summarise_dj.py reports a machine-trimmed arm as VOID-ENVIRONMENT (exit 3), never PASS.
# Exit: the summary's status (0 PASSED, 1 FAILED, 3 VOID-ENVIRONMENT); 2 on a refused start.
set -u
export PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
QUIET=${QUIET:-3.0}
TRIES=4
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
OUT="$G/evidence/workers-dj"
RT="test:$T/gg/workers6-r6"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
[ $# -ge 2 ] || { echo "usage: run_dj_rearm.sh <gen r2..> <set>:<workers> ..."; exit 2; }
gen=$1; shift
GN=${gen#r}
case $gen in r[0-9]*) ;; *) GN=x;; esac
# No leading zero (refuter 16 Oct, P3d): r02 would be a second generation 2 beside r2.
case $GN in ''|0*|*[!0-9]*) echo "bad generation $gen (want r2, r3, ...)"; exit 2;; esac
[ "$GN" -ge 2 ] || { echo "bad generation $gen (r1 is the first run)"; exit 2; }
M="$G/evidence/workers-dj-merged-$gen"
[ -e "$M" ] && { echo "exists: $M (never rewritten)"; exit 2; }
# A rerun must not hide an attempt that crashed or ran out of order (round 3 re-review, P1). Every
# attempt file in OUT is a first attempt <set>-w<n> or a rerun <set>-w<n>-r<k> (k >= 2, no leading
# zero) of an arm with a first attempt, at or below the generation allowed, and every log or store has
# its JSON: one without was crashed or killed, so its verdict is unknown. The start refuses (exit 2)
# and the merge FAILs (exit 1) on any line this prints, so such an attempt is ruled on before a later
# one can stand in for it.
audit () {  # <highest generation allowed>
  local f base stem rest n g set
  for f in "$OUT"/iv[12]-w* "$OUT"/iv[12]-store-w* "$OUT"/iv[12]-serial-r4enc.log "$OUT"/iv[12]-store-r4enc; do
    [ -e "$f" ] || continue
    base=${f##*/}
    case $base in
      iv[12]-serial-r4enc.log|iv[12]-store-r4enc)
        [ -e "$OUT/${base%%-*}-serial-r4enc.json" ] || echo "r4 serial with no JSON (crashed or killed): $base"
        continue;;
      *.json) stem=${base%.json};;
      *.log) stem=${base%.log};;
      iv[12]-store-w*) stem="${base%%-*}-${base#*-store-}";;
      *) echo "unknown file among the attempts: $base"; continue;;
    esac
    set=${stem%%-*}; rest=${stem#*-}
    n=${rest%%-*}
    case $n in w*) n=${n#w};; *) n=x;; esac
    case $n in ''|0*|*[!0-9]*|???*) echo "unknown file among the attempts: $base"; continue;; esac
    case $rest in
      *-*)
        g=${rest#*-}
        case $g in r*) g=${g#r};; *) g=x;; esac
        case $g in ''|0*|1|*[!0-9]*) echo "attempt with no generation number (r2 or later): $base"; continue;; esac
        [ "$g" -le "$1" ] || echo "generation above the one allowed (r$1): $base"
        [ -e "$OUT/$set-w$n.json" ] || echo "rerun of an arm with no first attempt: $base";;
    esac
    [ -e "$OUT/$stem.json" ] || echo "attempt with no JSON (crashed or killed): $base"
  done
}
seen=" "
for spec in "$@"; do
  set=${spec%%:*}; n=${spec##*:}
  case $set in iv1|iv2) ;; *) echo "unknown set $set"; exit 2;; esac
  case $n in r4serial) ;; ''|0*|*[!0-9]*) echo "bad workers $n"; exit 2;; esac
  # A repeated spec would copy a fresh store over the first pass's store and log (P3c).
  case $seen in *" $set:$n "*) echo "repeated $spec"; exit 2;; esac
  seen="$seen$set:$n "
  if [ "$n" = r4serial ]; then
    for p in "$OUT/$set-serial-r4enc.json" "$OUT/$set-store-r4enc" "$OUT/$set-serial-r4enc.log"; do
      [ -e "$p" ] && { echo "exists: $p (never rewritten)"; exit 2; }
    done
  else
    for p in "$OUT/$set-w$n-$gen.json" "$OUT/$set-store-w$n-$gen" "$OUT/$set-w$n-$gen.log"; do
      [ -e "$p" ] && { echo "exists: $p (never rewritten)"; exit 2; }
    done
  fi
done
problems=$(audit $((GN-1))
  for d in "$G/evidence"/workers-dj-merged-*; do
    [ -e "$d" ] || continue
    g=${d##*-r}
    case $g in ''|0*|1|*[!0-9]*) echo "merged folder with no generation number: ${d##*/}"; continue;; esac
    [ "$g" -lt "$GN" ] || echo "generation above the one allowed (r$((GN-1))): ${d##*/}"
  done)
[ -z "$problems" ] || { echo "$problems"; echo "refused: attempts above need a ruling first"; exit 2; }
cd "$G/scripts"
echo "start $gen $* $(date +%H:%M:%S)"
iv2=(--supports "$G/evidence/final-f2/iv2-supports.jsonl.gz" --partition "$G/evidence/final-f1/iv2-partition.grid.json.gz" --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --shard 0 --shards 20)
iv1=(--supports "$G/work/iv1-supports.jsonl.gz" --partition "$G/work/next-iv1-rc1-r1.grid.json.gz" --interval "$G/work/iv1-interval-r1.json.gz" --stream-width $W1 --minimum-seconds 1)
for spec in "$@"; do
  set=${spec%%:*}; n=${spec##*:}
  case $set in iv2) args=("${iv2[@]}");; iv1) args=("${iv1[@]}");; esac
  if [ "$n" = r4serial ]; then
    # The r2 IV1 serial (09:57) predates the 10:20 hex stream encoding, so its streams hash is
    # not comparable with r6's. Re-run that serial pass on r2's own runtime (gg/workers6-r4)
    # with the current harness; the summary's r2 view then uses it for the cross check.
    "$PY" -B parallel_parity.py --runtime "test:$T/gg/workers6-r4" "${args[@]}" --mode serial --workers 1 \
      --profile-store "$OUT/$set-store-r4enc" --output "$OUT/$set-serial-r4enc.json" > "$OUT/$set-serial-r4enc.log" 2>&1
    echo "done $set serial on workers6-r4 exit $? $(date +%H:%M:%S)"
    continue
  fi
  for attempt in $(seq 1 $TRIES); do
    "$PY" -B -I -c "import psutil,sys; b=psutil.cpu_percent(interval=5)*psutil.cpu_count()/100; print('$(date +%H:%M:%S) busy logical CPUs %.1f (quiet <= $QUIET)' % b); sys.exit(0 if b <= $QUIET else 1)" && break
    [ $attempt = $TRIES ] && { echo "CPU not quiet after $TRIES tries: running anyway (the gate decides; a machine trim is VOID, never PASS)"; break; }
    sleep 20
  done
  cp -r "$OUT/$set-store" "$OUT/$set-store-w$n-$gen"
  "$PY" -B parallel_parity.py --runtime "$RT" "${args[@]}" --mode auto --workers $n --profile-store "$OUT/$set-store-w$n-$gen" \
    --output "$OUT/$set-w$n-$gen.json" > "$OUT/$set-w$n-$gen.log" 2>&1
  echo "done $set w$n $gen exit $? $(date +%H:%M:%S)"
done
newest () {  # <set>-w<n>: path of its newest rerun output up to this generation, or nothing
  local best= bn=1 f g
  for f in "$OUT/$1"-r*.json; do
    [ -e "$f" ] || continue
    g=${f##*-r}; g=${g%.json}
    case $g in ''|0*|*[!0-9]*) continue;; esac   # r03 is no generation (P3d): it could tie r3
    [ "$g" -le "$GN" ] && [ "$g" -gt "$bn" ] && { best=$f; bn=$g; }
  done
  echo "$best"
}
problems=$(audit "$GN")
[ -z "$problems" ] || { echo "$problems"; echo "FAIL: attempts above cannot be judged; nothing merged"; exit 1; }
mkdir "$M" "$M/r2view" "$M/superseded" || exit 2
cp "$OUT"/*.json "$M"/
cp "$G/evidence/workers-six-r2"/*.json "$M/r2view"/
: > "$M/sources.txt"
for f in "$OUT"/iv[12]-w[0-9].json "$OUT"/iv[12]-w[0-9][0-9].json; do
  [ -e "$f" ] || continue
  b=$(basename "$f" .json); src=$(newest "$b"); [ -n "$src" ] || src=$f
  cp "$src" "$M/$b.json"
  echo "$b $(sha256sum "$src" | cut -c1-64) $(basename "$src")" >> "$M/sources.txt"
  # Every attempt up to <gen> that src replaced is judged too (refuter round 3, P1): the summary
  # FAILs unless each is PASS or VOID-ENVIRONMENT, so a rerun cannot hide a failed attempt.
  for a in "$f" "$OUT/$b"-r*.json; do
    [ -e "$a" ] && [ "$a" != "$src" ] || continue
    if [ "$a" != "$f" ]; then
      g=${a##*-r}; g=${g%.json}
      case $g in ''|0*|*[!0-9]*) continue;; esac
      [ "$g" -ge 2 ] && [ "$g" -le "$GN" ] || continue
    fi
    cp "$a" "$M/superseded/"
    echo "superseded/$(basename "$a") $(sha256sum "$a" | cut -c1-64)" >> "$M/sources.txt"
  done
done
for set in iv1 iv2; do
  if [ -e "$OUT/$set-serial-r4enc.json" ]; then
    # It stands in for r2's serial only if it ran r2's package (P3e).
    "$PY" -B -I -c "import json,sys; a,b=(json.load(open(p)).get('package_digest') for p in sys.argv[1:]); sys.exit(0 if a and a == b else 1)" \
      "$OUT/$set-serial-r4enc.json" "$G/evidence/workers-six-r2/$set-serial.json" \
      || { echo "FAIL: $set r4 serial is not r2's package"; exit 1; }
    cp "$OUT/$set-serial-r4enc.json" "$M/r2view/$set-serial.json"
    echo "r2view/$set-serial $(sha256sum "$OUT/$set-serial-r4enc.json" | cut -c1-64) $set-serial-r4enc.json" >> "$M/sources.txt"
  fi
done
for spec in "$@"; do
  set=${spec%%:*}; n=${spec##*:}
  if [ "$n" = r4serial ]; then
    [ -e "$OUT/$set-serial-r4enc.json" ] || { echo "FAIL: no $set r4 serial output"; exit 1; }
  else
    # Without this generation's output the merged copy would keep an older attempt: fail instead.
    [ -e "$OUT/$set-w$n-$gen.json" ] && cmp -s "$OUT/$set-w$n-$gen.json" "$M/$set-w$n.json" \
      || { echo "FAIL: no $set w$n $gen output in the merged copy"; exit 1; }
  fi
done
cat "$M/sources.txt"
"$PY" -B -I summarise_dj.py "$M" "$M/r2view" > "$M/summary.txt"; status=$?; echo "summary exit $status"
cat "$M/summary.txt"
echo "end $(date +%H:%M:%S)"
exit $status
