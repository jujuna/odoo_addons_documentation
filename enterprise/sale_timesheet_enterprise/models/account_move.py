# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models
from odoo.fields import Domain


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.model
    def _analytic_line_domain_get_invoiced_lines(self, so_lines):
        return Domain.AND([
            super()._analytic_line_domain_get_invoiced_lines(so_lines),
            self.env['account.analytic.line']._get_invoiced_timesheet_domain(),
        ])
