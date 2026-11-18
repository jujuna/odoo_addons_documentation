"""Changing a delivery's Operation Type never calls RS.GE: the draft waybill keeps its addresses and
waits for its own Save.
"""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestOperationTypeChange(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        self.with_transport = warehouse.out_type_id
        self.with_transport.write({'rs_create_waybill': True, 'rs_waybill_type': '2'})
        self.without_transport = self.with_transport.copy(
            {'name': 'Delivery without transport', 'sequence_code': 'OUT3', 'rs_waybill_type': '3'})
        stock, customers = warehouse.lot_stock_id, self.env.ref('stock.stock_location_customers')
        self.picking = self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'picking_type_id': self.with_transport.id, 'partner_id': self.buyer.id,
            'location_id': stock.id, 'location_dest_id': customers.id,
        })
        self.service = type(self.env['rs.waybill.soap.service'])

    def _draft(self, rs_id=False):
        waybill = self.make_waybill(state='draft', waybill_type='2', rs_internal_id=rs_id,
                                    picking_id=self.picking.id,
                                    start_address='Warehouse, Tbilisi, Kakheti Hwy 5',
                                    end_address='Customer depot, Rustavi 12')
        self.picking.waybill_id = waybill
        return waybill

    def test_saved_draft_is_updated_in_odoo_only(self):
        waybill = self._draft(rs_id=960001)

        with patch.object(self.service, 'save_waybill') as save:
            self.picking.picking_type_id = self.without_transport

        save.assert_not_called()
        self.assertEqual(waybill.waybill_type, '3')
        self.assertTrue(waybill.rs_needs_resave, "the waybill says it is not yet on RS.GE")

    def test_addresses_the_user_set_are_kept(self):
        waybill = self._draft(rs_id=960002)

        with patch.object(self.service, 'save_waybill'):
            self.picking.picking_type_id = self.without_transport

        self.assertEqual(waybill.start_address, 'Warehouse, Tbilisi, Kakheti Hwy 5')
        self.assertEqual(waybill.end_address, 'Customer depot, Rustavi 12')

    def test_save_on_the_waybill_clears_the_note(self):
        waybill = self._draft(rs_id=960003)
        with patch.object(self.service, 'save_waybill'):
            self.picking.picking_type_id = self.without_transport

        with patch.object(type(waybill), '_validate_before_save'), \
                patch.object(self.service, 'save_waybill',
                             return_value={'id': 960003, 'waybill_number': ''}), \
                patch.object(self.env.cr, 'commit'):
            waybill.action_save_to_rs()

        self.assertFalse(waybill.rs_needs_resave)

    def test_draft_never_sent_needs_no_note(self):
        waybill = self._draft()

        self.picking.picking_type_id = self.without_transport

        self.assertEqual(waybill.waybill_type, '3')
        self.assertFalse(waybill.rs_needs_resave)
