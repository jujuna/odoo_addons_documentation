# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import models
from odoo.addons.account.models.chart_template import template


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    @template('la', 'account.return.type')
    def _get_la_account_return_type(self):
        return {
            'l10n_la_reports.la_tax_return_type': {
                'tax_payable_account_id': 'l10n_la_account_433',
                'tax_receivable_account_id': 'l10n_la_account_1671',
                'advance_tax_payment_account_id': 'l10n_la_account_1672',
            },
        }
