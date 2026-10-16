"""Rebuild the pre-R2 run_prepared_restart.py by reversing the 16 Oct edits.

Usage: python -B reconstruct_runner_before.py EXPECTED_SHA256 OUT.py
Reverses exactly the four textual changes (COMPACT_MODULES, new_retained_scope,
the pre-seal call site and comment, the _successor_checks docstring) and
writes OUT only if the result hashes to EXPECTED_SHA256 (the package origin).
"""
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2]/'run_prepared_restart.py'

EDITS = (
    ("    'historical_compact_heat', 'bounded_preseal')",
     "    'historical_compact_heat')"),
    ('''def new_retained_scope(budget):
    # The runner advances the live interval, so its scope carries the named
    # live-producer child (coordinator decision D2-A): in-memory producer
    # records are booked there, and the 256 MiB aggregate keeps meaning views
    # and caches. The independent reader creates its own cold scope without it.
    # A child cap above its run budget would be meaningless (the parent always
    # governs), so a smaller test budget gets a child no larger than itself.
    from content_cache import LIVE_PRODUCER_BYTES, create_retained_scope
    return create_retained_scope(budget, process_epoch='prepared-restart-'+str(os.getpid()),
                                 live_producer_bytes=min(LIVE_PRODUCER_BYTES, budget.max_bytes))''',
     '''def new_retained_scope(budget):
    from content_cache import create_retained_scope
    return create_retained_scope(budget, process_epoch='prepared-restart-'+str(os.getpid()))'''),
    ('''                            if compact:
                                if after is None:      # root-only: store already sealed (line 636); unchanged
                                    record['record_identities'] = reader.endpoint_record_identities(workflow)
                                else:
                                    # R2 option A (coordinator decision, 16 Oct 2026): bounded
                                    # pre-seal checks of this unsealed interval only, no
                                    # per-scalar decode; the fresh reader re-derives the rest.
                                    import bounded_preseal as PRESEAL
                                    evidence = PRESEAL.bounded_preseal(workflow, store=store, before=before,
                                        after=after, budget=base._budget, cancel=check)
                                    record['record_identities'] = evidence.pop('record_identities')
                                    record['preseal_bounded_check'] = evidence
                                    save()
                                    store.seal_and_promote(after['head'])
                                record['compact_operations'] = store.statistics()
                        # publish_and_reopen cold-reopened the published root in
                        # this process. The successor is not reopened here (owner
                        # decision 14 Oct 2026): _advance_checked ran the cheap
                        # structural checks, bounded_preseal ran the bounded
                        # pre-seal checks (R2 option A), and the mandatory
                        # independent fresh-process reader performs the successor
                        # cold reopen and per-scalar re-derivation on the sealed file.''',
     '''                            if compact:
                                record['record_identities'] = reader.endpoint_record_identities(workflow)
                                if after is not None:
                                    store.seal_and_promote(after['head'])
                                record['compact_operations'] = store.statistics()
                        # publish_and_reopen cold-reopened the published root in
                        # this process. The successor is not reopened here (owner
                        # decision 14 Oct 2026): _advance_checked ran the cheap
                        # structural checks and the mandatory independent
                        # fresh-process reader performs the successor cold reopen.'''),
    ('''    inspect() on the live workflow is cheap when the driver's own publication
    adopted the store token it produced inside its writer transaction (R2
    option A, publication_token_transform); if any other write intervened the
    token stays unset and the native _refresh re-validates the persisted chain
    and restores its head (slower, never weaker). The successor is not
    re-validated per scalar before the seal: bounded_preseal runs the bounded
    pre-seal checks and the fresh reader re-derives every record on the sealed
    file. ``store`` is the workflow's store captured before the driver. A''',
     '''    inspect() on the live workflow is cheap when the driver's own publication
    left it at the current store token; a workflow left stale makes the native
    _refresh re-validate the persisted chain and restore its head (slower, never
    weaker). ``store`` is the workflow's store captured before the driver. A'''),
)


def main():
    expected, out = sys.argv[1], Path(sys.argv[2])
    text = SOURCE.read_bytes().decode('utf8')
    for new, old in EDITS:
        if text.count(new) != 1:
            raise SystemExit('edit not found exactly once: '+new[:60])
        text = text.replace(new, old)
    actual = sha256(text.encode('utf8')).hexdigest()
    if actual != expected:
        raise SystemExit('reconstruction differs: '+actual)
    out.write_bytes(text.encode('utf8'))
    print('reconstructed', actual, '->', out)


if __name__ == '__main__':
    main()
