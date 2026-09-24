"""Prove a long method was split into steps without rewriting its code.

Usage (any Python 3.10+, no Odoo needed):
    git show HEAD:models/account_move.py > /tmp/old.py
    python split_check.py /tmp/old.py AccountMove.action_refresh models/account_move.py [more new files]

Every statement of the old method (each simple statement, and the header of each
if/for/while/with/try) must still exist unchanged in some function of the new files.
Indentation and line numbers do not matter; renamed variables and reworded code do.
The statements printed as missing must be exactly the ones you changed on purpose,
such as the new step calls or several assignments merged into one write().
"""
import argparse
import ast
import collections
import sys


def _dump(node):
    return ast.dump(node, include_attributes=False)


def units(body, nested=True):
    """Yield (key, node) for each statement in body, recursing into compound statements
    (and into nested functions when ``nested``)."""
    for stmt in body:
        if isinstance(stmt, (ast.If, ast.While)):
            yield (type(stmt).__name__, _dump(stmt.test)), stmt
            yield from units(stmt.body, nested)
            yield from units(stmt.orelse, nested)
        elif isinstance(stmt, (ast.For, ast.AsyncFor)):
            yield ('for', _dump(stmt.target), _dump(stmt.iter)), stmt
            yield from units(stmt.body, nested)
            yield from units(stmt.orelse, nested)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            yield ('with', tuple(_dump(item) for item in stmt.items)), stmt
            yield from units(stmt.body, nested)
        elif isinstance(stmt, (ast.Try, getattr(ast, 'TryStar', ast.Try))):
            yield from units(stmt.body, nested)
            for handler in stmt.handlers:
                yield ('except', _dump(handler.type) if handler.type else None, handler.name), handler
                yield from units(handler.body, nested)
            yield from units(stmt.orelse, nested)
            yield from units(stmt.finalbody, nested)
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if nested:
                yield from units(stmt.body, nested)
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            continue
        else:
            yield ('stmt', _dump(stmt)), stmt


def find(tree, dotted):
    parts = dotted.split('.')
    scope = tree.body
    for i, part in enumerate(parts):
        wanted = (ast.ClassDef,) if i < len(parts) - 1 else (ast.FunctionDef, ast.AsyncFunctionDef)
        match = [n for n in scope if isinstance(n, wanted) and n.name == part]
        if not match:
            sys.exit('%s not found' % dotted)
        scope = match[0].body
        node = match[0]
    return node


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('old_file')
    parser.add_argument('method', help='Class.method or function')
    parser.add_argument('new_files', nargs='+')
    args = parser.parse_args()

    with open(args.old_file, encoding='utf-8') as fh:
        old_method = find(ast.parse(fh.read()), args.method)
    old = list(units(old_method.body))

    available = collections.Counter()
    for path in args.new_files:
        with open(path, encoding='utf-8') as fh:
            tree = ast.parse(fh.read(), path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                available.update(key for key, _node in units(node.body, nested=False))

    missing = []
    for key, node in old:
        if available[key] > 0:
            available[key] -= 1
        else:
            missing.append(node)
    print('%s: %d statements, %d found unchanged in the new code, %d missing' % (
        args.method, len(old), len(old) - len(missing), len(missing)))
    for node in missing:
        text = ast.unparse(node).split('\n')[0]
        print('  line %4d: %s' % (node.lineno, text if len(text) < 110 else text[:107] + '...'))


if __name__ == '__main__':
    main()
