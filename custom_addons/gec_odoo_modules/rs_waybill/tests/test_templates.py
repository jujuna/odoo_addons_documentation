"""Templates keep the goods, driver and car; a waybill made from one starts with them. A template never moves stock."""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestTemplates(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.source = self.make_waybill(transport_cost=40.0, comment='Weekly order')
        self.add_line(self.source, quantity=3, unit_price=12.5, bar_code='W-1', vat_type='0')
        self.add_line(self.source, quantity=1, unit_price=99, name='Second', bar_code='W-2', vat_type='2')
        self.service = type(self.env['rs.waybill.soap.service'])

    def _save_template(self, name='Nikora weekly'):
        wizard = self.env['rs.waybill.template.save.wizard'].create({'waybill_id': self.source.id, 'name': name})
        with patch.object(self.service, 'save_waybill_template', return_value=777) as save:
            wizard.action_save()
        save.assert_called_once()
        return self.env['rs.waybill'].search([('is_template', '=', True), ('rs_template_id', '=', 777)])

    def test_saved_template_keeps_goods_driver_and_car(self):
        template = self._save_template()

        self.assertEqual(len(template), 1)
        self.assertEqual(template.template_name, 'Nikora weekly')
        self.assertEqual((template.driver_tin, template.car_number, template.transport_cost, template.comment),
                         ('01001000001', 'AA-001-AA', 40.0, 'Weekly order'))
        self.assertEqual(template.line_ids.mapped('bar_code'), ['W-1', 'W-2'])
        self.assertEqual(template.line_ids.mapped('quantity'), [3, 1])
        self.assertEqual(template.line_ids.mapped('vat_type'), ['0', '2'])
        self.assertEqual(self.source.line_ids.mapped('bar_code'), ['W-1', 'W-2'], "the source keeps its lines")

    def test_saving_a_template_moves_no_stock(self):
        orders, pickings = self.env['sale.order'].search_count([]), self.env['stock.picking'].search_count([])

        template = self._save_template()

        self.assertFalse(template.picking_id or template.sales_order_id)
        self.assertFalse(template.line_ids.stock_move_id)
        self.assertEqual(self.env['sale.order'].search_count([]), orders)
        self.assertEqual(self.env['stock.picking'].search_count([]), pickings)

    def test_waybill_from_template_starts_with_the_goods(self):
        template = self._save_template()
        picker = self.env['rs.waybill.template.picker.wizard'].create({'template_id': template.id})

        action = picker.action_load()
        new = self.env['rs.waybill'].browse(action['res_id'])

        self.assertFalse(new.is_template)
        self.assertEqual((new.state, new.rs_internal_id, new.rs_waybill_number), ('draft', 0, False))
        self.assertEqual(new.line_ids.mapped('bar_code'), ['W-1', 'W-2'])
        self.assertEqual(new.line_ids.mapped('unit_price'), [12.5, 99])
        self.assertEqual(new.car_number, 'AA-001-AA')
        self.assertEqual(len(template.line_ids), 2, "the template keeps its own lines")
        self.assertFalse(new.line_ids & template.line_ids)
        self.assertFalse(new.picking_id, "no delivery until the new waybill is saved to RS.GE")
