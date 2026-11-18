# -*- coding: utf-8 -*-
"""The vetted query catalogue: an administrator writes and tests a source once, KPI designers pick it from a dropdown.
"""
from ast import literal_eval
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain

NUMERIC_TYPES = ('integer', 'float', 'monetary')
DATE_TYPES = ('date', 'datetime')


class BscKpiSource(models.Model):
    _name = 'bsc.kpi.source'
    _description = 'BSC Automated KPI Source'
    _order = 'name'

    name = fields.Char(required=True, translate=True,
                       help="How this source appears to the people designing KPIs, "
                            "e.g. 'Invoiced revenue' or 'Tasks closed on time'.")
    active = fields.Boolean(default=True)
    description = fields.Text(
        help="What exactly this counts, and what it deliberately excludes. "
             "Write it for the person who will have to defend the number.")

    # The technical names are stored related fields of the dropdowns, so downstream code reads them as before.
    model_id = fields.Many2one(
        'ir.model', string='Model', ondelete='cascade',
        help="Which records are counted, e.g. Sales Order, Journal Item, Task.")
    model_name = fields.Char(
        related='model_id.model', store=True, readonly=True,
        string='Technical Model',
        help="Technical model name, filled from the model chosen above.")
    domain = fields.Char(
        default='[]', required=True,
        help="Filter applied before the period dates. Read as a literal list - "
             "no function calls, no code.")
    aggregate = fields.Selection(
        [('count', 'Count of records'),
         ('sum', 'Sum of a field'),
         ('avg', 'Average of a field'),
         ('min', 'Minimum of a field'),
         ('max', 'Maximum of a field'),
         ('ratio', 'Share of records (%)')],
        default='count', required=True,
        help="'Share of records' counts the records that also match the condition "
             "below and divides by all records: e.g. won opportunities out of all "
             "closed ones.")
    ratio_domain = fields.Char(
        string='Counted as a Hit', default='[]',
        help="For a share: which of the records count in the numerator. Read as a "
             "literal list - no function calls, no code.")
    include_archived = fields.Boolean(
        string='Include Archived Records',
        help="Odoo hides archived records by default. A lost opportunity, for one, is "
             "archived - a win rate that ignores it would always be 100%.")
    recipe_key = fields.Char(
        string='Ready-made Measure', readonly=True, copy=False, index=True,
        help="Set when the source was created from the catalogue of ready-made "
             "measures. Editing it here is allowed; the catalogue will reuse it.")
    # Only stored fields: a non-stored one cannot be aggregated by _read_group or searched by date.
    value_field_id = fields.Many2one(
        'ir.model.fields', string='Field', ondelete='cascade',
        domain="[('model_id', '=', model_id),"
               " ('ttype', 'in', ['integer', 'float', 'monetary']),"
               " ('store', '=', True)]",
        help="The numeric field to aggregate. Not used for a plain count.")
    value_field = fields.Char(
        related='value_field_id.name', store=True, readonly=True,
        string='Technical Field')
    date_field_id = fields.Many2one(
        'ir.model.fields', string='Date Field', ondelete='cascade',
        domain="[('model_id', '=', model_id),"
               " ('ttype', 'in', ['date', 'datetime']),"
               " ('store', '=', True)]",
        help="Which date decides that a record belongs to a period. "
             "Choose deliberately: invoice_date and date do not give the same answer. "
             "Deliberately never guessed for you.")
    date_field = fields.Char(
        related='date_field_id.name', store=True, readonly=True,
        string='Technical Date Field')
    company_field_id = fields.Many2one(
        'ir.model.fields', string='Company Field', ondelete='cascade',
        domain="[('model_id', '=', model_id), ('ttype', '=', 'many2one'),"
               " ('relation', '=', 'res.company')]",
        help="Used to keep the figure inside the scorecard's company. "
             "Leave it empty for a model that has no company.")
    company_field = fields.Char(
        related='company_field_id.name', store=True, readonly=True,
        string='Technical Company Field')
    multiply_by = fields.Float(
        default=1.0, required=True,
        help="Unit conversion applied to the result, e.g. 0.001 to report in thousands.")
    uom_hint = fields.Char(
        string='Unit', help="What the result is expressed in. Shown to the KPI designer.")

    kpi_ids = fields.One2many('bsc.kpi', 'source_id', string='KPIs Using This')
    kpi_count = fields.Integer(compute='_compute_kpi_count')
    last_test_note = fields.Char(readonly=True, copy=False)

    _name_uniq = models.Constraint(
        'unique(name)',
        'A source with that name already exists.',
    )

    @api.depends('kpi_ids')
    def _compute_kpi_count(self):
        for source in self:
            source.kpi_count = len(source.kpi_ids)

    def write(self, vals):
        """Editing what a source counts voids the confirmed jumps of its KPIs."""
        result = super().write(vals)
        if {'model_id', 'domain', 'aggregate', 'value_field_id', 'date_field_id',
                'company_field_id', 'multiply_by', 'ratio_domain',
                'include_archived'} & set(vals):
            # Sources are shared by every company: reach the KPIs of all, archived included.
            self.sudo().with_context(active_test=False).kpi_ids._reset_deviation_confirmed()
        return result

    @api.constrains('model_id', 'model_name', 'value_field_id', 'value_field',
                    'date_field_id', 'date_field', 'company_field_id',
                    'company_field', 'aggregate', 'domain', 'ratio_domain')
    def _check_definition(self):
        """Full definition check: an import, data file or other module can still write the technical names directly."""
        for source in self:
            model = source._model_or_raise()
            if not source.date_field:
                raise ValidationError(_(
                    "Choose the date field that decides which period a record "
                    "belongs to."))
            if source.date_field not in model._fields:
                raise ValidationError(_(
                    "Model '%(model)s' has no field '%(field)s'.",
                    model=source.model_name, field=source.date_field))
            date_field = model._fields[source.date_field]
            if date_field.type not in DATE_TYPES:
                raise ValidationError(_(
                    "'%s' is not a date field, so it cannot decide which period a "
                    "record belongs to.", source.date_field))
            if not date_field.store:
                raise ValidationError(_(
                    "'%s' is not stored in the database, so a period cannot be "
                    "searched on it.", source.date_field))
            if source.aggregate not in ('count', 'ratio'):
                if not source.value_field:
                    raise ValidationError(_(
                        "Choose the field to aggregate, or switch the source to a "
                        "plain record count."))
                if source.value_field not in model._fields:
                    raise ValidationError(_(
                        "Model '%(model)s' has no field '%(field)s'.",
                        model=source.model_name, field=source.value_field))
                value_field = model._fields[source.value_field]
                if value_field.type not in NUMERIC_TYPES:
                    raise ValidationError(_(
                        "'%s' is not a numeric field.", source.value_field))
                if not value_field.store:
                    raise ValidationError(_(
                        "'%s' is not stored in the database, so it cannot be "
                        "aggregated.", source.value_field))
            if source.company_field and source.company_field not in model._fields:
                raise ValidationError(_(
                    "Model '%(model)s' has no field '%(field)s'. Clear the company "
                    "field if this model is not company-specific.",
                    model=source.model_name, field=source.company_field))
            source._domain_or_raise()
            if source.aggregate == 'ratio':
                source._domain_or_raise('ratio_domain')

    @api.onchange('model_id')
    def _onchange_model_id(self):
        """A new model invalidates every field chosen under the old one.
        Company field is set when the model has the usual one (a wrong one leaks across companies);
date field stays empty."""
        self.value_field_id = False
        self.date_field_id = False
        self.company_field_id = False
        self.domain = '[]'
        if not self.model_id:
            return
        self.company_field_id = self.env['ir.model.fields'].search([
            ('model_id', '=', self.model_id.id),
            ('name', '=', 'company_id'),
            ('ttype', '=', 'many2one'),
            ('relation', '=', 'res.company'),
        ], limit=1)

    @api.onchange('aggregate')
    def _onchange_aggregate(self):
        if self.aggregate in ('count', 'ratio'):
            self.value_field_id = False

    def _model_or_raise(self):
        self.ensure_one()
        if not self.model_name:
            raise ValidationError(_(
                "Choose the model this source reads from."))
        if self.model_name not in self.env:
            raise ValidationError(_("There is no model called '%s'.", self.model_name))
        model = self.env[self.model_name]
        if model._abstract or model._transient:
            raise ValidationError(_(
                "'%s' is not a stored model, so it holds no history to measure.",
                self.model_name))
        return model

    def _domain_or_raise(self, field_name='domain'):
        """Parse the domain as data. literal_eval cannot call anything."""
        self.ensure_one()
        try:
            parsed = literal_eval(self[field_name] or '[]')
        except (ValueError, SyntaxError) as error:
            raise ValidationError(_(
                "The domain of '%(name)s' is not a valid literal list: %(error)s",
                name=self.name, error=error)) from error
        if not isinstance(parsed, list):
            raise ValidationError(_("The domain must be a list."))
        try:
            Domain(parsed)
        except (ValueError, TypeError) as error:
            raise ValidationError(_(
                "The domain of '%(name)s' is not a valid domain: %(error)s",
                name=self.name, error=error)) from error
        return parsed

    def _period_bounds(self, model, date_from, date_to, tz_name=None):
        """Date bounds for the period, in the units the field stores.
        A datetime is stored in UTC, so the window runs from local midnight to local midnight, converted."""
        self.ensure_one()
        field = model._fields[self.date_field]
        if field.type == 'date':
            return [(self.date_field, '>=', date_from), (self.date_field, '<=', date_to)]
        # The zone is the scorecard's, so any caller gets the same figure.
        tz = ZoneInfo(tz_name or 'UTC')
        start = datetime.combine(date_from, time.min, tzinfo=tz).astimezone(timezone.utc)
        end = datetime.combine(date_to, time.max, tzinfo=tz).astimezone(timezone.utc)
        return [(self.date_field, '>=', start.replace(tzinfo=None)),
                (self.date_field, '<=', end.replace(tzinfo=None))]

    def _build_domain(self, date_from, date_to, company=None, extra_domain=None, tz_name=None):
        self.ensure_one()
        model = self._model_or_raise()
        parts = [self._domain_or_raise(),
                 self._period_bounds(model, date_from, date_to, tz_name=tz_name)]
        if self.company_field and company:
            parts.append(['|', (self.company_field, '=', False),
                          (self.company_field, '=', company.id)])
        if extra_domain:
            parts.append(extra_domain)
        return Domain.AND(parts)

    def _fetch_value(self, date_from, date_to, company=None, extra_domain=None, tz_name=None):
        """Return ``(value, record_count)`` for the window.
        Read as superuser so the figure is the same for everyone, in the scorecard's company for its currency."""
        self.ensure_one()
        model = self._model_or_raise().sudo().with_company(company)
        if self.include_archived:
            model = model.with_context(active_test=False)
        domain = self._build_domain(date_from, date_to, company=company,
                                    extra_domain=extra_domain, tz_name=tz_name)
        count = model.search_count(domain)
        if self.aggregate == 'count':
            value = float(count)
        elif not count:
            # Nothing matched. Deliberately not zero - see _apply_automated_value.
            value = None
        elif self.aggregate == 'ratio':
            hits = model.search_count(Domain.AND([domain, self._domain_or_raise('ratio_domain')]))
            value = hits / count * 100.0
        else:
            rows = model._read_group(domain, [], ['%s:%s' % (self.value_field, self.aggregate)])
            value = rows[0][0] if rows else None
            value = float(value) if value is not None else None
        if value is not None:
            value *= self.multiply_by or 1.0
        return value, count

    def action_test(self):
        """Run the source over the last 30 days and report the record count; zero matches means a wrong figure."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        date_from = today - relativedelta(days=30)
        try:
            value, count = self._fetch_value(date_from, today, company=self.env.company)
        except (UserError, ValidationError):
            raise
        except Exception as error:  # noqa: BLE001 - surfaced to the user as text
            raise UserError(_("The source failed: %s", error)) from error
        if value is None:
            note = _("No records matched in the last 30 days - check the filter.")
            kind = 'warning'
        else:
            note = _("%(count)s record(s), result %(value)s %(uom)s (last 30 days).",
                     count=count, value=round(value, 2), uom=self.uom_hint or '')
            kind = 'success'
        self.last_test_note = note
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': self.name, 'message': note, 'type': kind, 'sticky': False},
        }

    def action_open_kpis(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("KPIs"),
            'res_model': 'bsc.kpi',
            'view_mode': 'list,form',
            'domain': [('source_id', '=', self.id)],
        }
