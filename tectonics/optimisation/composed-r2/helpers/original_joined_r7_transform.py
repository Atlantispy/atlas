"""r6 -> r7 text of the original joined-control helper (16 Oct 2026, audit D4(ii)).

The Step 10 heat bundle composes this helper itself (private_heat_bundle.joined_driver_source).
r7_source() turns that r6 text into r7: the owned two-scalar account inspection reads through
heat_cold_patch.ledger_access, because a compact r13 CompactHeatSnapshot has no _metadata.
A native snapshot keeps r6's exact branch. Every anchor must occur exactly once.
R/private_heat_original_joined_r7.py is r7_source() of composed-r1's r6, byte for byte.
"""

R6_NOTE = ('R6 exposes the existing native partition component work ceiling, retaining the 8192\n'
           'default and refusing non-positive or non-integer selections before work.\n"""\n')
R7_NOTE = ('R6 exposes the existing native partition component work ceiling, retaining the 8192\n'
           'default and refusing non-positive or non-integer selections before work.\n'
           'R7 (16 Oct 2026) changes one account edit only: the two exact scalars of the owned\n'
           'account inspection are read through heat_cold_patch.ledger_access. A compact r13\n'
           'heat snapshot has no _metadata and is read through its ledger record; a native\n'
           'snapshot keeps r6\'s exact decode branch. Nothing else differs from r6.\n"""\n')
OLD_INSPECTION = (
    '     "    import private_heat_joined_consumer_r6 as _joined\\n"\n'
    '     "    heat = result.exterior._heat\\n"\n'
    '     "    if type(heat) is _joined.LiveJoinedHeat:\\n"\n'
    '     "        _joined.verify_live(heat, cancel=cancel)\\n"\n'
    '     "        with _joined.R.decoded(heat._result._snapshot._metadata,\\n"\n'
    '     "                budget=heat._budget, cancel=cancel) as decoded:\\n"\n')
NEW_INSPECTION = (
    '     "    import heat_cold_patch as _HEAT_COLD\\n"\n'
    '     "    import private_heat_joined_consumer_r6 as _joined\\n"\n'
    '     "    heat = result.exterior._heat\\n"\n'
    '     "    if type(heat) is _joined.LiveJoinedHeat:\\n"\n'
    '     "        _joined.verify_live(heat, cancel=cancel)\\n"\n'
    '     "        with _HEAT_COLD.ledger_access(heat._result._snapshot,\\n"\n'
    '     "                budget=heat._budget, cancel=cancel, resources=_joined.R) as decoded:\\n"\n')
REPLACEMENTS = (
    ('r7-note', R6_NOTE, R7_NOTE),
    ('compact-aware-two-scalar-inspection', OLD_INSPECTION, NEW_INSPECTION),
    ('derivation-schema', "    return dict(schema='atlas.private.original-joined-derivation.r6',",
     "    return dict(schema='atlas.private.original-joined-derivation.r7',"),
    ('exec-tag', "str(_SOURCE)+'[private_heat_original_joined_r6]'", "str(_SOURCE)+'[private_heat_original_joined_r7]'"),
)


def r7_source(r6_text):
    """The exact r7 text; refuses unless every r6 anchor occurs exactly once."""
    if type(r6_text) is not str:
        raise TypeError('r6 helper text required')
    text = r6_text
    for label, before, after in REPLACEMENTS:
        if text.count(before) != 1:
            raise ValueError('joined helper r6 anchor missing or ambiguous: '+label)
        text = text.replace(before, after, 1)
    return text
