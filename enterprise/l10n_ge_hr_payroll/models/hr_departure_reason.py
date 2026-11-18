# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class HrDepartureReason(models.Model):
    _inherit = 'hr.departure.reason'

    l10n_ge_severance = fields.Boolean(string="Severance Pay",
        help="The termination entitles the employee to a severance pay (Labour Code, art. 48(1) and (2)).")
