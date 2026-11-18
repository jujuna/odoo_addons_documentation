from odoo import api, fields, models


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    l10n_ma_reports_payment_method = fields.Selection(
        [
            ('1', 'Cash'),
            ('2', 'Check'),
            ('3', 'Direct Debit'),
            ('4', 'Bank Transfer'),
            ('5', 'Bill of Exchange'),
            ('6', 'Compensation'),
            ('7', 'Others'),
        ],
        string='Payment Channel',
        compute='_compute_l10n_ma_reports_payment_method', store=True, readonly=False, precompute=True,
        help='Payment method for Moroccan EDI. If left empty it will default to "Other" on the EDI declaration.'
    )

    @api.depends('line_ids')
    def _compute_l10n_ma_reports_payment_method(self):
        for wizard in self:
            methods = set(wizard.line_ids.move_id.mapped('l10n_ma_reports_payment_method')) - {False}
            wizard.l10n_ma_reports_payment_method = methods.pop() if len(methods) == 1 else '7'

    def _create_payment_vals_from_wizard(self, batch_result):
        payment_vals = super()._create_payment_vals_from_wizard(batch_result)
        payment_vals['l10n_ma_reports_payment_method'] = self.l10n_ma_reports_payment_method
        return payment_vals
