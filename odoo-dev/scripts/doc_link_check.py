#!/usr/bin/env python3
"""Check the ../-relative source links of one documentations/*.md file against the Odoo 20 tree.

Usage (from the project root):
    python3 .claude/skills/odoo-dev/scripts/doc_link_check.py documentations/<file>.md [--all]

Each markdown link whose target starts with ../ is resolved from documentations/ and classified:
    OK       file and line exist, and an identifier named near the link appears within +-3 lines of the target
    CHECK    line exists, but no identifier from the sentence was found near it -- judge by hand
    NOLINE   file/dir link without #L anchor, exists and is tracked
    MISSING  file or directory does not exist
    RANGE    #L line number is past the end of the file
    STALE    exists on disk but is not tracked by git: module deleted in 20.0 (leftover __pycache__ dir)
Only non-OK/NOLINE rows are printed unless --all is given. A summary line is printed last.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
DOCS = os.path.join(ROOT, 'documentations')
LINK_RE = re.compile(r'\[([^\]]*)\]\((\.\./[^)\s#]+)(?:#L(\d+)(?:-L?(\d+))?)?\)')
TICK_RE = re.compile(r'`([^`]+)`')
IDENT_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]{3,}')
NOISE = {'self', 'True', 'False', 'None', 'return', 'models', 'fields', 'model', 'field', 'record', 'records',
         'addons', 'enterprise', 'odoo', 'views', 'data', 'security', 'python', 'line', 'file'}


def tracked_sets():
    repos = [(ROOT, ['addons', 'odoo']), (os.path.join(ROOT, 'enterprise'), None),
             (os.path.join(ROOT, 'custom_addons', 'gec_odoo_modules'), None)]
    files = set()
    for repo, paths in repos:
        cmd = ['git', '-C', repo, 'ls-files'] + (paths or [])
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        except Exception:
            continue
        prefix = os.path.relpath(repo, ROOT)
        for rel in out.splitlines():
            files.add(os.path.normpath(os.path.join(prefix, rel)) if prefix != '.' else rel)
    dirs = set()
    for f in files:
        parts = f.split('/')
        for i in range(1, len(parts)):
            dirs.add('/'.join(parts[:i]))
    return files, dirs


def git_managed(rel):
    return rel.startswith(('addons/', 'odoo/', 'enterprise/', 'custom_addons/gec_odoo_modules/'))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    doc = sys.argv[1]
    show_all = '--all' in sys.argv
    files, dirs = tracked_sets()
    counts = {}
    cache = {}
    with open(doc, encoding='utf-8') as fh:
        doc_lines = fh.readlines()
    for n, text in enumerate(doc_lines, 1):
        for m in LINK_RE.finditer(text):
            label, target, l1, l2 = m.group(1), m.group(2), m.group(3), m.group(4)
            abs_path = os.path.normpath(os.path.join(DOCS, target))
            rel = os.path.relpath(abs_path, ROOT)
            status, content = None, ''
            if not os.path.exists(abs_path):
                status = 'MISSING'
            elif git_managed(rel) and rel not in files and rel not in dirs:
                status = 'STALE'
            elif not l1:
                status = 'NOLINE'
            elif os.path.isdir(abs_path):
                status = 'MISSING'
                content = 'anchor on a directory'
            else:
                if abs_path not in cache:
                    with open(abs_path, encoding='utf-8', errors='replace') as fh:
                        cache[abs_path] = fh.readlines()
                src = cache[abs_path]
                start = int(l1)
                end = int(l2) if l2 else start
                if start > len(src):
                    status = 'RANGE'
                    content = f'file has {len(src)} lines'
                else:
                    content = src[start - 1].strip()[:140]
                    window = ''.join(src[max(0, start - 4):min(len(src), end + 8)])
                    basename = os.path.basename(abs_path).rsplit('.', 1)[0]
                    words = {w for w in IDENT_RE.findall(label) if w not in NOISE}
                    before = text[max(0, m.start() - 150):m.start()]
                    after = text[m.end():m.end() + 40]
                    for tick in TICK_RE.findall(before) + TICK_RE.findall(after):
                        words.update(w for w in IDENT_RE.findall(tick) if w not in NOISE)
                    words = {w for w in words if w != basename and not w.isdigit()}
                    status = 'OK' if any(w in window for w in words) else 'CHECK'
                    if status == 'CHECK':
                        content = f'{content}    [looked for: {", ".join(sorted(words)[:6]) or "-"}]'
            counts[status] = counts.get(status, 0) + 1
            if show_all or status not in ('OK', 'NOLINE'):
                anchor = f'#L{l1}' + (f'-L{l2}' if l2 else '') if l1 else ''
                print(f'{status:<7} doc:{n:<5} [{label[:50]}] -> {target}{anchor}  | {content}')
    total = sum(counts.values())
    print('SUMMARY', doc, f'links={total}', ' '.join(f'{k}={v}' for k, v in sorted(counts.items())))


if __name__ == '__main__':
    main()
