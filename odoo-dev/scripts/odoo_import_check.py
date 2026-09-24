"""Import addons inside Odoo without a database and list the models they register.

Usage (run with the Odoo venv's python, e.g. data_venv/bin/python):
    python odoo_import_check.py -c odoo.conf rs_einvoice rs_base_methods [-o after.json] [--compare before.json]

Catches what pyflakes cannot: broken imports between addons, a class that no longer
registers, a method or field lost while moving code between files. It does not load
XML, build the registry or touch a database: views, data files, security rows and
_inherit of a model that is not loaded still need `-u <module>` on a test database.
Run it before a phase with -o, and after the phase with --compare.
"""
import argparse
import collections
import importlib
import json
import os
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('-c', '--config', required=True, help='odoo.conf with the addons_path to use')
    parser.add_argument('--odoo-root', help='directory holding the odoo package (default: next to the config)')
    parser.add_argument('addons', nargs='+')
    parser.add_argument('-o', '--output')
    parser.add_argument('--compare')
    args = parser.parse_args()

    sys.path.insert(0, os.path.abspath(args.odoo_root or os.path.dirname(os.path.abspath(args.config))))
    from odoo import fields
    from odoo.modules import module as odoo_module
    from odoo.orm.models import MetaModel
    from odoo.tools import config

    config.parse_config(['-c', args.config], setup_logging=False)
    odoo_module.initialize_sys_path()
    for addon in args.addons:
        importlib.import_module('odoo.addons.' + addon)
    print('import ok: %s' % ', '.join(args.addons))

    report = {}
    for addon in args.addons:
        models = collections.defaultdict(lambda: {'classes': 0, 'methods': set(), 'fields': set()})
        for cls in MetaModel._module_to_models__[addon]:
            inherit = cls._inherit if isinstance(cls._inherit, str) else (cls._inherit or [None])[0]
            entry = models[cls._name or inherit]
            entry['classes'] += 1
            for name, value in vars(cls).items():
                if isinstance(value, fields.Field):
                    entry['fields'].add(name)
                elif callable(value) or isinstance(value, (staticmethod, classmethod, property)):
                    entry['methods'].add(name)
        report[addon] = {m: {'classes': v['classes'], 'methods': sorted(v['methods']), 'fields': sorted(v['fields'])}
                         for m, v in sorted(models.items())}
        print('%s: %d models, %d classes, %d methods, %d fields' % (
            addon, len(models), sum(v['classes'] for v in models.values()),
            sum(len(v['methods']) for v in models.values()), sum(len(v['fields']) for v in models.values())))

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as fh:
            json.dump(report, fh, indent=1)
    if args.compare:
        with open(args.compare, encoding='utf-8') as fh:
            before = json.load(fh)
        same = True
        for addon in args.addons:
            old, new = before.get(addon, {}), report[addon]
            for model in sorted(set(old) | set(new)):
                o = old.get(model, {'classes': 0, 'methods': [], 'fields': []})
                n = new.get(model, {'classes': 0, 'methods': [], 'fields': []})
                for kind in ('methods', 'fields'):
                    lost, gained = sorted(set(o[kind]) - set(n[kind])), sorted(set(n[kind]) - set(o[kind]))
                    if lost or gained:
                        same = False
                        print('  %s %s: lost %s, gained %s' % (addon, model, lost or '-', gained or '-'))
                if o['classes'] != n['classes']:
                    print('  %s %s: %d -> %d classes (files split or merged)' % (addon, model, o['classes'], n['classes']))
        print('same models, methods and fields as before' if same else 'differences above')


if __name__ == '__main__':
    main()
