"""Product mappings belong to one company, and remember the unit picked for the seller's RS unit."""

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestMappingPerCompany(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.company_a = self.env.company
        self.company_b = self.env['res.company'].create({'name': 'Company B', 'vat': '405000002'})
        self.vendor = self.env['res.partner'].create({'name': 'Vendor X', 'vat': '404111111'})
        self.flour_a = self.env['product.product'].create({'name': 'Flour A', 'company_id': self.company_a.id})
        self.flour_b = self.env['product.product'].create({'name': 'Flour B', 'company_id': self.company_b.id})
        self.Ref = self.env['rs.product.external.ref']

    def _vendor_waybill(self, company):
        return self.make_waybill(waybill_direction='buyer', company_id=company.id,
                                 seller_tin=self.vendor.vat, seller_name=self.vendor.name)

    def _map(self, company, product):
        return self.Ref.create({'company_id': company.id, 'seller_partner_id': self.vendor.id,
                                'external_barcode': 'X-FLOUR', 'product_id': product.product_tmpl_id.id})

    def test_another_companys_mapping_is_not_used(self):
        self._map(self.company_a, self.flour_a)
        waybill_b = self._vendor_waybill(self.company_b)
        self.assertFalse(waybill_b._resolve_product('X-FLOUR', self.vendor))

    def test_each_company_resolves_with_its_own(self):
        self._map(self.company_a, self.flour_a)
        self._map(self.company_b, self.flour_b)
        self.assertEqual(self._vendor_waybill(self.company_a)._resolve_product('X-FLOUR', self.vendor),
                         self.flour_a)
        self.assertEqual(self._vendor_waybill(self.company_b)._resolve_product('X-FLOUR', self.vendor),
                         self.flour_b)

    def test_resolve_now_saves_the_mapping_in_the_waybills_company(self):
        self._map(self.company_a, self.flour_a)
        waybill_b = self._vendor_waybill(self.company_b)
        line = self.add_line(waybill_b, product_id=self.flour_b.id, external_barcode='X-FLOUR',
                             external_name='Flour 1kg')

        line._save_external_ref()

        mappings = self.Ref.search([('external_barcode', '=', 'X-FLOUR')])
        self.assertEqual(mappings.mapped('company_id'), self.company_a | self.company_b)
        self.assertEqual(mappings.filtered(lambda m: m.company_id == self.company_a).product_id,
                         self.flour_a.product_tmpl_id, "A's mapping is untouched")

    def test_a_vendor_contact_of_another_company_is_not_used(self):
        self.vendor.company_id = self.company_a
        self.assertFalse(self._vendor_waybill(self.company_b)._get_seller_partner())

    def test_the_unit_picked_once_is_reused(self):
        units = self.env.ref('uom.product_uom_unit')
        pack6, pack24 = (self.env['uom.uom'].create({'name': 'Pack of %d' % n, 'relative_factor': n,
                                                     'relative_uom_id': units.id, 'rs_unit_id': 14})
                         for n in (6, 24))
        self.flour_a.uom_ids = pack6 | pack24
        self.env.company.rs_mapping_cutoff_date = '2000-01-01'
        good = {'ID': '1', 'BAR_CODE': 'X-FLOUR', 'W_NAME': 'ფქვილი', 'QUANTITY': '2', 'PRICE': '40',
                'UNIT_ID': '14', 'UNIT_TXT': 'შეკვრა', 'VAT_TYPE': '0'}

        first = self._vendor_waybill(self.company_a)
        first._sync_goods_lines([good])
        line = first.line_ids
        self.assertTrue(line.unresolved, "no mapping yet")
        line.write({'product_id': self.flour_a.id, 'uom_id': pack24.id})
        ref = self.Ref.search([('external_barcode', '=', 'X-FLOUR')])
        self.assertEqual((ref.uom_id, ref.rs_unit_code), (pack24, 14))

        second = self._vendor_waybill(self.company_a)
        second._sync_goods_lines([good])
        self.assertEqual((second.line_ids.product_id, second.line_ids.uom_id, second.line_ids.uom_review),
                         (self.flour_a, pack24, False), "Pack of 6 or 24: answered last time")
