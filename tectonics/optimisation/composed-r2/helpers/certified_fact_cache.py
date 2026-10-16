"""Opt-in cross-query *certified* facts; no runtime hook or activation here.

The exact-geometry owner must construct every operand and parameter binding,
verify certificates, and measure the runtime path before enabling this cache.
Budget/cancellation/time/partial-proof declines are never certified facts.
"""
from __future__ import annotations

from dataclasses import dataclass

from content_cache import ContentCache, Owned, _key, check_cancel


def fact_key(*, process_epoch, predicate_kind, operands, parameters,
             method_identity, execution_identity, certificate_schema,
             verifier_schema):
    """Bind exact ordered role-labelled bytes; no assumed predicate symmetry."""
    if type(predicate_kind) is not str or not predicate_kind:
        raise ValueError('predicate kind must be nonempty text')
    fields = [('predicate-kind', predicate_kind.encode('utf-8'))]
    for prefix, values in (('operand:', operands), ('parameter:', parameters)):
        seen = set()
        for role, exact in values:
            if type(role) is not str or not role or role in seen:
                raise ValueError('operand/parameter roles must be nonempty and unique')
            if type(exact) is not bytes:
                raise TypeError('operands/parameters must use exact immutable bytes')
            seen.add(role)
            fields.append((prefix + role, exact))
    for name, value in (('method', method_identity), ('execution', execution_identity),
                        ('certificate-schema', certificate_schema),
                        ('verifier-schema', verifier_schema)):
        if type(value) is not bytes or not value:
            raise ValueError(name + ' requires exact nonempty identity bytes')
        fields.append((name, value))
    return _key('facts', process_epoch, 'atlas.certified-fact-cache.v1', fields)


@dataclass(frozen=True, slots=True)
class CertifiedFact:
    result: bool
    certificate: bytes
    status: str = 'certified'

    def __post_init__(self):
        if type(self.result) is not bool or type(self.certificate) is not bytes:
            raise TypeError('facts require a boolean and exact certificate bytes')
        if type(self.status) is not str:
            raise TypeError('fact status must be explicit text')


class CertifiedFactCache(ContentCache[CertifiedFact]):
    def __init__(self, scope, *, verifier, max_bytes=None, max_entries=None, enabled=True):
        super().__init__(scope, 'facts', verifier=verifier, max_bytes=max_bytes,
                         max_entries=max_entries, enabled=enabled)

    def offer_verified(self, key, value, *, cancel=None):
        self._validate(key)
        if not isinstance(value, Owned) or value.scope is not self.scope:
            raise ValueError('fact cache cannot adopt a foreign owner')
        check_cancel(cancel)
        fact = value.value
        if not isinstance(fact, CertifiedFact) or fact.status != 'certified':
            return False
        return super().offer_verified(key, value, cancel=cancel)
