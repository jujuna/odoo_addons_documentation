#!/usr/bin/env python3
"""Print a developer's map of an Odoo module, or check a README against the code.

Usage (from the project root, any Python 3.10+, no Odoo needed):
    python3 .claude/skills/odoo-readme/scripts/code_map.py MODULE_DIR
    python3 .claude/skills/odoo-readme/scripts/code_map.py MODULE_DIR --check README_DEV.md

Map mode prints Markdown: manifest facts; per Python file its classes (_name, _inherit), the
fields they add and every method with its decorators, whether it calls super() (an override
that extends core) and the first line of its docstring; data files with record counts per
model, <function> calls and noupdate blocks; view files with the views they inherit; access
rows; test files with their test methods.

Check mode reads a README and lists every `backticked` name that looks like code (a dotted
model, a method call, a _private name, a snake_case identifier or a file path) and cannot be
found anywhere in the module. Names that belong to Odoo itself (super, write, compute_sheet)
are found in core by grep, so each unknown name is only a candidate: confirm it by hand.
"""
import ast
import csv
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
CORE = [os.path.join(ROOT, d) for d in ('odoo', 'addons', 'enterprise', 'custom_addons')
        if os.path.isdir(os.path.join(ROOT, d))]
SKIP_DIRS = {'__pycache__', 'static', 'i18n', '.git', 'migrations'}


def rel(path, base):
    return os.path.relpath(path, base)


def py_files(module):
    for dirpath, dirnames, filenames in os.walk(module):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith('.py') and name not in ('__init__.py', '__manifest__.py'):
                yield os.path.join(dirpath, name)


def const(node):
    """Literal value of an AST node, or None."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def decorator_name(dec):
    target = dec.func if isinstance(dec, ast.Call) else dec
    name = ast.unparse(target)
    if isinstance(dec, ast.Call) and dec.args:
        first = const(dec.args[0])
        if isinstance(first, str):
            name += f"('{first}'{', ...' if len(dec.args) > 1 else ''})"
    return name


def calls_super(func):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'super'
               for n in ast.walk(func))


def first_doc_line(node):
    doc = ast.get_docstring(node)
    return doc.strip().splitlines()[0] if doc else ''


def field_line(target, call):
    ftype = ast.unparse(call.func).replace('fields.', '')
    label = const(call.args[0]) if call.args and isinstance(const(call.args[0]), str) else None
    flags = []
    for kw in call.keywords:
        if kw.arg == 'string' and isinstance(const(kw.value), str):
            label = const(kw.value)
        elif kw.arg in ('compute', 'related', 'inverse', 'search', 'compute_sql'):
            flags.append(f"{kw.arg}={const(kw.value) if isinstance(const(kw.value), str) else ast.unparse(kw.value)}")
        elif kw.arg in ('store', 'required', 'readonly', 'index', 'company_dependent', 'copy', 'tracking') \
                and const(kw.value) not in (None, False):
            flags.append(kw.arg)
        elif kw.arg == 'groups':
            flags.append(f"groups={const(kw.value)}")
    text = f"`{target}` {ftype}"
    if label:
        text += f' "{label}"'
    return text + (f" ({', '.join(flags)})" if flags else '')


def map_python(path, module):
    """Markdown lines for one Python file: classes, fields, methods."""
    with open(path, encoding='utf-8') as fh:
        source = fh.read()
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"### {rel(path, module)} - cannot parse: {exc}"]
    out = [f"### {rel(path, module)} ({len(source.splitlines())} lines)"]
    doc = first_doc_line(tree)
    if doc:
        out.append(f"_{doc}_")
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(f"- L{node.lineno} module function `{node.name}()` - {first_doc_line(node)}".rstrip(' -'))
        if not isinstance(node, ast.ClassDef):
            continue
        attrs, fields, methods = {}, [], []
        for item in node.body:
            if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
                name = item.targets[0].id
                if name in ('_name', '_inherit', '_description', '_order', '_rec_name', '_auto'):
                    attrs[name] = const(item.value)
                elif isinstance(item.value, ast.Call) and ast.unparse(item.value.func).startswith('fields.'):
                    fields.append(field_line(name, item.value))
            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                decs = ', '.join('@' + decorator_name(d) for d in item.decorator_list)
                tags = ' '.join(t for t in (decs, 'super()' if calls_super(item) else '') if t)
                line = f"- L{item.lineno} `{item.name}`" + (f" [{tags}]" if tags else '')
                doc = first_doc_line(item)
                methods.append(line + (f" - {doc}" if doc else ''))
        header = f"**class {node.name}**"
        for key in ('_name', '_inherit', '_description'):
            if attrs.get(key):
                header += f" · {key} = {attrs[key]!r}"
        out.append(header)
        if fields:
            out.append(f"Fields ({len(fields)}): " + '; '.join(fields))
        out.extend(methods or ['- (no methods)'])
    return out


def map_xml(path, module):
    """Record counts per model, function calls, noupdate and inherited views of one XML file."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [f"- {rel(path, module)}: cannot parse ({exc})"]
    counts, functions, inherits, noupdate = {}, [], [], False
    for block in root.iter():
        if block.tag in ('data', 'odoo') and block.get('noupdate') in ('1', 'True', 'true'):
            noupdate = True
    for rec in root.iter('record'):
        model = rec.get('model')
        counts[model] = counts.get(model, 0) + 1
        for field in rec.findall('field'):
            if field.get('name') == 'inherit_id' and field.get('ref'):
                inherits.append(field.get('ref'))
    for tag in ('menuitem', 'template'):
        found = len(list(root.iter(tag)))
        if found:
            counts[tag] = found
    for func in root.iter('function'):
        functions.append(f"{func.get('model')}.{func.get('name')}")
    parts = [f"{m} x{n}" for m, n in sorted(counts.items())]
    line = f"- {rel(path, module)}: " + (', '.join(parts) or 'no records')
    if noupdate:
        line += ' · has noupdate'
    if functions:
        line += ' · calls ' + ', '.join(functions)
    if inherits:
        line += ' · inherits ' + ', '.join(sorted(set(inherits)))
    return [line]


