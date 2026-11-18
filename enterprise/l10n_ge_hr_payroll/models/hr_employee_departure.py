# Part of Odoo. See LICENSE file for full copyright and licensing details.

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

# Notice giving the right to the severance of 1 month, 2 months below (Labour Code, art. 48(1) and (2))
L10N_GE_NOTICE_DAYS = 30


class HrEmployeeDeparture(models.Model):
    _inherit = 'hr.employee.departure'

    l10n_ge_notice_period = fields.Integer(string="Notice Period", default=L10N_GE_NOTICE_DAYS,
        help="Days of notice the employee serves after the dismissal date. With less than 30 days, the severance is "
             "of 2 months of salary instead of 1 (Labour Code, art. 48(1) and (2)).")
    l10n_ge_short_notice = fields.Boolean(string="Short Notice", compute='_compute_l10n_ge_short_notice')

    _check_l10n_ge_notice_period = models.Constraint(
        'CHECK(l10n_ge_notice_period >= 0)',
        "The notice period cannot be negative.",
    )

    def _get_departure_reason_domain(self):
        if self.env.company.country_id.code == 'GE':
            return [('country_id.code', '=', 'GE')]
        return super()._get_departure_reason_domain()

    @api.depends('l10n_ge_notice_period')
    def _compute_l10n_ge_short_notice(self):
        for departure in self:
            departure.l10n_ge_short_notice = departure.l10n_ge_notice_period < L10N_GE_NOTICE_DAYS

    @api.depends('dismissal_date', 'l10n_ge_notice_period', 'country_code')
    def _compute_departure_date(self):
        ge_departures = self.filtered(lambda departure: departure.country_code == 'GE')
        super(HrEmployeeDeparture, self - ge_departures)._compute_departure_date()
        for departure in ge_departures:
            departure.departure_date = departure.dismissal_date and \
                departure.dismissal_date + relativedelta(days=departure.l10n_ge_notice_period)
