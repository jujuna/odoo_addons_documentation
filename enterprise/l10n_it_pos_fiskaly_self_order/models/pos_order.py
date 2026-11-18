from odoo import api, models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def _load_pos_self_data_fields(self, config):
        return [*super()._load_pos_self_data_fields(config), 'l10n_it_fiskaly_compliance_number']
