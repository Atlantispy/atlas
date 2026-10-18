#!/usr/bin/env bash
# Re-run single D-j arms whose worker session the machine's CPU gate trimmed or refused (16 Oct:
# IV2 w6 found 1.66 free cores at session open and ran serial; its r2 rerun found 3.01 and ran two).
# For the coordinator's run queue:
#   runq.py run qNN -- <Git bash.exe> run_dj_rearm.sh <gen> iv2:6 [iv1:6 iv1:r4serial ...]
# <gen> is this rerun's generation, r2 or later (r2 was used at 13:5x; r3 is D08-excluded; next is r4).
# Outputs are <set>-w<n>-<gen>.* and the merged summary folder is evidence/workers-dj-merged-<gen>;
# nothing that exists is ever rewritten (the script refuses instead).
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
#
# Revision r5 (Plan 03 / D08, 18 Oct 2026; supersedes staged candidates r2, r3, and r4):
# - Prefixes Git usr/bin to child PATH without altering global PATH or shared runq.py.
# - Bounds the entire preflight probe and failure/cleanup path with finite deadlines via GNU timeout -k:
#   functional probe under DJ_PREFLIGHT_TIMEOUT_S (default 60s), scratch removal before invoking PY,
#   fallback scratch cleanup bounded by DJ_CLEANUP_TIMEOUT_S (default 2s) via rm without re-entering PY,
#   and exact preserved leftover scratch path reported on every failed probe (timeout or normal failure)
#   before exiting 2 prior to any attempt output.
# - Preflights all 13 external utilities (bash timeout date seq cp rm sleep mkdir basename sha256sum
#   cut cmp cat), selected Python interpreter (fail-closed PYTHONHASHSEED=0 / hash_randomization==0 +
#   psutil), and a tiny disposable synthetic directory copy before creating any output paths or logs.
#   Note: --preflight-only is an environment + named-D08 check; ordinary launch runs the full audit.
# - Recognises only the D08 fact-bound invalid-launch orphan (iv2-w6-r3.log: 0 B, sha256 e3b0c442...,
#   mtime 2026-10-16T20:22:00.860677600Z, absent .json/store/merged-r3, and outer dj-rearm-r3-q21b.log
#   sha256 3ba3da59...) for generations >= r4, retaining it in merged provenance under excluded/ and
#   sources.txt as INVALID_LAUNCH_ENVIRONMENT_D08 while refusing if modified or if any other orphan exists.
# - Explicitly checks the input-store cp -r result and verifies copied bytes (full file cmp -s for the
#   regular-file iv1-store/iv2-store; top-level regular-file cmp -s + immediate subdirectory check for
#   synthetic directory fixtures) before opening the attempt log or invoking parallel_parity.py.
# - Test-only override seams (inactive unless set by test_summarise_dj_r5.py on a temporary script copy):
#   DJ_GIT_USR_BIN, DJ_PYTHONHASHSEED, DJ_PREFLIGHT_TMP, DJ_PREFLIGHT_TIMEOUT_S, DJ_CLEANUP_TIMEOUT_S,
#   and PY basename stub.sh.
# Exit: the summary's status (0 PASSED, 1 FAILED, 3 VOID-ENVIRONMENT); 2 on a refused start/preflight.
set -u
export PYTHONHASHSEED=${DJ_PYTHONHASHSEED:-0} PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
GIT_USR_BIN=${DJ_GIT_USR_BIN:-/usr/bin}
export PATH="$GIT_USR_BIN${PATH:+:$PATH}"
PF_TIMEOUT=${DJ_PREFLIGHT_TIMEOUT_S:-60}
PF_CLN_TIMEOUT=${DJ_CLEANUP_TIMEOUT_S:-2}
QUIET=${QUIET:-3.0}
TRIES=4
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
OUT="$G/evidence/workers-dj"
RT="test:$T/gg/workers6-r6"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"

