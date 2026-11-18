"""A goods change made on RS.GE goes into the delivery whole or not at all; a refused change is
kept, shown on the waybill and retried.
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestRsGoodsAtomic(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        cls.Quant = cls.env['stock.quant']

    def setUp(self):
        super().setUp()
        self.plain = self.env['product.product'].create({'name': 'A', 'is_storable': True})
        self.lotted = self.env['product.product'].create(
            {'name': 'B', 'is_storable': True, 'tracking': 'lot'})
        self.lot = self.env['stock.lot'].create({'name': 'L1', 'product_id': self.lotted.id})
        self.Quant._update_available_quantity(self.plain, self.stock, 40)
        self.Quant._update_available_quantity(self.lotted, self.stock, 1, lot_id=self.lot)
        self.order = self.env['sale.order'].create({
            'partner_id': self.buyer.id,
            'order_line': [(0, 0, {'product_id': self.plain.id, 'product_uom_qty': 10}),
                           (0, 0, {'product_id': self.lotted.id, 'product_uom_qty': 1})],
        })
        self.order.with_context(skip_rs_auto_create=True).action_confirm()
        self.picking = self.order.picking_ids
        self.picking.move_ids.picked = True
        self.picking.with_context(skip_rs_auto_create=True)._action_done()
        self.waybill = self.make_waybill(state='completed', waybill_status='2', rs_internal_id=850001,
                                         picking_id=self.picking.id, sales_order_id=self.order.id)
        for move in self.picking.move_ids:
            self.add_line(self.waybill, quantity=move.quantity, product_id=move.product_id.id,
                          name=move.product_id.name, stock_move_id=move.id)

    def _move(self, product):
        return self.picking.move_ids.filtered(lambda m: m.product_id == product)

    def _line(self, product):
        return self.waybill.line_ids.filtered(lambda l: l.product_id == product)

    def _rs_change(self, quantities):
        """What the sync does: lines take the RS quantities, then the delivery follows."""
        snapshot = self.waybill._build_line_snapshot()
        for product, qty in quantities.items():
            self._line(product).quantity = qty
        return self.waybill._apply_rs_goods_diff_auto(snapshot)

    def test_a_refused_line_leaves_the_whole_delivery_unchanged(self):
        applied = self._rs_change({self.plain: 12, self.lotted: 2})

        self.assertFalse(applied)
        self.assertEqual(self._move(self.plain).quantity, 10, "A must not go in without B")
        self.assertEqual(self._move(self.lotted).quantity, 1)
        self.assertEqual(self.order.order_line.mapped('product_uom_qty'), [10, 1])
        self.assertTrue(self.waybill.rs_goods_pending_snapshot)
        self.assertIn('lot', self.waybill.rs_post_commit_error)
        self.assertTrue(self.waybill._rs_has_outstanding_step())

    def test_it_is_retried_and_goes_in_once_the_cause_is_fixed(self):
        self._rs_change({self.plain: 12, self.lotted: 2})
        self.waybill._rs_repair_local_state()
        self.assertTrue(self.waybill.rs_goods_pending_snapshot)
        self.Quant._update_available_quantity(self.lotted, self.stock, 1, lot_id=self.lot)

        self.waybill._rs_repair_local_state()

        self.assertEqual(self._move(self.plain).quantity, 12)
        self.assertEqual(self._move(self.lotted).quantity, 2)
        self.assertFalse(self.waybill.rs_goods_pending_snapshot)
        self.assertFalse(self.waybill.rs_post_commit_error)
        self.assertFalse(self.waybill._rs_has_outstanding_step())

    def test_a_second_rs_change_while_pending_is_applied_with_the_first(self):
        self._rs_change({self.plain: 12, self.lotted: 2})
        self._rs_change({self.plain: 13})
        self.Quant._update_available_quantity(self.lotted, self.stock, 1, lot_id=self.lot)

        self.waybill.action_retry_rs_goods_change()

        self.assertEqual(self._move(self.plain).quantity, 13, "from 10, not 12 + 1 twice")
        self.assertEqual(self._move(self.lotted).quantity, 2)

    def test_retry_shows_the_reason_while_it_still_fails(self):
        self._rs_change({self.plain: 12, self.lotted: 2})

        with self.assertRaises(UserError), self.env.cr.savepoint():
            self.waybill.action_retry_rs_goods_change()

    def test_no_adjustment_while_a_change_is_pending(self):
        self._rs_change({self.plain: 12, self.lotted: 2})

        with self.assertRaises(UserError):
            self.waybill.action_edit_waybill()

    def test_an_accepted_change_needs_nothing_more(self):
        self.assertTrue(self._rs_change({self.plain: 12}))

        self.assertEqual(self._move(self.plain).quantity, 12)
        self.assertFalse(self.waybill.rs_goods_pending_snapshot)

    def test_a_blocked_change_is_held_and_applied_once_unblocked(self):
        with patch.object(type(self.waybill), '_rs_auto_apply_blocked',
                          return_value="attached to invoice INV/1"):
            self.assertFalse(self._rs_change({self.plain: 12}))
            self.waybill._rs_repair_local_state()

        self.assertEqual(self._move(self.plain).quantity, 10)
        self.assertIn('INV/1', self.waybill.rs_post_commit_error)
        self.assertTrue(self.waybill.rs_goods_pending_snapshot)

        self.waybill._rs_repair_local_state()

        self.assertEqual(self._move(self.plain).quantity, 12)
        self.assertFalse(self.waybill.rs_goods_pending_snapshot)
        self.assertFalse(self.waybill.rs_post_commit_error)
