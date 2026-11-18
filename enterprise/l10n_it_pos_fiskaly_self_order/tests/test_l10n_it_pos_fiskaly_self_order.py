from odoo.addons.l10n_it_pos_fiskaly.tests.common import TestL10nItPosFiskalyCommon
from odoo.tests import tagged


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nItPosFiskalySelfOrder(TestL10nItPosFiskalyCommon):

    def test_self_order_receipt_carries_the_compliance_number(self):
        fields = self.env['pos.order']._load_pos_self_data_fields(self.config)
        self.assertIn('l10n_it_fiskaly_compliance_number', fields)

    def test_kiosk_terminal_payment_signs_the_order(self):
        calls = self._l10n_it_fake_fiskaly()
        order = self._order([self._line(self.product_22, 1, 122.0)], payment=0.0)
        order.add_payment({
            'amount': 122.0,
            'payment_method_id': self.bank_pm1.id,
            'pos_order_id': order.id,
        })
        self.patch(self.env.registry['pos.payment.method'], 'payment_provider', 'terminal')
        self.patch(self.env.registry['pos.order'], '_send_payment_result', lambda order, result: None)
        self.assertTrue(self.bank_pm1._payment_request_from_kiosk(order))
        self._l10n_it_assert_signed(order, calls)
