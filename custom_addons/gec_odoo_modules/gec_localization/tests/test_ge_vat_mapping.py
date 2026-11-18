from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestGeVatMapping(AccountTestInvoicingCommon):
    """l10n_ge's tax data as corrected by gec_localization: no wrong "Replaces" links, domestic sale
    taxes for buyers without a Tax ID, import-VAT-only taxes price-included."""

    @classmethod
    @AccountTestInvoicingCommon.setup_country('ge')
    def setUpClass(cls):
        super().setUpClass()
        cls.Template = cls.env['account.chart.template']
        ref = cls.Template.ref
        cls.tax_18 = ref('ge_vat_sale_18')
        cls.purchase_18 = ref('ge_vat_purchase_18')
        cls.tax_rcs = ref('ge_rcvat_18_ser')
        cls.tax_import = ref('ge_import_duty_18')
        cls.fixed_assets = ref('ge_tax_p_vat_18_fixed_assets')
        cls.fp_vat = ref('ge_fiscal_position_vat')
        cls.fp_nonvat = ref('ge_fiscal_position_nonvat')
        cls.fp_domestic = ref('ge_fiscal_position_domestic')
        cls.fp_foreign = ref('ge_fiscal_position_foreign')
        cls.product = cls._create_product(
            name='GE product', list_price=1000.0,
            taxes_id=cls.tax_18, supplier_taxes_id=cls.purchase_18,
        )
        Partner = cls.env['res.partner']
        georgia = cls.env.ref('base.ge')
        cls.customer_vat = Partner.create({'name': 'GE with Tax ID', 'country_id': georgia.id, 'vat': '204567890'})
        cls.customer_nonvat = Partner.create({'name': 'GE without Tax ID', 'country_id': georgia.id})
        cls.customer_individual = Partner.create({
            'name': 'GE individual', 'country_id': georgia.id,
            'property_account_position_id': cls.fp_domestic.id,
        })
        cls.vendor_foreign = Partner.create({'name': 'TR vendor', 'country_id': cls.env.ref('base.tr').id})
        cls.vendor_foreign_rcs = Partner.create({
            'name': 'TR vendor with default', 'country_id': cls.env.ref('base.tr').id,
            'property_purchase_tax_id': cls.tax_rcs.id,
        })

    def _bill(self, partner, price_unit=1000.0, taxes=None, post=False):
        return self._create_invoice(
            move_type='in_invoice', partner_id=partner,
            invoice_line_ids=[self._prepare_invoice_line(
                product_id=self.product, price_unit=price_unit, tax_ids=taxes)],
            post=post,
        )

    def _invoice(self, partner):
        return self._create_invoice(
            move_type='out_invoice', partner_id=partner,
            invoice_line_ids=[self._prepare_invoice_line(product_id=self.product, price_unit=1000.0)],
        )

    def test_sale_to_customer_with_tax_id(self):
        invoice = self._invoice(self.customer_vat)
        self.assertEqual(invoice.fiscal_position_id, self.fp_vat)
        self.assertEqual(invoice.invoice_line_ids.tax_ids, self.tax_18)
        self.assertEqual(invoice.amount_tax, 180.0)
        self.assertEqual(invoice.amount_total, 1180.0)

    def test_sale_to_customer_without_tax_id(self):
        for partner, position in (
            (self.customer_nonvat, self.fp_nonvat),
            (self.customer_individual, self.fp_domestic),
        ):
            invoice = self._invoice(partner)
            self.assertEqual(invoice.fiscal_position_id, position)
            self.assertEqual(invoice.invoice_line_ids.tax_ids, self.tax_18)
            self.assertEqual(invoice.amount_tax, 180.0)

    def test_bill_from_foreign_vendor(self):
        bill = self._bill(self.vendor_foreign, taxes=None)
        self.assertEqual(bill.fiscal_position_id, self.fp_foreign)
        self.assertFalse(bill.invoice_line_ids.tax_ids)

        bill = self._bill(self.vendor_foreign_rcs)
        self.assertEqual(bill.fiscal_position_id, self.fp_foreign)
        self.assertEqual(bill.invoice_line_ids.tax_ids, self.tax_rcs)
        self.assertEqual(bill.amount_total, 1000.0)

    def test_import_vat_bill_is_price_included(self):
        bill = self._bill(self.vendor_foreign, price_unit=180.0, taxes=self.tax_import, post=True)
        self.assertEqual(bill.amount_untaxed, 0.0)
        self.assertEqual(bill.amount_tax, 180.0)
        self.assertEqual(bill.amount_total, 180.0)

    def test_new_accounts(self):
        expected = {
            'gec_account_334011': ('334011', 'asset_current'),
            'gec_account_710700': ('710700', 'expense_direct_cost'),
            'gec_account_731000': ('731000', 'expense'),
            'gec_account_740430': ('740430', 'expense'),
        }
        for xmlid, (code, account_type) in expected.items():
            with self.subTest(xmlid=xmlid):
                account = self.Template.ref(xmlid)
                self.assertEqual((account.code, account.account_type), (code, account_type))

    def test_fixed_assets_tax_setup(self):
        self.assertEqual(self.fixed_assets.type_tax_use, 'purchase')
        self.assertEqual(self.fixed_assets.amount, 18.0)
        self.assertEqual(self.fixed_assets.ubl_cii_tax_category_code, 'S')
        self.assertEqual(self.fixed_assets.fiscal_position_ids, self.fp_vat)

    def test_fixed_assets_bill_posts_input_vat(self):
        bill = self._bill(self.customer_vat, taxes=self.fixed_assets, post=True)
        tax_line = bill.line_ids.filtered('tax_line_id')
        input_vat = self.Template.ref('gec_account_334011')
        self.assertRecordValues(tax_line, [{'account_id': input_vat.id, 'balance': 180.0}])
        self.assertEqual(tax_line.tax_tag_ids.mapped('name'), ['24(T)'])
        self.assertEqual(bill.invoice_line_ids.tax_tag_ids.mapped('name'), ['24(B)'])

    def test_fixed_assets_tax_is_removed_for_non_georgia(self):
        self.assertEqual(self.fp_vat.map_tax(self.fixed_assets), self.fixed_assets)
        self.assertFalse(self.fp_foreign.map_tax(self.fixed_assets))

    def test_reverse_charge_name(self):
        tax = self.Template.ref('ge_tax_p_rc_18_nonvatreg').with_context(lang='en_US')
        self.assertEqual(tax.name, 'Reverse Charge 18% Non-Deductible')

    def test_maintenance_recreates_missing_fixed_assets_tax(self):
        self.fixed_assets.unlink()
        self.assertFalse(self.Template.ref('ge_tax_p_vat_18_fixed_assets', raise_if_not_found=False))

        self.Template._ge_gec_apply_maintenance(self.env.company)

        tax = self.Template.ref('ge_tax_p_vat_18_fixed_assets')
        self.assertEqual(tax.fiscal_position_ids, self.fp_vat)
        self.assertEqual(tax.invoice_repartition_line_ids.account_id, self.Template.ref('gec_account_334011'))

    def _snapshot(self, xmlids):
        taxes = {xmlid: self.Template.ref(xmlid) for xmlid in xmlids}
        return {
            xmlid: (tax.original_tax_ids.ids, tax.fiscal_position_ids.ids, tax.price_include_override)
            for xmlid, tax in taxes.items()
        }

    def test_install_repair(self):
        sp_sale = self.Template.ref('ge_vat_sale_18_sp_sale')
        building = self.Template.ref('ge_vat_sale_18_building')
        sp_sale.original_tax_ids = [Command.link(self.tax_18.id)]
        self.tax_rcs.original_tax_ids = [Command.link(self.purchase_18.id)]
        self.tax_18.fiscal_position_ids = [Command.set(self.fp_vat.ids)]
        self.tax_import.price_include_override = False
        building.fiscal_position_ids = [Command.clear()]

        self.Template._ge_fix_core_vat_taxes(self.env.company)
        self.env.invalidate_all()

        self.assertNotIn(self.tax_18, sp_sale.original_tax_ids)
        self.assertNotIn(self.purchase_18, self.tax_rcs.original_tax_ids)
        self.assertEqual(self.fp_vat.map_tax(self.tax_18), self.tax_18)
        self.assertEqual(self.tax_18.fiscal_position_ids, self.fp_vat | self.fp_nonvat | self.fp_domestic)
        self.assertEqual(self.tax_import.price_include_override, 'tax_included')
        self.assertFalse(building.fiscal_position_ids)

        xmlids = ('ge_vat_sale_18', 'ge_vat_sale_18_sp_sale', 'ge_vat_sale_18_building',
                  'ge_rcvat_18_ser', 'ge_import_duty_18')
        before = self._snapshot(xmlids)
        self.Template._ge_fix_core_vat_taxes(self.env.company)
        self.assertEqual(self._snapshot(xmlids), before)

    def test_chart_reload_completes_repair(self):
        sp_sale = self.Template.ref('ge_vat_sale_18_sp_sale')
        sp_sale.original_tax_ids = [Command.link(self.tax_18.id)]

        self.Template.try_loading('ge', self.env.company, install_demo=False)
        self.env.invalidate_all()

        self.assertNotIn(self.tax_18, sp_sale.original_tax_ids)
        self.assertEqual(self.fp_nonvat.map_tax(self.tax_18), self.tax_18)
