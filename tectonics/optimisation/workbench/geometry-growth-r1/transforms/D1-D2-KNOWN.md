# D1 incidence_constant and D2 rotated_hoist: known limits

Both transforms give byte-identical records on every runtime route. A refutation pass on 16 Oct
found no counterexample, and its fuzz compared each helper with the original by repr:

- D1: about 118k cases over two runtimes, with -0, 0E+5, -0E-7, 3E+5, underflowing 1E-600000,
  80-digit endpoints and J.z jets;
- D2: about 28k cases, both exact interval algebras, with zero rates and zero or point posed endpoints.

The transforms' docstrings claim more than holds for inputs built by hand. The gaps are listed
below, each with the reason no runtime route reaches it. The docstrings will be narrowed at each
transform's next revision; until then, this file is the reference. It is kept outside the
transforms so their pinned bytes do not change.

## K1 (D1): an exception in a skipped coefficient is not raised

The fast path reads only coefficient 0 of the four jets; coefficients 1 to 12 are skipped. The full
expression `J.sub(J.mul(a[0], b[1]), J.mul(a[1], b[0]))[0]` computes them all. So an exception
that only a skipped coefficient would raise does not happen on the fast path. Two cases were seen
with the q2 algebra and leading values 1, 1, 2, 3:

- Coefficient 1 holding `(1E+600000, 1E+600000)`: the helper returns `(-5, -5)`, while the full
  expression raises `decimal.Overflow`.
- Coefficient 1 holding a `Fraction` pair: the helper returns `-5`, while the full expression raises
  `TypeError` (no Fraction-to-Decimal conversion).

Why no runtime route reaches it:
- Every jet that `contains()` passes in is built by operations of the unbudgeted q2 algebra
  (`constant`, `scale`, `_dot`, `_cross`, `_rotated`, `_reduced_normal`). So every coefficient is a
  prec-80 Decimal interval.
- Magnitudes near the Decimal context's Emax (about 1E+499999) are already outside the domain stated
  in D1's docstring.

## K2 (D1 and D2): the guards check the class, not its methods

The fast paths are guarded by `type(...) is` on `_Jets`, `_Intervals` and `_RationalIntervals`.
A subclass fails the guard and takes the original code. But an instance of the exact class whose
method has been replaced passes the guard and takes the fast path. That applies to a replacement
on the instance (for example `J.I.point = wrapper`) or on the class itself. In one such case D2
made 21 `point` calls where the original loop made 114; the result repr was the same.

So the claim in D2's docstring that "an instrumented one keeps the original loop" holds only for
subclasses.

Why no runtime route reaches it:
- No runtime module or transform assigns to an algebra's methods.
- The test instruments the algebras with subclasses only.
- A test that replaces a method on an exact instance must expect the fast path, and must not take
  that instance's call log as the original order of operations.

## Test notes (test_d1_d2.py)

- The 'no add of zero' mutant needs both products to have a zero endpoint (a -0 upper endpoint
  that only the add of zero turns into +0). The first corpus caught it in 2 of 980 D1 cases. With a
  band weighted to zero endpoints, it caught 6. The corpus now ends with 60 cases that have only
  signed-zero leads, and catches it in 17. The test requires at least 10.
- The fast-path counts (`d1_fast`, `d2_fast`) restate each guard. The test also observes the branch
  taken: D1's fallback calls `J.sub`, and D2's fast path makes fewer `point` calls than the
  original loop. It counts those calls with a wrapper on the instance (an exact-type instance
  takes the fast path, per K2). The branch observed must equal the guard case by case, both in the
  corpus and in situ. The in-situ byte identity of records, work units and leaves is the check that
  binds.
- Under `python -I`, `PYTHONHASHSEED` is ignored, so each process has its own string-hash seed. The
  test's children first ran that way. How many times D1 was called in situ, and how many calls took
  the fast path, changed with the seed: in one query, two runs made 2829 calls (2553 fast) and 2136
  calls (none fast). The records, work units and leaves were identical in both runs. Work units can
  follow set order, and production pins seed 0. So the children now start with `-s -P`, a cleaned
  environment and PYTHONHASHSEED=0, and each refuses unless `sys.flags.hash_randomization` is 0.
