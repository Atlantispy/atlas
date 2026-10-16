CK="$(cygpath -m "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)")"
CK="$("$(dirname "$CK")/.r44-env/Scripts/python.exe" -B -I -c "import os,sys; print(os.path.realpath(sys.argv[1]).replace(chr(92), '/'))" "$CK")" || exit 2   # canonical case: compare_ab_r2 matches roots case-sensitively
T="$(dirname "$CK")"
echo "$CK | $T"
