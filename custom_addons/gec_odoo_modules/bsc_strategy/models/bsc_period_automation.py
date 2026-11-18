# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BscPeriod(models.Model):
    _inherit = 'bsc.period'

    automated_count = fields.Integer(compute='_compute_automated_counts')
    attention_count = fields.Integer(
        compute='_compute_automated_counts',
        help="Automated rows that were held back, found nothing, or failed.")

    @api.depends('measurement_ids.is_automated', 'measurement_ids.auto_needs_attention')
    def _compute_automated_counts(self):
        for period in self:
            automated = period.measurement_ids.filtered(
                lambda m: m.kpi_id.data_source == 'odoo')
            period.automated_count = len(automated)
            period.attention_count = len(automated.filtered('auto_needs_attention'))

    def action_prepare_measurements(self):
        """Core only creates rows for manual KPIs; computed ones need them too."""
        result = super().action_prepare_measurements()
        for period in self:
            if period.state == 'closed':
                continue
            kpis = period.scorecard_id.objective_ids.kpi_ids.filtered(
                lambda k: k.active and k.data_source == 'odoo')
            if kpis:
                period._create_missing_measurements(kpis)
        return result

    def _create_missing_measurements(self, kpis):
        """Let each KPI propose its own target instead of always carrying one over."""
        Measurement = self.env['bsc.measurement']
        before = Measurement.search([('period_id', 'in', self.ids)]).ids
        result = super()._create_missing_measurements(kpis)
        created = Measurement.search([
            ('period_id', 'in', self.ids), ('id', 'not in', before)])
        created._apply_target_rule()
        return result

    def action_refresh_automated(self):
        """Pull every computed figure for this period now."""
        for period in self:
            if period.state == 'closed':
                raise UserError(_("Period '%s' is closed.", period.name))
            period.action_prepare_measurements()
            updated = period.measurement_ids._refresh_automated()
            period.scorecard_id.message_post(body=_(
                "Automated figures refreshed for %(period)s: %(updated)s updated, "
                "%(attention)s need attention.",
                period=period.name, updated=len(updated),
                attention=period.attention_count))
        return True

    def action_close(self, force=False):
        """Require the red-figure explanation of automated rows (exempt on write) when the period closes.
        Forcing the close still overrides it, as it does for missing figures."""
        if not force and not self.env.context.get('bsc_force_close'):
            for period in self:
                if period.state == 'closed':
                    continue
                unexplained = period.measurement_ids._filter_counted().filtered(
                    lambda m: m.is_automated and m.status == 'red' and not m.comment)
                if unexplained:
                    raise UserError(_(
                        "These automated figures came out off track and carry no "
                        "explanation:\n%(names)s\n\nWrite a variance comment on each, "
                        "or use Close Anyway.",
                        names="\n".join(unexplained.mapped('kpi_id.name'))))
        result = super().action_close(force=force)
        self._open_review()
        return result

    def _open_review(self):
        """Create a prepared draft review for a closed period; a period not yet started gets none."""
        Review = self.env['bsc.review']
        today = fields.Date.context_today(self)
        for period in self:
            scorecard = period.scorecard_id
            if (period.state != 'closed' or not scorecard.auto_create_review
                    or period.date_from > today):
                continue
            review = Review.search([('scorecard_id', '=', scorecard.id),
                                    ('period_id', '=', period.id)], limit=1)
            if review and review.state == 'done':
                continue
            if not review:
                review = Review.create({
                    'scorecard_id': scorecard.id,
                    'period_id': period.id,
                    'review_date': fields.Date.context_today(period),
                })
            # A review opened before the close holds earlier figures; freeze them again.
            review.action_prepare()
            scorecard.activity_schedule(
                act_type_xmlid='mail.mail_activity_data_todo',
                user_id=scorecard.responsible_id.id,
                summary=_("Hold the strategy review for %s", period.name),
                note=_("The figures are closed and the review is prepared. "
                       "Record the findings and, above all, the decisions."),
            )
        return True

    def action_open_attention(self):
        """The rows a person has to look at before the review."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Figures Needing Attention - %s", self.name),
            'res_model': 'bsc.measurement',
            'view_mode': 'list,form',
            'domain': [('period_id', '=', self.id), ('auto_needs_attention', '=', True)],
        }
