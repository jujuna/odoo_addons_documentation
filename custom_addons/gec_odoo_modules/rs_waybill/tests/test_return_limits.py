"""The same delivered goods can come back only once (shipped minus every return, open or done), and
the order is asked after a return.
"""

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestReturnLimits(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        cls.Quant = cls.env['stock.quant']

    def setUp(self):
        super().setUp()
        self._rs_id = 840000

    def _delivered(self, qty=10):
        product = self.env['product.product'].create({'name': 'Plain', 'is_storable': True})
        self.Quant._update_available_quantity(product, self.stock, 40)
        order = self.env['sale.order'].create({
            'partner_id': self.buyer.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': qty})],
        })
        order.with_context(skip_rs_auto_create=True).action_confirm()
        picking = order.picking_ids
        picking.move_ids.picked = True
        picking.with_context(skip_rs_auto_create=True)._action_done()
        waybill = self._waybill('2', picking, product, qty)
        return product, order, picking, waybill

    def _waybill(self, waybill_type, picking, product, qty, **vals):
        self._rs_id += 1
        vals = {'state': 'completed', 'waybill_status': '2', **vals}
        waybill = self.make_waybill(rs_internal_id=self._rs_id, waybill_type=waybill_type,
                                    picking_id=picking.id if picking else False, **vals)
        self.add_line(waybill, quantity=qty, product_id=product.id, name=product.name)
        return waybill

    def _return(self, delivery, qty, waybill=None):
        """Return button on the delivery: core's return, quantity typed, validated."""
        ret = delivery.with_context(skip_rs_auto_create=True)._create_return()
        ret.move_ids.product_uom_qty = qty
        ret.with_context(skip_rs_auto_create=True).action_confirm()
        ret.move_ids.quantity = qty
        ret.move_ids.picked = True
        if waybill:
            ret.waybill_id = waybill
            waybill.picking_id = ret
        ret.with_context(skip_rs_auto_create=True)._action_done()
        return ret

    def test_second_return_of_the_same_goods_is_refused(self):
        product, order, delivery, _waybill = self._delivered()
        self._return(delivery, 10)

        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._return(delivery, 1)

        self.assertEqual(order.order_line.qty_delivered, 0)

    def test_partial_returns_add_up_to_the_delivery(self):
        product, order, delivery, _waybill = self._delivered()
        self._return(delivery, 4)
        self._return(delivery, 6)

        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._return(delivery, 1)

        self.assertEqual(order.order_line.qty_delivered, 0)

    def test_return_from_waybill_never_takes_more_than_left(self):
        product, order, delivery, waybill = self._delivered()
        self._return(delivery, 7)

        returned = waybill._create_return_picking({product.id: 10}, create_waybill=False)

        self.assertEqual(returned.move_ids.product_uom_qty, 3)

    def test_open_return_counts_as_already_returned(self):
        product, order, delivery, waybill = self._delivered()
        waybill._create_return_picking({product.id: 10}, create_waybill=False)

        self.assertFalse(waybill._create_return_picking({product.id: 10}, create_waybill=False))

    def test_fully_returned_delivery_is_not_offered_again(self):
        product, order, delivery, _waybill = self._delivered()
        rs_return = self._waybill('5', False, product, 10, state='active', waybill_status='1')
        self.assertIn(delivery, rs_return._rs_return_origin_candidates())

        self._return(delivery, 10)

        self.assertNotIn(delivery, rs_return._rs_return_origin_candidates())
        rs_return.return_origin_picking_id = delivery
        with self.assertRaises(UserError), self.env.cr.savepoint():
            rs_return.action_create_return_from_origin()

    def _popup(self, waybill):
        action = waybill.action_reconcile_pending_return()
        return self.env[action['res_model']].browse(action['res_id'])

    def test_return_on_a_waybill_asks_deliver_later(self):
        product, order, delivery, _waybill = self._delivered()
        return_waybill = self._waybill('5', False, product, 1)
        self._return(delivery, 1, waybill=return_waybill)

        popup = self._popup(return_waybill)
        self.assertFalse(popup.ask_where, "the goods are physically back: only the order is asked")
        self.assertEqual(popup.line_ids.qty, 1)
        popup.action_deliver_later()

        later = order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')
                                           and p.picking_type_code == 'outgoing')
        self.assertEqual(later.move_ids.product_uom_qty, 1)
        self.assertEqual(order.order_line.product_uom_qty, 10)
        self.assertFalse(return_waybill.pending_return_json)

    def test_return_on_a_waybill_can_reduce_the_order(self):
        product, order, delivery, _waybill = self._delivered()
        return_waybill = self._waybill('5', False, product, 1)
        self._return(delivery, 1, waybill=return_waybill)

        self._popup(return_waybill).action_reduce_order()

        self.assertEqual(order.order_line.product_uom_qty, 9)
        self.assertEqual(order.order_line.qty_delivered, 9)

    def test_return_without_waybill_flags_the_order(self):
        product, order, delivery, _waybill = self._delivered()

        self._return(delivery, 1)

        self.assertTrue(order.activity_ids)
