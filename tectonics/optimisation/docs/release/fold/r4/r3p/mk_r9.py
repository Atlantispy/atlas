"""Write run_parity_r9.sh from run_parity_r8.sh. The changes:
- the composition and the fold output, with their pins;
- the arms become arms_r8 (arms_r7 with the native library record, RF2 condition c), which brings hcf_prepare_r15,
  the gmpy2 build record, the tight sizes and the cell-key save;
- bookings and limbs become v27 (r3);
- a tool-pin check;
- an r2 reference arm R, one child, used only for the keyed cell match;
- the keyed cell checks cells-ra (R vs A) and cells-ab (A vs B);
- the MPFR check mpfr (v27/mpfr_same.py).

    python -B mk_r9.py R8_SH R9_SH COMPOSITION_DIR COMPOSITION_SHA256 FOLD_DIR MANIFEST_SHA256

COMPOSITION_DIR is the name under ac/ (p20c-r3) and FOLD_DIR the name under rm/fold (out-c3). Every edit replaces one
whole r8 line, which must occur exactly once, with one or more lines. The script then diffs the two files (difflib)
and refuses unless the removed lines are exactly the edited r8 lines and the added lines are exactly their
replacements. R9_SH must not exist.
"""
import difflib
import re
import sys
from pathlib import Path

R2_SHA = '5ff62b90f38059a76323f4b7387774c96f602ec46a414bb091d212b428b5f0b1'


def edits(comp, comp_sha, fold, man_sha):
    book = {name: ('run %s "$V/bookings.py" %s' % (name, rest), 'run %s "$F/v27/bookings.py" %s' % (name, rest))
            for name, rest in (
                ('book-ab', '"$O/a" "$O/oa" "$O/b" "$O/ob" "$O/b/MANIFEST-h.json" "$O/book-ab.json"'),
                ('book-a2b', '"$O/a" "$O/oa2" "$O/b" "$O/ob" "$O/b/MANIFEST-h.json" "$O/book-a2b.json"'),
                ('book-ab2', '"$O/a" "$O/oa" "$O/b" "$O/ob2" "$O/b/MANIFEST-h.json" "$O/book-ab2.json"'))}
    return [
        ('# R2 parity run: run_parity_r7.sh on p20c-r2 and its fold out-c2; only the inputs, their pins, the records '
         'checker (v26 r3) and the arms (arms_r6: hcf_prepare_r14) differ. Small lane,',
         ['# R3 parity run: run_parity_r8.sh on %s and its fold %s with arms r7 (hcf_prepare_r15, the gmpy2 build '
          'record, tight sizes, the cell-key save), bookings and limbs r3 (v27), a tool-pin check, an r2 reference '
          'arm and the keyed cell checks. Small lane,' % (comp, fold)]),
        ('#   runq small --gib 2 -- bash run_parity_r8.sh WORKSPACE OUT',
         ['#   runq small --gib 2 -- bash run_parity_r9.sh WORKSPACE OUT']),
        ('#   ac/p20c-r2/composition.json  5ff62b90  (the R2 target)',
         ['#   ac/%s/composition.json  %s  (the R3 target)' % (comp, comp_sha[:8]),
          '#   ac/p20c-r2/composition.json  5ff62b90  (the reference arm R: one child, for the keyed cell match only)']),
        ("#   rm/fold/out-c2/MANIFEST.json  91800707  (its fold; B's arm record pins the same manifest)",
         ["#   rm/fold/%s/MANIFEST.json  %s  (its fold; B's arm record pins the same manifest)" % (fold, man_sha[:8]),
          '#   rm/fold/r3p/tools-frozen.sha256: every tool this script runs has its reviewed sha']),
        ("#   book-ab, book-a2b, book-ab2  bookings.py A vs B, A' vs B and A vs B'; same-bookings: the three reports are",
         ["#   book-ab, book-a2b, book-ab2  v27/bookings.py A vs B, A' vs B and A vs B'; same-bookings: the three "
          "reports are"]),
        ("#   limbs  v25/limbs_r2.py: A vs A' and B vs B' with no size difference, A vs B within the net per-row cap",
         ["#   limbs  v27/limbs_r3.py: A vs A' and B vs B' with no size difference, A vs B within the one-sided net "
          "per-row cap",
          '#   cells-ra  v27/cells_keyed.py R vs A: every cell matched by the mixed key (exterior logical_cell_id,',
          '#            collar physical_cell_id) with its values bitwise, 172 exterior and 64 collar; the report',
          '#            states the match count',
          '#   cells-ab  v27/cells_keyed.py A vs B (the fold, one composition), the same counts',
          '# Every child also saves its arrays and cell keys, with physical_cell_id, into OUT/<child>/save (arms_r8).',
          "#   mpfr  v27/mpfr_same.py: one libmpfr in each child (R, A, A', B, B') at RF2's exec_prefix path, one file",
          '#         everywhere; each worker with a snapshot at most one, the same file (RF2 condition c)']),
        ('P="$T/ac/p20c-r2"', ['P="$T/ac/%s"' % comp, 'P2="$T/ac/p20c-r2"']),
        ('FOLD="$F/out-c2"', ['FOLD="$F/%s"' % fold]),
        ('PIN_P="%s"' % R2_SHA, ['PIN_P="%s"' % comp_sha, 'PIN_P2="%s"' % R2_SHA]),
        ('PIN_FOLD="91800707f602db36fe1f8528deaf84d4ace05b426a1b3e5e5968a1f49e29f1ea"', ['PIN_FOLD="%s"' % man_sha]),
        ('pin "$P/composition.json" "$PIN_P"', ['pin "$P/composition.json" "$PIN_P"',
                                                 'pin "$P2/composition.json" "$PIN_P2"']),
        ('pin "$FOLD/MANIFEST.json" "$PIN_FOLD"',
         ['pin "$FOLD/MANIFEST.json" "$PIN_FOLD"',
          'sha256sum --strict --quiet -c "$F/r3p/tools-frozen.sha256" || { echo "a tool pin differs '
          '(r3p/tools-frozen.sha256)"; exit 1; }',
          'echo "r9 $(sha256sum "$0" | cut -c1-64)"']),
        ('"$PY" -B "$F/arms_r6.py" prepare-a "$O/a" "$P" "$HCF" "$CTL" "$P/composition.json"',
         ['"$PY" -B "$F/arms_r8.py" prepare-a "$O/a" "$P" "$HCF" "$CTL" "$P/composition.json"']),
        ('"$PY" -B "$F/arms_r6.py" prepare-b "$O/b" "$FOLD" "$O/a"',
         ['"$PY" -B "$F/arms_r8.py" prepare-b "$O/b" "$FOLD" "$O/a"',
          'echo "prepare-r $(date +%H:%M:%S) from p20c-r2"',
          '"$PY" -B "$F/arms_r8.py" prepare-a "$O/r" "$P2" "$HCF" "$CTL" "$P2/composition.json"']),
        ('for arm in "a oa" "b ob" "a oa2" "b ob2"; do', ['for arm in "a oa" "b ob" "a oa2" "b ob2" "r or"; do']),
        ('  "$PY" -B "$F/arms_r6.py" child "$O/$1" "$O/$2" || echo "child $2 exit $?"',
         ['  "$PY" -B "$F/arms_r8.py" child "$O/$1" "$O/$2" || echo "child $2 exit $?"']),
    ] + [(old, [new]) for old, new in book.values()] + [
        ('run limbs "$V/limbs_r2.py" "$V" "$O/b/MANIFEST-h.json" "$O/limbs.json" "$O/a" "$O/oa" "$O/a" "$O/oa2" '
         '"$O/b" "$O/ob" \\',
         ['run limbs "$F/v27/limbs_r3.py" "$F/v27" "$O/b/MANIFEST-h.json" "$O/limbs.json" "$O/a" "$O/oa" "$O/a" '
          '"$O/oa2" "$O/b" "$O/ob" \\']),
        ('echo "end $(date +%H:%M:%S)"',
         ['run cells-ra "$F/v27/cells_keyed.py" "$O/or/save" "$O/oa/save" "$O/cells-ra.json" 172 64',
          'run cells-ab "$F/v27/cells_keyed.py" "$O/oa/save" "$O/ob/save" "$O/cells-ab.json" 172 64',
          'run mpfr "$F/v27/mpfr_same.py" "$O/mpfr.json" "$O/or" "$O/oa" "$O/oa2" "$O/ob" "$O/ob2"',
          'echo "end $(date +%H:%M:%S)"']),
    ]


