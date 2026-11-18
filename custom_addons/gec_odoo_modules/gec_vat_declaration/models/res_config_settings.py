from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    gec_vat_fixed_asset_account_ids = fields.Many2many(related='company_id.gec_vat_fixed_asset_account_ids', readonly=False)
