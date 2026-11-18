# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import models


class AccountReturn(models.Model):
    _inherit = 'account.return'

    def _get_carryover_accounts_to_balance(self, key):
        # EXTENDS account_reports
        # The VAT credit carried forward (line 18) stays on the receivable account and is deducted on the next return
        # (line 14): the next closing uses it up, so the amount booked as payable matches line 19.
        accounts = super()._get_carryover_accounts_to_balance(key)
        if self.type_external_id == 'l10n_la_reports.la_tax_return_type':
            accounts.append((key[1], self.env._("Balance VAT credit carried forward (receivable)")))
        return accounts
