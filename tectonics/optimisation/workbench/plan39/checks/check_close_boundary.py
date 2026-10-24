"""Inert regression: extract actual boundary/close bodies; no Atlas imports or workloads."""
import ast
import json
from pathlib import Path
import sys
import threading
import types
import weakref

class TectonicsError(Exception):
    pass

def fixture(source):
    tree = ast.parse(source.read_text(encoding="utf-8"))
    publication = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "publication_boundary")
    context = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ExecutionContext")
    close = next(n for n in context.body if isinstance(n, ast.FunctionDef) and n.name == "close")
    namespace = {"TectonicsError": TectonicsError, "execution_mode": lambda: "strict",
                 "_release_state": types.SimpleNamespace(lock=threading.RLock(), handles=None),
                 "_entered": weakref.WeakKeyDictionary()}
    exec(compile(ast.Module(body=[publication, close], type_ignores=[]), str(source), "exec"), namespace)
    class Context:
        pass
    value = Context()
    value._closed = False
    value._source_handles = None
    value._close_verified = False
    value._close_lock = threading.RLock()
    value.verify = lambda: None
    value.verify_boundary = lambda: None
    value.close = types.MethodType(namespace["close"], value)
    namespace["_entered"][value] = 1
    return value, namespace["publication_boundary"]

def refuse():
    raise TectonicsError("loaded implementation changed")

def result(boundary):
    try:
        boundary()
        return "accepted"
    except TectonicsError:
        return "refused"

def exercise(source):
    outcomes = {}
    for failed in (False, True):
        value, boundary = fixture(source)
        errors = []
        if failed:
            value.verify = refuse
        def interleaved_close():
            try:
                value.close()
            except TectonicsError as exc:
                errors.append(str(exc))
            raise TectonicsError("execution context is closed")
        value.verify_boundary = interleaved_close
        outcomes["failed_mid_check" if failed else "healthy_mid_check"] = result(boundary)
        assert bool(errors) == failed
    for failed in (False, True):
        value, boundary = fixture(source)
        if failed:
            value.verify = refuse
        try:
            value.close()
        except TectonicsError:
            assert failed
        outcomes["failed_before_snapshot" if failed else "healthy_before_snapshot"] = result(boundary)
    value, boundary = fixture(source)
    started, finish = threading.Event(), threading.Event()
    errors = []
    def blocking_verify():
        started.set()
        if not finish.wait(2):
            raise RuntimeError("close control timed out")
    def close_owner():
        try:
            value.close()
        except BaseException as exc:
            errors.append(repr(exc))
    value.verify = blocking_verify
    owner = threading.Thread(target=close_owner)
    owner.start()
    try:
        assert started.wait(2), "close did not start"
        outcomes["in_progress_close"] = result(boundary)
    finally:
        finish.set()
        owner.join(2)
    assert not owner.is_alive() and not errors, errors
    outcomes["completed_close"] = result(boundary)
    value, boundary = fixture(source)
    value.verify_boundary = refuse
    outcomes["open_drift"] = result(boundary)
    value.verify_boundary = lambda: None
    outcomes["restored_after_refusal"] = result(boundary)
    return outcomes

if __name__ == "__main__":
    source = Path(sys.argv[1])
    outcomes = exercise(source)
    expected = {"healthy_mid_check": "accepted", "failed_mid_check": "refused",
                "healthy_before_snapshot": "accepted", "failed_before_snapshot": "refused",
                "in_progress_close": "refused", "completed_close": "accepted",
                "open_drift": "refused", "restored_after_refusal": "accepted"}
    if len(sys.argv) > 2 and sys.argv[2] == "--original":
        for key in ("failed_mid_check", "failed_before_snapshot", "in_progress_close"):
            expected[key] = "accepted"
    print(json.dumps({"source": str(source), "outcomes": outcomes, "pass": outcomes == expected}, sort_keys=True))
    if outcomes != expected:
        raise SystemExit(1)
