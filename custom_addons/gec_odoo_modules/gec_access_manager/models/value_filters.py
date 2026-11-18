import ast

from odoo.fields import Domain
from odoo.tools.safe_eval import expr_eval

OPERATORS = {'&': 2, '|': 2, '!': 1}
# the syntax of a filter: lists, comparisons, and/or/not, a conditional, a sum
ALLOWED_NODES = (
    ast.Expression, ast.List, ast.Tuple, ast.Constant, ast.Name, ast.Compare, ast.BoolOp, ast.UnaryOp,
    ast.IfExp, ast.BinOp, ast.Load, ast.And, ast.Or, ast.Not, ast.USub, ast.Add,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
)
CONSTANT_TYPES = (str, int, float, type(None))
# computed links of res.users a filter may follow: hr's employee of the user's company
USER_COMPUTED_LINKS = frozenset({'employee_id'})
# the models a user. chain may read fields of: their records are open to every employee, unlike hr.version
USER_CHAIN_MODELS = frozenset({'res.users', 'res.partner', 'res.company', 'hr.employee'})
# the plain fields of the user's own record a filter may read (user.tz)
USER_OWN_FIELDS = frozenset({'tz', 'lang'})
# the longest filter text a profile line takes: parsing a huge text costs memory on every request
MAX_FILTER_LENGTH = 4000
# the operators whose value is a domain, as field_guard's; not imported: it would load its Base before base_model's
SUBQUERY_OPERATORS = ('any', 'not any', 'any!', 'not any!')
# the names a value filter always reads from the evaluation context, never from the record (field_guard.py)
CONTEXT_NAMES = frozenset({'context', 'uid', 'allowed_company_ids', 'current_company_id', 'parent'})


def _elements(expression):
    """ The terms of a domain written as a list (AST nodes), or None when the expression is not a list. """
    try:
        node = ast.parse(expression.strip(), mode='eval').body
    except SyntaxError:
        return None
    return list(node.elts) if isinstance(node, ast.List) else None


def _operator(node):
    return node.value if isinstance(node, ast.Constant) and node.value in OPERATORS else None


def _normalized(elements):
    """ ``elements`` as a single prefix term: the implicit ANDs made explicit. """
    result, expected = [], 1
    for node in elements:
        if expected == 0:
            result.insert(0, ast.Constant('&'))
            expected = 1
        result.append(node)
        operator = _operator(node)
        expected += OPERATORS[operator] - 1 if operator else -1
    return result


def _unparse(elements):
    return ast.unparse(ast.List(elts=elements, ctx=ast.Load()))


def and_domains(expressions):
    """ The AND of domain expressions: lists are concatenated; anything else is added (``a + b``), which the server
    and the web client both evaluate to the concatenated list. """
    expressions = [e.strip() for e in expressions if e and e.strip()]
    if len(expressions) < 2:
        return expressions[0] if expressions else None
    parsed = [_elements(expression) for expression in expressions]
    if all(elements is not None for elements in parsed):
        return _unparse([node for elements in parsed for node in elements])
    return ' + '.join(f'({expression})' for expression in expressions)


def or_domains(expressions):
    """ The OR of domain expressions. None when they cannot be combined (not a list, or an empty one, which allows
    everything): the caller then leaves the values unfiltered. """
    expressions = [e.strip() for e in expressions if e and e.strip()]
    if len(expressions) < 2:
        return expressions[0] if expressions else None
    terms = []
    for expression in expressions:
        elements = _elements(expression)
        if not elements:
            return None
        terms.append(_normalized(elements))
    return _unparse([ast.Constant('|')] * (len(terms) - 1) + [node for term in terms for node in term])


def names_read(expression):
    try:
        node = ast.parse(expression.strip(), mode='eval')
    except SyntaxError:
        return set()
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _readable(field, value_filter):
    """ Whether a filter may read ``field`` as the superuser: stored or related, without groups (a compute may protect
    its value, which the superuser skips). A record filter is cached as ids, so only a field the user's own writes
    change: no related, computed or other model's one2many (hr.employee aside: its changes clear the cache). """
    if field.groups:
        return False
    if value_filter:
        return bool(field.store or field.related)
    return bool(field.store) and not field.related and not field.compute and (
        field.type != 'one2many' or field.comodel_name == 'hr.employee')


