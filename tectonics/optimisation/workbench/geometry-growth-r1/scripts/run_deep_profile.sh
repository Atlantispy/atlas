#!/usr/bin/env bash
# cProfile of the deep IV2 interfaces on a given composition, serial, for backlog item 4 (WP23
# remainder) and WP24 (shared with the compiled-kernels chat; it replaces their cancelled q07).
# The set is work/deep49-list.jsonl: the 36 of evidence/wp22-profile/cand-deep-s0 plus the 13 of
# ck/geo/deep16.jsonl not already in them (supports index the same decompressed
# final-f1 = final-f2 IV2 supports). For the run queue:
#   runq.py run qNN -- <Git bash.exe> run_deep_profile.sh <tag> [<composition folder under T>] [<list>]
# (<list> for a smoke only: a subset of deep49-list.jsonl; same script, arguments and layout.)
# No lock of its own (runq holds it). Outputs under evidence/<tag>/:
#   each/NNN-s<support>-<cell>.prof   raw pstats per interface (cumulative and own time)
#   merged.prof                       pstats merge of all of them
#   merged-tottime.txt, merged-cumulative.txt   top 60 lines of each, for reading
#   deep49.jsonl, deep49.log, compare-vs-wp22.json (numbers of the 36 vs the wp22 baseline)
set -u
export PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
TAG=$1; COMP=${2:-gg/workers6-r6}; LIST=${3:-$G/work/deep49-list.jsonl}
OUT="$G/evidence/$TAG"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
[ -e "$OUT" ] && { echo "exists: $OUT (never rewritten)"; exit 2; }
mkdir -p "$OUT"
cd "$G/scripts"
echo "$(date +%H:%M:%S) start $COMP"
"$PY" -B replay_surfaces.py --supports "$G/evidence/final-f2/iv2-supports.jsonl.gz" \
  --partition "$G/evidence/final-f1/iv2-partition.grid.json.gz" --interval "$G/work/iv2-interval-only-r1.json.gz" \
  --stream-width $W2 --runtime "test:$T/$COMP" --cap-cpu 120 --kinds interface \
  --only-list "$LIST" --profile-each "$OUT/each" --profile "$OUT/merged.prof" \
  --output "$OUT/deep49.jsonl" > "$OUT/deep49.log" 2>&1
replay=$?
echo "$(date +%H:%M:%S) replay exit $replay"
# Fail closed: every listed interface must have a row with a status and its own profile file.
"$PY" -B -I -c "
import json, os, sys
out, want = sys.argv[1], sum(1 for line in open(sys.argv[2]) if line.strip())
rows = [json.loads(line) for line in open(out + '/deep49.jsonl') if line.strip()] if os.path.exists(out + '/deep49.jsonl') else []
rows = [r for r in rows if r.get('kind') == 'interface']
profiles = [r for r in rows if r.get('status') and r.get('profile') and os.path.exists(out + '/each/' + r['profile'])]
print('interfaces %d of %d; with status and profile file %d; statuses %s' % (
    len(rows), want, len(profiles), sorted({str(r.get('status')) for r in rows})))
sys.exit(0 if len(rows) == want == len(profiles) and os.path.exists(out + '/merged.prof') else 1)
" "$OUT" "$LIST"
complete=$?
echo "completeness exit $complete"
"$PY" -B -I -c "
import pstats, sys
for key, name in (('tottime', 'merged-tottime.txt'), ('cumulative', 'merged-cumulative.txt')):
    with open(sys.argv[1] + '/' + name, 'w', encoding='utf8') as f:
        pstats.Stats(sys.argv[1] + '/merged.prof', stream=f).sort_stats(key).print_stats(60)
" "$OUT"
text=$?
echo "text summaries exit $text"
# The wp22 baseline predates measure_sha_nodigest, so compare numbers (bounds, leaves, work units, rule).
"$PY" -B -I compare_surfaces.py --numbers --baseline "$G/evidence/wp22-profile/cand-deep-s0.jsonl" \
  --candidate "$OUT/deep49.jsonl" > "$OUT/compare-vs-wp22.json" 2>&1
echo "compare exit $?"
tail -c 700 "$OUT/compare-vs-wp22.json"
echo "$(date +%H:%M:%S) end"
# The wp22 comparison is informational (another composition); the profile itself must be whole.
[ $replay -eq 0 ] && [ $complete -eq 0 ] && [ $text -eq 0 ]
