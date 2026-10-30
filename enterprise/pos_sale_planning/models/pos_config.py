# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    @api.model
    def _create_journal_and_payment_methods(self, cash_ref=None, cash_journal_vals=None):
        journal, payment_method_ids = super()._create_journal_and_payment_methods(cash_ref=cash_ref, cash_journal_vals=cash_journal_vals)
        resource_pm = self.env['pos.payment.method']._get_or_create_resource_payment_method(self.env.company.id)
        payment_method_ids.append(resource_pm.id)
        return journal, payment_method_ids
