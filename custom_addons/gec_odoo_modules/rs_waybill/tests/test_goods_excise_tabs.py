"""The Goods and Excise tabs each show only their own lines, split by the product's Excise flag."""

from lxml import etree

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestGoodsExciseTabs(RsWaybillCommon):

    def test_each_tab_holds_only_its_lines(self):
        code = self.env['rs.excise.code'].create({'rs_id': 990001, 'name': 'Wine',
                                                  'active_from': '2020-01-01'})
        wine = self.env['product.product'].create({'name': 'Wine', 'is_excise': True,
                                                   'rs_excise_id': code.id})
        waybill = self.make_waybill(state='draft')
        milk_line = self.add_line(waybill, quantity=10)
        wine_line = self.add_line(waybill, quantity=5, product_id=wine.id, name='Wine')

        self.assertEqual(waybill.goods_line_ids, milk_line)
        self.assertEqual(waybill.excise_line_ids, wine_line)
        self.assertEqual(waybill.line_ids, milk_line | wine_line, "RS.GE still gets both")

    def test_the_tabs_use_the_filtered_fields(self):
        arch = self.env['rs.waybill'].get_views([(False, 'form')])['views']['form']['arch']
        tree = etree.fromstring(arch)
        self.assertTrue(tree.xpath("//page[@name='goods_normal']//field[@name='goods_line_ids']"))
        self.assertTrue(tree.xpath("//page[@name='goods_excise']//field[@name='excise_line_ids']"))
