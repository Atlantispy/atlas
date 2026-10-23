"""Every entry point that reaches inspect_compact_preadvance checks the capture route at run start.

This is a source check; nothing is imported. DriverTests read the drivers found on sys.path
(fresh_interval_driver, prepared_interval_driver). They pass only once the integrator has added these
top-level statements to each function:
    from compact_restart_patch import require_capture_route
    require_capture_route(store)              # advance_first_interval, before _seed_pinned()
    require_capture_route(store)              # advance_successor_interval, before _seed_pinned()
    require_capture_route(workflow._store)    # advance_prepared_interval, after the duration require,
                                              # before record.update(original_target=...)
CheckerTests show the check refuses a missing, late, conditional or wrongly bound call.
"""
import ast
import importlib.util
import unittest
from pathlib import Path

NAME = 'require_capture_route'


def _function(source, name):
    found = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(found) != 1:
        raise AssertionError('%s defined %d times' % (name, len(found)))
    return found[0]


def _calls(node, test):
    return any(isinstance(item, ast.Call) and test(item) for item in ast.walk(node))


def _named(call, name):
    return (isinstance(call.func, ast.Name) and call.func.id == name or
            isinstance(call.func, ast.Attribute) and call.func.attr == name)


def _first(body, test, what):
    for index, statement in enumerate(body):
        if test(statement):
            return index
    raise AssertionError(what+' not found')


def route_check_index(source, function, argument):
    """Index (in the function's top-level body) of the unconditional route check with this argument."""
    tree, node = ast.parse(source), _function(source, function)

    def is_check(statement):
        return (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call) and
                _named(statement.value, NAME) and not statement.value.keywords and
                [ast.unparse(arg) for arg in statement.value.args] == [argument])
    index = _first(node.body, is_check, '%s: unconditional %s(%s)' % (function, NAME, argument))
    if any(_calls(statement, lambda call: _named(call, NAME)) for statement in node.body[:index]):
        raise AssertionError(function+': an earlier, different route check')
    statement = node.body[index]
    assert isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
    if isinstance(statement.value.func, ast.Name):
        def imports(statement):
            return (isinstance(statement, ast.ImportFrom) and statement.module == 'compact_restart_patch' and
                    any(alias.name == NAME and alias.asname is None for alias in statement.names))
        if not any(imports(statement) for statement in node.body[:index]+tree.body):
            raise AssertionError(function+': %s is not imported from compact_restart_patch' % NAME)
    return index


def check_fresh(source, function='advance_first_interval'):
    node = _function(source, function)
    if 'store' not in [arg.arg for arg in node.args.args+node.args.kwonlyargs]:
        raise AssertionError(function+': no store parameter')
    check = route_check_index(source, function, 'store')
    seed = _first(node.body, lambda s: _calls(s, lambda call: _named(call, '_seed_pinned')), '_seed_pinned()')
    if not check < seed:
        raise AssertionError(function+': the route check must come before _seed_pinned()')


def check_successor(source):
    check_fresh(source, 'advance_successor_interval')


def check_prepared(source):
    node = _function(source, 'advance_prepared_interval')
    check = route_check_index(source, 'advance_prepared_interval', 'workflow._store')

    def duration_require(statement):
        return _calls(statement, lambda call: _named(call, '_require') and call.args and
                      ast.unparse(call.args[0]) == 'duration == first_duration')

    def original_target(statement):
        return _calls(statement, lambda call: _named(call, 'update') and ast.unparse(call.func) == 'record.update' and
                      any(keyword.arg == 'original_target' for keyword in call.keywords))
    duration = _first(node.body, duration_require, 'the frozen-duration require')
    update = _first(node.body, original_target, 'record.update(original_target=...)')
    if not duration < check < update:
        raise AssertionError('advance_prepared_interval: the route check must come after the duration require '
                             'and before record.update(original_target=...)')


class DriverTests(unittest.TestCase):
    """The drivers as composed (first on sys.path)."""

    def source(self, module):
        spec = importlib.util.find_spec(module)
        if spec is None or spec.origin is None:
            self.fail(module+' is not on sys.path')
        return Path(spec.origin).read_text(encoding='utf8')

    def test_fresh_driver_checks_the_route_first(self):
        check_fresh(self.source('fresh_interval_driver'))

    def test_successor_driver_checks_the_route_first(self):
        check_successor(self.source('fresh_interval_driver'))

    def test_prepared_driver_checks_the_route_after_its_prechecks(self):
        check_prepared(self.source('prepared_interval_driver'))


FRESH = '''
def advance_first_interval(m, *, store, record):
    """doc"""
{lines}
    with admission(m) as a:
        pass
'''
PREPARED = '''
def advance_prepared_interval(*, workflow, record):
    _require(type(case) is State, 'state')
    _require(duration == first_duration, 'duration')
{middle}
    record.update(original_target=D.TARGET)
{after}
'''
IMPORT = '    from compact_restart_patch import require_capture_route\n'


class CheckerTests(unittest.TestCase):
    def test_fresh_placements(self):
        good = IMPORT+'    require_capture_route(store)\n    _seed_pinned()'
        check_fresh(FRESH.format(lines=good))
        check_fresh(FRESH.format(lines='    import compact_restart_patch as P\n    P.require_capture_route(store)\n'
                                       '    _seed_pinned()'))
        bad = {'missing': IMPORT+'    _seed_pinned()',
               'after the seed': IMPORT+'    _seed_pinned()\n    require_capture_route(store)',
               'conditional': IMPORT+'    if store:\n        require_capture_route(store)\n    _seed_pinned()',
               'other argument': IMPORT+'    require_capture_route(m.store)\n    _seed_pinned()',
               'keyword': IMPORT+'    require_capture_route(store=store)\n    _seed_pinned()',
               'not imported': '    require_capture_route(store)\n    _seed_pinned()'}
        for label, lines in bad.items():
            with self.assertRaises(AssertionError, msg=label):
                check_fresh(FRESH.format(lines=lines))

    def test_successor_placements(self):
        successor = FRESH.replace('advance_first_interval(m, *, store,', 'advance_successor_interval(m, *, store, lineage,')
        good = IMPORT+'    require_capture_route(store)\n    _seed_pinned()'
        check_successor(successor.format(lines=good))
        both = FRESH.format(lines=good)+successor.format(lines=good)
        check_fresh(both)
        check_successor(both)
        for label, lines in {'missing': IMPORT+'    _seed_pinned()',
                             'after the seed': IMPORT+'    _seed_pinned()\n    require_capture_route(store)',
                             'other argument': IMPORT+'    require_capture_route(lineage)\n    _seed_pinned()'}.items():
            with self.assertRaises(AssertionError, msg=label):
                check_successor(FRESH.format(lines=good)+successor.format(lines=lines))
        with self.assertRaises(AssertionError, msg='no successor'):
            check_successor(FRESH.format(lines=good))

    def test_prepared_placements(self):
        call = IMPORT+'    require_capture_route(workflow._store)'
        check_prepared(PREPARED.format(middle=call, after=''))
        bad = {'missing': ('', ''), 'after the update': ('', call),
               'before the duration require': None, 'store argument': (call.replace('workflow._store', 'store'), '')}
        for label, parts in bad.items():
            source = (PREPARED.replace("    _require(duration", call+"\n    _require(duration").format(middle='', after='')
                      if parts is None else PREPARED.format(middle=parts[0], after=parts[1]))
            with self.assertRaises(AssertionError, msg=label):
                check_prepared(source)


if __name__ == '__main__':
    unittest.main()
