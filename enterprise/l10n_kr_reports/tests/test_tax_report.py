# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo.tests import tagged, freeze_time

from odoo.addons.account_reports.tests.common import TestAccountReportsCommon


@freeze_time('2024-03-31')
@tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nKrTaxReport(TestAccountReportsCommon):

    @classmethod
    @TestAccountReportsCommon.setup_country('kr')
    def setUpClass(cls):
        super().setUpClass()
        cls.general_report = cls.env.ref('l10n_kr.l10n_kr_general_tp_vat')
        cls.simplified_report = cls.env.ref('l10n_kr.l10n_kr_simplified_tp_vat')

    def _post_move(self, tax_ref, price_unit, issuance_type, move_type='in_invoice'):
        self._create_invoice(
            move_type=move_type,
            invoice_date='2024-03-15',
            l10n_kr_issuance_type=issuance_type,
            invoice_line_ids=[self._prepare_invoice_line(
                price_unit=price_unit,
                tax_ids=self.env['account.chart.template'].ref(tax_ref),
            )],
            post=True,
        )

    def _assert_report_lines(self, report, expected):
        options = self._generate_options(report, '2024-03-01', '2024-03-31')
        lines = report._get_lines(options)
        for line_ref, expected_values in expected.items():
            line_id = self._get_basic_line_dict_id_from_report_line_ref(f'l10n_kr.{line_ref}')
            line = next(line for line in lines if line.id.endswith(line_id))
            values = {column.expression_label: column.no_format for column in line.columns}
            self.assertEqual({label: values[label] for label in expected_values}, expected_values, line_ref)

    def test_general_box_10_zero_rated_purchase(self):
        self._post_move('l10n_kr_Purchase_0', 1000.0, 'tax_invoice')
        self._assert_report_lines(self.general_report, {
            'l10n_kr_general_tp_vat_itpgs': {'balance': 1000.0, 'tax': 0.0},
        })

    def test_general_box_14_purchaser_invoice_fixed_asset(self):
        self._post_move('l10n_kr_Purchase_10_fa', 1000.0, 'purchaser_tax_invoice')
        self._assert_report_lines(self.general_report, {
            'l10n_kr_general_tp_vat_ittiip': {'balance': 1000.0, 'tax': 100.0},
        })

    def test_general_box_46_47_purchase_price(self):
        # Price-included deemed taxes: the boxes report the purchase price (base + deemed tax).
        self._post_move('l10n_kr_Purchase_4_dp', 1040.0, 'tax_invoice')
        self._post_move('l10n_kr_Purchase_3_dp', 1030.0, 'tax_invoice')
        self._assert_report_lines(self.general_report, {
            'l10n_kr_general_tp_vat_dit': {'balance': 1040.0, 'tax': 40.0},
            'l10n_kr_general_tp_vat_itcrsm': {'balance': 1030.0, 'tax': 30.0},
        })

    def test_general_box_90_deemed_input(self):
        self._post_move('l10n_kr_Purchase_4_dp', 1040.0, 'tax_exempt_invoice')
        self._assert_report_lines(self.general_report, {
            'l10n_kr_general_tp_vat_tfir': {'balance': 1040.0},
        })

    def test_simplified_box_15(self):
        self._post_move('l10n_kr_Purchase_10', 1000.0, 'tax_invoice')  # 1000 + 100 VAT
        self._post_move('l10n_kr_Purchase_0', 1000.0, 'tax_invoice')  # 1000 zero-rated
        self._post_move('l10n_kr_Purchase_10_im', 1000.0, 'tax_invoice')  # import: -1000 base deduction + 100 VAT
        self._post_move('l10n_kr_Purchase_10', 1000.0, 'tax_exempt_invoice')  # excluded
        self._assert_report_lines(self.simplified_report, {
            'l10n_kr_simplified_tp_vat_sticra': {'balance': 3200.0, 'tax': 16.0},
        })

    def test_simplified_box_10_11_zero_rated_sales(self):
        self._post_move('l10n_kr_Sales_0', 1000.0, 'tax_invoice', move_type='out_invoice')
        self._post_move('l10n_kr_Sales_0', 2000.0, 'card_payment', move_type='out_invoice')
        self._assert_report_lines(self.simplified_report, {
            'l10n_kr_simplified_tp_vat_szrti': {'balance': 1000.0},
            'l10n_kr_simplified_tp_vat_szro': {'balance': 2000.0},
        })
