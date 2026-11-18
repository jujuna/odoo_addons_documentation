"""The invoice wizard invoices a waybill in the unit of the matched SO line: an order of 2 x Pack of 12 delivered
as 24 Units is invoiced as 2 packs, never 24 packs; without an SO line it invoices in the product's unit."""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestInvoiceWizardUnits(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.units = cls.env.ref('uom.product_uom_unit')
        cls.pack12 = cls.env['uom.uom'].create({'name': 'Pack of 12', 'relative_factor': 12,
                                                'relative_uom_id': cls.units.id, 'rs_unit_id': 14})
        cls.water = cls.env['product.product'].create({
            'name': 'Water 0.5L', 'list_price': 2.5, 'invoice_policy': 'order', 'taxes_id': [(5, 0, 0)],
            'uom_ids': [(6, 0, cls.pack12.ids)]})
        cls.buyer = cls.env['res.partner'].create({'name': 'Test Buyer LLC', 'vat': '400000001'})

    def _wizard(self, waybill_line, standalone=False):
        waybill = waybill_line.rs_waybill_id
        return self.env['rs.invoice.from.waybill.wizard'].create({
            'partner_id': self.buyer.id, 'waybill_ids': [(6, 0, waybill.ids)], 'is_standalone': standalone,
            'line_ids': [(0, 0, {'waybill_id': waybill.id, 'waybill_line_id': waybill_line.id,
                                 'product_id': self.water.id})],
        })

    def _waybill_line(self, quantity, unit, order=None):
        waybill = self.env['rs.waybill'].with_context(rs_skip_resolve=True).create({
            'waybill_direction': 'seller', 'waybill_type': '2', 'buyer_id': self.buyer.id,
            'buyer_tin': self.buyer.vat, 'sales_order_id': order.id if order else False})
        return self.env['rs.waybill.line'].create({
            'rs_waybill_id': waybill.id, 'product_id': self.water.id, 'quantity': quantity, 'uom_id': unit.id})

    def _order(self):
        order = self.env['sale.order'].create({
            'partner_id': self.buyer.id,
            'order_line': [(0, 0, {'product_id': self.water.id, 'product_uom_qty': 2,
                                   'product_uom_id': self.pack12.id, 'price_unit': 30.0})]})
        order.with_context(skip_rs_auto_create=True).action_confirm()
        return order

    def test_packs_are_invoiced_as_packs(self):
        order = self._order()
        line = self._wizard(self._waybill_line(2, self.pack12, order)).line_ids
        self.assertEqual((line.sale_line_id, line.quantity), (order.order_line, 2))
        vals = line.wizard_id._prepare_line_vals(line)
        self.assertEqual((vals['quantity'], vals['product_uom_id']), (2, self.pack12.id))

    def test_units_on_the_waybill_are_converted_to_the_order_unit(self):
        order = self._order()
        line = self._wizard(self._waybill_line(18, self.units, order)).line_ids
        self.assertEqual(line.quantity, 1.5, "18 Units of a Pack of 12 order line")
        self.assertFalse(line.wizard_id.has_overdelivery)

    def test_without_an_order_the_products_unit(self):
        wizard = self._wizard(self._waybill_line(2, self.pack12), standalone=True)
        self.assertEqual(wizard.line_ids.quantity, 24)
        [(_, _, vals)] = wizard._aggregate_invoice_lines()
        self.assertEqual((vals['quantity'], vals['product_uom_id'], vals['price_unit']), (24, self.units.id, 2.5))
