"""Count how often the fuzz's candidate calls took the G-PY route (non-None) vs fallback."""
import runpy, sys, collections
FILE = sys.argv[2]
import importlib.util
counts = collections.Counter()
orig_exec = importlib.util.spec_from_file_location
def patched(name, path, *a, **k):
    spec = orig_exec(name, path, *a, **k)
    loader_exec = spec.loader.exec_module
    def exec_module(m):
        loader_exec(m)
        for fn in ('_gpy_mul', '_gpy_div'):
            f = getattr(m, fn)
            def w(*args, _f=f, _n=fn):
                try:
                    r = _f(*args)
                except Exception:
                    counts[_n + ':raise'] += 1
                    raise
                counts[_n + (':fast' if r is not None else ':fallback')] += 1
                return r
            setattr(m, fn, w)
    spec.loader.exec_module = exec_module
    return spec
importlib.util.spec_from_file_location = patched
sys.argv = ['fuzz_gpy.py'] + sys.argv[1:]
try:
    runpy.run_path('fuzz_gpy.py', run_name='__main__')
except SystemExit:
    pass
print(dict(counts))
