"""Production assertion engine for the runner-bound E2b checks.

Only the declared TestCase assertion surface is provided. Messages are diagnostic
only and deliberately never inspected, formatted or included in a predicate.
There are no tolerance, numerical, test-framework or optional dependencies.
"""

import re
import traceback


def _exception_type(expected):
    if isinstance(expected, tuple):
        return all(_exception_type(item) for item in expected)
    return isinstance(expected, type) and issubclass(expected, BaseException)


class _RaisesContext:
    def __init__(self, expected, expected_regex=None):
        self.expected = expected
        self.expected_regex = None if expected_regex is None else re.compile(expected_regex)

    def handle(self, name, args, kwargs):
        if not _exception_type(self.expected):
            raise TypeError(name + '() arg 1 must be an exception type or tuple of exception types')
        if not args:
            kwargs.pop('msg', None)
            if kwargs:
                raise TypeError(repr(next(iter(kwargs))) + ' is an invalid keyword argument')
            return self
        callable_obj, *call_args = args
        with self:
            callable_obj(*call_args, **kwargs)
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, tb):
        if exc_type is None:
            raise AssertionError('expected exception was not raised')
        traceback.clear_frames(tb)
        if not issubclass(exc_type, self.expected):
            return False
        self.exception = exc_value.with_traceback(None)
        if self.expected_regex is not None:
            if not self.expected_regex.search(str(exc_value)):
                raise AssertionError('exception did not match expected regex')
        return True


class Checks:
    """The eleven assertion methods used by the interval runner closure.

    Failed assertions raise AssertionError. Operand, callable and unexpected
    exception errors propagate. assertRaises* returns a context when no callable
    is supplied, otherwise invokes the callable and returns None. A matched
    context retains the captured exception without its traceback.
    """

    def assertEqual(self, first, second, msg=None):
        # TestCase dispatches exact built-in sets to set difference and exact
        # dictionaries to !=. Preserve those predicates as well as generic ==.
        if type(first) is type(second) and type(first) in (set, frozenset):
            if first.difference(second) or second.difference(first):
                raise AssertionError('values are not equal')
        elif type(first) is dict and type(second) is dict:
            if first != second:
                raise AssertionError('values are not equal')
        elif type(first) is type(second) and type(first) in (list, tuple):
            if first == second:
                return
            # On unequal exact sequences TestCase also compares successive
            # elements with !=; preserve errors from those operand methods.
            for left, right in zip(first, second, strict=False):
                if left != right:
                    break
            raise AssertionError('values are not equal')
        elif not first == second:
            raise AssertionError('values are not equal')

    def assertNotEqual(self, first, second, msg=None):
        if not first != second:
            raise AssertionError('values are equal')

    def assertGreater(self, a, b, msg=None):
        if not a > b:
            raise AssertionError('first value is not greater')

    def assertGreaterEqual(self, a, b, msg=None):
        if not a >= b:
            raise AssertionError('first value is not greater or equal')

    def assertLessEqual(self, a, b, msg=None):
        if not a <= b:
            raise AssertionError('first value is not less or equal')

    def assertIs(self, a, b, msg=None):
        if a is not b:
            raise AssertionError('objects are not identical')

    def assertIsNot(self, a, b, msg=None):
        if a is b:
            raise AssertionError('objects are identical')

    def assertNotIn(self, member, container, msg=None):
        if member in container:
            raise AssertionError('member is in container')

    def assertTrue(self, expr, msg=None):
        if not expr:
            raise AssertionError('expression is not true')

    def assertRaises(self, expected_exception, *args, **kwargs):
        return _RaisesContext(expected_exception).handle('assertRaises', args, kwargs)

    def assertRaisesRegex(self, expected_exception, expected_regex, *args, **kwargs):
        return _RaisesContext(expected_exception, expected_regex).handle('assertRaisesRegex', args, kwargs)
