# Part of the GEC Georgian translation modules.
"""Keep our Georgian on industry zip packages (each .po applied on its own: several rename one record): their
terms come only from the zip, so gec_i18n_base never reaches them. Repairs the import's Apps-remote-module
links on the "Start here!" article and demo bookings."""
import io
import logging
from difflib import get_close_matches

from lxml import etree, html

from odoo import api, models
from odoo.tools.translate import JAVASCRIPT_TRANSLATION_COMMENT, CodeTranslations, ParsedTranslation

from odoo.addons.gec_i18n_base.hooks import SourceCheckedImporter
from odoo.addons.gec_i18n_base.i18n_patch import AREA_FOLDERS, area_po_paths

_logger = logging.getLogger(__name__)

AREA = 'gec_i18n_industries'
ACTIVE_KEYS = ('active_model', 'active_id', 'active_ids')


def _area_addons():
    return {addon for addon, places in AREA_FOLDERS.items() if any(area == AREA for area, _folder in places)}


def _installed_packages(env):
    return env['ir.module.module'].search([
        ('name', 'in', sorted(_area_addons())), ('state', 'in', ('installed', 'to upgrade')),
    ]).mapped('name')


def _active_langs(env, langs=None):
    active = [code for code, _name in env['res.lang'].get_installed() if code != 'en_US']
    return [lang for lang in (langs or active) if lang in active]


def _skeleton(value):
    """Tag sequence of an html value: equal for renders of one template whose translations keep its tags."""
    if not value:
        return ()
    root = html.fragment_fromstring(str(value), create_parent='div')
    return tuple(node.tag for node in root.iter() if isinstance(node.tag, str))


def _render_welcome_articles(env, addons, langs=None):
    """Re-render the "Start here!" article of these packages in our language; return the count. An article
    whose blocks were edited by hand is left alone; sudo, as the import writes it."""
    env = env(su=True)
    if 'knowledge.article' not in env:
        return 0
    langs = _active_langs(env, langs)
    rewritten = 0
    for addon in addons:
        ours = [lang for lang in langs if any(area_po_paths(addon, lang, [AREA]))]
        article = env.ref(f'{addon}.welcome_article', raise_if_not_found=False)
        template = f'{addon}.welcome_article_body'
        if not (ours and article and article._name == 'knowledge.article' and env.ref(template, raise_if_not_found=False)):
            continue
        lang = env.user.lang if env.user.lang in ours else ours[0]
        qweb, body_field = env['ir.qweb'], article._fields['body']
        body = body_field.convert_to_cache(qweb._render(template, lang=lang), article)
        english = body_field.convert_to_cache(qweb._render(template, lang='en_US'), article)
        if article.body == body:
            continue
        if _skeleton(article.body) != _skeleton(english):
            _logger.info('gec_i18n_industries: kept article %s.welcome_article, its blocks differ from the template', addon)
            continue
        article.write({'body': body})
        rewritten += 1
    return rewritten


def _unlink_apps_links(env):
    """Clear the document link an Apps > Industries import put on bookings; return the count. The import
    context's negative remote-module id, copied by calendar.event default_get, makes a booking fail to open.
    sudo: all companies."""
    env = env(su=True)
    if 'calendar.event' not in env:
        return 0
    events = env['calendar.event'].with_context(active_test=False).search([
        ('res_model', '=', 'ir.module.module'), ('res_id', '<', 0),
    ])
    events.write({'res_model_id': False, 'res_id': False})
    return len(events)


