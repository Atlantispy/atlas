"""Exact, bounded owner-supplied formulas; no geological or unit defaults.

The R17 constant, coefficient_m/field product and maximum forms are unchanged.
Terms may be nested expressions or the R17 coefficient_m/field shorthand.
sum, minimum, maximum and product accept 1..64 terms; difference and quotient
take exactly two ordered terms (left-minus-right or numerator/denominator).
No arbitrary code, imports, source reads, implicit fields or unit conversions
are expressions. ``coefficient_m`` is retained as a schema name, not a licence
to infer dimensional compatibility; the integrating owner supplies that.
"""
from fractions import Fraction
from dataclasses import dataclass

from work.generator_upgrade_r16 import columns


MAX_DEPTH, MAX_NODES, MAX_TERMS = 16, 256, 64
OPERATIONS = {'constant', 'product', 'maximum', 'minimum', 'sum', 'difference', 'quotient'}


def _exact(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('exact owner formula fields required')


@dataclass(frozen=True, slots=True)
class _Prepared:
    """Detached immutable instructions; not a persisted validation cache."""
    root: tuple
    references: frozenset


def _arithmetic(operation, values):
    if operation == 'quotient' and values[1] == 0:
        raise ValueError('owner formula division by zero')
    if any(value is None for value in values):
        return None
    if operation == 'difference':
        return columns._q(values[0]-values[1], 'formula difference')
    if operation == 'quotient':
        return columns._q(values[0]/values[1], 'formula quotient')
    if operation in ('maximum', 'minimum'):
        return columns._q((max if operation == 'maximum' else min)(values), 'formula extremum')
    value = Fraction(1 if operation == 'product' else 0)
    for term in values:
        value = columns._q(value*term if operation == 'product' else value+term,
                           'formula '+operation)
    return value


def prepare(expression):
    """Validate once and detach bounded literal/field arithmetic instructions.

Every sample and arithmetic intermediate is still checked when evaluated.
The returned private frozen object contains only tuples, Fractions and names;
later edits to the input expression cannot change an in-flight programme.
"""
    if type(expression) is _Prepared:
        return expression
    references = set()
    nodes = 0

    def field_value(name):
        columns._text(name, 'formula field')
        if name in {'UNKNOWN', 'INCOMPLETE', 'CONFLICT'}:
            raise ValueError('resolved formula field identity required')
        references.add(name)
        return name

    def walk(node, depth=1, *, shorthand=False):
        nonlocal nodes
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise ValueError('owner formula depth/node budget exceeded')
        if type(node) is not dict:
            raise ValueError('explicit owner formula expression required')
        if 'operation' not in node:
            if not shorthand:
                raise ValueError('explicit owner formula operation required')
            _exact(node, ('coefficient_m', 'field'))
            operation = 'product'
        else:
            operation = node['operation']
            if type(operation) is not str or operation not in OPERATIONS:
                raise ValueError('known owner formula operation required')
        if operation == 'constant':
            _exact(node, ('operation', 'value'))
            value = columns._q(node['value'], 'formula constant')
            return ('constant', value), value
        if operation == 'product' and 'terms' not in node:
            _exact(node, ('operation', 'coefficient_m', 'field') if 'operation' in node
                   else ('coefficient_m', 'field'))
            coefficient = columns._q(node['coefficient_m'], 'formula coefficient')
            name = field_value(node['field'])
            return ('field', coefficient, name), None
        _exact(node, ('operation', 'terms'))
        terms = node['terms']
        if type(terms) is not list or not 1 <= len(terms) <= MAX_TERMS:
            raise ValueError('owner formula requires 1..64 terms')
        if operation in ('difference', 'quotient') and len(terms) != 2:
            raise ValueError('difference/quotient require exactly two ordered terms')
        children = [walk(term, depth+1, shorthand=True) for term in terms]
        return (operation, tuple(child[0] for child in children)), _arithmetic(operation, [child[1] for child in children])

    root, _ = walk(expression)
    return _Prepared(root, frozenset(references))


def evaluate(expression, samples):
    """Return an exact Fraction; require every referenced sample even at weight 0.

Every input and arithmetic intermediate retains the unchanged R16 8192-bit
numerator/denominator bound. Float inputs retain their exact represented value.
Unreferenced samples are not interpreted. No clipping or normalisation occurs.
"""
    if type(samples) is not dict:
        raise ValueError('explicit formula sample mapping required')
    prepared = prepare(expression)

    def run(node):
        operation = node[0]
        if operation == 'constant':
            return node[1]
        if operation == 'field':
            coefficient, name = node[1:]
            if name not in samples:
                raise ValueError('missing formula field: '+name)
            value = columns._q(samples[name], 'formula sample '+name)
            return columns._q(coefficient*value, 'formula product')
        return _arithmetic(operation, [run(child) for child in node[1]])

    return run(prepared.root)


def referenced_fields(expression):
    """Validate bounded shape/literals and return all referenced field names.

No samples are substituted; sample-dependent numeric validity is checked by
evaluate. Constant-only invalid arithmetic (including a literal zero divisor)
is rejected here as well.
"""
    return set(prepare(expression).references)
