"""A return waybill linked to its delivery with Create Return follows later goods changes: the return receipt
changes, the sales order's ordered quantity never does (Odoo counts the returned goods itself), and a done return
lowered on RS.GE is simply lowered, with nothing to ask."""

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestReturnGoodsChange(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        stock = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1).lot_stock_id
        self.milk = self.env['product.product'].create({'name': 'Milk', 'is_storable': True})
        self.env['stock.quant']._update_available_quantity(self.milk, stock, 100)
        self.order = self.env['sale.order'].create({
            'partner_id': self.buyer.id,
            'order_line': [(0, 0, {'product_id': self.milk.id, 'product_uom_qty': 100})],
        })
        self.order.with_context(skip_rs_auto_create=True).action_confirm()
        delivery = self.order.picking_ids
        delivery.move_ids.picked = True
        delivery.with_context(skip_rs_auto_create=True)._action_done()

        self.waybill = self.make_waybill(waybill_type='5', state='active', waybill_status='1',
                                         rs_internal_id=998001, return_origin_picking_id=delivery.id)
        self.line = self.add_line(self.waybill, quantity=10, product_id=self.milk.id, name='Milk')
        self.waybill.action_create_return_from_origin()
        self.receipt = self.waybill.picking_id
        self.sol = self.order.order_line

    def _rs_changes_to(self, qty):
        snapshot = self.waybill._build_line_snapshot()
        self.line.quantity = qty
        self.assertTrue(self.waybill._apply_rs_goods_diff_auto(snapshot), self.waybill.rs_post_commit_error)

    def test_lines_are_linked_to_the_return_moves(self):
        self.assertEqual(self.line.stock_move_id, self.receipt.move_ids)

    def test_more_back_changes_the_receipt_not_the_order(self):
        self._rs_changes_to(12)
        self.assertEqual(self.receipt.move_ids.product_uom_qty, 12)
        self.assertEqual(self.sol.product_uom_qty, 100, "a return never changes what was ordered")

    def test_a_done_return_lowered_is_lowered_without_asking(self):
        self.waybill.write({'state': 'completed', 'waybill_status': '2'})  # RS.GE closed it: no close call
        self.receipt.move_ids.quantity = 10
        self.receipt.move_ids.picked = True
        self.receipt.with_context(skip_rs_auto_create=True)._action_done()
        self.assertEqual(self.sol.qty_delivered, 90)
        [asked] = self.waybill._rs_load_pending_corrections()
        self.assertEqual((asked['qty'], asked['returned']), (10, True), "the return's 'deliver later or reduce?'")

        self._rs_changes_to(8)

        self.assertEqual(self.receipt.move_ids.quantity, 8)
        self.assertEqual(self.sol.qty_delivered, 92)
        self.assertEqual(self.sol.product_uom_qty, 100)
        [asked] = self.waybill._rs_load_pending_corrections()
        self.assertEqual((asked['qty'], asked['returned']), (8, True),
                         "asked about what came back now; no 'where are the goods' question added")

    def test_a_settled_return_is_not_settled_again(self):
        self.waybill.write({'state': 'completed', 'waybill_status': '2'})
        self.receipt.move_ids.quantity = 10
        self.receipt.move_ids.picked = True
        self.receipt.with_context(skip_rs_auto_create=True)._action_done()
        self.waybill.pending_return_json = False  # the operator answered 'deliver later or reduce?'

        self._rs_changes_to(8)

        self.assertFalse(self.waybill.pending_return_json, "not asked again")
        self.assertIn('settled', self.waybill.message_ids[0].body)
