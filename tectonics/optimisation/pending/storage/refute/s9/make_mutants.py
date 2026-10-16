import sys, pathlib
S = pathlib.Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/so/s9')
D = pathlib.Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/so/refute/s9/mutants')
src = (S/'private_heat_indexed_runtime.py').read_text()
muts = {
  'no_sha': ("len(blob) == size and sha256(blob).hexdigest() == ident", "len(blob) == size"),
  'no_loop_check': ("        view._check()\n        blob = reader(ident, size)", "        blob = reader(ident, size)"),
  'no_iterjson_guard': ("view._segment is not None or\n            hasattr(reader, 'iter_json') or hasattr(reader, 'export')):", "view._segment is not None):"),
  'no_owner_count': ("    if len(owners) != 1:\n        return None\n", ""),
  'skip_last_blob': ("for index in range(len(arrays['s.id'])):", "for index in range(len(arrays['s.id'])-1):"),
  'no_loop_rcheck': ("        del blob, owner\n        R.check(cancel)\n", "        del blob, owner\n"),
  'no_source_check': ("        check_unchanged()\n    identity", "        pass\n    identity"),
}
for name, (old, new) in muts.items():
    assert src.count(old) == 1, name
    (D/name).mkdir(parents=True, exist_ok=True)
    (D/name/'private_heat_indexed_runtime.py').write_text(src.replace(old, new))
print('made', list(muts))
