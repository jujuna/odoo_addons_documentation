from odoo import fields, models


class HotelRmsPrice(models.Model):
    _inherit = 'hotel.rms.price'

    not_for_sale = fields.Boolean(readonly=True, copy=False,
        help="The pricelist price of this night is 0: the night is not sold, so it has no recommendation and its price is not applied.")

    def _calendar_cell(self):
        cell = super()._calendar_cell()
        cell['not_for_sale'] = self.not_for_sale
        return cell

    def get_panel_data(self):
        data = super().get_panel_data()
        if self.not_for_sale:
            data['actions'].update(accept=False, use_my_price=False, reject=False)
        return data

    def _engine_skip_write(self, today):
        return self.not_for_sale or super()._engine_skip_write(today)

    def action_use_my_price(self):
        return super(HotelRmsPrice, self.filtered(lambda p: not p.not_for_sale)).action_use_my_price()
