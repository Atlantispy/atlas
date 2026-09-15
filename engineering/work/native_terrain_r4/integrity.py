"""Versioned active-body commitment over authenticated immutable R3 history.

This digest is deliberately NOT the R2/R3 full scientific-body SHA256. It binds
the active body and every ordered history reference, including logical/frame
hashes, sizes, codec and authenticated summaries. Each hot call rereads and
hashes every compressed frame; no timestamp, persistent verification token or
raw-history cache establishes trust. Frozen entries come only from R3 append
or from_refs, which already authenticate their summary-to-logical-row mapping.

Load/import must retain from_refs canonical/summary authentication. Save uses
verify_history(full=True) to retain R3's streamed decompression and logical-hash
check, without adding a full JSON parse. scientific_sha exposes the unchanged
legacy body digest when an explicit parity comparison needs it. These checks
share R3's cooperative-file threat model, not a malicious in-process boundary.
"""
import hashlib
from pathlib import Path

from work.native_terrain_r3 import history as h
from work.native_terrain_r3 import provenance as retained


SCHEMA = 'diadem.native-history-commitment.r4'


def _verify_source():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != globals().get('_R12_EXECUTED_SHA256'):
        raise ValueError('executed history integrity source differs; no repin')


def verify_history(history, *, full=False):
    """Return a fresh, ordered reference snapshot after checking actual bytes.

    full=False checks each compressed frame against its previously authenticated
    immutable entry. full=True additionally decodes/checks the logical bytes,
    as R3 save did. Both modes use one bounded record at a time and check the
    loaded codec; neither trusts file metadata as evidence of unchanged content.
    """
    _verify_source()
    h._verify_source()
    if type(history) is not h.History or type(full) is not bool:
        raise ValueError('exact archive-backed history and boolean verification mode required')
    if h._encoded(h.compression.identity()) != history._codec_bytes:
        raise ValueError('archive compression identity changed')
    entries = history._entries
    for entry in entries:
        if entry.codec_bytes != history._codec_bytes:
            raise ValueError('archive compression identity changed')
        if full:
            history._raw(entry)
        else:
            frame = h._read(history.root / entry.path, entry.frame_size_bytes)
            if hashlib.sha256(frame).hexdigest() != entry.frame_sha256:
                raise ValueError('immutable compressed frame hash differs')
    references = [entry.reference() for entry in entries]
    if history._entries is not entries:
        raise ValueError('accepted history changed during integrity verification')
    return references


def commitment(body):
    """Hash an explicit R4 projection, never masquerading as the legacy SHA."""
    _verify_source()
    if type(body) is not dict or type(body.get('history')) is not h.History:
        raise ValueError('complete active body with archive-backed history required')
    projected = dict(body, history=verify_history(body['history']))
    return retained.retained.sha({'schema': SCHEMA, 'body': projected})


def scientific_sha(body):
    """Stream the exact original R2/R3 scientific-body SHA256, with raw checks."""
    _verify_source()
    return retained.sha(body)
