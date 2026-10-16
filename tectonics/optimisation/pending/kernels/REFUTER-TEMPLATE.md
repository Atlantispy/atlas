# Refuter / helper prompt template (T/ck)

Every helper or refuter prompt from this chat carries these lines verbatim:

- Never grep, walk or find from T's root. Use explicit subpaths only (for example T/ck, T/hs/scripts, T/gg/final-f2),
  and always exclude bridge (`grep --exclude-dir=bridge`, `find ... -path '*/bridge' -prune`). Never touch T/bridge.
- Read-only outside your own report folder. No installs, no downloads, no git writes.
- Any process that imports the runtime runs at seed 0: no `-I`, PYTHONHASHSEED=0 with other PYTHON* variables unset,
  and a fail-closed `sys.flags.hash_randomization == 0` check. `-I` only for helpers that never import the runtime.
- Small-lane only for runs (`T/q/runq.py small [--cores N] -- cmd`); stop only PIDs you started.
- Report: verdict first (REFUTED / NOT REFUTED), then numbered defects with reproducer paths.
