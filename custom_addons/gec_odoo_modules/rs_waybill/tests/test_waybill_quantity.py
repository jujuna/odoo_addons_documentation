"""What quantity a waybill declares: the RESERVED quantity (what goes on the truck), never the
ordered one.
"""

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestWaybillDeclaredQuantity(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)

    def setUp(self):
        super().setUp()
        self._seq = 0

    def _picking(self, backorder=False):
        # Explicit names: two pickings per test drawn from the same sequence collide on
        # stock_picking_name_uniq under a rolled-back test transaction.
        def make(suffix):
            self._seq += 1
            return self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
                'name': 'RSQTY/%s/%s' % (self._seq, suffix),
                'picking_type_id': self.warehouse.out_type_id.id,
                'location_id': self.warehouse.lot_stock_id.id,
                'location_dest_id': self.env.ref('stock.stock_location_customers').id,
                'company_id': self.env.company.id,
            })

        picking = make('bo' if backorder else 'main')
        if backorder:
            picking.backorder_id = make('origin').id
        return picking

    def _move(self, picking, demand, reserved):
        move = self.env['stock.move'].with_context(skip_rs_auto_create=True).create({
            'product_id': self.product.id,
            'product_uom_qty': demand,
            'uom_id': self.product.uom_id.id,
            'picking_id': picking.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'company_id': self.env.company.id,
        })
        move.quantity = reserved
        return move

    def test_normal_picking_declares_what_is_reserved(self):
        picking = self._picking()
        move = self._move(picking, demand=100, reserved=60)
        self.assertEqual(picking._rs_waybill_qty(move), 60)

    def test_normal_picking_with_nothing_reserved_declares_nothing(self):
        """No reservation means no waybill for this picking yet; the module creates one when stock
        reserves."""
        picking = self._picking()
        move = self._move(picking, demand=100, reserved=0)
        self.assertEqual(picking._rs_waybill_qty(move), 0)
        self.assertEqual(picking._rs_build_waybill_lines(), [])

    def test_backorder_declares_what_is_reserved_not_what_is_owed(self):
        """40 owed, 25 on the truck: the waybill says 25."""
        picking = self._picking(backorder=True)
        move = self._move(picking, demand=40, reserved=25)
        self.assertEqual(picking._rs_waybill_qty(move), 25,
                         "the waybill declared goods that never left the warehouse")

    def test_a_fresh_backorder_falls_back_to_demand(self):
        """Nothing reserved yet: the draft is created up front so the operator can prepare driver
        and vehicle; it cannot be sent."""
        picking = self._picking(backorder=True)
        move = self._move(picking, demand=40, reserved=0)
        self.assertEqual(picking._rs_waybill_qty(move), 40)

    def test_fully_reserved_backorder_is_unchanged(self):
        picking = self._picking(backorder=True)
        move = self._move(picking, demand=40, reserved=40)
        self.assertEqual(picking._rs_waybill_qty(move), 40)

    def test_built_lines_carry_the_reserved_quantity(self):
        picking = self._picking(backorder=True)
        self._move(picking, demand=40, reserved=25)
        lines = picking._rs_build_waybill_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0][2]['quantity'], 25)

    def test_a_draft_waybill_converges_as_stock_arrives(self):
        """_rs_sync_waybill_lines keeps a not-yet-sent waybill mirrored, walking the draft toward
        the reserved quantity."""
        picking = self._picking(backorder=True)
        move = self._move(picking, demand=40, reserved=0)
        waybill = self.make_waybill(state=False)
        waybill.picking_id = picking.id
        picking.waybill_id = waybill.id
        self.env['rs.waybill.line'].create({
            'rs_waybill_id': waybill.id,
            'product_id': self.product.id,
            'quantity': 40,
            'stock_move_id': move.id,
        })

        move.quantity = 25
        picking._rs_sync_waybill_lines()

        self.assertEqual(waybill.line_ids.quantity, 25)

        move.quantity = 40
        picking._rs_sync_waybill_lines()

        self.assertEqual(waybill.line_ids.quantity, 40)

    def test_a_picking_with_nothing_reserved_cannot_be_saved_to_rs(self):
        """The guard that makes the demand fallback safe: with nothing reserved the picking is not
        Ready and _validate_before_save refuses it."""
        from odoo.exceptions import UserError
        picking = self._picking(backorder=True)
        self._move(picking, demand=40, reserved=0)
        waybill = self.make_waybill()
        self.add_line(waybill)
        waybill.picking_id = picking.id

        self.assertNotIn(picking.state, ('assigned', 'done'))
        with self.assertRaises(UserError) as e:
            waybill._validate_before_save()
        self.assertIn('Reserve stock', e.exception.args[0])
