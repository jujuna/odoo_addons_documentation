# pylint: disable=C0326
from odoo import Command
from .common import TestAccountReportsCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestIntercoComparisonReport(TestAccountReportsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env.ref('account_reports.interco_comparison_report')

        cls.company_data_3 = cls.setup_other_company(name='company_3')
        cls.currency_euro = cls.setup_other_currency('EUR', rounding=0.001, rates=[('2015-12-31', 2.0), ('2016-12-31', 2.0)])

        cls.test_tax = cls.env['account.tax'].create({
            'name': 'Tax 10%',
            'amount': 10.0,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
            'invoice_repartition_line_ids': [
                Command.create({'repartition_type': 'base'}),
                Command.create({'repartition_type': 'tax', 'account_id': cls.company_data['default_account_tax_sale'].id}),
            ],
        })

        cls.test_tax_purchase = cls.env['account.tax'].with_company(cls.company_data_2['company']).create({
            'name': 'Tax 10%',
            'amount': 10.0,
            'amount_type': 'percent',
            'type_tax_use': 'purchase',
        })

    def test_interco_tax_lines_filter(self):
        """
        Check that tax lines are hidden by default, and shown when the filter is unset
        """
        # Invoice in 2017 from company_1 to company 2, with taxes
        self._create_invoice_one_line(
            partner_id=self.company_data_2['company'].partner_id,
            invoice_date='2017-01-01',
            payment_reference='ref345',
            journal_id=self.company_data['default_journal_sale'],
            price_unit=1500.0,
            account_id=self.company_data['default_account_revenue'],
            tax_ids=self.test_tax,
            post=True,
        )

        # Generate lines, with the tax lines hidden
        options = self._generate_options(
            self.report,
            '2017-01-01',
            '2017-01-31',
            default_options={'unfold_all': True},
        )

        lines = self.report._get_lines(options)
        self.assertLinesValues(
            lines,
            [0, 1, 2, 3],
            [
                ('Interco Comparison',                              '',             '',             ''),
                ('USD',                                             '150.00',       '0.00',         '150.00'),
                ('company_2',                                       '150.00',       '0.00',         '150.00'),
                ('Income',                                          '-1,500.00',    '0.00',         '-1,500.00'),
                ('400000 Product Sales (company_1_data)',           '-1,500.00',    '0.00',         '-1,500.00'),
                ('Receivable',                                      '1,650.00',     '0.00',         '1,650.00'),
                ('121000 Accounts Receivable (company_1_data)',     '1,650.00',     '0.00',         '1,650.00'),
            ],
            options,
        )

        # Generate lines again, with the tax lines shown
        options = self.report.get_options({**options, 'hide_tax_lines': False})

        lines = self.report._get_lines(options)
        self.assertLinesValues(
            lines,
            [0, 1, 2, 3],
            [
                ('Interco Comparison',                              '',             '',             ''),
                ('USD',                                             '0.00',         '0.00',         '0.00'),
                ('company_2',                                       '0.00',         '0.00',         '0.00'),
                ('Current Liabilities',                             '-150.00',    '0.00',         '-150.00'),
                ('251000 Tax Received (company_1_data)',            '-150.00',    '0.00',         '-150.00'),
                ('Income',                                          '-1,500.00',    '0.00',         '-1,500.00'),
                ('400000 Product Sales (company_1_data)',           '-1,500.00',    '0.00',         '-1,500.00'),
                ('Receivable',                                      '1,650.00',     '0.00',         '1,650.00'),
                ('121000 Accounts Receivable (company_1_data)',     '1,650.00',     '0.00',         '1,650.00'),
            ],
            options,
        )

    def test_interco_comparison_basic(self):
        """
        Check the report lines for the journal entries within the first month of 2017,
        before and after the counterpart of the invoice is registered in the other company
        """
        # Invoice in 2017 from company_1 to company 2, with taxes
        self._create_invoice_one_line(
            partner_id=self.company_data_2['company'].partner_id,
            invoice_date='2017-01-01',
            payment_reference='ref345',
            journal_id=self.company_data['default_journal_sale'],
            price_unit=1500.0,
            account_id=self.company_data['default_account_revenue'],
            tax_ids=self.test_tax,
            post=True,
        )

        # Generate lines, without counterpart
        options = self._generate_options(
            self.report,
            '2017-01-01',
            '2017-01-31',
            default_options={'unfold_all': True},
        )

        lines = self.report._get_lines(options)
        self.assertLinesValues(
            lines,
            [0, 1, 2, 3],
            [
                ('Interco Comparison',                              '',             '',             ''),
                ('USD',                                             '150.00',       '0.00',         '150.00'),
                ('company_2',                                       '150.00',       '0.00',         '150.00'),
                ('Income',                                          '-1,500.00',    '0.00',         '-1,500.00'),
                ('400000 Product Sales (company_1_data)',           '-1,500.00',    '0.00',         '-1,500.00'),
                ('Receivable',                                      '1,650.00',     '0.00',         '1,650.00'),
                ('121000 Accounts Receivable (company_1_data)',     '1,650.00',     '0.00',         '1,650.00'),
            ],
            options,
        )

        # Vendor bill in 2017 in company_2 from company_1, counterpart of the invoice above (so in the currency of company_1)
        self._create_invoice_one_line(
            move_type='in_invoice',
            company_id=self.company_data_2['company'],
            partner_id=self.company_data['company'].partner_id,
            invoice_date='2017-01-01',
            journal_id=self.company_data_2['default_journal_purchase'],
            currency_id=self.company_data['currency'],
            price_unit=1500.0,
            account_id=self.company_data_2['default_account_expense'],
            tax_ids=self.test_tax_purchase,
            post=True,
        )

        # Generate lines again, with the counterpart
        lines = self.report._get_lines(options)
        self.assertLinesValues(
            lines,
            [0, 1, 2, 3],
            [
                ('Interco Comparison',                              '',             '',             ''),
                ('USD',                                             '150.00',       '-150.00',      '0.00'),
                ('company_2',                                       '150.00',       '-150.00',      '0.00'),
                ('Income',                                          '-1,500.00',    '1,500.00',     '0.00'),
                ('400000 Product Sales (company_1_data)',           '-1,500.00',    '0.00',         '-1,500.00'),
                ('600000 Expenses (company_2)',                     '0.00',         '1,500.00',     '1,500.00'),
                ('Receivable',                                      '1,650.00',     '-1,650.00',    '0.00'),
                ('121000 Accounts Receivable (company_1_data)',     '1,650.00',     '0.00',         '1,650.00'),
                ('211000 Accounts Payable (company_2)',             '0.00',         '-1,650.00',    '-1,650.00'),
            ],
            options,
        )

    def test_interco_with_3_companies(self):
        """
        Check the report behaviour when there are several companies
        """
        # Invoice from company_2 to company_1, with other currency
        self._create_invoice_one_line(
            company_id=self.company_data_2['company'],
            partner_id=self.company_data['company'].partner_id,
            invoice_date='2017-01-01',
            journal_id=self.company_data_2['default_journal_sale'],
            currency_id=self.currency_euro,
            price_unit=2500.0,
            account_id=self.company_data_2['default_account_revenue'],
            tax_ids=[],
            post=True,
        )

        # Invoice from company_3 to company_1
        self._create_invoice_one_line(
            company_id=self.company_data_3['company'],
            partner_id=self.company_data['company'].partner_id,
            invoice_date='2017-01-01',
            journal_id=self.company_data_3['default_journal_sale'],
            price_unit=3000.0,
            account_id=self.company_data_3['default_account_revenue'],
            tax_ids=[],
            post=True,
        )

        # Generate lines
        options = self._generate_options(
            self.report,
            '2017-01-01',
            '2017-01-31',
            default_options={'unfold_all': True},
        )

        lines = self.report._get_lines(options)
        self.assertLinesValues(
            lines,
            [0, 1, 2, 3],
            [
                ('Interco Comparison',                              '',             '',             ''),
                ('EUR',                                             '0.000',        '0.000',        '0.000'),
                ('company_2',                                       '0.000',        '0.000',        '0.000'),
                ('Expense',                                         '0.000',        '-2,500.000',   '-2,500.000'),
                ('400000 Product Sales (company_2)',                '0.000',        '-2,500.000',   '-2,500.000'),
                ('Payable',                                         '0.000',        '2,500.000',    '2,500.000'),
                ('121000 Accounts Receivable (company_2)',          '0.000',        '2,500.000',    '2,500.000'),

                ('USD',                                             '0.00',         '0.00',         '0.00'),
                ('company_3',                                       '0.00',         '0.00',         '0.00'),
                ('Expense',                                         '0.00',         '-3,000.00',    '-3,000.00'),
                ('400000 Product Sales (company_3)',                '0.00',         '-3,000.00',    '-3,000.00'),
                ('Payable',                                         '0.00',         '3,000.00',     '3,000.00'),
                ('121000 Accounts Receivable (company_3)',          '0.00',         '3,000.00',     '3,000.00'),
            ],
            options,
        )

    def test_interco_invoices_between_companies_not_shown(self):
        """
        Check that invoices are not shown when made between companies that are not the main one.
        """
        # Invoice from company_3 to company_1
        self._create_invoice_one_line(
            company_id=self.company_data_3['company'],
            partner_id=self.company_data['company'].partner_id,
            invoice_date='2017-01-01',
            journal_id=self.company_data_3['default_journal_sale'],
            price_unit=3000.0,
            account_id=self.company_data_3['default_account_revenue'],
            tax_ids=[],
            post=True,
        )

        expected_lines = [
            ('Interco Comparison',                              '',             '',             ''),
            ('USD',                                             '0.00',         '0.00',         '0.00'),
            ('company_3',                                       '0.00',         '0.00',         '0.00'),
            ('Expense',                                         '0.00',         '-3,000.00',    '-3,000.00'),
            ('400000 Product Sales (company_3)',                '0.00',         '-3,000.00',    '-3,000.00'),
            ('Payable',                                         '0.00',         '3,000.00',     '3,000.00'),
            ('121000 Accounts Receivable (company_3)',          '0.00',         '3,000.00',     '3,000.00'),
        ]

        # Generate lines
        options = self._generate_options(
            self.report,
            '2017-01-01',
            '2017-01-31',
            default_options={'unfold_all': True},
        )

        lines = self.report._get_lines(options)
        self.assertLinesValues(
            lines,
            [0, 1, 2, 3],
            expected_lines,
            options,
        )

        # Invoice from company_3 to company_2, with other currency
        self._create_invoice_one_line(
            company_id=self.company_data_3['company'],
            partner_id=self.company_data_2['company'].partner_id,
            invoice_date='2017-01-01',
            journal_id=self.company_data_3['default_journal_sale'],
            currency_id=self.currency_euro,
            price_unit=2500.0,
            account_id=self.company_data_3['default_account_revenue'],
            tax_ids=[],
            post=True,
        )

        # Generate lines again, nothing should have changed
        lines = self.report._get_lines(options)
        self.assertLinesValues(
            lines,
            [0, 1, 2, 3],
            expected_lines,
            options,
        )

    def test_interco_invoices_with_external_partners_not_shown(self):
        """
        Check that adding invoices don't change anything to the report if they're made for partners not corresponding to a company
        """
        # Invoice in 2017 from company_1 to company 2, with taxes
        self._create_invoice_one_line(
            partner_id=self.company_data_2['company'].partner_id,
            invoice_date='2017-01-01',
            payment_reference='ref345',
            journal_id=self.company_data['default_journal_sale'],
            price_unit=1500.0,
            account_id=self.company_data['default_account_revenue'],
            tax_ids=self.test_tax,
            post=True,
        )

        expected_lines = [
            ('Interco Comparison',                              '',             '',             ''),
            ('USD',                                             '150.00',       '0.00',         '150.00'),
            ('company_2',                                       '150.00',       '0.00',         '150.00'),
            ('Income',                                          '-1,500.00',    '0.00',         '-1,500.00'),
            ('400000 Product Sales (company_1_data)',           '-1,500.00',    '0.00',         '-1,500.00'),
            ('Receivable',                                      '1,650.00',     '0.00',         '1,650.00'),
            ('121000 Accounts Receivable (company_1_data)',     '1,650.00',     '0.00',         '1,650.00'),
        ]

        # Generate lines
        options = self._generate_options(
            self.report,
            '2017-01-01',
            '2017-01-31',
            default_options={'unfold_all': True},
        )

        lines = self.report._get_lines(options)
        self.assertLinesValues(
            lines,
            [0, 1, 2, 3],
            expected_lines,
            options,
        )

        # Invoice in 2017 for company_1 with external
        self._create_invoice_one_line(
            partner_id=self.partner_a,
            invoice_date='2017-01-01',
            journal_id=self.company_data['default_journal_sale'],
            payment_reference='ref123',
            price_unit=3000.0,
            account_id=self.company_data['default_account_revenue'],
            tax_ids=self.test_tax,
            post=True,
        )

        # Generate lines again, nothing should have changed
        lines = self.report._get_lines(options)
        self.assertLinesValues(
            lines,
            [0, 1, 2, 3],
            expected_lines,
            options,
        )
