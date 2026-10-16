"""Merge cProfile files and print self-time rankings (read-only analysis aid)."""
import os
import pstats
import sys


def short(fn):
    return os.path.basename(fn.replace(chr(92), "/"))


def main():
    n = int(sys.argv[1])
    files = sys.argv[2:]
    st = pstats.Stats(files[0])
    for f in files[1:]:
        st.add(f)
    tot = st.total_tt
    print(f"files={len(files)} total_tt={tot:.1f}s")
    rows = []
    for (fn, ln, name), (cc, nc, tt, ct, callers) in st.stats.items():
        rows.append((tt, ct, nc, fn, ln, name))
    rows.sort(reverse=True)
    for tt, ct, nc, fn, ln, name in rows[:n]:
        print(f"{tt:8.1f} {100*tt/tot:5.1f}% cum={ct:8.1f} calls={nc:>10} {short(fn)}:{ln} {name}")
    mods = {}
    for tt, ct, nc, fn, ln, name in rows:
        key = short(fn)
        if key == "~":
            key = name
        mods[key] = mods.get(key, 0) + tt
    print("--- by module")
    for k, v in sorted(mods.items(), key=lambda x: -x[1])[:30]:
        print(f"{v:8.1f} {100*v/tot:5.1f}% {k}")


if __name__ == "__main__":
    main()
