from unittest.mock import patch

import requests

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.glovo_base.utils.glovo_client import GlovoBadRequestError, GlovoClient
from odoo.addons.pos_platform_order_glovo.tests.common import TestGlovoCommon

LOGGER = 'odoo.addons.pos_platform_order_glovo.models.pos_order'
BOOKED = {'success': True, 'message': "The customer picked up the order; the sale is booked."}
REFUSED_MSG = "Glovo couldn't mark this order picked up. Check the order in the Glovo Partner Webapp or ask a POS manager."
NOT_PICKUP_MSG = "Only an order the customer collects at the store can be marked picked up by the customer."


@tagged('post_install', '-at_install')
class TestGlovoCustomerPickup(TestGlovoCommon):

    def setUp(self):
        super().setUp()
        self.main_pos_config.with_user(self.pos_user).open_ui()

    def _pickup_order(self, order_id, **extra):
        self._webhook('dispatched', order_id, is_picked_up_by_customer=True, **extra)
        return self._glovo_order(order_id)

    def _customer_picked_up(self, order, side_effect=None):
        with patch.object(GlovoClient, 'customer_picked_up', side_effect=side_effect) as picked_up:
            result = order.with_user(self.pos_user).platform_order_status_update_from_ui('customer_picked_up')
        return result, picked_up

    def test_glovo_accepts_and_the_sale_is_booked(self):
        order = self._pickup_order('8101', payment_method='DELAYED')
        result, picked_up = self._customer_picked_up(order)
        self.assertEqual(result, BOOKED)
        picked_up.assert_called_once_with('8101', 'LOCK-STORE')
        self.assertEqual((order.state, order.platform_order_status, len(order.payment_ids)), ('paid', 'delivered', 1))
        self.assertEqual(order.payment_ids.payment_method_id, self.store.payment_method_id)

    def test_cash_order_is_booked_on_the_cash_method(self):
        cash = self.main_pos_config._get_cash_payment_method()
        if not cash:
            journal = self.env['account.journal'].create({'name': 'Glovo Cash', 'type': 'cash', 'code': 'GLVC', 'company_id': self.env.company.id})
            cash = self.env['pos.payment.method'].create({'name': 'Glovo Cash', 'type': 'cash', 'journal_id': journal.id})
            self.main_pos_config.payment_method_ids = [Command.link(cash.id)]
        order = self._pickup_order('8102', payment_method='CASH')
        result, picked_up = self._customer_picked_up(order)
        self.assertEqual(result, BOOKED)
        picked_up.assert_called_once_with('8102', 'LOCK-STORE')
        self.assertEqual((order.state, order.platform_order_status, len(order.payment_ids)), ('paid', 'delivered', 1))
        self.assertEqual(order.payment_ids.payment_method_id, cash)

    def test_refused_by_glovo_books_nothing(self):
        order = self._pickup_order('8103')
        response = requests.Response()
        response.status_code = 400
        response._content = b'{"error": "simulated"}'
        with self.assertLogs(LOGGER, 'ERROR') as logs:
            result, picked_up = self._customer_picked_up(order, side_effect=GlovoBadRequestError(response))
        self.assertEqual(result, {'success': False, 'message': REFUSED_MSG})
        self.assertIn("failed to mark order 8103 picked up by the customer", logs.output[0])
        picked_up.assert_called_once_with('8103', 'LOCK-STORE')
        order.invalidate_recordset()
        self.assertEqual((order.state, order.platform_order_status, len(order.payment_ids)), ('draft', 'accepted', 0))
        self.assertEqual(self._customer_picked_up(order)[0], BOOKED)

    def test_courier_order_is_refused_without_calling_glovo(self):
        self._webhook('dispatched', '8104')
        order = self._glovo_order('8104')
        result, picked_up = self._customer_picked_up(order)
        self.assertEqual(result, {'success': False, 'message': NOT_PICKUP_MSG})
        picked_up.assert_not_called()
        self.assertEqual((order.state, len(order.payment_ids)), ('draft', 0))

    def test_paid_order_is_refused_without_calling_glovo(self):
        order = self._pickup_order('8105')
        self.assertEqual(self._customer_picked_up(order)[0], BOOKED)
        result, picked_up = self._customer_picked_up(order)
        self.assertEqual(result, {'success': False, 'message': NOT_PICKUP_MSG})
        picked_up.assert_not_called()
        self.assertEqual(len(order.payment_ids), 1)

    def test_cashier_marks_pickup_order_in_pos(self):
        pickup = self._pickup_order('8201')
        self._webhook('dispatched', '8202')
        courier = self._glovo_order('8202')
        with patch.object(GlovoClient, 'customer_picked_up', return_value=None) as picked_up:
            self.start_pos_tour('glovo_customer_pickup_tour', login='pos_user')
        picked_up.assert_called_once_with('8201', 'LOCK-STORE')
        self.env.invalidate_all()
        self.assertEqual((pickup.state, pickup.platform_order_status, len(pickup.payment_ids)), ('paid', 'delivered', 1))
        self.assertEqual((courier.state, len(courier.payment_ids)), ('draft', 0))