def main(argv):
    if len(argv) != 6:
        print(__doc__)
        return 2
    r8, r9 = Path(argv[0]), Path(argv[1])
    comp, comp_sha, fold, man_sha = argv[2:]
    if not all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name) for name in (comp, fold)) \
            or not all(re.fullmatch(r'[0-9a-f]{64}', sha) for sha in (comp_sha, man_sha)):
        print('FAIL: names must be plain folder names and pins 64 lower-case hex digits')
        return 1
    old_lines = r8.read_text(encoding='utf8').split('\n')
    table = edits(comp, comp_sha, fold, man_sha)
    for old, _ in table:
        if old_lines.count(old) != 1:
            print('FAIL: r8 line not found exactly once as a whole line: %s' % old)
            return 1
    replace = dict(table)
    new_lines = [line for old in old_lines for line in replace.get(old, [old])]
    expect_removed = [old for old in old_lines if old in replace and old not in replace[old]]
    expect_added = [line for old in old_lines if old in replace for line in replace[old] if line != old]
    removed, added = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes():
        if tag != 'equal':
            removed += old_lines[i1:i2]
            added += new_lines[j1:j2]
    if removed != expect_removed or added != expect_added:
        print('FAIL: the diff is not exactly the declared edits')
        return 1
    with open(r9, 'x', encoding='utf8', newline='\n') as f:
        f.write('\n'.join(new_lines))
    for line in removed:
        print('- ' + line)
    for line in added:
        print('+ ' + line)
    print('OK: %d lines removed, %d added; %s written' % (len(removed), len(added), r9.name))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
