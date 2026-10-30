from odoo import models

# A gift card / eWallet redemption is not a `pos.payment`: the FDM gets it as a
# financial, mirrored here in the payments blocks of the turnover and user reports.
# See `generateFinancialsInput` in static/src/common/blackbox/utils/input_generator.js.
L10N_BE_VOUCHER_PAYMENTS = {
    'gift_card': {'name': "Gift Card", 'type': 'VOUCHER_STORE'},
    'ewallet': {'name': "Ewallet", 'type': 'VOUCHER_OTHER'},
}


class PosSession(models.Model):
    _inherit = "pos.session"

    def _l10n_be_voucher_payment_vals(self, program_type, amount):
        """ Build the payment entry reporting ``amount`` redeemed on a voucher program. """
        voucher = L10N_BE_VOUCHER_PAYMENTS[program_type]
        return {
            "id": program_type,
            "name": voucher['name'],
            "type": voucher['type'],
            "amount": {
                "type": "PAYMENT",
                "totalAmount": amount,
                "normalAmount": amount,
                "negativeCorrections": 0,
                "positiveCorrections": 0,
                "correctionsCount": 0,
            },
        }

    def _get_l10n_be_payments(self, data_payments, orders):
        # The redemption is not a transaction line, so the vats, departments and N
        # transactions blocks are all gross of it. Without its financial here the
        # payments block would be the only one net of it, and the report would no
        # longer add up.
        payments = super()._get_l10n_be_payments(data_payments, orders)
        for program_type, amount in orders.lines._l10n_be_voucher_amounts().items():
            amount = self.currency_id.round(amount)
            if amount:
                payments.append(self._l10n_be_voucher_payment_vals(program_type, amount))
        return payments

    def _l10n_be_add_user_voucher_payment(self, user_data, program_type, amount):
        """ Add ``amount`` to the voucher payment of a cashier, and to their turnover. """
        vals = self._l10n_be_voucher_payment_vals(program_type, amount)
        for payment in user_data.get("payments", []):
            if payment["id"] == vals["id"]:
                payment["amount"]["normalAmount"] = self.currency_id.round(
                    payment["amount"]["normalAmount"] + amount
                )
                payment["amount"]["totalAmount"] = self.currency_id.round(
                    payment["amount"]["totalAmount"] + amount
                )
                break
        else:
            user_data.setdefault("payments", []).append(vals)
        # `users[].totalAmount` is the sum of the transaction totals of the user's N
        # events, hence gross of the redemption, and must keep matching the sum of
        # their payments. The base total is built from `order.amount_total`, which is
        # already net of it.
        user_data["totalAmount"] = self.currency_id.round(user_data["totalAmount"] + amount)

    def _get_l10n_be_users_data(self, orders):
        users = super()._get_l10n_be_users_data(orders)
        users_by_employee_id = {
            user_data.get("employeeId"): user_data
            for user_data in users
            if user_data.get("employeeId")
        }

        for order in orders:
            # The key must be derived the same way the base module built `employeeId`,
            # otherwise a cashier whose INSZ only lives on their employee record would
            # silently lose their voucher payments.
            employee_id = self._l10n_be_get_cashier_insz(order._get_cashier())
            user_data = users_by_employee_id.get(employee_id)
            if not user_data:
                continue
            for program_type, amount in order.lines._l10n_be_voucher_amounts().items():
                amount = self.currency_id.round(amount)
                if amount:
                    self._l10n_be_add_user_voucher_payment(user_data, program_type, amount)

        return users
