# -*- coding: utf-8 -*-
"""The guided way to let Odoo fill a KPI: pick a measure or source, optionally narrow it, preview, connect.
"""
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .bsc_kpi_recipes import CURRENCY, RECIPES, RECIPES_BY_KEY


class BscKpiConnect(models.TransientModel):
    _name = 'bsc.kpi.connect'
    _description = 'Connect a KPI to Odoo data'

    kpi_id = fields.Many2one('bsc.kpi', required=True, ondelete='cascade')
    mode = fields.Selection(
        [('recipe', 'A ready-made measure'),
         ('source', 'A data source defined by your administrator')],
        default='recipe', required=True)
    recipe = fields.Selection(
        selection='_recipe_selection', string='Measure',
        help="Only measures of the apps installed in this database are listed.")
    source_id = fields.Many2one(
        'bsc.kpi.source', string='Data Source',
        domain="[('recipe_key', '=', False)]")
    model_name = fields.Char(compute='_compute_model_name')
    extra_domain = fields.Char(
        string='Only count records where', default='[]',
        help="Optional. Narrow the measure, e.g. to one sales team, one project or one "
             "product category. Leave empty to count everything the measure covers.")
    scale = fields.Selection(
        [('1', 'As it is'), ('0.001', 'In thousands'), ('0.000001', 'In millions')],
        string='Report the figure', default=lambda self: self._default_scale(), required=True,
        help="Use thousands or millions when the KPI's targets are written that way.")
    explanation = fields.Html(compute='_compute_explanation', sanitize=False)
    preview = fields.Html(compute='_compute_preview', sanitize=False)
    has_source_choice = fields.Boolean(compute='_compute_has_source_choice')

    @api.model
    def _default_scale(self):
        kpi = self.env['bsc.kpi'].browse(self.env.context.get('default_kpi_id'))
        unit = (kpi.exists().uom_name or '').lower()
        if any(word in unit for word in ('million', 'მილიონ', 'mln')):
            return '0.000001'
        if any(word in unit for word in ('thousand', 'ათას', "'000")):
            return '0.001'
        return '1'

    @api.model
    def _installed_recipes(self):
        installed = set(self.env['ir.module.module'].sudo().search(
            [('state', '=', 'installed')]).mapped('name'))
        # Offer a measure only to someone who may read what it counts: the preview must not bypass their access.
        return [r for r in RECIPES if r['module'] in installed and r['model'] in self.env
                and self.env[r['model']].has_access('read')]

    @api.model
    def _t(self, text, lang=None):
        """Translate a catalogue text in the user's language (they are lazy)."""
        if hasattr(text, '_translate'):
            return text._translate(lang or self.env.lang or 'en_US')
        return text or ''

    @api.model
    def _recipe_label(self, recipe, lang=None):
        return '%s: %s' % (self._t(recipe['app'], lang), self._t(recipe['name'], lang))

    @api.model
    def _recipe_selection(self):
        return [(r['key'], self._recipe_label(r)) for r in self._installed_recipes()]

    @api.depends('mode')
    def _compute_has_source_choice(self):
        has_any = bool(self.env['bsc.kpi.source'].search_count([('recipe_key', '=', False)]))
        for wizard in self:
            wizard.has_source_choice = has_any

    @api.depends('mode', 'recipe', 'source_id')
    def _compute_model_name(self):
        for wizard in self:
            if wizard.mode == 'recipe' and wizard.recipe:
                wizard.model_name = RECIPES_BY_KEY[wizard.recipe]['model']
            elif wizard.mode == 'source' and wizard.source_id:
                wizard.model_name = wizard.source_id.model_name
            else:
                wizard.model_name = False

    @api.onchange('mode', 'recipe', 'source_id')
    def _onchange_measure(self):
        self.extra_domain = '[]'

    @api.depends('mode', 'recipe', 'source_id')
    def _compute_explanation(self):
        for wizard in self:
            recipe = RECIPES_BY_KEY.get(wizard.recipe) if wizard.mode == 'recipe' else None
            if recipe:
                direction = dict(self.env['bsc.kpi']._fields['direction']._description_selection(
                    self.env)).get(recipe['direction'], '')
                wizard.explanation = Markup(
                    "<p>%s</p><p class='text-muted mb-0'>%s: <b>%s</b> · %s</p>") % (
                    self._t(recipe['description']), _("Unit"), wizard._recipe_uom(recipe),
                    direction)
            elif wizard.mode == 'source' and wizard.source_id:
                wizard.explanation = Markup("<p>%s</p>") % (
                    wizard.source_id.description or _("No definition was written for this source."))
            else:
                wizard.explanation = False

    @api.depends('mode', 'recipe', 'source_id', 'extra_domain', 'kpi_id', 'scale')
    def _compute_preview(self):
        for wizard in self:
            wizard.preview = wizard._render_preview()

    def _recipe_uom(self, recipe):
        uom = recipe.get('uom') or ''
        if uom == CURRENCY:
            company = self.kpi_id.scorecard_id.company_id or self.env.company
            return company.currency_id.name
        return self._t(uom)

    def _recipe_source_values(self, recipe):
        """The ``bsc.kpi.source`` values a recipe stands for."""
        Model = self.env['ir.model']
        Fields = self.env['ir.model.fields']
        model = recipe['model']
        model_rec = Model._get(model)

        def field(name):
            return Fields._get(model, name).id if name else False

        company = 'company_id' if 'company_id' in self.env[model]._fields else False
        return {
            'name': self._recipe_label(recipe, 'en_US'),
            'description': self._t(recipe['description']),
            'recipe_key': recipe['key'],
            'model_id': model_rec.id,
            'domain': repr(recipe.get('domain') or []),
            'aggregate': recipe['aggregate'],
            'ratio_domain': repr(recipe.get('ratio_domain') or []),
            'include_archived': recipe.get('include_archived', False),
            'value_field_id': field(recipe.get('value_field')),
            'date_field_id': field(recipe['date_field']),
            'company_field_id': field(company),
            'multiply_by': recipe.get('multiply_by', 1.0),
            'uom_hint': self._recipe_uom(recipe),
        }

    def _chosen_source(self, create=False):
        """The source to read: an existing record, a virtual one from the recipe (preview), or one created on connect.
        An archived recipe source is found, but returned in normal context so the count skips it."""
        self.ensure_one()
        if self.mode == 'source':
            return self.source_id
        recipe = RECIPES_BY_KEY.get(self.recipe)
        if not recipe:
            return self.env['bsc.kpi.source']
        Source = self.env['bsc.kpi.source'].sudo().with_context(active_test=False)
        existing = Source.search([('recipe_key', '=', recipe['key'])], limit=1)
        if existing:
            if create and not existing.active:
                existing.active = True
            return existing.with_context(active_test=True)
        values = self._recipe_source_values(recipe)
        if not create:
            return Source.with_context(active_test=True).new(values)
        # Recipes are vetted in code, so a manager may create one; hand-written sources are for administrators.
        if Source.search_count([('name', '=', values['name'])]):
            values['name'] = '%s (%s)' % (values['name'], recipe['key'])
        source = Source.with_context(lang='en_US').create(values)
        for lang, __ in self.env['res.lang'].get_installed():
            if lang != 'en_US':
                source.update_field_translations('name', {lang: self._recipe_label(recipe, lang)})
        return source.with_context(lang=self.env.lang, active_test=True)

    def _extra_domain_list(self):
        kpi = self.env['bsc.kpi'].new({'name': 'x', 'source_extra_domain': self.extra_domain or '[]'})
        return kpi._extra_domain()

    def _render_preview(self):
        self.ensure_one()
        source = self._chosen_source()
        kpi = self.kpi_id
        if not source or not kpi:
            return Markup("<p class='text-muted'>%s</p>") % _(
                "Choose a measure to see what it would report.")
        scorecard = kpi.scorecard_id
        period = scorecard.current_period_id or scorecard.period_ids.sorted('date_from')[-1:]
        if period:
            date_from, date_to, label = period.date_from, period.date_to, period.name
        else:
            date_to = fields.Date.context_today(self)
            date_from = date_to.replace(day=1)
            label = _("this month")
        try:
            company = scorecard.company_id or self.env.company
            extra = self._extra_domain_list()
            if source.with_env(self.env)._bsc_unreadable_reason(extra, company):
                return Markup("<div class='alert alert-warning mb-0'>%s</div>") % _(
                    "You may not see every record this measure would count, so no figure "
                    "is shown. Ask a Balanced Scorecard administrator to connect it.")
            value, count = source._fetch_value(
                date_from, date_to, company=company, extra_domain=extra,
                tz_name=scorecard.responsible_id.tz or 'UTC')
        except Exception as error:  # noqa: BLE001 - shown to the user, not raised
            return Markup("<div class='alert alert-danger mb-0'>%s</div>") % _(
                "This measure cannot be read: %s", error)
        if value is None:
            return Markup("<div class='alert alert-warning mb-0'>%s</div>") % _(
                "%(period)s: no records matched yet, so the figure would stay empty "
                "(it is never reported as zero). That is normal early in a period or "
                "before the app is in use - check the filter otherwise.", period=label)
        value *= float(self.scale or 1)
        digits = kpi.digits if kpi.digits is not None else 2
        shown = ('{:,.%df}' % max(digits, 0)).format(value)
        unit = self._scaled_unit(source.uom_hint)
        result = Markup(
            "<div class='alert alert-success mb-0'><b>%s</b> %s &#160; <span class='text-muted'>%s</span></div>"
        ) % (shown, unit, _(
            "%(period)s, from %(count)s record(s)", period=label, count=count))
        if kpi.uom_name and unit and kpi.uom_name.strip().lower() != unit.strip().lower():
            result += Markup("<div class='alert alert-warning mt-2 mb-0'>%s</div>") % _(
                "The KPI is kept in \"%(kpi_unit)s\"; this measure reports \"%(unit)s\". "
                "Make sure the targets mean the same thing - choose thousands or millions "
                "above, or correct the KPI's unit and target after connecting.",
                kpi_unit=kpi.uom_name, unit=unit)
        return result

    def _scaled_unit(self, unit):
        unit = unit or ''
        if self.scale == '0.001':
            return _("thousand %s", unit).strip()
        if self.scale == '0.000001':
            return _("million %s", unit).strip()
        return unit

    def action_connect(self):
        self.ensure_one()
        if self.mode == 'recipe' and not self.recipe:
            raise UserError(_("Choose a measure first."))
        if self.mode == 'source' and not self.source_id:
            raise UserError(_("Choose a data source first."))
        self._extra_domain_list()   # validates the filter before anything is saved
        source = self._chosen_source(create=True)
        kpi = self.kpi_id
        values = {
            'data_source': 'odoo',
            'source_id': source.id,
            'source_extra_domain': self.extra_domain or '[]',
            'source_scale': float(self.scale or 1),
        }
        if not kpi.uom_name and source.uom_hint:
            values['uom_name'] = self._scaled_unit(source.uom_hint)
        recipe = RECIPES_BY_KEY.get(source.recipe_key)
        if recipe and not kpi.measurement_ids.filtered('actual_value_set'):
            # Nothing reported yet, so the direction can still follow the measure.
            values['direction'] = recipe['direction']
        kpi.write(values)
        kpi.message_post(body=_("Connected to Odoo data: %s.", source.name))
        rows = kpi._refresh_open_periods()
        filled = rows.filtered(lambda m: m.auto_state == 'ok')
        held = rows.filtered('auto_needs_attention')
        kept = rows.filtered(lambda m: m.auto_state == 'manual')
        message = _("%(kpi)s is now filled from Odoo data. %(filled)s period(s) filled now; "
                    "the figure is refreshed every night.", kpi=kpi.name, filled=len(filled))
        if kept:
            message += ' ' + _("%s period(s) already had a typed figure, which was kept. "
                               "Clear it to let Odoo fill it.", len(kept))
        if held:
            message += ' ' + _("%s period(s) need a look - see the Data Entry list.", len(held))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Connected"), 'message': message,
                'type': 'warning' if held else 'success', 'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }
