"""Revocable ownership of funded optional work in the private dispatcher.

This module neither computes geometry nor admits a scientific result. The
dispatcher must fund this owner's metadata before construction and retain that
funding until the owner and any held failure traceback are gone. The shutdown
callback must close optional admissions, confirm all owned workers have exited,
then release only their optional leases. Mandatory and held-error owners are
separate. Returning from that callback asserts that this ordering completed.
SPDX-License-Identifier: AGPL-3.0-only
"""
import threading

from .resources import WorkBudget, _BudgetLocks


def nodes_for(budgets):
    """Unique complete budget ancestry, in the resource ledger's lock order."""
    unique = {}
    for budget in budgets:
        seen = set()
        while budget is not None:
            if not isinstance(budget, WorkBudget):
                raise TypeError('budgets must be WorkBudget instances')
            if id(budget) in seen:
                raise ValueError('cyclic budget ancestry')
            seen.add(id(budget))
            unique[id(budget)] = budget
            budget = budget._parent
    return sorted(unique.values(), key=id)


class RevocableOwner:
    """One optional owner per shared byte/predicate ancestry, entered once.

    Stop and concurrent waits run outside every ledger lock. A failed stop
    retains registration and its failure; no lease is released here. Only an
    explicit close may retry cancellation-interrupted cleanup; ordinary
    revocation never retries it, and actual shutdown failures remain sticky.
    The dispatcher alone releases optional leases after confirming exit.
    """

    def __init__(self, budgets, stop):
        ledgers = tuple(budgets)
        if not ledgers or any(not isinstance(b, WorkBudget) for b in ledgers):
            raise ValueError('an optional owner requires explicit WorkBudget instances')
        if not callable(stop):
            raise TypeError('stop must be callable')
        self.nodes = nodes_for(ledgers + tuple(
            b._predicate_work for b in ledgers if b._predicate_work is not None))
        self.stop = stop
        self.condition = threading.Condition()
        self.state = 'ACTIVE'
        self.owner_thread = None
        self.failure = None
        self.calls = 0
        self._entered = False
        self._unregistering = self._exited = False

    def __enter__(self):
        with _BudgetLocks(self.nodes):
            if self._entered or self.state != 'ACTIVE':
                raise RuntimeError('optional owner may only be entered once')
            if any(node._revoker is not None for node in self.nodes):
                raise RuntimeError('one optional owner per shared resource ancestry')
            try:
                for node in self.nodes:
                    node._revoker = self
                self._entered = True
            except BaseException:
                # No worker has been admitted by this owner yet. Roll back
                # only our registration if entry itself was interrupted.
                for node in self.nodes:
                    if node._revoker is self:
                        node._revoker = None
                self._entered = False
                raise
        return self

    def revoke(self, *, _retry_interrupted=False):
        with self.condition:
            while self.state == 'REVOKING':
                if self.owner_thread == threading.get_ident():
                    raise RuntimeError('revocation must not make mandatory admissions')
                self.condition.wait()
            if self.state == 'FAILED':
                raise RuntimeError('optional work could not be confirmed stopped') from self.failure
            if self.state == 'INTERRUPTED' and not _retry_interrupted:
                raise RuntimeError('optional cleanup was interrupted; explicit close required') from self.failure
            if self.state == 'REVOKED':
                return
            self.state, self.owner_thread = 'REVOKING', threading.get_ident()
            self.calls += 1
        try:
            self.stop()
        except BaseException as error:
            with self.condition:
                self.failure = error
                self.state = 'INTERRUPTED' if isinstance(error, (KeyboardInterrupt, SystemExit)) else 'FAILED'
                self.owner_thread = None
                self.condition.notify_all()
            raise
        else:
            with self.condition:
                self.state, self.owner_thread = 'REVOKED', None
                self.failure = None
                self.condition.notify_all()

    def __exit__(self, *args):
        if not self._entered or self._exited:
            return False
        self.revoke(_retry_interrupted=True)
        with _BudgetLocks(self.nodes):
            # Check the whole registration before clearing any part of it.
            # If clearing itself was interrupted, a repeated close may finish
            # its own missing entries, but may never clear another owner.
            if any(node._revoker is not self and
                   not (self._unregistering and node._revoker is None) for node in self.nodes):
                raise RuntimeError('optional owner registration changed')
            self._unregistering = True
            for node in self.nodes:
                node._revoker = None
            self._exited = True
        return False
