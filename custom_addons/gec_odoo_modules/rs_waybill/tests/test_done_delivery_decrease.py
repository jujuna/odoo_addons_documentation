"""Fewer goods than a completed waybill declared: the same done delivery is lowered in place, no
return waybill, and the operator decides where the goods are and what the order does.
"""

import json

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestDoneDeliveryDecrease(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        cls.customers = cls.env.ref('stock.stock_location_customers')
        cls.Quant = cls.env['stock.quant']

    def _product(self, name, tracking=False):
        return self.env['product.product'].create({
            'name': name, 'is_storable': True, 'tracking': tracking})

    def _lot(self, product, name):
        return self.env['stock.lot'].create({'name': name, 'product_id': product.id})

    def _add_stock(self, product, qty, lot=None):
        self.Quant._update_available_quantity(product, self.stock, qty, lot_id=lot)

    def _available(self, product, lot=None):
        return self.Quant._get_available_quantity(product, self.stock, lot_id=lot, strict=bool(lot))

    def _order(self, product, qty):
        order = self.env['sale.order'].create({
            'partner_id': self.buyer.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': qty})],
        })
        order.with_context(skip_rs_auto_create=True).action_confirm()
        return order

    def _delivered(self, product, qty, order_qty=None):
        """A completed waybill on a done delivery of `qty`."""
        self._add_stock(product, 40) if not product.tracking else None
        order = self._order(product, order_qty or qty)
        picking = order.picking_ids
        picking.move_ids.picked = True
        picking.with_context(skip_rs_auto_create=True)._action_done()
        return order, picking, self._waybill(picking, order)

    def _waybill(self, picking, order=None):
        waybill = self.make_waybill(state='completed', waybill_status='2', rs_internal_id=830001,
                                    picking_id=picking.id,
                                    sales_order_id=order.id if order else False)
        for move in picking.move_ids:
            self.add_line(waybill, quantity=move.quantity, product_id=move.product_id.id,
                          name=move.product_id.name, stock_move_id=move.id)
        return waybill

    def _lower(self, waybill, product, qty):
        """The Adjustment's local step: lower the delivery, keep the decision pending."""
        waybill._rs_add_pending_corrections(waybill._rs_lower_done_delivery({product.id: qty}))

    def _popup(self, waybill):
        action = waybill.action_reconcile_pending_return()
        return self.env[action['res_model']].browse(action['res_id'])

    def _open_deliveries(self, order):
        return order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))

    def test_lowering_puts_the_goods_back_and_leaves_the_order(self):
        product = self._product('Plain')
        order, picking, waybill = self._delivered(product, 10)

        self._lower(waybill, product, 2)

        self.assertEqual(picking.move_ids.quantity, 8)
        self.assertEqual(picking.move_ids.product_uom_qty, 8)
        self.assertEqual(self._available(product), 32)
        self.assertEqual(order.order_line.product_uom_qty, 10, "the popup decides the order")
        self.assertEqual(order.order_line.qty_delivered, 8)
        self.assertTrue(waybill.pending_return_json)

    def test_reduce_the_order(self):
        product = self._product('Plain')
        order, picking, waybill = self._delivered(product, 10)
        self._lower(waybill, product, 1)

        self._popup(waybill).action_reduce_order()

        self.assertEqual(order.order_line.product_uom_qty, 9)
        self.assertEqual(order.order_line.qty_delivered, 9)
        self.assertFalse(self._open_deliveries(order), "nothing re-procured")
        self.assertFalse(waybill.pending_return_json)
        self.assertEqual(self._available(product), 31)

    def test_deliver_later_creates_a_delivery_for_the_rest(self):
        product = self._product('Plain')
        order, picking, waybill = self._delivered(product, 10)
        self._lower(waybill, product, 1)

        self._popup(waybill).action_deliver_later()

        later = self._open_deliveries(order)
        self.assertEqual(len(later), 1)
        self.assertEqual(later.move_ids.product_uom_qty, 1)
        self.assertEqual(order.order_line.product_uom_qty, 10)
        self.assertFalse(waybill.pending_return_json)

    def test_lost_on_the_way_is_scrapped_and_delivered_again(self):
        product = self._product('Plain')
        order, picking, waybill = self._delivered(product, 10)
        self._lower(waybill, product, 1)
        popup = self._popup(waybill)
        popup.line_ids.disposition = 'scrap'

        popup.action_deliver_later()

        on_hand = product.with_context(location=self.stock.id).qty_available
        self.assertEqual(on_hand, 30, "the lost unit left the stock")
        scrap = self.env['stock.move'].search([('is_scrap', '=', True), ('product_id', '=', product.id)])
        self.assertEqual((scrap.state, scrap.quantity, scrap.picking_id), ('done', 1, picking))
        self.assertEqual(self._open_deliveries(order).move_ids.product_uom_qty, 1)

    def test_lost_lot_scraps_the_lot_that_came_back(self):
        product = self._product('Lotted', tracking='lot')
        lot_a, lot_b = self._lot(product, 'A'), self._lot(product, 'B')
        self._add_stock(product, 4, lot=lot_a)
        self._add_stock(product, 10, lot=lot_b)
        order, picking, waybill = self._delivered(product, 10)
        self._lower(waybill, product, 2)
        self.assertEqual(self._available(product, lot_b), 6, "setup: B 6 → 4 shipped, 2 back")
        popup = self._popup(waybill)
        popup.line_ids.disposition = 'scrap'

        popup.action_reduce_order()

        self.assertEqual(self._available(product, lot_a), 0)
        self.assertEqual(self._available(product, lot_b), 4)
        scrap = self.env['stock.move'].search([('is_scrap', '=', True), ('product_id', '=', product.id)])
        self.assertEqual(scrap.move_line_ids.lot_id, lot_b)

    def test_closing_the_popup_keeps_the_decision(self):
        product = self._product('Plain')
        order, picking, waybill = self._delivered(product, 10)
        self._lower(waybill, product, 2)

        self._popup(waybill)

        popup = self._popup(waybill)
        self.assertEqual(popup.line_ids.qty, 2)
        self.assertEqual(picking.move_ids.quantity, 8, "reopening does not lower twice")

    def test_a_decrease_seen_on_rs_lowers_the_delivery_at_once(self):
        product = self._product('Plain')
        order, picking, waybill = self._delivered(product, 10)
        snapshot = waybill._build_line_snapshot()
        waybill.line_ids.quantity = 7

        waybill._apply_rs_goods_diff_auto(snapshot)

        self.assertEqual(picking.move_ids.quantity, 7)
        self.assertEqual(self._available(product), 33)
        self.assertEqual(self._popup(waybill).line_ids.qty, 3)

    def test_pending_from_the_old_code_is_lowered_when_reconciled(self):
        product = self._product('Plain')
        order, picking, waybill = self._delivered(product, 10)
        waybill.pending_return_json = json.dumps({str(product.id): 2.0})

        popup = self._popup(waybill)

        self.assertEqual(picking.move_ids.quantity, 8)
        self.assertEqual(popup.line_ids.qty, 2)

    def test_answer_keeps_corrections_added_meanwhile(self):
        product = self._product('Plain')
        order, picking, waybill = self._delivered(product, 10)
        self._lower(waybill, product, 1)
        popup = self._popup(waybill)
        self._lower(waybill, product, 2)

        popup.action_reduce_order()

        self.assertEqual(self._popup(waybill).line_ids.qty, 2)

    def test_without_sales_order_only_where_is_asked(self):
        product = self._product('Plain')
        self._add_stock(product, 40)
        picking = self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.stock.id,
            'location_dest_id': self.customers.id,
            'move_ids': [(0, 0, {'product_id': product.id, 'product_uom_qty': 10,
                                 'uom_id': product.uom_id.id,
                                 'location_id': self.stock.id,
                                 'location_dest_id': self.customers.id})],
        })
        picking.action_confirm()
        picking.action_assign()
        picking.move_ids.picked = True
        picking.with_context(skip_rs_auto_create=True)._action_done()
        waybill = self._waybill(picking)
        self._lower(waybill, product, 2)
        popup = self._popup(waybill)

        self.assertFalse(popup.has_sale_lines)
        popup.action_confirm()

        self.assertFalse(waybill.pending_return_json)
        self.assertEqual(self._available(product), 32)

    def test_locked_order_is_not_procured_but_flagged(self):
        product = self._product('Plain')
        order, picking, waybill = self._delivered(product, 10)
        self._lower(waybill, product, 1)
        order.action_lock()

        self._popup(waybill).action_deliver_later()

        self.assertFalse(self._open_deliveries(order))
        self.assertTrue(order.activity_ids)

    def test_no_return_waybill_is_offered(self):
        self.assertFalse(hasattr(self.env['rs.waybill.return.decision.wizard'], 'action_create_with_waybill'))

    def test_cancel_on_a_completed_waybill_is_refused(self):
        product = self._product('Plain')
        order, picking, waybill = self._delivered(product, 10)

        with self.assertRaises(UserError):
            waybill.action_refuse_waybill()

        self.assertEqual(waybill.state, 'completed')
        self.assertEqual(picking.move_ids.quantity, 10)
