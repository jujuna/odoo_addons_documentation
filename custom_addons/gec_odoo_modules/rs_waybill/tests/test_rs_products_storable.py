"""Products created from RS.GE (unknown goods, product list, excise catalog) track their stock."""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestRsProductsStorable(RsWaybillCommon):

    def test_unknown_goods_on_a_synced_waybill(self):
        waybill = self.make_waybill(rs_internal_id=997001)
        waybill._sync_goods_lines([{'ID': '1', 'BAR_CODE': 'RS-NEW-1', 'W_NAME': 'Brand new goods',
                                    'QUANTITY': '3', 'PRICE': '2', 'UNIT_TXT': '', 'VAT_TYPE': '0'}])
        product = waybill.line_ids.product_id
        self.assertEqual(product.name, 'Brand new goods')
        self.assertTrue(product.is_storable)

    def test_rs_product_list_and_excise_catalog(self):
        self.env['rs.excise.code'].create({'rs_id': 99001, 'name': 'Beer (99001) _ ლიტრი _ (1)',
                                           'active_from': '2020-01-01'})
        service = type(self.env['rs.waybill.soap.service'])
        with patch.object(service, 'get_akciz_codes', return_value=[]), \
                patch.object(service, 'get_bar_codes',
                             return_value=[{'CODE': 'RS-LIST-1', 'NAME': 'Listed goods'}]):
            self.env['product.product'].action_update_rs_products()

        listed = self.env['product.product'].search([('barcode', '=', 'RS-LIST-1')])
        excise = self.env['product.product'].search([('rs_excise_id.rs_id', '=', 99001)])
        self.assertTrue(listed.is_storable)
        self.assertTrue(excise.is_storable)
