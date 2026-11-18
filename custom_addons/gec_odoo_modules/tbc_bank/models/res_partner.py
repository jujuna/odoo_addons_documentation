from odoo import models

from .account_payment_method import TBC_METHOD_CODE


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def write(self, vals):
        """A Treasury Code added, changed or removed on a contact reaches its TBC transfers still Pending."""
        res = super().write(vals)
        if 'gec_treasury_code' in vals:
            self._tbc_refresh_pending_treasury()
        return res

    def _tbc_refresh_pending_treasury(self):
        """Recompute Treasury Code and transfer type of this contact's Pending TBC transfers. Only Pending: an
        approved or sent transfer keeps what was approved or sent."""
        # sudo: the contact's editor may not read payments; only the derived fields are recomputed.
        payments = self.env['account.payment'].sudo().search([
            ('partner_id.commercial_partner_id', 'in', self.commercial_partner_id.ids),
            ('payment_method_id.code', '=', TBC_METHOD_CODE),
            ('gec_bank_state', '=', 'pending'),
        ])
        if payments:
            for name in ('tbc_treasury_code', 'tbc_transfer_type'):
                self.env.add_to_compute(payments._fields[name], payments)
            payments.flush_recordset(['tbc_treasury_code', 'tbc_transfer_type'])
