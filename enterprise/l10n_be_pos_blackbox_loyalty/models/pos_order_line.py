from collections import defaultdict

from odoo import models


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    def _l10n_be_is_sendable_to_blackbox(self):
        # Mirror of `PosOrder.linesSendableToBlackbox` in static/src/common/models/pos_order.js:
        # a free product reward line carries the rewarded product at a 0 price and is real
        # merchandise, so it is reported to the FDM. The other reward lines are not goods:
        # a discount becomes a price change on the lines it discounts and a gift card /
        # eWallet redemption becomes a financial.
        if self.is_reward_line and self.reward_id.reward_type != 'product':
            return False
        return super()._l10n_be_is_sendable_to_blackbox()

    def _l10n_be_voucher_program_type(self):
        """ Return 'gift_card' / 'ewallet' if this line spends such a card, else False.

        Mirror of `getRewardProgramType` in
        static/src/common/blackbox/utils/input_generator.js: a payment reward is linked
        to the card it spends from, and falls back on its reward's program for a card
        that isn't loaded (a code redeemed offline). Only the redemption is a voucher;
        the line *selling* the card is a plain sale.
        """
        self.ensure_one()
        if not self.is_reward_line or self.price_unit >= 0:
            return False
        program_type = (self.card_id.program_id or self.reward_id.program_id).program_type
        return program_type if program_type in ('gift_card', 'ewallet') else False

    def _l10n_be_voucher_amounts(self):
        """ Return {program_type: amount} redeemed by these lines, as the FDM reports it.

        A redemption lowers the order total but reaches the FDM as a VOUCHER financial
        instead of a transaction line, and `getTransactionTotal` adds it back so that
        `transactionTotal == sum(lineTotal)`. The amount to report is therefore the
        opposite of the line total -- signed, never `abs()`: a refund line is stored
        with a positive subtotal, and must subtract.
        """
        amounts = defaultdict(float)
        for line in self:
            if program_type := line._l10n_be_voucher_program_type():
                amounts[program_type] -= line.price_subtotal_incl
        return amounts
