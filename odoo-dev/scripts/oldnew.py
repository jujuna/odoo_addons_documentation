"""Run the OLD and the NEW version of a module's methods side by side, without a database.

For a refactor that rewrites method bodies (not a pure move): same inputs must give the
same result, the same error text, and the same calls to the outside world. Import this
from a throwaway script run with the Odoo venv's python:

    import sys; sys.path.insert(0, '<odoo root>/.claude/skills/odoo-dev/scripts')
    import oldnew
    oldnew.boot('<odoo root>/odoo.conf')
    old = oldnew.load_old('custom_addons/gec_odoo_modules/rs_einvoice', rev='89ca0cb')
    new = oldnew.module('rs_einvoice')
    for version in (old, new):
        calls = oldnew.Recorder(reply=lambda path, args, kwargs: True)
        svc = oldnew.fake_record(version.models.rs_soap_service.RsSoapService,
                                 _get_client=lambda self: calls,
                                 _get_credentials=lambda self: {'user_id': 1, 'su': 'u', 'sp': 'p'})
        print(oldnew.outcome(svc.delete_invoice, 10), calls.log)

A method that reaches super() cannot run on a fake record; outcome() reports that as
'reached super()', which means every guard before it passed. Anything that needs the
ORM (search, write, computes) needs a test database instead.
"""
import atexit
import importlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

_TMP = None


def boot(config_path, odoo_root=None):
    """Put Odoo on sys.path and make every addon of the config's addons_path importable."""
    sys.path.insert(0, os.path.abspath(odoo_root or os.path.dirname(os.path.abspath(config_path))))
    from odoo.modules import module as odoo_module
    from odoo.tools import config
    config.parse_config(['-c', config_path], setup_logging=False)
    odoo_module.initialize_sys_path()


def module(addon, dotted=''):
    """Import the current (working tree) version of an addon, or one of its submodules."""
    return importlib.import_module('odoo.addons.%s%s' % (addon, '.' + dotted if dotted else ''))


def load_old(addon_dir, rev=None, alias=None):
    """Import another version of an addon under a private name (default '<addon>_old').

    ``addon_dir`` is the addon in a git repository (with ``rev``), or a copied snapshot
    directory (without ``rev``). Its relative imports resolve inside the old version;
    absolute imports of other addons resolve to their current version.
    """
    global _TMP
    import odoo.addons
    addon_dir = os.path.abspath(addon_dir)
    alias = alias or os.path.basename(addon_dir) + '_old'
    if _TMP is None:
        _TMP = tempfile.mkdtemp(prefix='oldnew_')
        atexit.register(shutil.rmtree, _TMP, True)
        odoo.addons.__path__.append(_TMP)
    target = os.path.join(_TMP, alias)
    shutil.rmtree(target, ignore_errors=True)
    if rev is None:
        shutil.copytree(addon_dir, target, ignore=shutil.ignore_patterns('__pycache__'))
    else:
        repo = subprocess.run(['git', '-C', addon_dir, 'rev-parse', '--show-toplevel'],
                              capture_output=True, text=True, check=True).stdout.strip()
        prefix = os.path.relpath(addon_dir, repo)
        archive = os.path.join(_TMP, alias + '.tar')
        subprocess.run(['git', '-C', repo, 'archive', '-o', archive, rev, prefix], check=True)
        with tarfile.open(archive) as tar:
            tar.extractall(_TMP, filter='data')
        os.rename(os.path.join(_TMP, prefix), target)
        os.remove(archive)
    return importlib.import_module('odoo.addons.' + alias)


def fake_record(*classes, **attrs):
    """An object carrying the methods and constants of ``classes`` (later ones win, like an
    _inherit chain) plus ``attrs``: values, or functions taking ``self``."""
    from odoo import fields
    namespace = {}
    for cls in classes:
        for key, value in vars(cls).items():
            if not key.startswith('__') and not isinstance(value, fields.Field):
                namespace[key] = value
    namespace.update({k: v for k, v in attrs.items() if callable(v)})
    record = type('Fake' + classes[-1].__name__, (), namespace)()
    record.__dict__.update({k: v for k, v in attrs.items() if not callable(v)})
    return record


def outcome(func, *args, **kwargs):
    """Call func and return something comparable: the result, the error, or 'reached super()'."""
    try:
        return ('returned', repr(func(*args, **kwargs)))
    except TypeError as e:
        if 'super(' in str(e):
            return ('reached super()', None)
        return ('raised', 'TypeError', str(e))
    except Exception as e:  # noqa: BLE001 - the error itself is the outcome being compared
        return ('raised', type(e).__name__, str(e))


class Recorder:
    """Stands in for an external client: any attribute path can be called, every call is
    logged as (path, args, sorted kwargs), and ``reply(path, args, kwargs)`` gives the answer."""

    def __init__(self, reply=None, path='', log=None):
        self._reply, self._path = reply, path
        self.log = [] if log is None else log

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return Recorder(self._reply, '%s.%s' % (self._path, name) if self._path else name, self.log)

    def __call__(self, *args, **kwargs):
        self.log.append((self._path, args, sorted(kwargs.items())))
        return self._reply(self._path, args, kwargs) if self._reply else None
