#!/usr/bin/env bash
# Complementary-cut certificate: parity and deep projection (PYTHONHASHSEED=0, as production).
#  1. IV1 surfaces, all: RC1+cpcut vs RC1 (byte; baseline evidence/wp23-seed0/iv1-surfaces-rc1).
#  2. IV2 1-in-10 sample, cap 2 s: RC1+cpcut vs RC1 (byte; baseline evidence/wp23-seed0/iv2-sample-rc1).
#  3. Every interface the RC1 sample capped at 2 s, rerun at cap 120 s under RC1, RC1+cpcut and
#     RC1+wp23rot+cpcut (job-balanced: the capped list is dealt round-robin into 6 files).
# One arm at a time, 6 processes (under 2 GiB, no lock). Evidence: evidence/cpcut-r1/.
set -u
export PYTHONHASHSEED=0   # production pins it; interface work units follow set order
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
OUT="$G/evidence/cpcut-r1"
B="$G/evidence/wp23-seed0"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
CP="test:$T/gg/cpcut-r1"
CPW="test:$T/gg/cpcut-wp23-r1"
mkdir -p "$OUT"
cd "$G/scripts"
run6 () {  # tag runtime supports partition interval width cap shards [extra args...] ; shard list fixed by $SHARDS
  local tag=$1 rt=$2 sup=$3 part=$4 iv=$5 w=$6 cap=$7 n=$8; shift 8; local pids=()
  for i in $SHARDS; do
    timeout 5400 "$PY" -B replay_surfaces.py --supports "$sup" --partition "$part" --interval "$iv" --stream-width $w \
      --runtime "$rt" --cap-cpu "$cap" --shard $i --shards "$n" --output "$OUT/$tag-s$i.jsonl" "$@" > "$OUT/$tag-s$i.log" 2>&1 &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  echo "done $tag $(date +%H:%M:%S)"
}
echo "start $(date +%H:%M:%S)"
SHARDS="0 1 2 3 4 5" run6 iv1-surfaces-cpcut "$CP" "$G/work/iv1-supports.jsonl.gz" "$G/work/next-iv1-rc1-r1.json.gz" "$G/work/iv1-interval-r1.json.gz" "$W1" 60 6
"$PY" -B -I compare_surfaces.py --baseline "$B/iv1-surfaces-rc1-s*.jsonl" --candidate "$OUT/iv1-surfaces-cpcut-s*.jsonl" > "$OUT/cmp-iv1-surfaces.json"; echo "iv1 surfaces exit $?"
SHARDS="0 10 20 30 40 50" run6 iv2-sample-cpcut "$CP" "$G/work/iv2-supports.jsonl.gz" "$G/work/iv2-partition-r1.json.gz" "$G/work/iv2-interval-only-r1.json.gz" "$W2" 2 60
"$PY" -B -I compare_surfaces.py --baseline "$B/iv2-sample-rc1-s*.jsonl" --candidate "$OUT/iv2-sample-cpcut-s*.jsonl" > "$OUT/cmp-iv2-sample.json"; echo "iv2 sample exit $?"
# The capped list from the seed-pinned RC1 sample, dealt into 6 job-balanced files.
"$PY" -B -I -c "
import glob, json, sys
rows = [json.loads(l) for p in sorted(glob.glob(sys.argv[1])) for l in open(p, encoding='utf8')]
capped = [dict(support_index=r['support_index'], cell=r['cell'], other=r.get('other'), constraint_name=r['constraint_name'])
          for r in rows if r.get('kind') == 'interface' and r['status'] == 'capped']
for i in range(6):
    with open(sys.argv[2] % i, 'x', encoding='utf8', newline='\n') as f:
        for row in capped[i::6]:
            f.write(json.dumps(row) + '\n')
print('capped interfaces', len(capped))
" "$B/iv2-sample-rc1-s*.jsonl" "$OUT/capped-list-%d.jsonl"
for arm in rc1 cpcut cpcut-wp23; do
  rt=rc1; [ $arm = cpcut ] && rt="$CP"; [ $arm = cpcut-wp23 ] && rt="$CPW"
  pids=()
  for i in 0 1 2 3 4 5; do
    timeout 5400 "$PY" -B replay_surfaces.py --supports "$G/work/iv2-supports.jsonl.gz" --partition "$G/work/iv2-partition-r1.json.gz" \
      --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --runtime "$rt" --cap-cpu 120 --kinds interface \
      --only-list "$OUT/capped-list-$i.jsonl" --output "$OUT/deep-$arm-s$i.jsonl" > "$OUT/deep-$arm-s$i.log" 2>&1 &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  echo "done deep-$arm $(date +%H:%M:%S)"
done
"$PY" -B -I compare_surfaces.py --baseline "$OUT/deep-rc1-s*.jsonl" --candidate "$OUT/deep-cpcut-s*.jsonl" > "$OUT/cmp-deep-rc1-cpcut.json"; echo "deep rc1 vs cpcut exit $?"
"$PY" -B -I compare_surfaces.py --baseline "$OUT/deep-cpcut-s*.jsonl" --candidate "$OUT/deep-cpcut-wp23-s*.jsonl" > "$OUT/cmp-deep-cpcut-wp23.json"; echo "deep cpcut vs cpcut+wp23 exit $?"
echo "end $(date +%H:%M:%S)"
