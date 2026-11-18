"""Customer pickup: waybill type 3 (Without Transport) and its Operation Type."""

from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestCustomerPickup(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1)
        self.delivery_type = self.warehouse.out_type_id
        self.delivery_type.write({'rs_create_waybill': True, 'rs_waybill_type': '2'})
        self.pickup_type = self.warehouse._rs_pickup_type()
        self.picking = self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'picking_type_id': self.delivery_type.id, 'partner_id': self.buyer.id,
            'location_id': self.warehouse.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
        })

    def _waybill(self, **vals):
        vals = {'state': 'draft', 'waybill_type': '2', 'picking_id': self.picking.id,
                'driver_tin': '01001000001', 'car_number': 'AA-001-AA', **vals}
        waybill = self.make_waybill(**vals)
        self.picking.waybill_id = waybill
        return waybill

    def test_every_warehouse_has_a_customer_pickup_type(self):
        pickup = self.pickup_type
        self.assertEqual((pickup.code, pickup.rs_waybill_type, pickup.rs_create_waybill),
                         ('outgoing', '3', True))
        self.assertEqual(pickup.default_location_src_id, self.warehouse.lot_stock_id)

    def test_a_new_warehouse_gets_one_too(self):
        new = self.env['stock.warehouse'].create({'name': 'Batumi', 'code': 'BTM'})
        self.assertEqual(new._rs_pickup_type().rs_waybill_type, '3')

    def test_waybill_to_without_transport_moves_the_delivery_to_pickup(self):
        waybill = self._waybill()

        waybill.waybill_type = '3'

        self.assertEqual(self.picking.picking_type_id, self.pickup_type)
        self.assertFalse(waybill.driver_tin or waybill.car_number, "no transport on type 3")

    def test_back_to_with_transport_moves_it_back(self):
        waybill = self._waybill(waybill_type='3', driver_tin=False, car_number=False)
        self.picking.with_context(rs_from_waybill=True).picking_type_id = self.pickup_type

        waybill.waybill_type = '2'

        self.assertEqual(self.picking.picking_type_id, self.delivery_type)

    def test_delivery_to_pickup_makes_the_waybill_without_transport(self):
        waybill = self._waybill()

        self.picking.picking_type_id = self.pickup_type

        self.assertEqual(waybill.waybill_type, '3')

    def test_saved_draft_waits_for_save(self):
        waybill = self._waybill(rs_internal_id=970001)
        service = type(self.env['rs.waybill.soap.service'])
        with patch.object(service, 'save_waybill') as save:
            waybill.waybill_type = '3'
        save.assert_not_called()
        self.assertTrue(waybill.rs_needs_resave)

    def test_a_sales_waybill_cannot_become_internal_distribution_or_return(self):
        order = self.env['sale.order'].create({'partner_id': self.buyer.id})
        waybill = self._waybill(sales_order_id=order.id)
        for other in ('1', '4', '5'):
            with self.subTest(type=other), self.assertRaises(UserError):
                waybill.waybill_type = other

    def test_documents_of_a_type_3_waybill_use_customer_pickup(self):
        waybill = self.make_waybill(state='active', waybill_status='1', waybill_type='3',
                                    rs_internal_id=970002)
        self.add_line(waybill)

        waybill._rs_create_so_and_delivery_from_waybill()

        self.assertEqual(waybill.picking_id.picking_type_id.rs_waybill_type, '3')

    def test_active_waybill_keeps_the_delivery_type(self):
        self._waybill(state='active', waybill_status='1', rs_internal_id=970003)
        with self.assertRaises(UserError):
            self.picking.picking_type_id = self.pickup_type

    def _readonly(self, model, field):
        arch = etree.fromstring(self.env[model].get_view(view_type='form')['arch'])
        nodes = arch.xpath("//field[@name='%s'][not(ancestor::list)]" % field)
        self.assertTrue(nodes, field)
        return ' '.join(n.get('readonly') or '' for n in nodes)

    def test_type_is_editable_only_on_drafts(self):
        self.assertEqual(self._readonly('rs.waybill', 'waybill_type'), "state != 'draft'")

    def test_adjustment_offers_only_what_rs_allows(self):
        for field in ('transport_type', 'end_address', 'driver_partner_id', 'vehicle_id',
                      'trailer', 'transport_cost', 'transport_cost_payer', 'transporter_tin'):
            with self.subTest(field=field):
                self.assertIn("edit_mode", self._readonly('rs.waybill', field))
        for field in ('start_address', 'buyer_id', 'reception_info', 'receiver_info', 'comment'):
            with self.subTest(field=field):
                self.assertNotIn("edit_mode", self._readonly('rs.waybill', field))

    def test_delivery_type_field_locked_on_active_waybills(self):
        self.assertIn('rs_waybill_state', self._readonly('stock.picking', 'picking_type_id'))
