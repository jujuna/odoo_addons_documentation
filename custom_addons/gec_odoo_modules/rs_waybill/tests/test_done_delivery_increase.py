"""More goods left than a done delivery recorded: the same done delivery follows the waybill, taking
the extra from real stock per lot and location.
"""

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestDoneDeliveryIncrease(RsWaybillCommon):

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

    def _add_stock(self, product, qty, location=None, lot=None):
        self.Quant._update_available_quantity(product, location or self.stock, qty, lot_id=lot)

    def _available(self, product, lot=None):
        return self.Quant._get_available_quantity(product, self.stock, lot_id=lot, strict=bool(lot))

    def _order(self, product, qty):
        order = self.env['sale.order'].create({
            'partner_id': self.buyer.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': qty})],
        })
        order.with_context(skip_rs_auto_create=True).action_confirm()
        return order

    def _validate(self, picking):
        """Ship what is reserved; the rest goes to a backorder."""
        picking.move_ids.picked = True
        picking.with_context(skip_rs_auto_create=True)._action_done()
        return picking.backorder_ids

    def _completed_waybill(self, picking, order=None):
        waybill = self.make_waybill(state='completed', waybill_status='2', rs_internal_id=810001,
                                    picking_id=picking.id,
                                    sales_order_id=order.id if order else False)
        for move in picking.move_ids:
            self.add_line(waybill, quantity=move.quantity, product_id=move.product_id.id,
                          name=move.product_id.name, stock_move_id=move.id)
        return waybill

    def _qty_up(self, waybill, product, new_qty):
        line = waybill.line_ids.filtered(lambda l: l.product_id == product)
        diff = {'type': 'qty_up', 'line': line, 'product_id': product.id,
                'old_qty': line.quantity, 'new_qty': new_qty, 'qty_diff': new_qty - line.quantity}
        line.quantity = new_qty
        waybill._apply_line_diffs_increase_on_done([diff])
        return line

    def _added(self, waybill, product, qty, price=7.0):
        line = self.add_line(waybill, quantity=qty, unit_price=price,
                             product_id=product.id, name=product.name)
        diff = {'type': 'added', 'line': line, 'product_id': product.id,
                'old_qty': 0, 'new_qty': qty, 'qty_diff': qty}
        waybill._apply_line_diffs_increase_on_done([diff])
        return line

    def test_increase_ships_the_extra_from_stock_and_raises_the_order(self):
        product = self._product('Plain')
        self._add_stock(product, 40)
        order = self._order(product, 10)
        picking = order.picking_ids
        self._validate(picking)
        waybill = self._completed_waybill(picking, order)

        self._qty_up(waybill, product, 12)

        self.assertEqual(picking.move_ids.quantity, 12)
        self.assertEqual(picking.move_ids.product_uom_qty, 12)
        self.assertEqual(self._available(product), 28)
        self.assertEqual(order.order_line.product_uom_qty, 12)
        self.assertEqual(order.order_line.qty_delivered, 12)
        self.assertEqual(len(order.picking_ids), 1, "no second delivery")

    # ── Lock Confirmed Sales: a locked order still follows the waybill and stays locked ──

    def _assert_followed_and_locked(self, order):
        self.assertTrue(order.locked)
        self.assertTrue(order.message_ids.filtered(lambda m: 'the order stays locked' in (m.body or '')))

    def test_locked_order_follows_an_increase_and_stays_locked(self):
        product = self._product('Plain')
        self._add_stock(product, 40)
        order = self._order(product, 10)
        order.action_lock()
        picking = order.picking_ids
        self._validate(picking)
        waybill = self._completed_waybill(picking, order)

        self._qty_up(waybill, product, 12)

        self.assertEqual(order.order_line.product_uom_qty, 12)
        self._assert_followed_and_locked(order)

    def test_locked_order_gets_an_added_product_and_stays_locked(self):
        product, extra = self._product('Plain'), self._product('Extra')
        self._add_stock(product, 10)
        self._add_stock(extra, 10)
        order = self._order(product, 10)
        order.action_lock()
        picking = order.picking_ids
        self._validate(picking)
        waybill = self._completed_waybill(picking, order)

        self._added(waybill, extra, 3)

        self.assertEqual(order.order_line.filtered(lambda l: l.product_id == extra).product_uom_qty, 3)
        self._assert_followed_and_locked(order)

    def test_locked_order_follows_a_decrease_before_delivery_and_stays_locked(self):
        product = self._product('Plain')
        self._add_stock(product, 40)
        order = self._order(product, 10)
        order.action_lock()
        picking = order.picking_ids
        waybill = self.make_waybill(state='active', waybill_status='1', rs_internal_id=810002,
                                    picking_id=picking.id, sales_order_id=order.id)
        line = self.add_line(waybill, quantity=10, product_id=product.id, name=product.name,
                             stock_move_id=picking.move_ids.id)
        diff = {'type': 'qty_down', 'line': line, 'product_id': product.id,
                'old_qty': 10, 'new_qty': 8, 'qty_diff': -2}
        line.quantity = 8

        waybill._apply_line_diffs_to_picking_in_place([diff])

        self.assertEqual(picking.move_ids.product_uom_qty, 8)
        self.assertEqual(order.order_line.product_uom_qty, 8)
        self._assert_followed_and_locked(order)

    def test_increase_on_lots_takes_the_lot_that_has_stock(self):
        """The extra quantity goes on the lot that has stock."""
        product = self._product('Lotted', tracking='lot')
        lot_a, lot_b = self._lot(product, 'A'), self._lot(product, 'B')
        self._add_stock(product, 4, lot=lot_a)
        self._add_stock(product, 10, lot=lot_b)
        order = self._order(product, 10)
        picking = order.picking_ids
        lines = picking.move_line_ids
        self.assertEqual(sorted(lines.mapped('quantity')), [4, 6], "setup: A 4 + B 6 reserved")
        self._validate(picking)
        waybill = self._completed_waybill(picking, order)

        self._qty_up(waybill, product, 12)

        shipped = {ml.lot_id.name: ml.quantity for ml in picking.move_line_ids}
        self.assertEqual(shipped, {'A': 4, 'B': 8})
        self.assertEqual(self._available(product, lot_a), 0, "lot A must not go negative")
        self.assertEqual(self._available(product, lot_b), 2)

    def test_increase_on_a_serial_without_stock_is_refused_and_changes_nothing(self):
        """A serial without stock is refused and nothing changes."""
        product = self._product('Serial', tracking='serial')
        sn1 = self._lot(product, 'SN1')
        self._add_stock(product, 1, lot=sn1)
        order = self._order(product, 1)
        picking = order.picking_ids
        self._validate(picking)
        waybill = self._completed_waybill(picking, order)

        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._qty_up(waybill, product, 2)

        self.assertEqual(picking.move_line_ids.mapped('quantity'), [1])
        self.assertEqual(order.order_line.qty_delivered, 1)

    def test_added_product_lands_on_the_same_delivery_not_the_open_backorder(self):
        """With the first delivery done and the second open, a product added on the first waybill
        goes on the first delivery, not on the second or a new third."""
        product_c, product_x = self._product('C'), self._product('X')
        self._add_stock(product_c, 4)
        self._add_stock(product_x, 10)
        order = self._order(product_c, 10)
        d1 = order.picking_ids
        d2 = self._validate(d1)
        self.assertEqual(d2.move_ids.product_uom_qty, 6, "setup: backorder for 6")
        waybill = self._completed_waybill(d1, order)

        line = self._added(waybill, product_x, 3, price=25.0)

        self.assertEqual(line.stock_move_id.picking_id, d1)
        self.assertEqual(line.stock_move_id.state, 'done')
        self.assertEqual(d1.move_ids.product_id, product_c | product_x)
        self.assertEqual(d2.state, 'confirmed', "the open backorder is untouched")
        self.assertEqual(d2.move_ids.product_id, product_c)
        self.assertEqual(order.picking_ids, d1 | d2, "no third delivery")
        x_line = order.order_line.filtered(lambda l: l.product_id == product_x)
        self.assertEqual((x_line.product_uom_qty, x_line.qty_delivered), (3, 3))
        self.assertAlmostEqual(x_line.price_total / 3, 25.0, msg="the waybill price has the VAT in it")
        self.assertEqual(self._available(product_x), 7)

    def test_added_product_on_two_shelves_ships_exactly_the_declared_quantity(self):
        """Two shelves reserving 2 + 3 ship exactly the declared 5."""
        product = self._product('Plain')
        shelf_1 = self.env['stock.location'].create({'name': 'Shelf 1', 'location_id': self.stock.id})
        shelf_2 = self.env['stock.location'].create({'name': 'Shelf 2', 'location_id': self.stock.id})
        other = self._product('Other')
        self._add_stock(other, 5)
        self._add_stock(product, 2, location=shelf_1)
        self._add_stock(product, 3, location=shelf_2)
        order = self._order(other, 5)
        picking = order.picking_ids
        self._validate(picking)
        waybill = self._completed_waybill(picking, order)

        line = self._added(waybill, product, 5)

        self.assertEqual(sum(line.stock_move_id.move_line_ids.mapped('quantity')), 5)
        self.assertEqual(self._available(product), 0)
        self.assertFalse(self.Quant.search([('product_id', '=', product.id),
                                            ('location_id', 'child_of', self.stock.id),
                                            ('quantity', '<', 0)]), "no negative stock")

    def test_added_serial_without_stock_is_refused(self):
        other = self._product('Other')
        self._add_stock(other, 1)
        serial = self._product('Serial', tracking='serial')
        order = self._order(other, 1)
        picking = order.picking_ids
        self._validate(picking)
        waybill = self._completed_waybill(picking, order)

        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._added(waybill, serial, 1)

        self.assertEqual(picking.move_ids.product_id, other)

    def test_added_product_without_sales_order_still_moves_the_stock(self):
        product, other = self._product('Plain'), self._product('Other')
        self._add_stock(product, 5)
        self._add_stock(other, 1)
        picking = self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.stock.id,
            'location_dest_id': self.customers.id,
            'move_ids': [(0, 0, {'product_id': other.id, 'product_uom_qty': 1,
                                 'uom_id': other.uom_id.id,
                                 'location_id': self.stock.id,
                                 'location_dest_id': self.customers.id})],
        })
        picking.action_confirm()
        picking.action_assign()
        self._validate(picking)
        waybill = self._completed_waybill(picking)

        line = self._added(waybill, product, 2)

        self.assertEqual(line.stock_move_id.picking_id, picking)
        self.assertFalse(line.stock_move_id.sale_line_id)
        self.assertEqual(self._available(product), 3)
