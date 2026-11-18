# -*- coding: utf-8 -*-
from ast import literal_eval

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain


class BscKpi(models.Model):
    """Lets a KPI draw its figure from a vetted source instead of a keyboard."""
    _inherit = 'bsc.kpi'

    source_id = fields.Many2one(
        'bsc.kpi.source', string='Source Query', ondelete='restrict',
        help="A query defined and tested by an administrator.")
    source_extra_domain = fields.Char(
        string='Additional Filter', default='[]',
        help="Optional narrowing on top of the source, e.g. one team or one "
             "product category. Read as a literal list, never as code.")
    source_uom_hint = fields.Char(
        related='source_id.uom_hint', readonly=True, string='Source Unit')
    source_scale = fields.Float(
        string='Scale', default=1.0, digits=(16, 6),
        help="Applied to what the source returns, so a KPI kept in thousands can use "
             "a source that counts in units: 0.001 for thousands, 0.000001 for millions.")
    source_model_name = fields.Char(
        related='source_id.model_name', readonly=True, string='Source Model')
    source_description = fields.Text(
        related='source_id.description', readonly=True, string='What the Source Counts')
    auto_deviation_limit = fields.Float(
        string='Deviation Alert (%)', default=50.0,
        help="A new figure that differs from the previous period by more than this "
             "is held back for a human to confirm, instead of being published. "
             "Zero disables the check - do that only for a measure you expect to "
             "jump around.")
    auto_last_run = fields.Datetime(string='Last Synchronised', readonly=True, copy=False)
    auto_last_error = fields.Char(readonly=True, copy=False)

    @api.constrains('data_source', 'source_id')
    def _check_source_is_set(self):
        for kpi in self:
            if kpi.data_source == 'odoo' and not kpi.source_id:
                raise ValidationError(_(
                    "KPI '%s' is set to be computed but has no data source.", kpi.name))

    @api.constrains('source_extra_domain')
    def _check_extra_domain(self):
        for kpi in self:
            kpi._extra_domain()

    def _extra_domain(self):
        self.ensure_one()
        if not self.source_extra_domain:
            return []
        try:
            parsed = literal_eval(self.source_extra_domain)
        except (ValueError, SyntaxError) as error:
            raise ValidationError(_(
                "The additional filter of '%(name)s' is not a valid literal list: "
                "%(error)s", name=self.name, error=error)) from error
        if not isinstance(parsed, list):
            raise ValidationError(_("The additional filter must be a list."))
        try:
            Domain(parsed)
        except (ValueError, TypeError) as error:
            raise ValidationError(_(
                "The additional filter of '%(name)s' is not a valid domain: %(error)s",
                name=self.name, error=error)) from error
        return parsed

    def write(self, vals):
        """A changed source or filter voids confirmations of a held figure in open periods."""
        result = super().write(vals)
        if {'source_id', 'source_extra_domain', 'source_scale', 'data_source'} & set(vals):
            self._reset_deviation_confirmed()
        return result

    def _reset_deviation_confirmed(self):
        """Clear 'Jump Confirmed' on the open-period rows of these KPIs, as superuser (automation-only field)."""
        self.env['bsc.measurement'].sudo().search([
            ('kpi_id', 'in', self.ids),
            ('period_id.state', '=', 'open'),
            ('auto_deviation_confirmed', '=', True),
        ]).write({'auto_deviation_confirmed': False})

    @api.onchange('data_source')
    def _onchange_data_source(self):
        """A computed KPI still needs an owner - the person who defends the number."""
        if self.data_source != 'odoo':
            self.source_id = False

    @api.onchange('source_id')
    def _onchange_source_id(self):
        if self.source_id and not self.uom_name:
            self.uom_name = self.source_id.uom_hint

    def _fetch_for_period(self, period):
        """Return ``(value, count)`` from the source for one period."""
        self.ensure_one()
        scorecard = period.scorecard_id
        value, count = self.source_id._fetch_value(
            period.date_from, period.date_to,
            company=scorecard.company_id,
            extra_domain=self._extra_domain(),
            tz_name=scorecard.responsible_id.tz or 'UTC')
        if value is not None and self.source_scale and self.source_scale != 1.0:
            value *= self.source_scale
        return value, count

    def action_test_source(self):
        """Show what this KPI would report for the current period, without writing."""
        self.ensure_one()
        if self.data_source != 'odoo' or not self.source_id:
            raise UserError(_("This KPI is not computed from Odoo data."))
        period = self.scorecard_id.current_period_id
        if not period:
            raise UserError(_(
                "There is no period to test against. Activate the scorecard first."))
        value, count = self._fetch_for_period(period)
        if value is None:
            message = _("No records matched for %s. The figure would be left empty.",
                        period.name)
            kind = 'warning'
        else:
            message = _("%(period)s: %(count)s record(s), result %(value)s %(uom)s.",
                        period=period.name, count=count, value=round(value, 2),
                        uom=self.uom_name or '')
            kind = 'success'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': self.name, 'message': message, 'type': kind,
                       'sticky': False},
        }

    def action_open_connect_wizard(self):
        """The guided way to let Odoo fill this KPI."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Connect to Odoo data"),
            'res_model': 'bsc.kpi.connect',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_kpi_id': self.id},
        }

    def action_disconnect_source(self):
        """Back to figures typed in by the owner. Figures already pulled stay."""
        for kpi in self:
            if kpi.data_source != 'odoo':
                continue
            name = kpi.source_id.name
            kpi.write({'data_source': 'manual', 'source_id': False, 'source_scale': 1.0,
                       'source_extra_domain': '[]', 'auto_last_error': False})
            kpi.message_post(body=_(
                "Disconnected from the data source %s. From now on the owner enters "
                "the figure each period; figures already pulled are kept.", name))
        return True

    def _refresh_open_periods(self):
        """Create and fill this KPI's rows in every open period that has started."""
        self.ensure_one()
        scorecard = self.scorecard_id
        if not scorecard or scorecard.state != 'active':
            return self.env['bsc.measurement']
        today = fields.Date.context_today(self)
        periods = scorecard.period_ids.filtered(
            lambda p: p.state == 'open' and p.date_from <= today)
        for period in periods:
            period._create_missing_measurements(self)
        rows = self.env['bsc.measurement'].search([
            ('kpi_id', '=', self.id), ('period_id', 'in', periods.ids)])
        rows._refresh_automated()
        return rows

    def action_refresh_now(self):
        """Pull the figure for the current period straight away."""
        self.ensure_one()
        period = self.scorecard_id.current_period_id
        if not period or period.state != 'open':
            raise UserError(_("There is no open period to write into."))
        measurements = self.env['bsc.measurement'].search([
            ('kpi_id', '=', self.id), ('period_id', '=', period.id)])
        if not measurements:
            period._create_missing_measurements(self)
            measurements = self.env['bsc.measurement'].search([
                ('kpi_id', '=', self.id), ('period_id', '=', period.id)])
        measurements._refresh_automated()
        return True