def map_access(path, module):
    with open(path, encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    out = [f"- {rel(path, module)}: {len(rows)} rows"]
    for row in rows:
        group = row.get('group_id/id') or row.get('group_id:id') or '(restriction, no group)'
        rights = row.get('operation') or ''.join(
            k[5] for k in ('perm_read', 'perm_write', 'perm_create', 'perm_unlink') if row.get(k) == '1')
        domain = row.get('domain') or ''
        out.append(f"  - {row.get('model_id') or row.get('model_id:id')} · {group} · {rights}"
                   + (f" · {domain}" if domain else ''))
    return out


def map_module(module):
    out = []
    manifest_path = os.path.join(module, '__manifest__.py')
    manifest = const(ast.parse(open(manifest_path, encoding='utf-8').read()).body[0].value) or {}
    out.append(f"# {manifest.get('name', os.path.basename(module))} (`{os.path.basename(module)}`)")
    out.append(f"- version {manifest.get('version')} · depends {', '.join(manifest.get('depends', []))}")
    desc = (manifest.get('description') or '').strip()
    out.append('- manifest description: ' + ('set' if desc else 'MISSING (Odoo will render README.* as reStructuredText)'))
    out.append(f"- data: {', '.join(manifest.get('data', []))}")
    code, tests = [], []
    for path in py_files(module):
        (tests if os.sep + 'tests' + os.sep in path else code).append(path)
    out.append('\n## Python')
    for path in code:
        out.extend(map_python(path, module))
    out.append('\n## Data and views')
    for dirpath, dirnames, filenames in os.walk(module):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if name.endswith('.xml'):
                out.extend(map_xml(path, module))
            elif name.endswith('.csv') and 'security' in dirpath:
                out.extend(map_access(path, module))
    out.append('\n## Tests')
    for path in tests:
        tree = ast.parse(open(path, encoding='utf-8').read())
        names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')]
        doc = first_doc_line(tree)
        out.append(f"- {rel(path, module)}: {len(names)} tests" + (f" - {doc}" if doc else ''))
    return '\n'.join(out)


CODE_LIKE = re.compile(r'^(?:[a-z_][a-z0-9_]*\.)+[a-z_][a-z0-9_]*(?:\(\))?$|^_?[a-z][a-z0-9_]*_[a-z0-9_]+(?:\(\))?$'
                       r'|^_[a-z][a-z0-9_]*(?:\(\))?$|^[\w./-]+\.(?:py|xml|csv|js|scss)$')


def check_readme(module, readme):
    """List backticked code-like names of README that the module source never mentions."""
    text = open(readme, encoding='utf-8').read()
    names = sorted({m.strip() for m in re.findall(r'`([^`\n]+)`', text)})
    corpus, files = [], set()
    for dirpath, dirnames, filenames in os.walk(module):
        dirnames[:] = sorted(d for d in dirnames if d not in {'__pycache__', '.git'})
        for name in filenames:
            files.add(name)
            files.add(rel(os.path.join(dirpath, name), module))
            if name.endswith(('.py', '.xml', '.csv', '.js')):
                corpus.append(open(os.path.join(dirpath, name), encoding='utf-8', errors='ignore').read())
    corpus = '\n'.join(corpus)
    addons = {d for base in CORE for d in (os.listdir(base) if os.path.isdir(base) else [])}
    addons |= {d for base in CORE if base.endswith('custom_addons')
               for sub in os.listdir(base) if os.path.isdir(os.path.join(base, sub))
               for d in os.listdir(os.path.join(base, sub))}
    missing, outside = [], []
    for name in names:
        if not CODE_LIKE.match(name):
            continue
        token = name.removesuffix('()')
        if token.endswith(('.py', '.xml', '.csv', '.js', '.scss')):
            if token in files or os.path.basename(token) in files:
                continue
            missing.append(name)
            continue
        leaf = token.split('.')[-1]
        if leaf in corpus or token in corpus:
            continue
        if token in addons:
            outside.append(name)
            continue
        hit = subprocess.run(['grep', '-rqsF', '--include=*.py', '--include=*.xml', leaf, *CORE]).returncode == 0
        (outside if hit else missing).append(name)
    print(f"{len(names)} backticked names in {rel(readme, ROOT)}")
    print(f"found only outside this module - Odoo or another addon ({len(outside)}): {', '.join(outside) or '-'}")
    print(f"found nowhere - check these by hand ({len(missing)}): {', '.join(missing) or '-'}")
    return 1 if missing else 0


def main(argv):
    if len(argv) < 2 or not os.path.isfile(os.path.join(argv[1], '__manifest__.py')):
        print(__doc__)
        return 2
    module = os.path.abspath(argv[1])
    if len(argv) == 4 and argv[2] == '--check':
        inside = os.path.join(module, argv[3])
        readme = inside if os.path.isfile(inside) else os.path.abspath(argv[3])
        return check_readme(module, readme)
    print(map_module(module))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