def _check_attribute(node, users, value_filter):
    """ Accept ``user.<many2one>....id`` (or ``ids``, also after an x2many), the user's tz or lang (USER_OWN_FIELDS)
    and, in a value filter, ``parent.<field>``; no other field is read. A record filter follows one user field at
    most: its ids are cached, and a value two hops away changes with writes nothing clears. """
    chain = []
    while isinstance(node, ast.Attribute):
        chain.insert(0, node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        raise ValueError("an attribute of an expression is not allowed")
    if value_filter and node.id == 'parent':
        if len(chain) != 1 or chain[0].startswith('_'):
            raise ValueError("only parent.<field> is allowed")
        return
    if node.id != 'user':
        raise ValueError("an attribute of '%s' is not allowed" % node.id)
    *steps, last = chain
    if not steps and last in USER_OWN_FIELDS and last in users._fields:
        return
    if not value_filter and len(steps) > 1:
        raise ValueError(
            "a record filter may follow one field of the user ('user.employee_id.id'); write a join instead, "
            "e.g. [('department_id.member_ids.user_id', '=', uid)]")
    model = users
    for index, name in enumerate(steps):
        if model._name not in USER_CHAIN_MODELS:
            raise ValueError("the fields of '%s' cannot be read in a filter" % model._name)
        field = model._fields.get(name)
        if field is None:
            raise ValueError("'%s' is not a field of the user" % name)
        if not (_readable(field, value_filter) or (index == 0 and name in USER_COMPUTED_LINKS)):
            if value_filter or field.groups:
                raise ValueError("the field '%s' cannot be read in a filter" % name)
            raise ValueError(
                "the field '%s' of the user changes without a write of the user; a record filter is cached, "
                "write a join instead" % name)
        if field.type == 'many2one':
            model = model.env[field.comodel_name]
        elif not (field.type in ('one2many', 'many2many') and index == len(steps) - 1 and last == 'ids'):
            raise ValueError("'%s' cannot be followed by '%s'" % (name, last))
    if last not in ('id', 'ids'):
        raise ValueError("only the id of a user's relation is allowed, not '%s'" % last)


def _check_node(node, users, value_filter):
    if isinstance(node, ast.Attribute):
        return _check_attribute(node, users, value_filter)
    if not isinstance(node, ALLOWED_NODES):
        raise ValueError("%s is not allowed in a filter" % type(node).__name__)
    if isinstance(node, ast.Constant) and not isinstance(node.value, CONSTANT_TYPES):
        raise ValueError("a constant of type %s is not allowed" % type(node.value).__name__)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and not isinstance(node.operand, ast.Constant):
        raise ValueError("a minus is only allowed before a number")
    for child in ast.iter_child_nodes(node):
        _check_node(child, users, value_filter)


def check_filter(expression, users, value_filter=False):
    """ The parsed expression, or a ValueError when it uses more than a filter needs: calls, indexes, lambdas,
    comprehensions, products, powers, or a field of the user other than the ids of its relations and USER_OWN_FIELDS.
    ``users`` is the res.users model. The message names the construct, never a value. """
    try:
        tree = ast.parse(expression.strip(), mode='eval')
    except (SyntaxError, ValueError, RecursionError, MemoryError) as error:
        raise ValueError("the expression is not valid Python syntax") from error
    try:
        _check_node(tree, users, value_filter)
    except RecursionError as error:
        raise ValueError("the expression is nested too deeply") from error
    return tree


class _ParentItems(ast.NodeTransformer):
    """ ``parent.<field>`` as ``parent['<field>']``: expr_eval reads the values of a record being saved by key. """

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == 'parent':
            return ast.Subscript(value=node.value, slice=ast.Constant(node.attr), ctx=ast.Load())
        return self.generic_visit(node)


def eval_filter(expression, context, users, value_filter=False):
    """ Evaluate a filter after check_filter(): it reads only the names of ``context`` and the user's relation ids. """
    tree = check_filter(expression, users, value_filter)
    if not value_filter:
        return expr_eval(expression, context)
    return expr_eval(ast.unparse(ast.fix_missing_locations(_ParentItems().visit(tree))), context)


def _check_path(model, path):
    """ Check that the user of ``model`` can read each field of the dotted ``path``. Returns the model the path ends on
    (``id`` keeps the model), or None when it ends on a plain or unknown field. """
    target = model
    for name in path.split('.'):
        field = target._fields.get(name)
        if field is None:
            return None
        target.check_field_access(field, 'read')
        if name == 'id':
            continue
        if not field.relational:
            return None
        target = target.env[field.comodel_name]
    return target


def check_read_fields(model, domain):
    """ Core's search refuses a field the user cannot read, step by step along a path and inside an ``any``: so
    does a saved filter. Raises the AccessError of the first field the user of ``model`` cannot read. """
    for condition in domain.iter_conditions():
        target = _check_path(model, condition.field_expr)
        if target is not None and condition.operator in SUBQUERY_OPERATORS and isinstance(
                condition.value, (list, tuple, Domain)):
            check_read_fields(target, Domain(condition.value))


def check_filter_paths(model, node):
    """ ``check_read_fields`` for the parsed text of a value filter, searched on ``model`` as the superuser: every
    ``(path, operator, value)`` in the tree is checked, inside an ``any`` too. Values (names, ``user.``, ``parent.``)
    are not paths. """
    if isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) == 3:
        path, operator, value = node.elts
        if (isinstance(path, ast.Constant) and isinstance(path.value, str) and path.value not in OPERATORS
                and isinstance(operator, ast.Constant) and isinstance(operator.value, str)):
            target = _check_path(model, path.value)
            if target is not None and operator.value in SUBQUERY_OPERATORS and isinstance(value, (ast.List, ast.Tuple)):
                check_filter_paths(target, value)
            return
    for child in ast.iter_child_nodes(node):
        check_filter_paths(model, child)
