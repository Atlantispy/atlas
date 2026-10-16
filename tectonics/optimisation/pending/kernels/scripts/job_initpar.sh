#!/usr/bin/env bash
# Item 19 (r2.2) proof: route (1)'s admission on ck/ip8/src (composed-r2 src + transforms/initpar_r1.py +
# initpar/r2/integration_initial_parallel.py). Plan, workflow and bounds IDs depend on the native tree
# (smoke-s1: every plan ID differs from run A on another tree), so IDs are compared on THIS tree and the
# measurements themselves against run A's store with the execution identity re-derived.
# Usage: bash job_initpar.sh TAG smoke [W]           (small lane; W default 2)
#        bash job_initpar.sh TAG proof [W] SMOKE_W0   (q19; SMOKE_W0 = a passed smoke's w0/report.json)
#  smoke  seed = run A's store re-keyed to this tree's identity (store_rekey.py rekey), every query a hit:
#         w0  --workers=0 (no pass): the same-tree serial reference; --expect-store=seed (unchanged);
#         wW  --workers=W: the pass must launch nothing; --expect=w0 report (workflow ID, preparation IDs,
#             identities, store digest) and --expect-store=seed.
#  proof  wW --workers=W on a fresh store; then compare_reports.py wW vs SMOKE_W0 (workflow ID,
#         preparation IDs, every identity key, same tree and loaded modules).
#  both   store_rekey.py compare of every arm's final store vs run A's pinned store e337fc20: chunks
#         byte-equal in put order; each snapshot re-derived under run A's identity is byte-equal.
# FAIL CLOSED: exit 1 on any failed check, pin mismatch, or a candidate source change during the run.
# Each harness arm runs under scripts/peak_tree.py (tree peak = parent + workers, for TOTAL).
set -u
export PYTHONHASHSEED=0
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
R="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
H="$T/fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests"
PY="$T/.r44-env/Scripts/python.exe"
CK="$T/ck"
NATIVE="$CK/ip8/src"
MODULE_SHA=5ffc7fb2f5407e233d10ad1eb246b5ade17dc33d13005a44831a8853dffa7f5f
STORE_A="$R/s2/attempt-1/run-root/initial-measurements.sqlite"
STORE_A_SHA=e337fc205071fc6754b47b18f1c990fbfaec2162ae55cc3a1210cdbc9872ce81
TAG="${1:?tag}"; MODE="${2:?smoke|proof}"; W="${3:-2}"; REF="${4:-}"
OUT="$CK/initpar/$MODE-$TAG"
[ -e "$OUT" ] && { echo "$OUT exists"; exit 2; }
mkdir -p "$OUT"
cd "$CK/initpar"
sha () { sha256sum "$1" | cut -d' ' -f1; }
fail () { echo "FAIL: $*"; echo "end $(date +%H:%M:%S) exit 1"; exit 1; }
[ "$(sha "$STORE_A")" = "$STORE_A_SHA" ] || fail "run A store differs from its pin"
[ "$(sha "$NATIVE/atlas_tectonics/integration_initial_parallel.py")" = "$MODULE_SHA" ] || fail "module is not r2.2"
ROOTS=("$NATIVE" "$R/composed-r2/helpers" "$H")
(cd "$NATIVE" && find . -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum) > "$OUT/sources-start.sha256"
echo "start $(date +%H:%M:%S) mode $MODE workers $W native $NATIVE"
s=0
arm () {  # name, harness flags...
  local name=$1; shift
  "$PY" -B -I "$CK/scripts/peak_tree.py" "$MODE-$name" -- "$PY" -B time_admission_initpar.py "$@" \
    "$OUT/$name" "${ROOTS[@]}" > "$OUT/$name.log" 2>&1 || s=1
  tail -n 2 "$OUT/$name.log" | cut -c1-400
  "$PY" -B -I store_rekey.py compare "$OUT/$name/initial-measurements.sqlite" "$STORE_A@$STORE_A_SHA" \
    --report "$OUT/$name-store-compare.json" || s=1
}
if [ "$MODE" = smoke ]; then
  IDENT=$("$PY" -B ident.py "${ROOTS[@]}") || fail "identity"
  SEED_SHA=$("$PY" -B -I store_rekey.py rekey "$STORE_A@$STORE_A_SHA" "$IDENT" "$OUT/seed.sqlite") || fail "rekey"
  echo "identity $IDENT; seed $SEED_SHA"
  arm w0 --workers=0 "--seed-store=$OUT/seed.sqlite@$SEED_SHA" "--expect-store=$SEED_SHA"
  arm "w$W" --workers="$W" "--seed-store=$OUT/seed.sqlite@$SEED_SHA" "--expect-store=$SEED_SHA" \
    "--expect=$OUT/w0/report.json"
elif [ "$MODE" = proof ]; then
  [ -f "$REF" ] || fail "proof needs a passed smoke w0 report"
  arm "w$W" --workers="$W"
  "$PY" -B -I compare_reports.py compare "$OUT/w$W/report.json" "$REF" --report "$OUT/w$W-vs-w0.json" || s=1
  # The fresh (empty) store makes every query a miss: unless workers measured some of them, this run says
  # nothing about the parallel path (coordinator, 16 Oct). Fail closed on 0 or a missing count.
  STARTED=$("$PY" -B -I -c "import json,sys; p=(json.load(open(sys.argv[1])).get('initial_parallel') or {}); \
v=(p.get('stats') or {}).get('started'); a=p.get('adopted'); \
print(v if isinstance(v,int) and isinstance(a,int) else 'missing', a)" "$OUT/w$W/report.json" 2>&1)
  echo "workers_started adopted: $STARTED" | tee "$OUT/workers_started.txt"
  case "$STARTED" in ''|missing*|0\ *|*\ 0|*[!0-9\ ]*) echo "FAIL: no worker-measured positions ($STARTED)"; s=1;; esac
else
  fail "mode must be smoke or proof"
fi
(cd "$NATIVE" && find . -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum) > "$OUT/sources-end.sha256"
cmp -s "$OUT/sources-start.sha256" "$OUT/sources-end.sha256" || { echo "FAIL: candidate sources changed during the run"; s=1; }
echo "end $(date +%H:%M:%S) exit $s"
exit $s