preflight () {
  local u p pf_dir pf_rc pf_leftover
  case $PF_TIMEOUT in ''|0*|*[!0-9]*) echo "preflight failed: invalid timeout $PF_TIMEOUT"; return 1;; esac
  case $PF_CLN_TIMEOUT in ''|0*|*[!0-9]*) echo "preflight failed: invalid cleanup timeout $PF_CLN_TIMEOUT"; return 1;; esac
  for u in bash timeout date seq cp rm sleep mkdir basename sha256sum cut cmp cat; do
    p=$(type -P "$u" 2>/dev/null) || { echo "preflight failed: missing utility $u"; return 1; }
    [ -n "$p" ] && [ -x "$p" ] || { echo "preflight failed: non-executable utility $u"; return 1; }
  done
  [ -x "$PY" ] || { echo "preflight failed: missing python interpreter $PY"; return 1; }
  pf_dir="${DJ_PREFLIGHT_TMP:-${TMPDIR:-${TEMP:-/tmp}}}/dj-preflight-$$"
  [ ! -e "$pf_dir" ] || { echo "preflight failed: scratch path exists $pf_dir"; return 1; }
  timeout -k 1 "$PF_TIMEOUT" bash -c '
    set -u
    pf_dir=$1; PY=$2; G=$3
    d_out=$(date +%H:%M:%S 2>/dev/null) || { echo "preflight failed: date execution"; exit 1; }
    case $d_out in [0-9][0-9]:[0-9][0-9]:[0-9][0-9]) ;; *) echo "preflight failed: date output $d_out"; exit 1;; esac
    s_out=$(seq 1 3 2>/dev/null) || { echo "preflight failed: seq execution"; exit 1; }
    [ "$s_out" = "$(printf "1\n2\n3")" ] || { echo "preflight failed: seq output"; exit 1; }
    sleep 0 >/dev/null 2>&1 || { echo "preflight failed: sleep execution"; exit 1; }
    mkdir "$pf_dir" "$pf_dir/src" "$pf_dir/src/sub" 2>/dev/null || { echo "preflight failed: mkdir"; exit 1; }
    printf "atlas-pf-a\n" > "$pf_dir/src/a.txt" || { echo "preflight failed: write a.txt"; exit 1; }
    printf "atlas-pf-b\n" > "$pf_dir/src/sub/b.txt" || { echo "preflight failed: write b.txt"; exit 1; }
    [ "$(cat "$pf_dir/src/a.txt" 2>/dev/null)" = "atlas-pf-a" ] || { echo "preflight failed: cat"; exit 1; }
    cp -r "$pf_dir/src" "$pf_dir/dst" 2>/dev/null || { echo "preflight failed: synthetic cp -r"; exit 1; }
    [ -f "$pf_dir/dst/a.txt" ] && [ -f "$pf_dir/dst/sub/b.txt" ] || { echo "preflight failed: copied files missing"; exit 1; }
    cmp -s "$pf_dir/src/a.txt" "$pf_dir/dst/a.txt" 2>/dev/null || { echo "preflight failed: cmp a.txt"; exit 1; }
    cmp -s "$pf_dir/src/sub/b.txt" "$pf_dir/dst/sub/b.txt" 2>/dev/null || { echo "preflight failed: cmp b.txt"; exit 1; }
    ! cmp -s "$pf_dir/src/a.txt" "$pf_dir/dst/sub/b.txt" 2>/dev/null || { echo "preflight failed: cmp false-positive"; exit 1; }
    [ "$(basename "$pf_dir/dst/a.txt" .txt 2>/dev/null)" = "a" ] || { echo "preflight failed: basename"; exit 1; }
    a_sha=$(sha256sum "$pf_dir/dst/a.txt" 2>/dev/null | cut -c1-64) || { echo "preflight failed: sha256sum/cut"; exit 1; }
    b_sha=$(sha256sum "$pf_dir/dst/sub/b.txt" 2>/dev/null | cut -c1-64) || { echo "preflight failed: sha256sum/cut"; exit 1; }
    [ "$a_sha" = "dfecd001254f833cd7ffa09075365a1aadf1630861e2071b01017d436a9223da" ] \
      && [ "$b_sha" = "34f567bc5142e1a088f4466e906c3df9fe2a63002ebb24247b99744fef8750f5" ] \
      || { echo "preflight failed: sha256sum digest"; exit 1; }
    rm -rf "$pf_dir" 2>/dev/null || { echo "preflight failed: rm scratch"; exit 1; }
    [ ! -e "$pf_dir" ] || { echo "preflight failed: scratch dir remained $pf_dir"; exit 1; }
    "$PY" -B -c "import os, sys, psutil; sys.exit(0 if not sys.flags.hash_randomization and os.environ.get(\"PYTHONHASHSEED\") == \"0\" and hasattr(psutil, \"cpu_percent\") else 1)" >/dev/null 2>&1 \
      || { echo "preflight failed: python/hash_seed/psutil"; exit 1; }
    if [ "${PY##*/}" != "stub.sh" ]; then
      [ -f "$G/scripts/parallel_parity.py" ] && [ -f "$G/scripts/summarise_dj.py" ] && [ -f "$G/scripts/rc1_env.py" ] \
        || { echo "preflight failed: missing harness scripts in $G/scripts"; exit 1; }
    fi
    exit 0
  ' _ "$pf_dir" "$PY" "$G"
  pf_rc=$?
  pf_leftover=""
  if [ -d "$pf_dir" ]; then
    timeout -k 1 "$PF_CLN_TIMEOUT" rm -rf "$pf_dir" >/dev/null 2>&1 || true
    [ ! -d "$pf_dir" ] || pf_leftover=" (leftover scratch: $pf_dir)"
  fi
  if [ "$pf_rc" -eq 124 ] || [ "$pf_rc" -eq 137 ]; then
    echo "preflight failed: timed out after ${PF_TIMEOUT}s (exit $pf_rc)${pf_leftover}"
    return 1
  fi
  if [ "$pf_rc" -ne 0 ]; then
    [ -z "$pf_leftover" ] || echo "preflight failed: probe exit ${pf_rc}${pf_leftover}"
    return 1
  fi
  [ -z "$pf_leftover" ] || { echo "preflight failed: scratch cleanup incomplete${pf_leftover}"; return 1; }
  return 0
}

