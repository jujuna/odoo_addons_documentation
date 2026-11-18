# Part of the GEC Georgian translation modules.
"""Force our Georgian translations onto records an upgrade skips: ``overwrite=False`` keeps an existing
``ka_GE`` value, and a ``noupdate`` record needs ``force_overwrite``. Applied with ``force_overwrite=True``
over our own files only."""
import logging
from collections import defaultdict

from odoo.tools import SQL
from odoo.tools.translate import TranslationImporter

_logger = logging.getLogger(__name__)


class SourceCheckedImporter(TranslationImporter):
    """TranslationImporter that drops a field translation whose English no longer matches: `model:` terms apply
    by xmlid without comparing the source, which would overwrite a customised label. View terms
    (`model_terms:`) match by term."""

    def __init__(self, cr, verbose=True):
        super().__init__(cr, verbose=verbose)
        self.model_sources = defaultdict(dict)  # (model, field) -> {xmlid: source}

    def _load(self, reader, lang, xmlids=None):
        rows = list(reader)
        for row in rows:
            if row.get('type') == 'model' and row.get('value') and row.get('src'):
                key = (row['imd_model'], row['name'].split(',')[1])
                self.model_sources[key][f"{row['module']}.{row['imd_name']}"] = row['src']
        return super()._load(iter(rows), lang, xmlids)

    def save(self, overwrite=False, force_overwrite=False):
        for (model_name, field_name), sources in self.model_sources.items():
            entries = self.model_translations.get(model_name, {}).get(field_name)
            if not entries or model_name not in self.env:
                continue
            table = self.env[model_name]._table
            current = dict(self.env.execute_query(SQL(
                """SELECT imd.module || '.' || imd.name, m.%s->>'en_US'
                   FROM ir_model_data imd JOIN %s m ON m.id = imd.res_id
                   WHERE imd.model = %s AND imd.module || '.' || imd.name = ANY(%s)""",
                SQL.identifier(field_name), SQL.identifier(table), model_name, list(sources),
            )))
            for xmlid, source in sources.items():
                english = current.get(xmlid)
                if english is not None and english.strip() != source.strip():
                    entries.pop(xmlid, None)
        self.model_sources.clear()
        return super().save(overwrite=overwrite, force_overwrite=force_overwrite)


def force_apply_translations(env, areas=None, langs=None):
    """Re-import the files of the given area modules (all when None) for the installed addons; return the file
    count. Only our strings are touched, a field label only while its English equals ours."""
    from .i18n_patch import AREA_FOLDERS, area_po_paths  # noqa: PLC0415

    active = [code for code, _name in env['res.lang'].get_installed() if code != 'en_US']
    langs = [lang for lang in (langs or active) if lang in active]
    if not langs:
        return 0
    addons = env['ir.module.module'].search([('state', 'in', ('installed', 'to upgrade'))]).mapped('name')
    importer = SourceCheckedImporter(env.cr, verbose=False)
    loaded = 0
    for addon in addons:
        if addon not in AREA_FOLDERS:
            continue
        for lang in langs:
            for path in area_po_paths(addon, lang, areas):
                importer.load_file(path, lang)
                loaded += 1
    importer.save(force_overwrite=True)
    _logger.info('gec_i18n: force-applied %d file(s) for %s (areas: %s)', loaded, langs, ', '.join(areas or ['all']))
    return loaded
