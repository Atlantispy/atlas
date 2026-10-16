"""Print the top callers (by time attributed) of functions matching a pattern."""
import os
import pstats
import sys


def short(fn):
    return os.path.basename(fn.replace(chr(92), "/"))


def main():
    pattern = sys.argv[1]
    n = int(sys.argv[2])
    files = sys.argv[3:]
    st = pstats.Stats(files[0])
    for f in files[1:]:
        st.add(f)
    for (fn, ln, name), (cc, nc, tt, ct, callers) in st.stats.items():
        label = f"{short(fn)}:{ln} {name}"
        if pattern not in label:
            continue
        print(f"== {label} self={tt:.1f} cum={ct:.1f} calls={nc}")
        rows = sorted(callers.items(), key=lambda kv: -kv[1][3])
        for (cfn, cln, cname), (ccc, cnc, ctt, cct) in rows[:n]:
            print(f"    {cct:8.1f} cum {ctt:8.1f} self calls={cnc:>10} <- {short(cfn)}:{cln} {cname}")


if __name__ == "__main__":
    main()
