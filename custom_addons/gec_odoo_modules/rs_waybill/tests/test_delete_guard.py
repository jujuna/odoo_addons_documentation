"""A waybill that is on RS.GE cannot be deleted in Odoo: the user is sent to the button that updates
RS.GE and Odoo together.
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestDeleteGuard(RsWaybillCommon):

    def test_active_waybill_cannot_be_deleted(self):
        waybill = self.make_waybill(state='active', waybill_status='1', rs_internal_id=900001)

        with self.assertRaisesRegex(UserError, 'Cancel'):
            waybill.unlink()

        self.assertTrue(waybill.exists())

    def test_completed_waybill_points_to_adjustment(self):
        waybill = self.make_waybill(state='completed', waybill_status='2', rs_internal_id=900002)

        with self.assertRaisesRegex(UserError, 'Adjustment'):
            waybill.unlink()

    def test_list_delete_refuses_all(self):
        local = self.make_waybill(state='draft')
        on_rs = self.make_waybill(state='completed', waybill_status='2', rs_internal_id=900003)

        with self.assertRaises(UserError):
            (local | on_rs).unlink()

        self.assertTrue(local.exists() and on_rs.exists(), "nothing is deleted")

    def test_local_draft_cancelled_and_template_can_be_deleted(self):
        local = self.make_waybill(state='draft')
        cancelled = self.make_waybill(state='cancelled', waybill_status='-2', rs_internal_id=900004)
        template = self.make_waybill(is_template=True, rs_internal_id=900005)

        (local | cancelled | template).unlink()

        self.assertFalse((local | cancelled | template).exists())

    def test_delete_button_still_works(self):
        waybill = self.make_waybill(state='draft', rs_internal_id=900006)
        service = type(self.env['rs.waybill.soap.service'])

        with patch.object(service, 'delete_waybill', return_value=True), \
                patch.object(self.env.cr, 'commit'):
            waybill.action_delete_waybill()

        self.assertFalse(waybill.exists())


@tagged('post_install', '-at_install')
class TestDeleteOnRs(RsWaybillCommon):
    """Once RS.GE deleted the waybill, Odoo keeps it deleted even if cancelling its delivery fails;
    the delivery is flagged."""

    def setUp(self):
        super().setUp()
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        self.picking = self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'picking_type_id': warehouse.out_type_id.id, 'partner_id': self.buyer.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
        })
        self.waybill = self.make_waybill(state='draft', rs_internal_id=980001, picking_id=self.picking.id)
        self.picking.waybill_id = self.waybill
        service = type(self.env['rs.waybill.soap.service'])
        for patcher in (patch.object(service, 'delete_waybill', return_value=True),
                        patch.object(self.env.cr, 'commit')):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_delete_cancels_the_delivery(self):
        self.waybill.action_delete_waybill()
        self.assertFalse(self.waybill.exists())
        self.assertEqual(self.picking.state, 'cancel')

    def test_a_failing_delivery_cancel_keeps_the_waybill_deleted(self):
        with patch.object(type(self.picking), 'action_cancel', side_effect=UserError("locked")):
            self.waybill.action_delete_waybill()

        self.assertFalse(self.waybill.exists(), "RS.GE deleted it: so does Odoo")
        self.assertNotEqual(self.picking.state, 'cancel')
        self.assertTrue(self.picking.activity_ids, "someone is told to cancel it by hand")
