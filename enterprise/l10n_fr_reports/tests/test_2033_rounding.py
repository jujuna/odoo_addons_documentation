from odoo.tests import tagged
from odoo.addons.account_reports.tests.common import TestAccountReportsCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestFr2033Rounding(TestAccountReportsCommon):
    """ Subtotals of the 2033 reports must round the sum of the unrounded values of their children,
    not sum the rounded values of their children.
    """

    @classmethod
    @TestAccountReportsCommon.setup_country('fr_comp')
    def setUpClass(cls):
        super().setUpClass()
        cls.report_2033_a = cls.env.ref('l10n_fr_reports.l10n_fr_2033_A')
        cls.report_2033_b = cls.env.ref('l10n_fr_reports.l10n_fr_2033_B')

    def _post_entry(self, entry_lines):
        self.env['account.move'].create({'date': '2024-06-30', 'line_ids': entry_lines}).action_post()

    def _get_values_by_code(self, report, codes, expression_label='balance'):
        options = self._generate_options(report, '2024-01-01', '2024-12-31', default_options={'unfold_all': True})
        return {
            line.code: column.no_format
            for line in report._get_lines(options)
            if line.code in codes
            for column in line.columns
            if column.expression_label == expression_label
        }

    def test_2033_a_subtotal_rounds_unrounded_sum(self):
        """ A subtotal is round(sum of the unrounded children), not sum(rounded children), here on the net column.

        III. Debts                                    unrounded   displayed
        ├── Borrowings (164)                            0.33        0
        ├── Trade payables (401)                        0.33        0
        └── Tax and social security liabilities (421)   0.33        0
        => III. Debts = round(0.33 + 0.33 + 0.33) = round(0.99) = 1   (summing the rounded children would give 0)
        """
        account = self.env['account.chart.template'].ref
        self._post_entry([
            self._prepare_entry_line(account_id=account('pcg_164'), credit=0.33),          # Borrowings and similar liabilities
            self._prepare_entry_line(account_id=account('pcg_401_account'), credit=0.33),  # Trade payables and related accounts
            self._prepare_entry_line(account_id=account('pcg_421'), credit=0.33),          # Tax and social security liabilities
            self._prepare_entry_line(account_id=self.company_data['default_account_expense'], debit=0.99),
        ])

        self.assertEqual(self._get_values_by_code(self.report_2033_a, {'l10n_fr_emprunts_dettes', 'l10n_fr_dettes_rattaches', 'l10n_fr_dettes_sociales', 'l10n_fr_dettes'}, 'net_round'), {
            'l10n_fr_emprunts_dettes': 0.0,
            'l10n_fr_dettes_rattaches': 0.0,
            'l10n_fr_dettes_sociales': 0.0,
            'l10n_fr_dettes': 1.0,  # round(0.99), not 0 + 0 + 0
        })

    def test_2033_a_multi_level_subtotal_uses_unrounded_children(self):
        """ The unrounded value goes up through every level: a subtotal never uses the rounded value of a child subtotal, here on the net column.

        I. Fixed assets                               unrounded   displayed
        ├── Intangible assets                           0.60        1
        │   ├── Commercial fund (206)                   0.30        0
        │   └── Others (205)                            0.30        0
        ├── Property, plant and equipment (2154)        0.30        0
        └── Financial assets (2611)                     0.30        0
        => I. Fixed assets = round(0.60 + 0.30 + 0.30) = round(1.20) = 1
           - old formulas, every level sums rounded values:            (0 + 0) + 0 + 0           = 0
           - only Intangible assets fixed, I uses its rounding:        round(1 + 0.30 + 0.30)    = 2
           - fixed, the unrounded value goes up every level:           round(0.60 + 0.30 + 0.30) = 1
        """
        account = self.env['account.chart.template'].ref
        self._post_entry([
            self._prepare_entry_line(account_id=account('pcg_206'), debit=0.30),   # Commercial fund, in Intangible assets
            self._prepare_entry_line(account_id=account('pcg_205'), debit=0.30),   # Others, in Intangible assets
            self._prepare_entry_line(account_id=account('pcg_2154'), debit=0.30),  # Property, plant and equipment
            self._prepare_entry_line(account_id=account('pcg_2611'), debit=0.30),  # Financial assets
            self._prepare_entry_line(account_id=self.company_data['default_account_revenue'], credit=1.20),
        ])

        self.assertEqual(self._get_values_by_code(self.report_2033_a, {'l10n_fr_fonds_commercial', 'l10n_fr_autres_incorp', 'l10n_fr_immobilis_incorpo', 'l10n_fr_immobilis_corporelles', 'l10n_fr_immobilis_fin', 'l10n_fr_actif_immobilise'}, 'net_round'), {
            'l10n_fr_fonds_commercial': 0.0,
            'l10n_fr_autres_incorp': 0.0,
            'l10n_fr_immobilis_incorpo': 1.0,  # round(0.60)
            'l10n_fr_immobilis_corporelles': 0.0,
            'l10n_fr_immobilis_fin': 0.0,
            # round(0.60 + 0.30 + 0.30): neither 0 + 0 + 0 (rounded leaves) nor round(1 + 0.30 + 0.30) = 2 (rounded Intangible assets)
            'l10n_fr_actif_immobilise': 1.0,
        })

    def test_2033_b_subtotal_rounds_unrounded_sum(self):
        """ A subtotal is round(sum of the unrounded children), not sum(rounded children).

        c264 Operating expenses (II)                  unrounded   displayed
        ├── c234 Purchases of goods (607)               0.33        0
        ├── c238 Purchases of raw materials (601)       0.33        0
        └── c250 Personnel remuneration (648)           0.33        0
        => c264 = round(0.33 + 0.33 + 0.33) = round(0.99) = 1   (summing the rounded children would give 0)
        """
        account = self.env['account.chart.template'].ref
        self._post_entry([
            self._prepare_entry_line(account_id=account('pcg_607_account'), debit=0.33),  # c234 Purchases of goods
            self._prepare_entry_line(account_id=account('pcg_601_account'), debit=0.33),  # c238 Purchases of raw materials
            self._prepare_entry_line(account_id=account('pcg_648'), debit=0.33),          # c250 Personnel remuneration
            self._prepare_entry_line(account_id=self.company_data['default_account_receivable'], credit=0.99),
        ])

        self.assertEqual(self._get_values_by_code(self.report_2033_b, {'FR_2033_B_c234', 'FR_2033_B_c238', 'FR_2033_B_c250', 'FR_2033_B_c264'}), {
            'FR_2033_B_c234': 0.0,
            'FR_2033_B_c238': 0.0,
            'FR_2033_B_c250': 0.0,
            'FR_2033_B_c264': 1.0,  # round(0.99), not 0 + 0 + 0
        })

    def test_2033_b_multi_level_subtotal_uses_unrounded_children(self):
        """ The unrounded value goes up through every level: a subtotal never uses the rounded value of a child subtotal.

        c232 Operating income (I)                     unrounded   displayed
        ├── c210 Sales of goods (707)                   0.30        0
        ├── Production sold                             0.60        1
        │   ├── c214 Goods (702)                        0.30        0
        │   └── c218 Services (706)                     0.30        0
        └── c230 Other products (758)                   0.30        0
        => c232 = round(0.30 + 0.60 + 0.30) = round(1.20) = 1
           - old formulas, every level sums rounded values:       0 + (0 + 0) + 0           = 0
           - only Production sold fixed, c232 uses its rounding:  round(0.30 + 1 + 0.30)    = 2
           - fixed, the unrounded value goes up every level:      round(0.30 + 0.60 + 0.30) = 1
        """
        account = self.env['account.chart.template'].ref
        self._post_entry([
            self._prepare_entry_line(account_id=account('pcg_702'), credit=0.30),          # c214 Goods, in Production sold
            self._prepare_entry_line(account_id=account('pcg_706'), credit=0.30),          # c218 Services, in Production sold
            self._prepare_entry_line(account_id=account('pcg_707_account'), credit=0.30),  # c210 Sales of goods
            self._prepare_entry_line(account_id=account('pcg_758'), credit=0.30),          # c230 Other products
            self._prepare_entry_line(account_id=self.company_data['default_account_receivable'], debit=1.20),
        ])

        self.assertEqual(self._get_values_by_code(self.report_2033_b, {'FR_2033_B_c214', 'FR_2033_B_c218', 'FR_2033_B_prod_sold', 'FR_2033_B_c210', 'FR_2033_B_c230', 'FR_2033_B_c232'}), {
            'FR_2033_B_c214': 0.0,
            'FR_2033_B_c218': 0.0,
            'FR_2033_B_prod_sold': 1.0,  # round(0.60)
            'FR_2033_B_c210': 0.0,
            'FR_2033_B_c230': 0.0,
            # round(0.30 + 0.60 + 0.30): neither 0 + 0 + 0 (rounded leaves) nor round(0.30 + 1 + 0.30) = 2 (rounded Production sold)
            'FR_2033_B_c232': 1.0,
        })