class BscKpiTargetRule(models.Model):
    """How next period's target is proposed; every value stays editable and 'Leave empty' is allowed."""
    _inherit = 'bsc.kpi'

    target_rule = fields.Selection(
        [('carry', 'Same as last period'),
         ('previous_growth', 'Last period actual, plus a percentage'),
         ('baseline_growth', 'Baseline, plus a percentage'),
         ('empty', 'Leave empty')],
        string='Target Rule', default='carry', required=True,
        help="Applied when the rows for a new period are created.")
    target_growth = fields.Float(
        string='Growth (%)', default=0.0,
        help="Added to the basis chosen above. Use a negative figure for a measure "
             "that is supposed to come down.")

    def _proposed_target(self, previous_measurement, carried_target):
        """Return the target to write on a freshly created row."""
        self.ensure_one()
        factor = 1.0 + (self.target_growth or 0.0) / 100.0
        if self.target_rule == 'empty':
            return 0.0
        if self.target_rule == 'baseline_growth':
            return (self.baseline_value or 0.0) * factor
        if self.target_rule == 'previous_growth':
            if previous_measurement and previous_measurement.actual_value_set:
                return previous_measurement.actual_value * factor
            # No history to grow from; the carried target is the honest fallback.
            return carried_target
        return carried_target
