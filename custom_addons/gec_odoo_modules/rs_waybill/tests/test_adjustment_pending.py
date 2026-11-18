"""An Adjustment RS.GE refused is kept and shown, and can be sent again or discarded."""

import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestAdjustmentPending(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        self.milk = self.env['product.product'].create(
            {'name': 'Milk', 'is_storable': True, 'barcode': 'B-MILK'})
        self.env['stock.quant']._update_available_quantity(self.milk, warehouse.lot_stock_id, 40)
        order = self.env['sale.order'].create({
            'partner_id': self.buyer.id,
            'order_line': [(0, 0, {'product_id': self.milk.id, 'product_uom_qty': 10})],
        })
        order.with_context(skip_rs_auto_create=True).action_confirm()
        self.picking = order.picking_ids
        self.picking.move_ids.picked = True
        self.picking.with_context(skip_rs_auto_create=True)._action_done()
        self.waybill = self.make_waybill(state='completed', waybill_status='2', rs_internal_id=930001,
                                         picking_id=self.picking.id, sales_order_id=order.id)
        self.line = self.add_line(self.waybill, quantity=10, unit_price=5, product_id=self.milk.id,
                                  name='Milk', bar_code='B-MILK', rs_good_id='5001',
                                  stock_move_id=self.picking.move_ids.id)
        service = type(self.env['rs.waybill.soap.service'])
        for name, value in (('get_full_waybill', (None, [])),):
            patcher = patch.object(service, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for patcher in (patch.object(type(self.waybill), '_send_notification_email'),
                        patch.object(self.env.cr, 'commit')):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.service = service

    def _goods(self, qty):
        return [{'ID': '5001', 'BAR_CODE': 'B-MILK', 'W_NAME': 'Milk', 'QUANTITY': str(qty),
                 'PRICE': '5', 'UNIT_TXT': '', 'VAT_TYPE': '0'}]

    def _submit(self, refused=False):
        """Submit the open Adjustment; returns RS.GE's refusal text, or None.
        No assertRaises: it would roll back what the refusal keeps."""
        side = UserError("delivery date is in the past") if refused else None
        with patch.object(self.service, 'save_waybill', side_effect=side, return_value={}):
            try:
                self.waybill.action_submit_edit_to_rs()
            except UserError as error:
                return str(error)
        return None

    def _refused_adjustment_to_8(self):
        self.waybill.action_edit_waybill()
        self.line.quantity = 8
        return self._submit(refused=True)

    def test_refusal_keeps_the_change_and_says_why(self):
        message = self._refused_adjustment_to_8()

        self.assertIn('delivery date is in the past', message or '')
        self.assertIn('delivery date is in the past', self.waybill.rs_adjustment_error)
        self.assertEqual(self.line.quantity, 8, "the user's change is kept")
        self.assertEqual(self.picking.move_ids.quantity, 10, "nothing reached the delivery")

    def test_submit_again_starts_from_what_rs_has(self):
        self._refused_adjustment_to_8()

        self.waybill.action_edit_waybill()
        self.assertEqual(json.loads(self.waybill.edit_snapshot_json)[0]['quantity'], 10)
        self.assertIsNone(self._submit())

        self.assertEqual(self.picking.move_ids.quantity, 8)
        self.assertFalse(self.waybill.rs_adjustment_error)
        self.assertFalse(self.waybill.edit_snapshot_json)

    def test_sync_leaves_a_waiting_adjustment_alone(self):
        self._refused_adjustment_to_8()

        self.waybill._sync_goods_lines(self._goods(10))

        self.assertEqual(self.line.quantity, 8)
        self.assertFalse(self.waybill._goods_lines_changed(self.waybill, self._goods(10)),
                         "no 'goods changed' (no chatter, no email) while it waits")

    def test_discard_reloads_the_waybill_from_rs(self):
        self._refused_adjustment_to_8()

        with patch.object(self.service, 'get_full_waybill',
                          return_value=({'ID': '930001'}, self._goods(10))), \
                patch.object(type(self.waybill), '_map_rs_waybill_vals', return_value={}):
            self.waybill.action_discard_adjustment()

        self.assertEqual(self.line.quantity, 10)
        self.assertFalse(self.waybill.rs_adjustment_error)
        self.assertFalse(self.waybill.edit_snapshot_json)
        self.assertEqual(self.picking.move_ids.quantity, 10)

    def test_a_closed_popup_does_not_keep_an_old_starting_point(self):
        self.waybill.action_edit_waybill()
        self.line.quantity = 12

        self.waybill.action_edit_waybill()

        self.assertEqual(json.loads(self.waybill.edit_snapshot_json)[0]['quantity'], 12)

    def test_already_sent_and_rs_down_keeps_the_saved_lines_until_discarded(self):
        self.line.quantity = 12

        message = self._submit()

        self.assertIn('Discard Adjustment', message or '')
        self.assertTrue(self.waybill.rs_adjustment_error)
        self.assertEqual(self.line.quantity, 12)
        self.assertEqual(self.picking.move_ids.quantity, 10)
        self.assertFalse(self.waybill._goods_lines_changed(self.waybill, self._goods(10)))
        with self.assertRaises(UserError):
            self.waybill.action_edit_waybill()

        with patch.object(self.service, 'get_full_waybill',
                          return_value=({'ID': '930001'}, self._goods(10))), \
                patch.object(type(self.waybill), '_map_rs_waybill_vals', return_value={}):
            self.waybill.action_edit_waybill()

        self.assertEqual(self.line.quantity, 10)
        self.assertFalse(self.waybill.rs_adjustment_error)
        self.assertTrue(self.waybill.edit_snapshot_json)

    def test_a_refusal_without_a_text_still_blocks_the_sync(self):
        self.waybill.action_edit_waybill()
        self.line.quantity = 8

        with patch.object(type(self.waybill), '_rs_send_adjustment', side_effect=ValueError()):
            self._submit()
        self.waybill._sync_goods_lines(self._goods(10))

        self.assertTrue(self.waybill.rs_adjustment_error)
        self.assertEqual(self.line.quantity, 8, "the sync keeps the unsent Adjustment")

    def test_retry_refuses_while_an_adjustment_waits(self):
        before_refusal = self.waybill._build_line_snapshot()
        self._refused_adjustment_to_8()
        self.waybill.rs_goods_pending_snapshot = before_refusal

        with self.assertRaises(UserError):
            self.waybill.action_retry_rs_goods_change()

        self.assertEqual(self.picking.move_ids.quantity, 10)

    def test_update_moves_nothing_while_an_adjustment_waits(self):
        before_refusal = self.waybill._build_line_snapshot()
        self._refused_adjustment_to_8()
        self.waybill.rs_goods_pending_snapshot = before_refusal

        self.waybill._apply_rs_goods_diff_auto(self.waybill._build_line_snapshot())

        self.assertEqual(self.picking.move_ids.quantity, 10)
        self.assertEqual(self.line.quantity, 8)

    def test_an_invoiced_waybill_holds_only_a_real_goods_change(self):
        with patch.object(type(self.waybill), '_rs_auto_apply_blocked', return_value="attached to invoice INV/1"):
            self.waybill._apply_rs_goods_diff_auto(self.waybill._build_line_snapshot())

        self.assertFalse(self.waybill.rs_goods_pending_snapshot)
        self.assertFalse(self.waybill.rs_post_commit_error)
