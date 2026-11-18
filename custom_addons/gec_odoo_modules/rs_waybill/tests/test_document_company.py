"""Records are created in the document's company, not the company switcher's."""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestDocumentCompany(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.company_a = self.env.company
        self.company_b = self.env['res.company'].create({
            'name': 'Company B', 'vat': '405000003', 'street': 'Batumi, Rustaveli 1'})
        self.env.user.company_ids |= self.company_b
        self.env_a = self.env(context=dict(self.env.context,
                                           allowed_company_ids=[self.company_a.id, self.company_b.id]))
        self.warehouse_b = self.env['stock.warehouse'].search([('company_id', '=', self.company_b.id)], limit=1)
        self.product = self.env['product.product'].create({'name': 'Goods', 'is_storable': True})
        self.env['stock.quant'].with_company(self.company_b)._update_available_quantity(
            self.product, self.warehouse_b.lot_stock_id, 10)

    def test_a_b_delivery_makes_its_waybill_in_b(self):
        out_type = self.warehouse_b.out_type_id
        out_type.rs_create_waybill = True
        picking = self.env['stock.picking'].with_company(self.company_b).with_context(
            skip_rs_auto_create=True).create({
                'picking_type_id': out_type.id, 'partner_id': self.buyer.id,
                'location_id': self.warehouse_b.lot_stock_id.id,
                'location_dest_id': self.env.ref('stock.stock_location_customers').id,
                'move_ids': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 4,
                                     'location_id': self.warehouse_b.lot_stock_id.id,
                                     'location_dest_id': self.env.ref('stock.stock_location_customers').id})]})
        picking.action_confirm()
        picking.action_assign()

        waybill = picking.with_env(self.env_a)._rs_try_create_waybill()

        self.assertEqual(waybill.company_id, self.company_b)
        self.assertEqual((waybill.seller_tin, waybill.seller_name),
                         (self.company_b.vat, self.company_b.name))

    def test_a_template_of_a_b_waybill_is_in_b(self):
        waybill = self.make_waybill(company_id=self.company_b.id, rs_internal_id=996001)
        wizard = self.env_a['rs.waybill.template.save.wizard'].create(
            {'waybill_id': waybill.id, 'name': 'B route'})
        with patch.object(type(self.env['rs.waybill.soap.service']), 'save_waybill_template',
                          return_value=77):
            wizard.action_save()
        template = self.env['rs.waybill'].search([('rs_template_id', '=', 77)])
        self.assertEqual(template.company_id, self.company_b)

    def test_the_order_built_from_a_b_waybill_is_in_b(self):
        waybill = self.make_waybill(company_id=self.company_b.id, state='active',
                                    waybill_status='1', rs_internal_id=996002)
        self.add_line(waybill, product_id=self.product.id)

        waybill.with_env(self.env_a)._rs_create_so_and_delivery_from_waybill()

        self.assertEqual(waybill.sales_order_id.company_id, self.company_b)