def _rebase_moved_terms(env, importer):
    """Move a translation to the stored view term with the same text but other markup (industry links hold
    database ids, href="/shop/%(xmlid)d")."""
    for model_name, model_terms in importer.model_terms_translations.items():
        for field_name, records in model_terms.items():
            translate = env[model_name]._fields[field_name].translate
            term_adapter = getattr(translate, 'term_adapter', None)
            if not term_adapter:
                continue
            for xmlid, src2langs in records.items():
                record = env.ref(xmlid, raise_if_not_found=False)
                value = record and record.with_context(lang='en_US')[field_name]
                if not value:
                    continue
                terms = ParsedTranslation(record._fields[field_name], value).terms
                for src in [src for src in src2langs if src not in terms]:
                    text = translate.get_text_content(src)
                    same_text = [
                        term for term in terms
                        if term not in src2langs and not translate.is_text(term)
                        and translate.get_text_content(term) == text
                    ]
                    if not same_text:
                        continue
                    term = get_close_matches(src, same_text, n=1, cutoff=0)[0]
                    try:
                        adapt = term_adapter(term)
                        moved = {lang: adapt(translated) for lang, translated in src2langs[src].items()}
                        fits = adapt(src) is not None and None not in moved.values()
                    except etree.XMLSyntaxError:
                        continue
                    if fits:
                        src2langs[term] = moved
                        del src2langs[src]


def _apply_per_package(env, langs=None):
    """Force-apply our file of every installed industry package, one importer per file."""
    langs = _active_langs(env, langs)
    loaded = 0
    for addon in _installed_packages(env):
        for lang in langs:
            for path in area_po_paths(addon, lang, [AREA]):
                importer = SourceCheckedImporter(env.cr, verbose=False)
                importer.load_file(path, lang)
                _rebase_moved_terms(env, importer)
                importer.save(force_overwrite=True)
                loaded += 1
    _logger.info('gec_i18n_industries: applied %d file(s) for %s', loaded, langs)
    return loaded


def _refresh_industries(env, langs=None):
    """Apply our files to the installed industry packages, then repair what their import left."""
    _apply_per_package(env, langs)
    articles = _render_welcome_articles(env, _installed_packages(env), langs)
    bookings = _unlink_apps_links(env)
    _logger.info('gec_i18n_industries: re-rendered %d article(s), cleared %d booking link(s)', articles, bookings)


class IrModuleModule(models.Model):
    _inherit = 'ir.module.module'

    @api.model
    def _load_module_terms(self, modules, langs, overwrite=False):
        """Re-apply our files after Odoo loaded an industry package's own terms; while the registry is not
        ready (this module loads before most apps) the pass waits for _register_hook."""
        super()._load_module_terms(modules, langs, overwrite=overwrite)
        if AREA in modules or _area_addons() & set(modules):
            if self.pool.ready:
                _refresh_industries(self.env, langs)
            else:
                self.pool._gec_industries_langs = langs

    def _register_hook(self):
        super()._register_hook()
        langs = getattr(self.pool, '_gec_industries_langs', None)
        if langs is not None:
            del self.pool._gec_industries_langs
            _refresh_industries(self.env, langs)

    @api.model
    def _import_zipfile(self, module_file, force=False, with_demo=False):
        """Import without the Apps list's active_* keys (they name a remote module that does not exist locally;
        calendar.event default_get would copy them), then put the articles in our language."""
        context = {key: value for key, value in self.env.context.items() if key not in ACTIVE_KEYS}
        result = super(IrModuleModule, self.with_context(context))._import_zipfile(
            module_file, force=force, with_demo=with_demo,
        )
        _render_welcome_articles(self.env, result[1])
        return result

    @api.model
    def _get_imported_module_translations_for_webclient(self, module, lang):
        result = super()._get_imported_module_translations_for_webclient(module, lang)
        lang = lang or self.env.context.get('lang') or 'en_US'
        if module not in _area_addons():
            return result
        ours = {}
        for path in area_po_paths(module, lang, [AREA]):
            with open(path, 'rb') as raw:
                fileobj = io.BytesIO(raw.read())
                fileobj.name = path
                ours.update(CodeTranslations._read_code_translations_file(
                    fileobj, lambda row: row.get('value') and JAVASCRIPT_TRANSLATION_COMMENT in row['comments'],
                ))
        if not ours:
            return result
        merged = {message['id']: message['string'] for message in result['messages']}
        merged.update(ours)
        return {'messages': tuple({'id': src, 'string': value} for src, value in merged.items())}
