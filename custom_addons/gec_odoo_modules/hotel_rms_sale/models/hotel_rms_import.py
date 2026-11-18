from odoo import models
from odoo.exceptions import UserError


class HotelRmsImport(models.Model):
    _inherit = 'hotel.rms.import'

    def action_import(self):
        if self.kind == 'rates' and self.property_id.pricelist_id:
            raise UserError(self.env._("The current prices of this hotel come from its pricelist. Import reservations only."))
        return super().action_import()
