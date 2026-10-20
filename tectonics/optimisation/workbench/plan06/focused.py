"""Candidate-bound Plan06 checks. Invoked by check.py; no standalone runtime bootstrap."""
import importlib.util
import inspect
import pickle
import sys
import os
from contextlib import contextmanager, ExitStack
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace


def checks(g):
    E, D, W, R, V, O, Q = (g[k] for k in ('E', 'D5', 'W', 'REF', 'V', 'O', 'Q'))
    Budget, N = g['WorkBudget'], g['NATIVE_RETAINED']
    from atlas_tectonics.integration_volume_bounds import _Arena
    rotation = ((1, 0, 0), (0, 0, 1), Q(0), Q(1), 0)
    poly = ((Q(0), Q(0)), (Q(2), Q(0)), (Q(2), Q(2)), (Q(0), Q(2)))
    line = (Q(1), Q(0), Q(-1))
    report = {}

    def case(name, fn):
        try:
            detail = fn()
            report[name] = dict(ok=True, evidence=detail)
        except Exception as exc:
            import traceback
            report[name] = dict(ok=False, error=repr(exc), traceback=traceback.format_exc())

    class TraceBudget(Budget):
        def __init__(self, limit):
            super().__init__(limit)
            self.events = []

        @contextmanager
        def reserve(self, count, *, category='work'):
            before = self.reserved_bytes
            self.events.append(('attempt', count, category, before))
            entered = False
            try:
                with super().reserve(count, category=category):
                    entered = True
                    self.events.append(('enter', count, category, self.statistics()))
                    yield
            except Exception:
                if not entered:
                    self.events.append(('refuse', count, category, before))
                raise
            finally:
                if entered:
                    self.events.append(('exit', count, category, self.statistics()))

    def invoke(mod, limit, real=True):
        b = TraceBudget(limit)
        try:
            with _Arena(b) if real else ExitStack() as arena:
                if not real:
                    arena = g['Arena'](b)
                result = mod._rotated_normal(*rotation, arena)
            error = None
        except Exception as exc:
            result, error = None, (type(exc).__name__, str(exc))
        assert b.reserved_bytes == 0
        return result, error, b

    def lease():
        assert E.lease is E._work
        assert list(inspect.signature(E._work).parameters) == ['bits', 'count', 'budget', 'pairs']
        vals = (1, Q(1, 3), 0)
        traces = []
        for native in (False, True):
            b = TraceBudget(1 << 30)
            cm = E._work(sum(V._bits(x) for x in vals), len(vals), b, pairs=7) if native else V._work(vals, b, pairs=7)
            with cm:
                pass
            traces.append((b.events, b.statistics()))
        assert traces[0] == traces[1]
        return traces
    case('D8 lease alias signature diagnostics', lease)

    def orderzero():
        rows = []
        class Bare:
            def work(self, n):
                raise AssertionError('order zero work')
        class Property(Bare):
            @property
            def resource(self):
                raise AssertionError('order zero resource read')
        for arena in (Bare(), Property()):
            args = (*rotation[:3], Q(0), 0, arena)
            assert pickle.dumps(R._rotated_normal(*args), 5) == pickle.dumps(W._rotated_normal(*args), 5)
            rows.append(type(arena).__name__)
        class Revoker:
            calls = 0
            def revoke(self):
                self.calls += 1
        b = TraceBudget(1 << 20)
        with b.reserve((1 << 20)-1, category='optional'):
            rv = Revoker()
            b._revoker = rv
            before = list(b.events)
            W._rotated_normal(*rotation[:3], Q(0), 0, g['Arena'](b))
            assert rv.calls == 0 and b.events == before
            b._revoker = None
        return rows + ['near-full revoker untouched']
    case('D1 mathematical order zero', orderzero)

    def badresource():
        class Bad:
            resource = 7
            def work(self, n):
                seen.append(n)
        results = []
        for mod in (R, W):
            seen = []
            try:
                mod._rotated_normal(*rotation, Bad())
            except Exception as exc:
                results.append((type(exc).__name__, str(exc), seen))
        assert len(results) == 2 and results[0] == results[1] and results[0][2] == [64]
        return results
    case('work before bad resource validation', badresource)

    def identities():
        rows = []
        for owner, name in ((W, 'V'), (W, 'O'), (V, 'Fraction'), (O, 'Fraction')):
            old = getattr(owner, name)
            replacement = SimpleNamespace(**vars(old)) if name in ('V', 'O') else lambda *a: Q(*a)
            setattr(owner, name, replacement)
            try:
                assert not D._resident()
                assert D.clip2(poly, line, None) is D.DECLINED
                rows.append(name)
            finally:
                setattr(owner, name, old)
        assert D._resident()
        return rows
    case('reference object identity mutations', identities)

    def noncanonical():
        rows = []
        for n, d in ((4, 2), (0, 2), (1, -2)):
            q = object.__new__(Q)
            q._numerator, q._denominator = n, d
            args = (((1, 0, 0),)*3, (q, 0, 0), 0)
            assert D.line(*args) is D.DECLINED
            a, b = R._line(*args), W._line(*args)
            for p in (2, 3, 4, 5):
                assert pickle.dumps((args, a), p) == pickle.dumps((args, b), p)
            rows.append((n, d))
        return rows
    case('noncanonical Fraction decline', noncanonical)

    def nativeerror():
        original = E.native
        seen = []
        class NativeFailure(RuntimeError):
            pass
        def fail(value):
            seen.append(value)
            raise NativeFailure('native sentinel')
        E.native = fail
        try:
            try:
                W._line(((1, 0, 0),)*3, (1, 0, 0), 0)
            except NativeFailure as exc:
                assert str(exc) == 'native sentinel' and len(seen) == 1
            else:
                raise AssertionError('native failure swallowed or retried')
        finally:
            E.native = original
        return dict(native_calls=len(seen))
    case('native exception no retry', nativeerror)

    def provider():
        # Exercise the executing provider's selection function with bounded injected faults.
        X = g['X']
        old_env = os.environ.get(X.ENVIRONMENT)
        saved = X._canary, X._native_files, X.TESTED_GMPY2
        rows = []
        try:
            for fault in ('untested', 'canary', 'unsealed', 'MemoryError', 'RecursionError'):
                for mode in ('auto', 'gmpy2'):
                    X._canary, X._native_files, X.TESTED_GMPY2 = saved
                    if fault == 'untested':
                        X.TESTED_GMPY2 = ()
                    elif fault == 'unsealed':
                        X._native_files = lambda native: ({}, False)
                    else:
                        error = {'canary': ValueError, 'MemoryError': MemoryError,
                                 'RecursionError': RecursionError}[fault]
                        def fail(native, error=error):
                            raise error('provider sentinel')
                        X._canary = fail
                    os.environ[X.ENVIRONMENT] = mode
                    try:
                        selection = X._select()
                    except Exception as exc:
                        assert mode == 'gmpy2' or fault in ('MemoryError', 'RecursionError')
                        if fault in ('MemoryError', 'RecursionError'):
                            assert type(exc).__name__ == fault and str(exc) == 'provider sentinel'
                        rows.append(dict(fault=fault, mode=mode, error=type(exc).__name__, text=str(exc)))
                    else:
                        assert mode == 'auto' and fault not in ('MemoryError', 'RecursionError')
                        assert selection[1] == 'python'
                        rows.append(dict(fault=fault, mode=mode, backend=selection[1]))
        finally:
            X._canary, X._native_files, X.TESTED_GMPY2 = saved
            if old_env is None:
                os.environ.pop(X.ENVIRONMENT, None)
            else:
                os.environ[X.ENVIRONMENT] = old_env
        return rows
    case('provider eligibility errors and process errors', provider)

    def ceiling():
        # Actual above-ceiling operand: unlike old two-million-bit example this exceeds 2**27.
        huge = 1 << E.CEILING_BITS
        b = TraceBudget(1 << 40)
        huge_line = (Q(0), Q(0), Q(huge))
        results = []
        for arena in (None, g['Arena'](b)):
            before = list(b.events)
            assert D.clip2(poly, huge_line, arena) is D.DECLINED
            assert b.events == before
            assert W._clip2(poly, huge_line, arena) is poly
            results.append(dict(route='inner' if arena is None else 'arena', events=list(b.events)))
        args = ((huge, 0, 0), (0, 0, 1), Q(0), Q(0), 0, g['Arena'](b))
        before = list(b.events)
        assert D.rotated_normal(*args) is D.DECLINED and b.events == before
        assert W._rotated_normal(*args) == R._rotated_normal(*args)
        del huge, huge_line, args
        # Bounded boundary injection forces a *later step* to cross while initial width admits.
        # No global scientific limit is altered: restore the twin eligibility constant in finally.
        saved = E.CEILING_BITS
        initial = (sum(V._bits(v) for v in rotation[0])+sum(V._bits(v) for v in rotation[1])
                   + V._bits(Q(1, 2))+V._bits(1))
        try:
            E.CEILING_BITS = initial
            ref, run = invoke(R, 1 << 30, False), invoke(W, 1 << 30, False)
            assert ref[:2] == run[:2] and ref[1] is None
            ordinary = lambda b: [(a, n, c) for a, n, c, _ in b.events if c != N]
            assert ordinary(ref[2]) == ordinary(run[2])
            # At least one real native lifetime followed by ordinary continuation is necessary evidence.
            assert any(e[2] == N and e[0] == 'enter' for e in run[2].events)
            last_native_exit = max(i for i, e in enumerate(run[2].events) if e[2] == N and e[0] == 'exit')
            assert any(e[0] == 'enter' and e[2] != N for e in run[2].events[last_native_exit+1:])
            results.append(dict(route='rotated later step bounded injected threshold', threshold=initial,
                                reference=ref[2].events, candidate=run[2].events))
        finally:
            E.CEILING_BITS = saved
        return dict(actual_ceiling=saved, actual_entry_width_over_ceiling=True, cases=results)
    case('D2 both clip routes rotated entry and later step', ceiling)

    def midcall():
        results = []
        for mod in (R, W):
            seen = []
            original = O._cross
            class Arena(g['Arena']):
                def work(self, n):
                    if O._cross is original:
                        def cross(*a):
                            seen.append(1)
                            return original(*a)
                        O._cross = cross
            try:
                result = mod._rotated_normal(*rotation, Arena(Budget(1 << 30)))
            finally:
                O._cross = original
            results.append((result, len(seen)))
        assert results[0] == results[1] and results[0][1] > 0
        return results
    case('midcall arena work instrumentation', midcall)

    def budgets():
        baseline = invoke(R, 1 << 30)
        candidate = invoke(W, 1 << 30)
        assert baseline[:2] == candidate[:2] and baseline[1] is None
        def ordinary(b):
            return [(a, n, c) for a, n, c, _ in b.events if c != N]
        assert ordinary(baseline[2]) == ordinary(candidate[2])
        peak = baseline[2].peak_reserved_bytes
        limits = sorted({1, peak-1, peak, peak+1, candidate[2].peak_reserved_bytes,
                         *[e[3]+e[1]-1 for e in candidate[2].events if e[0] == 'attempt']})
        rows, earlier = [], 0
        for limit in limits:
            ref, run = invoke(R, limit), invoke(W, limit)
            assert not (ref[1] and run[1] is None), 'later admission'
            ra = [(n, c) for a, n, c, _ in ref[2].events if a == 'attempt' and c != N]
            ta = [(n, c) for a, n, c, _ in run[2].events if a == 'attempt' and c != N]
            assert ta == ra[:len(ta)], 'not common ordinary prefix'
            refusal = [e for e in run[2].events if e[0] == 'refuse']
            attributed = False
            if run[1]:
                assert len(refusal) == 1
                _, requested, category, used = refusal[0]
                held = 0
                for action, amount, cat, _ in run[2].events:
                    if action == 'refuse':
                        break
                    if cat == N:
                        held += amount if action == 'enter' else -amount if action == 'exit' else 0
                attributed = (category == N or used-held+requested <= limit) and used+requested > limit
                if ref[1] is None or len(ta) < len(ra):
                    assert attributed and run[2].statistics()['refusals'] > 0
                    earlier += 1
                else:
                    assert ref[1] == run[1]
            else:
                assert ref[:2] == run[:2]
            rows.append(dict(limit=limit, reference_error=ref[1], candidate_error=run[1],
                             surcharge_attributed=attributed, reference_events=ref[2].events,
                             candidate_events=run[2].events))
        assert earlier > 0, 'missing observed Policy A earlier refusal'
        # Exact WorkBudget exercises _Arena's growing-lease fast path too.
        fast = []
        for mod in (R, W):
            b = Budget(1 << 30)
            with _Arena(b) as a:
                value = mod._rotated_normal(*rotation, a)
            assert b.reserved_bytes == 0
            fast.append(value)
        assert fast[0] == fast[1]
        return dict(earlier_refusals=earlier, never_later=True, real_arena_fast_path=True, cases=rows)
    case('real Arena near-full Policy A', budgets)

    def caps():
        rows = []
        for count in (0, 60, 61, 62, 63, 64):
            histories = []
            for mod in (R, W):
                b = TraceBudget(1 << 30)
                with ExitStack() as stack:
                    for i in range(count):
                        stack.enter_context(b.reserve(i+1, category='c%d' % i))
                    mod._rotated_normal(*rotation, g['Arena'](b))
                    stack.enter_context(b.reserve(11, category='later'))
                    with b.reserve(17, category='overlap'):
                        with b.reserve(5, category='last'):
                            pass
                # Independently replay actual ordered lifetimes using unchanged cap.
                current, peaks, labels = {}, {}, []
                for action, amount, category, actual in b.events:
                    if action == 'enter':
                        label = category if category in current or len(current) < 63 else 'other'
                        labels.append((amount, category, label))
                        current[label] = current.get(label, 0)+amount
                        peaks[label] = max(peaks.get(label, 0), current[label])
                    elif action == 'exit':
                        index = next(i for i in range(len(labels)-1, -1, -1)
                                     if labels[i][:2] == (amount, category))
                        _, _, label = labels.pop(index)
                        current[label] -= amount
                    else:
                        continue
                    assert current == actual['categories'] and peaks == actual['category_peaks']
                assert not labels and all(v == 0 for v in current.values())
                histories.append(dict(events=b.events, statistics=b.statistics(), category_count=len(current)))
            strip = lambda h: [(a, n, c) for a, n, c, _ in h['events'] if c != N]
            assert strip(histories[0]) == strip(histories[1])
            assert any(e[2] == N for e in histories[1]['events'])
            rows.append(dict(prefill=count, reference=histories[0], candidate=histories[1]))
        return dict(scope='focused ordered overlapping-lifetime cap regimes; no consumer waiver', cases=rows)
    case('D6 ordered cap causal attribution', caps)

    def secondcopy():
        old = (D._module, D._loaded, D._closed)
        spec = importlib.util.spec_from_file_location('atlas_tectonics._plan06_second_copy', W.__file__)
        copy = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = copy
        try:
            spec.loader.exec_module(copy)
            assert D._closed and not D._resident() and D._module is old[0]
            counts = []
            for mod in (R, W, copy):
                original = mod._clip2
                seen = []
                def wrapped(*a):
                    seen.append(1)
                    return original(*a)
                mod._clip2 = wrapped
                try:
                    assert original(poly, line, g['Arena'](Budget(1 << 30))) == R._clip2(poly, line)
                    counts.append(len(seen))
                finally:
                    mod._clip2 = original
            # RHS reference call adds a wrapper observation only while R itself is wrapped.
            assert counts[0]-1 == counts[1] == counts[2] == 1
            D.attach(W.__name__)
            assert D._closed and not D._resident()
            return dict(closed=True, first_attachment_preserved=True, both_routes_reference=True)
        finally:
            D._module, D._loaded, D._closed = old
            sys.modules.pop(spec.name, None)
    case('second module copy fail closed', secondcopy)
    from atlas_tectonics import resources, integration_volume_bounds
    report['source_hashes'] = {str(Path(m.__file__).resolve()): sha256(Path(m.__file__).read_bytes()).hexdigest()
                               for m in (E, D, W, R, V, O, g['X'], resources, integration_volume_bounds)}
    return report