copy_input_store () {
  # For the selected regular-file iv1-store (18,962 B) and iv2-store (15,314 B), cmp -s verifies
  # complete file byte identity. The directory branch supports synthetic test fixtures by checking
  # top-level regular files with cmp -s and immediate subdirectory presence.
  local src=$1 dst=$2 f rel
  [ -e "$src" ] && [ ! -e "$dst" ] || return 1
  cp -r "$src" "$dst" || return 1
  if [ -f "$src" ]; then
    [ -f "$dst" ] && cmp -s "$src" "$dst" || return 1
  elif [ -d "$src" ]; then
    [ -d "$dst" ] || return 1
    for f in "$src"/*; do
      [ -e "$f" ] || continue
      rel=${f##*/}
      if [ -f "$f" ]; then
        [ -f "$dst/$rel" ] && cmp -s "$f" "$dst/$rel" || return 1
      elif [ -d "$f" ]; then
        [ -d "$dst/$rel" ] || return 1
      fi
    done
  else
    return 1
  fi
  return 0
}

audit () {  # <highest generation allowed>
  local f base stem rest n g set
  d08_ruled_orphan_ok () {
    [ -f "$OUT/iv2-w6-r3.log" ] && [ ! -L "$OUT/iv2-w6-r3.log" ] && [ ! -s "$OUT/iv2-w6-r3.log" ] || return 1
    [ ! -e "$OUT/iv2-w6-r3.json" ] && [ ! -L "$OUT/iv2-w6-r3.json" ] || return 1
    [ ! -e "$OUT/iv2-store-w6-r3" ] && [ ! -L "$OUT/iv2-store-w6-r3" ] || return 1
    [ ! -e "$G/evidence/workers-dj-merged-r3" ] && [ ! -L "$G/evidence/workers-dj-merged-r3" ] || return 1
    [ "$(date -u -r "$OUT/iv2-w6-r3.log" +"%Y-%m-%dT%H:%M:%S.%NZ" 2>/dev/null)" = "2026-10-16T20:22:00.860677600Z" ] || return 1
    [ "$(sha256sum "$OUT/iv2-w6-r3.log" 2>/dev/null | cut -c1-64)" = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" ] || return 1
    [ -f "$G/work/dj-rearm-r3-q21b.log" ] && [ ! -L "$G/work/dj-rearm-r3-q21b.log" ] || return 1
    [ "$(sha256sum "$G/work/dj-rearm-r3-q21b.log" 2>/dev/null | cut -c1-64)" = "3ba3da59468bb4db3bc3a3fffd2c4ed0f263aafd2589364e7804285674fc1e3f" ] || return 1
    return 0
  }
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
    if [ ! -e "$OUT/$stem.json" ]; then
      if [ "$base" = "iv2-w6-r3.log" ] && [ "$1" -ge 3 ] && d08_ruled_orphan_ok; then
        continue
      fi
      echo "attempt with no JSON (crashed or killed): $base"
    fi
  done
}

if [ "${1:-}" = "--preflight-only" ]; then
  [ $# -eq 1 ] || { echo "usage: run_dj_rearm_r5.sh --preflight-only"; exit 2; }
  preflight || exit 2
  # Parent audit call defines d08_ruled_orphan_ok in the current shell namespace.
  audit 3 >/dev/null
  d08_ruled_orphan_ok || { echo "preflight failed: D08 ruled orphan state mismatch"; exit 2; }
  echo "PREFLIGHT OK $(date +%H:%M:%S) bash=$(type -P bash) timeout=$(type -P timeout) cp=$(type -P cp) rm=$(type -P rm) sha256sum=$(type -P sha256sum) py=$PY timeout_s=$PF_TIMEOUT d08_orphan=INVALID_LAUNCH_ENVIRONMENT_VERIFIED"
  exit 0
fi

[ $# -ge 2 ] || { echo "usage: run_dj_rearm.sh <gen r2..> <set>:<workers> ..."; exit 2; }
gen=$1; shift
GN=${gen#r}
case $gen in r[0-9]*) ;; *) GN=x;; esac
# No leading zero (refuter 16 Oct, P3d): r02 would be a second generation 2 beside r2.
case $GN in ''|0*|*[!0-9]*) echo "bad generation $gen (want r2, r3, ...)"; exit 2;; esac
[ "$GN" -ge 2 ] || { echo "bad generation $gen (r1 is the first run)"; exit 2; }
M="$G/evidence/workers-dj-merged-$gen"
[ -e "$M" ] && { echo "exists: $M (never rewritten)"; exit 2; }
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
preflight || exit 2
problems=$(audit $((GN-1))
  for d in "$G/evidence"/workers-dj-merged-*; do
    [ -e "$d" ] || continue
    g=${d##*-r}
    case $g in ''|0*|1|*[!0-9]*) echo "merged folder with no generation number: ${d##*/}"; continue;; esac
    [ "$g" -lt "$GN" ] || echo "generation above the one allowed (r$((GN-1))): ${d##*/}"
  done)
[ -z "$problems" ] || { echo "$problems"; echo "refused: attempts above need a ruling first"; exit 2; }
cd "$G/scripts" || exit 2
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
  if ! copy_input_store "$OUT/$set-store" "$OUT/$set-store-w$n-$gen"; then
    echo "FAIL: input-store copy failed for $set w$n $gen"
    exit 1
  fi
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
# Parent audit call defines d08_ruled_orphan_ok in the current shell namespace after the $() subshell above.
audit "$GN" >/dev/null
mkdir "$M" "$M/r2view" "$M/superseded" || exit 2
cp "$OUT"/*.json "$M"/ || exit 1
cp "$G/evidence/workers-six-r2"/*.json "$M/r2view"/ || exit 1
: > "$M/sources.txt"
for f in "$OUT"/iv[12]-w[0-9].json "$OUT"/iv[12]-w[0-9][0-9].json; do
  [ -e "$f" ] || continue
  b=$(basename "$f" .json); src=$(newest "$b"); [ -n "$src" ] || src=$f
  cp "$src" "$M/$b.json" || exit 1
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
    cp "$a" "$M/superseded/" || exit 1
    echo "superseded/$(basename "$a") $(sha256sum "$a" | cut -c1-64)" >> "$M/sources.txt"
  done
done
if [ "$GN" -ge 4 ] && d08_ruled_orphan_ok; then
  mkdir "$M/excluded" || exit 1
  cp "$OUT/iv2-w6-r3.log" "$M/excluded/iv2-w6-r3.log" || exit 1
  cp "$G/work/dj-rearm-r3-q21b.log" "$M/excluded/dj-rearm-r3-q21b.log" || exit 1
  echo "excluded/iv2-w6-r3.log $(sha256sum "$OUT/iv2-w6-r3.log" | cut -c1-64) INVALID_LAUNCH_ENVIRONMENT_D08 mtime=2026-10-16T20:22:00.860677600Z bytes=0" >> "$M/sources.txt"
  echo "excluded/dj-rearm-r3-q21b.log $(sha256sum "$G/work/dj-rearm-r3-q21b.log" | cut -c1-64) INVALID_LAUNCH_ENVIRONMENT_D08 ticket=q21 exit=15" >> "$M/sources.txt"
  [ -f "$M/excluded/iv2-w6-r3.log" ] && cmp -s "$OUT/iv2-w6-r3.log" "$M/excluded/iv2-w6-r3.log" \
    && [ -f "$M/excluded/dj-rearm-r3-q21b.log" ] && cmp -s "$G/work/dj-rearm-r3-q21b.log" "$M/excluded/dj-rearm-r3-q21b.log" \
    && [ ! -e "$M/iv2-w6-r3.json" ] && [ ! -e "$M/superseded/iv2-w6-r3.json" ] \
    || { echo "FAIL: D08 excluded provenance missing or invalid in merged copy"; exit 1; }
fi
for set in iv1 iv2; do
  if [ -e "$OUT/$set-serial-r4enc.json" ]; then
    # It stands in for r2's serial only if it ran r2's package (P3e).
    "$PY" -B -I -c "import json,sys; a,b=(json.load(open(p)).get('package_digest') for p in sys.argv[1:]); sys.exit(0 if a and a == b else 1)" \
      "$OUT/$set-serial-r4enc.json" "$G/evidence/workers-six-r2/$set-serial.json" \
      || { echo "FAIL: $set r4 serial is not r2's package"; exit 1; }
    cp "$OUT/$set-serial-r4enc.json" "$M/r2view/$set-serial.json" || exit 1
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
