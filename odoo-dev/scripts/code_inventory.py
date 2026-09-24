"""Snapshot a module's Python code and compare two snapshots, to prove a refactor.

Usage (any Python 3.10+, no Odoo needed):
    python code_inventory.py snapshot <module_dir> [--rev REV] -o before.json
    python code_inventory.py compare before.json after.json
    python code_inventory.py long <module_dir> [--min 80]

snapshot reads every .py file of the module, from the working tree or from git revision
REV of the repository that holds <module_dir>, and stores:
  - texts:   first string argument of every _() / env._() / _lt() call. Code translations
             are looked up by (module, source text), so a changed text loses its translation.
  - entries: every function, method, class attribute (fields, _name, _inherit, ...), class
             docstring and module constant, keyed by WHAT it is (model + name) and stored as
             its AST without line numbers. Same entries = same code, however files moved.
  - po:      msgids of i18n/*.po per language, and whether each one is translated.
compare prints what changed. For a "moves only" phase, entries must show no removed, added
or changed items; only files, imports and "moved" lines may differ.
long lists the functions longer than --min lines, longest first: the split candidates.
"""
import argparse
import ast
import collections
import json
import os
import subprocess
import sys


def _git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True, check=True).stdout


def _sources(module_dir, rev):
    """Yield (relative path, text) for every .py and i18n/*.po file of the module."""
    module_dir = os.path.abspath(module_dir)
    if rev is None:
        for dirpath, dirnames, filenames in os.walk(module_dir):
            dirnames[:] = sorted(d for d in dirnames if d != '__pycache__')
            for name in sorted(filenames):
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, module_dir)
                if name.endswith('.py') or (name.endswith('.po') and rel.startswith('i18n' + os.sep)):
                    with open(path, encoding='utf-8') as fh:
                        yield rel, fh.read()
        return
    repo = _git(module_dir, 'rev-parse', '--show-toplevel').strip()
    prefix = os.path.relpath(module_dir, repo)
    for path in _git(repo, 'ls-tree', '-r', '--name-only', rev, '--', prefix).split('\n'):
        rel = os.path.relpath(path, prefix) if path else ''
        if path.endswith('.py') or (path.endswith('.po') and rel.startswith('i18n/')):
            yield rel, _git(repo, 'show', '%s:%s' % (rev, path))


def _dump(node):
    return ast.dump(node, include_attributes=False)


def _model_key(cls):
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                and isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id in ('_name', '_inherit'):
            value = stmt.value
            if isinstance(value, ast.Constant):
                return value.value
            if isinstance(value, (ast.List, ast.Tuple)) and value.elts and isinstance(value.elts[0], ast.Constant):
                return value.elts[0].value
    return 'class:' + cls.name


def _is_translation_call(node):
    func = node.func
    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
    return name in ('_', '_lt') and node.args and isinstance(node.args[0], ast.Constant) \
        and isinstance(node.args[0].value, str)


def _parse_po(text):
    """Return {msgid: translated?} for a .po file (enough for msgid/msgstr pairs)."""
    result, current, key = {}, {}, None
    for line in text.split('\n') + ['']:
        line = line.strip()
        for field in ('msgid', 'msgstr'):
            if line.startswith(field + ' '):
                if field == 'msgid' and 'msgstr' in current:
                    result[current['msgid']] = bool(current['msgstr'])
                    current = {}
                key = field
                current[key] = ast.literal_eval(line[len(field) + 1:])
                break
        else:
            if line.startswith('"') and key:
                current[key] += ast.literal_eval(line)
            elif not line or line.startswith('#'):
                key = None
    if 'msgstr' in current:
        result[current['msgid']] = bool(current['msgstr'])
    result.pop('', None)
    return result


def snapshot(module_dir, rev):
    entries = collections.defaultdict(list)
    where = collections.defaultdict(list)
    texts, imports, lines, po = [], {}, {}, {}

    def add(key, node, path):
        entries[key].append(_dump(node))
        where[key].append(path)

    for rel, source in _sources(module_dir, rev):
        if rel.endswith('.po'):
            po[os.path.splitext(os.path.basename(rel))[0]] = _parse_po(source)
            continue
        lines[rel] = source.count('\n') + 1
        tree = ast.parse(source, rel)
        imports[rel] = sorted(ast.unparse(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)))
        texts += [n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_translation_call(n)]
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                add('func %s' % node.name, node, rel)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                add('const %s' % ','.join(ast.unparse(t) for t in targets), node, rel)
            elif isinstance(node, ast.ClassDef):
                model = _model_key(node)
                add('class %s %s' % (model, node.name), ast.Tuple(elts=node.bases, ctx=ast.Load()), rel)
                for stmt in node.body:
                    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        add('method %s.%s' % (model, stmt.name), stmt, rel)
                    elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                        add('attr %s.%s' % (model, ','.join(ast.unparse(t) for t in targets)), stmt, rel)
                    else:
                        add('other %s %s' % (model, node.name), stmt, rel)
            elif not (isinstance(node, (ast.Import, ast.ImportFrom))
                      or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))):
                add('toplevel %s' % rel, node, rel)
    return {'rev': rev or 'WORKTREE', 'module': os.path.basename(os.path.abspath(module_dir)),
            'texts': sorted(texts), 'entries': entries, 'where': where,
            'imports': imports, 'lines': lines, 'po': po}


