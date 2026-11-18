from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.gec_localization.models.template_ge import GE_RC_TEXTS_KEY, GE_TAX_TEXTS_KEY
from odoo.tests import tagged

GE_TAX_CATEGORIES_KEY = 'gec_localization.tax_categories_20261028'


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestGeTaxCategories(AccountTestInvoicingCommon):
    """Tax Category Codes (ubl_cii_tax_category_code) on Georgian taxes: from the chart template and the one-time pass."""

    @classmethod
    @AccountTestInvoicingCommon.setup_country('ge')
    def setUpClass(cls):
        super().setUpClass()
        cls.Template = cls.env['account.chart.template']
        cls.params = cls.env['ir.config_parameter'].sudo()

    def test_new_company_gets_codes(self):
        expected = {
            'ge_vat_sale_18': 'S',
            'ge_vat_purchase_18': 'S',
            'ge_vat_sale_exempt_transport': 'Z',
            'ge_vat_sale_0_ex': 'G',
            'ge_vat_sale_exempt_financial': 'E',
            'ge_tax_s_out_of_scope': 'O',
            'ge_tax_p_vat_exempt': 'E',
            'ge_tax_p_vat_0': 'Z',
            'ge_tax_p_vat_18_fixed_assets': 'S',
            'ge_import_duty_18': False,
            'ge_tax_p_wht_nr_dividends_5': False,
        }
        for xmlid, code in expected.items():
            with self.subTest(xmlid=xmlid):
                self.assertEqual(self.Template.ref(xmlid).ubl_cii_tax_category_code, code)

    def test_template_carries_codes(self):
        template = self.Template.with_context(ignore_missing_tags=True)._get_chart_template_model_data('ge', 'account.tax')
        self.assertEqual(template['ge_vat_sale_18'].get('ubl_cii_tax_category_code'), 'S')
        self.assertEqual(template['ge_vat_sale_exempt_financial'].get('ubl_cii_tax_category_code'), 'E')
        self.assertEqual(template['ge_tax_p_vat_0'].get('ubl_cii_tax_category_code'), 'Z')
        self.assertFalse(template['ge_import_duty_18'].get('ubl_cii_tax_category_code'))

    def test_pass_fills_only_empty_codes_once(self):
        tax_18 = self.Template.ref('ge_vat_sale_18')
        tax_exempt_ta = self.Template.ref('ge_vat_sale_exempt_ta')
        self.params.set_bool(GE_TAX_CATEGORIES_KEY, False)
        tax_18.ubl_cii_tax_category_code = False
        tax_exempt_ta.ubl_cii_tax_category_code = 'E'

        self.Template._ge_apply_tax_categories()

        self.assertEqual(tax_18.ubl_cii_tax_category_code, 'S')
        self.assertEqual(tax_exempt_ta.ubl_cii_tax_category_code, 'E')
        self.assertTrue(self.params.get_bool(GE_TAX_CATEGORIES_KEY))

        tax_18.ubl_cii_tax_category_code = False
        self.Template._ge_apply_tax_categories()
        self.assertFalse(tax_18.ubl_cii_tax_category_code)

    def test_text_pass_with_xmlids_rewrites_only_those_taxes(self):
        rc_tax = self.Template.ref('ge_tax_p_rc_18_nonvatreg').with_context(lang='en_US')
        other_tax = self.Template.ref('ge_tax_p_out_of_scope').with_context(lang='en_US')
        self.params.set_bool(GE_TAX_TEXTS_KEY, True)
        self.params.set_bool(GE_RC_TEXTS_KEY, False)
        rc_tax.name = 'Wrong name'
        other_tax.invoice_label = 'Custom label'

        self.Template._ge_apply_tax_texts(GE_RC_TEXTS_KEY, ('ge_tax_p_rc_18_nonvatreg',))

        self.assertEqual(rc_tax.name, 'Reverse Charge 18% Non-Deductible')
        self.assertEqual(other_tax.invoice_label, 'Custom label')
        self.assertTrue(self.params.get_bool(GE_RC_TEXTS_KEY))
