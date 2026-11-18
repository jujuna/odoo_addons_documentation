"""A line renamed on RS.GE is the same line: matched by RS line ID, then barcode + name, then
barcode.
"""

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestRsLineMatching(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)

    def setUp(self):
        super().setUp()
        self.milk = self.env['product.product'].create(
            {'name': 'Milk 1L', 'is_storable': True, 'barcode': 'B-MILK'})
        self.env['stock.quant']._update_available_quantity(self.milk, self.warehouse.lot_stock_id, 40)
        self.order = self.env['sale.order'].create({
            'partner_id': self.buyer.id,
            'order_line': [(0, 0, {'product_id': self.milk.id, 'product_uom_qty': 10})],
        })
        self.order.with_context(skip_rs_auto_create=True).action_confirm()
        self.picking = self.order.picking_ids
        self.picking.move_ids.picked = True
        self.picking.with_context(skip_rs_auto_create=True)._action_done()
        self.waybill = self.make_waybill(state='completed', waybill_status='2', rs_internal_id=860001,
                                         picking_id=self.picking.id, sales_order_id=self.order.id)
        self.line = self.add_line(self.waybill, quantity=10, unit_price=5, product_id=self.milk.id,
                                  name='Milk 1L', bar_code='B-MILK', rs_good_id='7001',
                                  unit_name='ცალი', vat_type='0',
                                  stock_move_id=self.picking.move_ids.id)

    def _goods(self, **item):
        good = {'ID': '7001', 'BAR_CODE': 'B-MILK', 'W_NAME': 'Milk 1L', 'QUANTITY': '10',
                'PRICE': '5', 'UNIT_TXT': 'ცალი', 'VAT_TYPE': '0'}
        good.update(item)
        return [good]

    def _sync(self, goods):
        """What sync / Update / drift do with RS goods."""
        changed = self.waybill._goods_lines_changed(self.waybill, goods)
        if changed:
            snapshot = self.waybill._build_line_snapshot()
            self.waybill._sync_goods_lines(goods)
            self.waybill._apply_rs_goods_diff_auto(snapshot)
        return changed

    def test_rename_on_rs_keeps_the_line_and_the_order(self):
        self.assertTrue(self._sync(self._goods(W_NAME='Milk 1 L')), "a rename is a change")

        self.assertEqual(self.waybill.line_ids, self.line, "same line, not deleted + added")
        self.assertEqual(self.line.name, 'Milk 1 L')
        self.assertEqual(len(self.order.order_line), 1, "no second order line")
        self.assertEqual(self.picking.move_ids.quantity, 10)
        self.assertEqual(self.order.order_line.qty_delivered, 10)
        self.assertFalse(self.waybill.pending_return_json)

    def test_rename_and_quantity_change_together(self):
        self._sync(self._goods(W_NAME='Milk 1 L', QUANTITY='12'))

        self.assertEqual(self.waybill.line_ids, self.line)
        self.assertEqual(self.picking.move_ids.quantity, 12)
        self.assertEqual(self.order.order_line.product_uom_qty, 12)

    def test_vat_type_or_unit_change_is_noticed(self):
        self.assertTrue(self._sync(self._goods(VAT_TYPE='1')))
        self.assertEqual(self.line.vat_type, '1')
        self.assertTrue(self._sync(self._goods(VAT_TYPE='1', UNIT_TXT='კგ')))
        self.assertEqual(self.line.unit_name, 'კგ')

    def test_nothing_changed_is_nothing_changed(self):
        self.assertFalse(self._sync(self._goods()))

    def test_line_without_rs_id_is_matched_by_barcode(self):
        """Lines saved before RS IDs were stored."""
        self.line.rs_good_id = False

        self._sync(self._goods(W_NAME='Milk 1 L'))

        self.assertEqual(self.waybill.line_ids, self.line)
        self.assertEqual(self.line.rs_good_id, '7001')
        self.assertEqual(len(self.order.order_line), 1)

    def test_another_product_on_the_same_rs_line_is_a_swap(self):
        cheese = self.env['product.product'].create(
            {'name': 'Cheese', 'is_storable': True, 'barcode': 'B-CHEESE'})

        self._sync(self._goods(BAR_CODE='B-CHEESE', W_NAME='Cheese'))

        self.assertEqual(self.waybill.line_ids.product_id, cheese, "a different product is a new line")
        self.assertNotIn(self.line, self.waybill.line_ids)
