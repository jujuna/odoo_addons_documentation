"""List the functions and methods of a module that nothing references.

Usage (any Python 3.10+, no Odoo needed):
    python dead_names.py <module_dir> [--roots DIR ...]

A name is reported when it is defined in <module_dir> and appears nowhere else: not in the
module's own code (as a call, attribute, or an exact string such as compute='_compute_x'),
and not as a word in any .py/.xml/.js/.csv file under the roots (default: addons/,
enterprise/, custom_addons/, odoo/ and themes/ of the Odoo tree that holds the module).
A report is a candidate, not proof. Before deleting, check what files cannot show:
code stored in the database (the SQL printed at the end), names built at run time
(getattr(self, 'action_%s' % x)), and external systems calling the method over RPC.
"""
import argparse
import ast
import collections
import os
import re
import sys

TOKEN = re.compile(rb'[A-Za-z_][A-Za-z0-9_]{2,}')
EXTENSIONS = ('.py', '.xml', '.js', '.csv')
FRAMEWORK_HOOKS = re.compile(r'^(__\w+__|test_\w+|setUp\w*|tearDown\w*|_register_hook|_auto_init|init|_init_column)$')


def odoo_root(start):
    path = os.path.abspath(start)
    while path != os.path.dirname(path):
        if os.path.isfile(os.path.join(path, 'odoo-bin')) or \
                os.path.isfile(os.path.join(path, 'odoo', 'release.py')):
            return path
        path = os.path.dirname(path)
    sys.exit('no Odoo tree above %s; pass --roots' % start)


def module_py_files(module_dir):
    for dirpath, dirnames, filenames in os.walk(module_dir):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for name in filenames:
            if name.endswith('.py'):
                yield os.path.join(dirpath, name)


class Uses(ast.NodeVisitor):
    """Collect definitions and uses; a use inside the function of the same name does not
    count (a wrapper calling the remote operation it is named after is still unused)."""

    FRAMEWORK_DECORATORS = {'constrains', 'onchange', 'ondelete', 'autovacuum'}

    def __init__(self, rel):
        self.rel, self.stack = rel, []
        self.defined, self.used = collections.defaultdict(list), collections.Counter()
        self.framework = set()

    def visit_FunctionDef(self, node):
        self.defined[node.name].append('%s:%d' % (self.rel, node.lineno))
        for deco in node.decorator_list:
            func = deco.func if isinstance(deco, ast.Call) else deco
            if isinstance(func, ast.Attribute) and func.attr in self.FRAMEWORK_DECORATORS:
                self.framework.add(node.name)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def use(self, name):
        if not self.stack or self.stack[-1] != name:
            self.used[name] += 1

    def visit_Attribute(self, node):
        self.use(node.attr)
        self.generic_visit(node)

    def visit_Name(self, node):
        self.use(node.id)

    def visit_Constant(self, node):
        if isinstance(node.value, str) and node.value.isidentifier():
            self.use(node.value)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('module_dir')
    parser.add_argument('--roots', nargs='+')
    args = parser.parse_args()
    module_dir = os.path.abspath(args.module_dir)
    if args.roots:
        roots = [os.path.abspath(r) for r in args.roots]
    else:
        base = odoo_root(module_dir)
        roots = [os.path.join(base, d) for d in ('addons', 'enterprise', 'custom_addons', 'odoo', 'themes')
                 if os.path.isdir(os.path.join(base, d))]

    defined = collections.defaultdict(list)
    used_inside = collections.Counter()
    framework = set()
    for path in module_py_files(module_dir):
        with open(path, encoding='utf-8') as fh:
            visitor = Uses(os.path.relpath(path, module_dir))
            visitor.visit(ast.parse(fh.read(), path))
        for name, places in visitor.defined.items():
            defined[name] += places
        used_inside.update(visitor.used)
        framework |= visitor.framework
    candidates = {n for n in defined
                  if not used_inside[n] and n not in framework and not FRAMEWORK_HOOKS.match(n)}

    found = set()
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ('__pycache__', 'node_modules', '.git')]
            if os.path.abspath(dirpath).startswith(module_dir + os.sep) or os.path.abspath(dirpath) == module_dir:
                continue
            for name in filenames:
                if name.endswith(EXTENSIONS):
                    try:
                        with open(os.path.join(dirpath, name), 'rb') as fh:
                            tokens = set(TOKEN.findall(fh.read()))
                    except OSError:
                        continue
                    found.update(n for n in candidates if n.encode() in tokens)
    for dirpath, dirnames, filenames in os.walk(module_dir):
        for name in filenames:
            if name.endswith(('.xml', '.js', '.csv')):
                with open(os.path.join(dirpath, name), 'rb') as fh:
                    tokens = set(TOKEN.findall(fh.read()))
                found.update(n for n in candidates if n.encode() in tokens)
    unused = sorted(candidates - found)

    print('%s: %d functions/methods defined, %d referenced nowhere (searched: the module, %s)' % (
        os.path.basename(module_dir), len(defined), len(unused), ', '.join(os.path.basename(r) for r in roots)))
    for name in unused:
        print('  %-45s %s' % (name, ', '.join(defined[name])))
    if unused:
        pattern = '|'.join(unused)
        print('\nCode stored in the database is not in any file. Check it before deleting:')
        print("  SELECT a.id, m.model, a.code FROM ir_act_server a JOIN ir_model m ON m.id = a.model_id"
              " WHERE a.state = 'code' AND a.code ~ '(%s)';" % pattern)


if __name__ == '__main__':
    main()
