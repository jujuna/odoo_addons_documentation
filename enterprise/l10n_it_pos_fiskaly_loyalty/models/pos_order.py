from odoo import models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _l10n_it_fiskaly_voucher_products(self):
        self.ensure_one()
        programs = self.config_id._get_program_ids().filtered(
            lambda program: program.program_type in ('gift_card', 'ewallet'))
        return programs.trigger_product_ids

    def _l10n_it_fiskaly_total(self):
        sign = self._l10n_it_fiskaly_sign()
        return super()._l10n_it_fiskaly_total() + self.currency_id.round(sum(
            -sign * line.price_subtotal_incl
            for line in self.lines
            if line._l10n_it_fiskaly_is_voucher_redemption()
        ))

    def _l10n_it_fiskaly_lines(self):
        return super()._l10n_it_fiskaly_lines().filtered(
            lambda line: not line._l10n_it_fiskaly_is_voucher_redemption())

    def _l10n_it_fiskaly_sold_lines(self, lines):
        return super()._l10n_it_fiskaly_sold_lines(
            lines.filtered(lambda line: not line._l10n_it_fiskaly_is_product_reward()))

    def _l10n_it_fiskaly_entry_base_lines(self):
        sign = self._l10n_it_fiskaly_sign()
        rewards = self._l10n_it_fiskaly_lines().filtered(
            lambda line: line.qty and line._l10n_it_fiskaly_is_product_reward())
        gift_lines = self._l10n_it_fiskaly_tax_details([
            line._l10n_it_fiskaly_base_line(sign * line.qty, price_unit=line._l10n_it_fiskaly_list_price_unit())
            for line in rewards
        ])
        return super()._l10n_it_fiskaly_entry_base_lines() + [(base_line, True) for base_line in gift_lines]