def _short(text, width=110):
    text = ' '.join(str(text).split())
    return text if len(text) <= width else text[:width - 3] + '...'


def compare(before, after):
    b_lines, a_lines = before['lines'], after['lines']
    print('%s: %s -> %s' % (after['module'], before['rev'], after['rev']))
    print('python files: %d -> %d, lines: %d -> %d (%+d)' % (
        len(b_lines), len(a_lines), sum(b_lines.values()), sum(a_lines.values()),
        sum(a_lines.values()) - sum(b_lines.values())))
    for rel in sorted(set(b_lines) | set(a_lines)):
        if b_lines.get(rel) != a_lines.get(rel):
            print('  %-60s %5s -> %5s' % (rel, b_lines.get(rel, '-'), a_lines.get(rel, '-')))

    b_texts, a_texts = collections.Counter(before['texts']), collections.Counter(after['texts'])
    gone, new = sorted(set(b_texts) - set(a_texts)), sorted(set(a_texts) - set(b_texts))
    print('\ntranslatable texts: %d distinct -> %d distinct; removed %d, added %d' % (
        len(b_texts), len(a_texts), len(gone), len(new)))
    for text in gone:
        print('  - %s' % _short(text))
    for text in new:
        print('  + %s' % _short(text))
    for lang, msgids in sorted(after['po'].items()):
        missing = sorted(t for t in a_texts if not msgids.get(t))
        was_missing = {t for t in b_texts if not before['po'].get(lang, {}).get(t)}
        print('  %s: %d texts have no translation (%d before)' % (lang, len(missing), len(was_missing)))
        for text in missing:
            if text not in was_missing:
                print('    newly untranslated: %s' % _short(text))

    b_ent, a_ent = before['entries'], after['entries']
    common = set(b_ent) & set(a_ent)
    removed = sorted(set(b_ent) - set(a_ent))
    added = sorted(set(a_ent) - set(b_ent))
    changed = sorted(k for k in common if set(b_ent[k]) != set(a_ent[k]))
    recounted = sorted(k for k in common if k not in changed and len(b_ent[k]) != len(a_ent[k]))
    moves = collections.Counter(
        (', '.join(sorted(set(before['where'][k]))), ', '.join(sorted(set(after['where'][k]))))
        for k in common if k not in changed and k not in recounted
        and sorted(before['where'][k]) != sorted(after['where'][k]))
    print('\ncode entries: %d -> %d; removed %d, added %d, changed %d, moved unchanged %d' % (
        len(b_ent), len(a_ent), len(removed), len(added), len(changed), sum(moves.values())))
    for label, keys in (('removed', removed), ('added', added), ('changed', changed)):
        for key in keys:
            print('  %-8s %s' % (label, key))
    for key in recounted:
        print('  count    %s: %d -> %d (same code; files split or merged)' % (key, len(b_ent[key]), len(a_ent[key])))
    for (src, dst), count in sorted(moves.items()):
        print('  moved    %3d unchanged: %s -> %s' % (count, src, dst))
    dupes = sorted(k for k, v in a_ent.items() if len(v) > 1 and k.startswith(('method', 'func', 'attr'))
                   and not k.endswith(('._inherit', '._description', ' _logger')))
    if dupes:
        print('\nsame name defined more than once (an _inherit chain inside one module; check it is meant):')
        for key in dupes:
            print('  %s in %s' % (key, ', '.join(after['where'][key])))


def longest(module_dir, minimum):
    found = []
    for rel, source in _sources(module_dir, None):
        if rel.endswith('.py'):
            for node in ast.walk(ast.parse(source, rel)):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    size = node.end_lineno - node.lineno + 1
                    if size >= minimum:
                        found.append((size, '%s:%d' % (rel, node.lineno), node.name))
    for size, where, name in sorted(found, reverse=True):
        print('%5d  %-45s %s' % (size, name, where))
    print('%d functions of %d+ lines' % (len(found), minimum))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='cmd', required=True)
    snap = sub.add_parser('snapshot')
    snap.add_argument('module_dir')
    snap.add_argument('--rev', help='git revision (default: working tree)')
    snap.add_argument('-o', '--output', required=True)
    comp = sub.add_parser('compare')
    comp.add_argument('before')
    comp.add_argument('after')
    long_ = sub.add_parser('long')
    long_.add_argument('module_dir')
    long_.add_argument('--min', type=int, default=80)
    args = parser.parse_args()
    if args.cmd == 'long':
        return longest(args.module_dir, args.min)
    if args.cmd == 'snapshot':
        data = snapshot(args.module_dir, args.rev)
        with open(args.output, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False)
        print('%s @ %s: %d python files, %d lines, %d code entries, %d translatable texts, po: %s' % (
            data['module'], data['rev'], len(data['lines']), sum(data['lines'].values()),
            len(data['entries']), len(set(data['texts'])), ', '.join(sorted(data['po'])) or 'none'))
    else:
        with open(args.before, encoding='utf-8') as fb, open(args.after, encoding='utf-8') as fa:
            compare(json.load(fb), json.load(fa))


if __name__ == '__main__':
    sys.exit(main())
