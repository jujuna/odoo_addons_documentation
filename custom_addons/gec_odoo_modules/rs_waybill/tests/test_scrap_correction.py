"""Lowered goods that came back to several places (two lots, two locations) can be scrapped in one go."""

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestScrapCorrection(RsWaybillCommon):

    def test_goods_from_two_places_are_all_scrapped(self):
        stock = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1).lot_stock_id
        Location = self.env['stock.location']
        shelf_a = Location.create({'name': 'Shelf A', 'location_id': stock.id})
        shelf_b = Location.create({'name': 'Shelf B', 'location_id': stock.id})
        milk = self.env['product.product'].create({'name': 'Milk', 'is_storable': True})
        Quant = self.env['stock.quant']
        Quant._update_available_quantity(milk, shelf_a, 4)
        Quant._update_available_quantity(milk, shelf_b, 6)
        waybill = self.make_waybill(state='completed', waybill_status='2', rs_internal_id=997001)

        scraps = waybill._rs_scrap_correction(milk, [[shelf_a.id, False, 4], [shelf_b.id, False, 6]])

        self.assertEqual(scraps.mapped('state'), ['done', 'done'])
        self.assertEqual(Quant._get_available_quantity(milk, shelf_a), 0)
        self.assertEqual(Quant._get_available_quantity(milk, shelf_b), 0)
        self.assertEqual(sum(scraps.mapped('quantity')), 10)
        self.assertEqual(scraps.location_dest_id, self.env.company.scrap_location_id)
