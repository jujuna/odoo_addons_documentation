# Part of the GEC Georgian translation modules.
"""Let the gec_i18n_* area modules supply the translations of any Odoo addon: we wrap get_po_paths() (used by
ir_module._load_module_terms, CodeTranslations, Manifest.get_translations) to also yield <area
module>/i18n_extra/<addon>/<lang>.po last, so our value wins."""
import logging
import os

from odoo.addons.base.models import ir_module
from odoo.modules import module as odoo_module
from odoo.tools import file_path, translate

_logger = logging.getLogger(__name__)

AREA_MODULES = (
    'gec_i18n_base',
    'gec_i18n_accounting',
    'gec_i18n_sales',
    'gec_i18n_pos',
    'gec_i18n_supply_chain',
    'gec_i18n_hr',
    'gec_i18n_services',
    'gec_i18n_productivity',
    'gec_i18n_website',
    'gec_i18n_marketing',
    'gec_i18n_industries',
)


def _index_area_folders():
    """Return {addon: [(area, folder), ...]} for every i18n_extra/<addon> folder on disk."""
    index = {}
    for area in AREA_MODULES:
        try:
            root = file_path(f'{area}/i18n_extra')
        except FileNotFoundError:
            continue
        for addon in sorted(os.listdir(root)):
            folder = os.path.join(root, addon)
            if os.path.isdir(folder):
                index.setdefault(addon, []).append((area, folder))
    duplicates = sorted(addon for addon, places in index.items() if len(places) > 1)
    if duplicates:
        _logger.warning('gec_i18n: addons with a folder in more than one area module: %s', duplicates)
    return index


AREA_FOLDERS = _index_area_folders()


def area_po_paths(module_name, lang, areas=None):
    """Yield our .po files for this addon and language, least to most specific."""
    for area, folder in AREA_FOLDERS.get(module_name, ()):
        if areas and area not in areas:
            continue
        for filename in translate.get_base_langs(lang):
            path = os.path.join(folder, filename + '.po')
            if os.path.isfile(path):
                yield path


_odoo_get_po_paths = translate.get_po_paths


def get_po_paths(module_name, lang):
    yield from _odoo_get_po_paths(module_name, lang)
    yield from area_po_paths(module_name, lang)


def install_patch(namespace):
    """Point a module that imported get_po_paths by name at our version."""
    if getattr(namespace, 'get_po_paths', None) is not get_po_paths:
        namespace.get_po_paths = get_po_paths


for _namespace in (translate, ir_module, odoo_module):
    install_patch(_namespace)
_logger.info('gec_i18n: Georgian area translations active for %d addons', len(AREA_FOLDERS))
