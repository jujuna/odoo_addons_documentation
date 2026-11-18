"""A delivery cancelled from its order takes its RS.GE draft with it; waybill users can pick a car plate,
and only those who may open them see Car Plates and Settings."""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import new_test_user, tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestCancelledMovesDeleteRsDraft(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.product.is_storable = True
        order = self.env['sale.order'].create({
            'partner_id': self.buyer.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 5})],
        })
        order.with_context(skip_rs_auto_create=True).action_confirm()
        self.picking = order.picking_ids
        self.waybill = self.make_waybill(state='draft', waybill_status='0', rs_internal_id=905001,
                                         picking_id=self.picking.id, sales_order_id=order.id)
        self.picking.waybill_id = self.waybill
        self.service = type(self.env['rs.waybill.soap.service'])

    def test_draft_on_rs_is_deleted_with_the_moves(self):
        with patch.object(self.service, 'delete_waybill', return_value=1) as delete, \
                patch.object(self.env.cr, 'commit'):
            self.picking.move_ids._action_cancel()

        delete.assert_called_once_with(905001)
        self.assertFalse(self.waybill.exists())

    def test_rs_error_stops_the_cancel(self):
        with patch.object(self.service, 'delete_waybill', side_effect=UserError("RS.GE could not be reached")), \
                patch.object(self.env.cr, 'commit'):
            with self.assertRaisesRegex(UserError, 'could not be reached'):
                self.picking.move_ids._action_cancel()

        self.assertTrue(self.waybill.exists(), "nothing is left half done: the change can be made again")


@tagged('post_install', '-at_install')
class TestWaybillUserAccess(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.salesperson = new_test_user(self.env, login='rsw_sales', groups='sales_team.group_sale_salesman')
        self.vehicle = self.env['fleet.vehicle'].create({
            'license_plate': 'AA-123-BB',
            'model_id': self.env['fleet.vehicle']._ensure_rs_placeholder_model().id})

    def test_a_salesperson_can_pick_a_car_plate(self):
        Vehicle = self.env['fleet.vehicle'].with_user(self.salesperson).with_context(rs_plate_only=True)

        found = Vehicle.name_search('AA-123')

        self.assertIn(self.vehicle.id, [vid for vid, _name in found])
        with self.assertRaises(Exception, msg="read only: a salesperson does not edit cars"):
            self.vehicle.with_user(self.salesperson).write({'license_plate': 'XX-000-XX'})

    def test_settings_and_car_plates_menus_are_hidden_from_a_salesperson(self):
        visible = self.env['ir.ui.menu'].with_user(self.salesperson)._visible_menu_ids()

        self.assertNotIn(self.env.ref('rs_waybill.menu_rs_waybill_settings').id, visible)
        self.assertNotIn(self.env.ref('rs_waybill.menu_rs_waybill_driver').id, visible)
        self.assertIn(self.env.ref('rs_waybill.menu_rs_waybill_products').id, visible)
