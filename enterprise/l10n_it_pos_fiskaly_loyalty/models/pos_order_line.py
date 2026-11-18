from odoo import models

from odoo.addons.l10n_it_pos_fiskaly.models.pos_order import EXEMPTION_NOT_SUBJECT


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    def _l10n_it_fiskaly_is_voucher_redemption(self):
        self.ensure_one()
        return self.is_reward_line and self.card_id.program_id.program_type in ('gift_card', 'ewallet')

    def _l10n_it_fiskaly_is_product_reward(self):
        self.ensure_one()
        return self.is_reward_line and self.reward_id.reward_type == 'product'

    def _l10n_it_fiskaly_is_free(self):
        return not self.is_reward_line and super()._l10n_it_fiskaly_is_free()

    def _l10n_it_fiskaly_vat_code(self, tax):
        if not self.is_reward_line and self.product_id in self.order_id._l10n_it_fiskaly_voucher_products():
            return EXEMPTION_NOT_SUBJECT
        return super()._l10n_it_fiskaly_vat_code(tax)

    def _l10n_it_fiskaly_is_global_discount(self):
        if super()._l10n_it_fiskaly_is_global_discount():
            return True
        reward = self.reward_id
        return self.is_reward_line and reward.reward_type == 'discount' and reward.discount_applicability == 'order'
