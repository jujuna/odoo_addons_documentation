"""VAT_TYPE declared: 0 = standard 18%, 1 = exempt WITH credit (Art 172), 2 = exempt WITHOUT credit (Arts 170-171).
The rate cannot tell 1 from 2, so the type comes from each tax's Tax Category Code."""

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestWaybillVatType(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        Tax = cls.env['account.tax']
        cls.tax_standard = Tax.create({
            'name': 'RS Test VAT 18%', 'amount': 18.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'ubl_cii_tax_category_code': 'S',
        })
        cls.tax_export = Tax.create({
            'name': 'RS Test Export 0%', 'amount': 0.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'ubl_cii_tax_category_code': 'Z',
        })
        cls.tax_export_g = Tax.create({
            'name': 'RS Test Free Export 0%', 'amount': 0.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'ubl_cii_tax_category_code': 'G',
        })
        cls.tax_exempt = Tax.create({
            'name': 'RS Test Exempt', 'amount': 0.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'ubl_cii_tax_category_code': 'E',
        })
        cls.tax_out_of_scope = Tax.create({
            'name': 'RS Test Out of Scope', 'amount': 0.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'ubl_cii_tax_category_code': 'O',
        })
        cls.tax_uncoded = Tax.create({
            'name': 'RS Test No Code 0%', 'amount': 0.0, 'amount_type': 'percent',
            'type_tax_use': 'sale',
        })

    def setUp(self):
        super().setUp()
        self._seq = 0

    def _picking(self):
        self._seq += 1
        return self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'name': 'RSVAT/%s' % self._seq,
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.warehouse.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'company_id': self.env.company.id,
        })

    def _move_with_taxes(self, picking, taxes=None):
        """A move linked to a sale order line carrying the given taxes."""
        order = self.env['sale.order'].with_context(skip_rs_auto_create=True).create({
            'partner_id': self.buyer.id,
        })
        line = self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.product.id,
            'product_uom_qty': 5.0,
        })
        line.tax_ids = [(6, 0, taxes.ids)] if taxes else [(5, 0, 0)]
        move = self.env['stock.move'].with_context(skip_rs_auto_create=True).create({
            'product_id': self.product.id,
            'product_uom_qty': 5.0,
            'uom_id': self.product.uom_id.id,
            'picking_id': picking.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'company_id': self.env.company.id,
            'sale_line_id': line.id,
        })
        return move

    def test_a_tax_without_a_code_declares_standard(self):
        """A tax without a Tax Category Code is not VAT, so it never changes the type."""
        picking = self._picking()
        move = self._move_with_taxes(picking, self.tax_uncoded)
        self.assertEqual(picking._rs_vat_type_for_move(move), '0')

    def test_standard_tax_declares_standard(self):
        picking = self._picking()
        move = self._move_with_taxes(picking, self.tax_standard)
        self.assertEqual(picking._rs_vat_type_for_move(move), '0')

    def test_export_tax_declares_zero_rated(self):
        """An export waybill declares zero-rated, not standard 18%."""
        picking = self._picking()
        move = self._move_with_taxes(picking, self.tax_export)
        self.assertEqual(picking._rs_vat_type_for_move(move), '1',
                         "an export was declared to RS.GE as standard-rated")

    def test_free_export_tax_declares_zero_rated(self):
        picking = self._picking()
        move = self._move_with_taxes(picking, self.tax_export_g)
        self.assertEqual(picking._rs_vat_type_for_move(move), '1')

    def test_exempt_tax_declares_exempt(self):
        picking = self._picking()
        move = self._move_with_taxes(picking, self.tax_exempt)
        self.assertEqual(picking._rs_vat_type_for_move(move), '2')

    def test_out_of_scope_tax_declares_exempt(self):
        picking = self._picking()
        move = self._move_with_taxes(picking, self.tax_out_of_scope)
        self.assertEqual(picking._rs_vat_type_for_move(move), '2')

    def test_zero_rated_and_exempt_are_not_conflated(self):
        """Both charge 0%; only the Tax Category Code tells them apart."""
        picking = self._picking()
        self.assertEqual(self.tax_export.amount, self.tax_exempt.amount)
        self.assertNotEqual(
            picking._rs_vat_type_for_move(self._move_with_taxes(picking, self.tax_export)),
            picking._rs_vat_type_for_move(self._move_with_taxes(picking, self.tax_exempt)))

    def test_a_line_with_no_tax_declares_standard(self):
        picking = self._picking()
        move = self._move_with_taxes(picking, taxes=None)
        self.assertEqual(picking._rs_vat_type_for_move(move), '0')

    def test_a_move_with_no_order_line_declares_standard(self):
        """A manually built waybill has nothing to read the tax from."""
        picking = self._picking()
        move = self.env['stock.move'].with_context(skip_rs_auto_create=True).create({
            'product_id': self.product.id,
            'product_uom_qty': 5.0,
            'uom_id': self.product.uom_id.id,
            'picking_id': picking.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'company_id': self.env.company.id,
        })
        self.assertEqual(picking._rs_vat_type_for_move(move), '0')

    def test_conflicting_taxes_declare_the_first_type(self):
        """Zero-rated and exempt on one line contradict; the first of 0, 1, 2 wins (here 1)."""
        picking = self._picking()
        move = self._move_with_taxes(picking, self.tax_export | self.tax_exempt)
        self.assertEqual(picking._rs_vat_type_for_move(move), '1')

    def test_standard_wins_over_zero_rated(self):
        picking = self._picking()
        move = self._move_with_taxes(picking, self.tax_export | self.tax_standard)
        self.assertEqual(picking._rs_vat_type_for_move(move), '0')

    def test_an_uncoded_tax_alongside_a_coded_one_is_ignored(self):
        """A non-VAT tax must not veto the real type."""
        picking = self._picking()
        move = self._move_with_taxes(picking, self.tax_uncoded | self.tax_exempt)
        self.assertEqual(picking._rs_vat_type_for_move(move), '2')

    def test_the_built_line_carries_the_type(self):
        picking = self._picking()
        move = self._move_with_taxes(picking, self.tax_export)
        move.quantity = 5.0
        lines = picking._rs_build_waybill_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0][2]['vat_type'], '1')
