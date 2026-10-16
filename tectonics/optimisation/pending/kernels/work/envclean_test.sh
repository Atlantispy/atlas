export PYTHONHASHSEED=0
for v in $(compgen -e | grep '^PYTHON'); do [ "$v" = PYTHONHASHSEED ] || unset "$v"; done   # cleaned env: seed 0 only (every runtime process pins it)
env | grep ^PYTHON
