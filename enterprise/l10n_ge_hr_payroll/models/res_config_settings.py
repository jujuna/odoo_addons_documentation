# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    l10n_ge_tax_regime = fields.Selection(related='company_id.l10n_ge_tax_regime', readonly=False)
    l10n_ge_annual_leave_type_id = fields.Many2one(related='company_id.l10n_ge_annual_leave_type_id', readonly=False)
