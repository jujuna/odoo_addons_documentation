"""Stock creation paths that use the Odoo 20 UoM fields."""

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestOdoo20Stock(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)

    def _picking(self, incoming=False):
        picking_type = self.warehouse.in_type_id if incoming else self.warehouse.out_type_id
        return self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'picking_type_id': picking_type.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': picking_type.default_location_dest_id.id,
            'partner_id': self.buyer.id,
        })

    def test_build_transfer_moves(self):
        picking = self._picking()
        waybill = self.make_waybill(picking_id=picking.id)
        self.add_line(waybill, quantity=3)

        waybill._rs_build_moves_on_picking(
            picking, picking.location_id, picking.location_dest_id)

        self.assertEqual(len(picking.move_ids), 1)
        self.assertEqual(picking.move_ids.uom_id, self.product.uom_id)
        self.assertEqual(picking.move_ids.product_uom_qty, 3)

    def test_add_goods_to_open_picking(self):
        picking = self._picking()
        waybill = self.make_waybill(picking_id=picking.id).with_context(skip_rs_auto_create=True)
        line = self.add_line(waybill, quantity=4)

        waybill._apply_line_diffs_to_picking_in_place([{'type': 'added', 'line': line}])

        self.assertEqual(line.stock_move_id, picking.move_ids)
        self.assertEqual(picking.move_ids.uom_id, self.product.uom_id)
        self.assertEqual(picking.move_ids.product_uom_qty, 4)

    def test_native_partial_return_preserves_origin(self):
        picking = self._picking()
        waybill = self.make_waybill(picking_id=picking.id).with_context(skip_rs_auto_create=True)
        self.add_line(waybill, quantity=5)
        waybill._rs_build_moves_on_picking(
            picking, picking.location_id, picking.location_dest_id)
        picking.action_confirm()
        waybill._force_validate_moves(picking.move_ids)
        self.assertEqual(picking.state, 'done')

        returned = waybill._create_return_picking({self.product.id: 2}, create_waybill=False)

        self.assertEqual(returned.return_id, picking)
        self.assertEqual(returned.move_ids.origin_returned_move_id, picking.move_ids)
        self.assertEqual(returned.move_ids.uom_id, self.product.uom_id)
        self.assertEqual(returned.move_ids.product_uom_qty, 2)
        self.assertNotIn(returned.state, ('draft', 'done', 'cancel'))
        self.assertFalse(returned.waybill_id)

    def test_return_quantity_is_shared_between_moves_of_same_product(self):
        picking = self._picking()
        waybill = self.make_waybill(picking_id=picking.id).with_context(skip_rs_auto_create=True)
        self.add_line(waybill, quantity=3)
        self.add_line(waybill, quantity=3)
        waybill._rs_build_moves_on_picking(
            picking, picking.location_id, picking.location_dest_id)
        picking.move_ids._action_confirm(merge=False)
        waybill._force_validate_moves(picking.move_ids)
        self.assertEqual(len(picking.move_ids), 2)

        returned = waybill._create_return_picking({self.product.id: 2}, create_waybill=False)

        self.assertEqual(sum(returned.move_ids.mapped('product_uom_qty')), 2)
        self.assertEqual(len(returned.move_ids), 1)
        self.assertIn(returned.move_ids.origin_returned_move_id, picking.move_ids)
