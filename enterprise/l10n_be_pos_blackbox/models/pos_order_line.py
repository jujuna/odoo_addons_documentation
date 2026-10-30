from collections import defaultdict

from odoo import api, fields, models
from odoo.tools import float_is_zero


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    l10n_be_vats = fields.Json(string="l10n_be VATs JSON")

    @api.model
    def _load_pos_data_fields(self, config):
        params = super()._load_pos_data_fields(config)
        params += ['l10n_be_vats']
        return params

    def _l10n_be_is_sendable_to_blackbox(self):
        """ Whether this line was sent to the FDM as a product. (see `linesSendableToBlackbox` for js equivalent) """
        self.ensure_one()
        config = self.order_id.config_id
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        if float_is_zero(self.qty, precision_digits=precision):
            return False
        if config.discount_product_id and self.product_id == config.discount_product_id:
            return False
        if config.tip_product_id and self.product_id == config.tip_product_id:
            return bool(self.order_id.is_refund)
        return True

    def _l10n_be_lines_sendable_to_blackbox(self):
        return self.filtered(lambda line: line._l10n_be_is_sendable_to_blackbox())

    def _l10n_be_neg_quantity_lines(self):
        return self._l10n_be_lines_sendable_to_blackbox().filtered(lambda line: line.qty < 0)

    def _l10n_be_fdm_vat_amounts(self):
        """ Return {vat_label: amount} for these lines as sent to the FDM.
        Calculates VAT amounts by summing price and price changes from l10n_be_vats.
        """
        amounts = defaultdict(float)
        for line in self:
            for vat in line.l10n_be_vats or []:
                amounts[vat.get('label')] += (vat.get('price') or 0.0) + sum(
                    change.get('amount') or 0.0
                    for change in vat.get('priceChanges') or []
                )
        return amounts

    def _l10n_be_fdm_total(self):
        """ Total amount for these lines sent to the FDM (lineTotal), including VAT. """
        return sum(self._l10n_be_fdm_vat_amounts().values())
