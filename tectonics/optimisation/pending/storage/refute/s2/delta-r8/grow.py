import sys, psutil
mode = sys.argv[1]
n, chunk = 182 << 20, 5 << 20
if mode == 'append':
    out = bytearray()
    for _ in range(n // chunk):
        out += bytes(chunk)
elif mode == 'prealloc':
    out = bytearray(n)
    for i in range(n // chunk):
        out[i*chunk:(i+1)*chunk] = bytes(chunk)
mi = psutil.Process().memory_info()
print(mode, 'peak_wset MiB %.0f' % (mi.peak_wset / 2**20), 'len MiB', len(out) >> 20)
