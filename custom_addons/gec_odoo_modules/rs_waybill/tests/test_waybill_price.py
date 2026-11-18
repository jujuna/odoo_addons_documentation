"""Waybill price (#28): the RS.GE unit price contains the discount and the VAT.

Before, the waybill took the order line's price as typed: a 10% discount was ignored and a
VAT added on top of the price was missing.
"""

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestWaybillPrice(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.goods = self.env['product.product'].create(
            {'name': 'Juice', 'is_storable': True, 'list_price': 50.0, 'taxes_id': [(5, 0, 0)]})

    def _tax(self, included=False):
        return self.env['account.tax'].create({
            'name': 'VAT 18%% %s' % ('incl' if included else 'excl'),
            'amount': 18.0, 'amount_type': 'percent', 'type_tax_use': 'sale',
            'price_include_override': 'tax_included' if included else 'tax_excluded',
        })

    def _price(self, price_unit, discount=0.0, taxes=None):
        order = self.env['sale.order'].create({
            'partner_id': self.buyer.id,
            'order_line': [(0, 0, {'product_id': self.goods.id, 'product_uom_qty': 2,
                                   'price_unit': price_unit, 'discount': discount,
                                   'tax_ids': [(6, 0, taxes.ids if taxes else [])]})],
        })
        order.with_context(skip_rs_auto_create=True).action_confirm()
        move = order.picking_ids.move_ids
        return move.picking_id._rs_line_vals_from_move(move, 2, 1)['unit_price']

    def test_discount_and_vat_on_top(self):
        self.assertAlmostEqual(self._price(100, discount=10, taxes=self._tax()), 106.20)

    def test_vat_already_in_the_price(self):
        self.assertAlmostEqual(self._price(118, taxes=self._tax(included=True)), 118.0)

    def test_discount_with_vat_in_the_price(self):
        self.assertAlmostEqual(self._price(118, discount=10, taxes=self._tax(included=True)), 106.20)

    def test_no_tax_keeps_the_discounted_price(self):
        self.assertAlmostEqual(self._price(100, discount=10), 90.0)

    def test_without_an_order_the_sales_price_with_its_vat(self):
        self.goods.taxes_id = self._tax()
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        picking = self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'picking_type_id': warehouse.out_type_id.id, 'partner_id': self.buyer.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'move_ids': [(0, 0, {'product_id': self.goods.id, 'product_uom_qty': 1,
                                 'location_id': warehouse.lot_stock_id.id,
                                 'location_dest_id': self.env.ref('stock.stock_location_customers').id})],
        })

        self.assertAlmostEqual(picking._rs_line_vals_from_move(picking.move_ids, 1, 1)['unit_price'], 59.0)

    # ── currency: RS.GE takes GEL ──

    def _rates(self, **rates):
        """Rates of today against the company currency, e.g. GEL=2.7 (2.7 GEL per 1 unit)."""
        for code, rate in rates.items():
            currency = self.env.ref('base.%s' % code)
            currency.active = True
            if currency != self.env.company.currency_id:
                self.env['res.currency.rate'].create({
                    'currency_id': currency.id, 'rate': rate, 'company_id': self.env.company.id})
        return [self.env.ref('base.%s' % code) for code in rates]

    def test_an_order_in_another_currency_is_sent_in_gel(self):
        gel, eur = self._rates(GEL=2.7, EUR=0.9)
        pricelist = self.env['product.pricelist'].create({'name': 'EUR', 'currency_id': eur.id})
        order = self.env['sale.order'].create({
            'partner_id': self.buyer.id, 'pricelist_id': pricelist.id,
            'order_line': [(0, 0, {'product_id': self.goods.id, 'product_uom_qty': 1,
                                   'price_unit': 100, 'tax_ids': [(5, 0, 0)]})],
        })
        order.with_context(skip_rs_auto_create=True).action_confirm()
        move = order.picking_ids.move_ids

        price = move.picking_id._rs_line_vals_from_move(move, 1, 1)['unit_price']

        self.assertAlmostEqual(price, 300.0, msg="100 EUR = 111.11 base = 300 GEL")

    # ── the other way: an order line built from a waybill price ──

    def _rs_waybill(self, price, **vals):
        waybill = self.make_waybill(state='active', waybill_status='1', rs_internal_id=993001,
                                    activation_date='2026-10-26 10:00:00', **vals)
        self.add_line(waybill, quantity=1, unit_price=price, product_id=self.goods.id,
                      name=self.goods.name)
        return waybill

    def test_sales_order_from_a_waybill_takes_the_vat_out(self):
        self.goods.taxes_id = self._tax()
        waybill = self._rs_waybill(118)

        waybill._rs_create_so_and_delivery_from_waybill()

        line = waybill.sales_order_id.order_line
        self.assertAlmostEqual(line.price_unit, 100.0)
        self.assertAlmostEqual(line.price_total, 118.0, msg="the order says what the waybill says")

    def test_sales_order_with_vat_in_the_price_keeps_it(self):
        self.goods.taxes_id = self._tax(included=True)
        waybill = self._rs_waybill(118)

        waybill._rs_create_so_and_delivery_from_waybill()

        self.assertAlmostEqual(waybill.sales_order_id.order_line.price_unit, 118.0)

    def test_purchase_order_from_a_vendor_waybill_takes_the_vat_out(self):
        tax = self._tax()
        tax.type_tax_use = 'purchase'
        self.goods.supplier_taxes_id = tax
        vendor = self.env['res.partner'].create({'name': 'Vendor LLC', 'vat': '400000077'})
        waybill = self._rs_waybill(118, waybill_direction='buyer', seller_tin=vendor.vat)

        order = waybill._rs_create_own_purchase(vendor)

        self.assertAlmostEqual(order.order_line.price_unit, 100.0)
        self.assertAlmostEqual(order.order_line.price_total, 118.0)

    def test_a_waybill_price_in_gel_becomes_the_order_currency(self):
        gel, = self._rates(GEL=2.7)
        waybill = self._rs_waybill(270)

        waybill._rs_create_so_and_delivery_from_waybill()

        self.assertAlmostEqual(waybill.sales_order_id.order_line.price_unit, 100.0,
                               msg="270 GEL at 2.7 = 100 in the order's currency")
