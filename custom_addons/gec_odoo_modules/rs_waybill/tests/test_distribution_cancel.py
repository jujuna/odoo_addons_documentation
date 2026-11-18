"""Cancelling a distribution waybill cancels all its sub-waybills, finished or not."""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestDistributionCancel(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.parent = self.make_waybill(waybill_type='4', state='completed', waybill_status='2',
                                        rs_internal_id=991000, buyer_id=False)
        self.done_order, self.done_sub = self._sub(991001, ship=True)
        self.open_order, self.open_sub = self._sub(991002, ship=False)
        self.service = type(self.env['rs.waybill.soap.service'])
        patcher = patch.object(self.env.cr, 'commit')
        patcher.start()
        self.addCleanup(patcher.stop)

    def _sub(self, rs_id, ship):
        order = self.env['sale.order'].create({
            'partner_id': self.buyer.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 5})]})
        order.with_context(skip_rs_auto_create=True).action_confirm()
        picking = order.picking_ids
        if ship:
            picking.move_ids.quantity = 5
            picking.move_ids.picked = True
            picking.with_context(skip_rs_auto_create=True)._action_done()
        sub = self.make_waybill(waybill_type='4', parent_waybill_id=self.parent.id,
                                state='completed' if ship else 'active',
                                waybill_status='2' if ship else '1', rs_internal_id=rs_id,
                                sales_order_id=order.id, picking_id=picking.id)
        picking.waybill_id = sub
        return order, sub

    def test_one_call_cancels_the_distribution_and_every_sub(self):
        with patch.object(self.service, 'ref_waybill_vd', return_value=1) as cancel_main, \
                patch.object(self.service, 'refuse_waybill') as cancel_one:
            self.parent.action_refuse_waybill()

        cancel_main.assert_called_once()
        cancel_one.assert_not_called()
        self.assertEqual((self.parent | self.done_sub | self.open_sub).mapped('state'),
                         ['cancelled'] * 3)
        self.assertEqual(self.open_sub.picking_id.state, 'cancel', "open delivery follows")
        self.assertEqual(self.done_sub.picking_id.state, 'done', "delivered goods stay delivered")
        self.assertTrue(self.done_sub.activity_ids)

    def test_rs_refusal_changes_nothing(self):
        with patch.object(self.service, 'ref_waybill_vd', side_effect=UserError("RS.GE: no")), \
                patch.object(self.service, 'refuse_waybill', side_effect=UserError("RS.GE: no")), \
                self.assertRaises(UserError):
            self.parent.action_refuse_waybill()

        self.assertEqual(self.parent.state, 'completed')
        self.assertEqual(self.open_sub.state, 'active')

    def test_falls_back_to_cancelling_active_subs_first(self):
        calls = []

        def cancel_main(rs_id, comment=''):
            calls.append('main')
            if calls.count('main') == 1:
                raise UserError("RS.GE: the distribution still has live sub-waybills")
            return 1
        with patch.object(self.service, 'ref_waybill_vd', side_effect=cancel_main), \
                patch.object(self.service, 'refuse_waybill',
                             side_effect=lambda rs_id: calls.append(rs_id) or 1):
            self.parent.action_refuse_waybill()

        self.assertEqual(calls, ['main', 991002, 'main'], "only the active sub, then the main again")
        self.assertEqual(self.done_sub.state, 'cancelled')

    def test_a_normal_completed_waybill_is_still_not_cancelled(self):
        waybill = self.make_waybill(state='completed', waybill_status='2', rs_internal_id=991003)
        with self.assertRaises(UserError):
            waybill.action_refuse_waybill()
