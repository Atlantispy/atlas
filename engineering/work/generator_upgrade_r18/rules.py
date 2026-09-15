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

from work.generator_upgrade_r16 import columns


MAX_DEPTH, MAX_NODES, MAX_TERMS = 16, 256, 64
OPERATIONS = {'constant', 'product', 'maximum', 'minimum', 'sum', 'difference', 'quotient'}


def _exact(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('exact owner formula fields required')


def _run(expression, samples):
    references = set()
    nodes = 0

    def field_value(name):
        columns._text(name, 'formula field')
        if name in {'UNKNOWN', 'INCOMPLETE', 'CONFLICT'}:
            raise ValueError('resolved formula field identity required')
        references.add(name)
        if samples is None:
            return None
        if name not in samples:
            raise ValueError('missing formula field: '+name)
        return columns._q(samples[name], 'formula sample '+name)

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
            return columns._q(node['value'], 'formula constant')
        if operation == 'product' and 'terms' not in node:
            _exact(node, ('operation', 'coefficient_m', 'field') if 'operation' in node
                   else ('coefficient_m', 'field'))
            coefficient = columns._q(node['coefficient_m'], 'formula coefficient')
            value = field_value(node['field'])
            return None if value is None else columns._q(coefficient*value, 'formula product')
        _exact(node, ('operation', 'terms'))
        terms = node['terms']
        if type(terms) is not list or not 1 <= len(terms) <= MAX_TERMS:
            raise ValueError('owner formula requires 1..64 terms')
        if operation in ('difference', 'quotient') and len(terms) != 2:
            raise ValueError('difference/quotient require exactly two ordered terms')
        values = [walk(term, depth+1, shorthand=True) for term in terms]
        if operation == 'quotient' and values[1] == 0:
            raise ValueError('owner formula division by zero')
        if any(value is None for value in values):
            return None  # reference discovery never invents missing sample values
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

    value = walk(expression)
    return value, references


def evaluate(expression, samples):
    """Return an exact Fraction; require every referenced sample even at weight 0.

Every input and arithmetic intermediate retains the unchanged R16 8192-bit
numerator/denominator bound. Float inputs retain their exact represented value.
Unreferenced samples are not interpreted. No clipping or normalisation occurs.
"""
    if type(samples) is not dict:
        raise ValueError('explicit formula sample mapping required')
    return _run(expression, samples)[0]


def referenced_fields(expression):
    """Validate bounded shape/literals and return all referenced field names.

No samples are substituted; sample-dependent numeric validity is checked by
evaluate. Constant-only invalid arithmetic (including a literal zero divisor)
is rejected here as well.
"""
    return _run(expression, None)[1]
