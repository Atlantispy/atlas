import sys, importlib
sys.path[:0] = ['C:/Users/LOCAL_USER/h13l1/runtime-src', 'C:/Users/LOCAL_USER/h13l1/helpers']
for name in sys.argv[1:]:
    try:
        importlib.import_module(name); status = 'ok'
    except Exception as e:
        status = '%s: %s' % (type(e).__name__, str(e)[:80])
    print(name, status, '| scipy.linalg loaded:', 'scipy.linalg' in sys.modules, '| numba loaded:', 'numba' in sys.modules)
