from .common import TestAccountReportsCommon

from odoo import Command
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestCashFlowIndirectReport(TestAccountReportsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.report = cls.env.ref('account_reports.cash_flow_report_indirect')

        cls.misc_journal = cls.company_data['default_journal_misc']
        cls.bank_journal = cls.company_data['default_journal_bank']

        cls.account_bank = cls.bank_journal.default_account_id
        cls.account_bank.tag_ids = False

        tags_and_types = [
            (cls.env.ref('account.account_tag_non_applicable'), 'asset_current'),               # 0
            (cls.env.ref('account.account_tag_non_applicable'), 'expense_depreciation'),        # 1
            (cls.env.ref('account.account_tag_adj_depreciation_and_amortization'), 'expense'),  # 2
            (cls.env.ref('account.account_tag_adj_PPE_sale'), 'income_other'),                  # 3
            (cls.env.ref('account.account_tag_wcap_trade_receivable'), 'asset_receivable'),     # 4
            (cls.env.ref('account.account_tag_inv_cash_advances'), 'asset_current'),            # 5
            (cls.env.ref('account.account_tag_fin_share_issuance'), 'equity'),                  # 6
            (cls.env.ref('account.account_tag_fin_dividends'), 'expense'),                      # 7
            (cls.env.ref('account.account_tag_fin_borrowings_lt'), 'liability_non_current'),    # 8
            (cls.env.ref('account.account_tag_fin_borrowings_st'), 'liability_current'),        # 9
        ]

        accounts = cls.env['account.account'].create([{
            'name': 'account%s' % i,
            'code': 'code%s' % i,
            'account_type': account_type,
            'tag_ids': account_tag,
        } for i, (account_tag, account_type) in enumerate(tags_and_types)])

        misc_move_2026 = cls.env['account.move'].create({
            'move_type': 'entry',
            'date': '2026-06-01',
            'journal_id': cls.misc_journal.id,
            'line_ids': [
                # Adjustments section
                Command.create({'debit': 1000.0,    'credit': 0.0,      'account_id': accounts[1].id}),
                Command.create({'debit': 400.0,     'credit': 0.0,      'account_id': accounts[2].id}),
                Command.create({'debit': 0.0,       'credit': 300.0,    'account_id': accounts[3].id}),
                Command.create({'debit': 0.0,       'credit': 1100.0,   'account_id': accounts[0].id}),
                # Working Capital section
                Command.create({'debit': 500.0,     'credit': 0.0,      'account_id': accounts[4].id}),
                Command.create({'debit': 0.0,       'credit': 500.0,    'account_id': accounts[0].id}),
                # Investing Activities - Cash advances: should be ignored because misc journal
                Command.create({'debit': 0.0,       'credit': 1000.0,   'account_id': accounts[5].id}),
                Command.create({'debit': 1000.0,    'credit': 0.0,      'account_id': accounts[0].id}),
                # Financial Activities section
                Command.create({'debit': 0.0,       'credit': 5000.0,   'account_id': accounts[8].id}),
                Command.create({'debit': 1200.0,    'credit': 0.0,      'account_id': accounts[9].id}),
                Command.create({'debit': 3800.0,    'credit': 0.0,      'account_id': accounts[0].id}),
            ]
        })
        misc_move_2026.action_post()

        bank_move_2026 = cls.env['account.move'].create({
            'move_type': 'entry',
            'date': '2026-06-01',
            'journal_id': cls.bank_journal.id,
            'line_ids': [
                # Investing Activities section
                Command.create({'debit': 800.0,     'credit': 0.0,      'account_id': cls.account_bank.id}),
                Command.create({'debit': 0.0,       'credit': 800.0,    'account_id': accounts[5].id}),
                Command.create({'debit': 0.0,       'credit': 300.0,    'account_id': cls.account_bank.id}),
                Command.create({'debit': 300.0,     'credit': 0.0,      'account_id': accounts[5].id}),
                # Financial Activities section
                Command.create({'debit': 10000.0,   'credit': 0.0,      'account_id': cls.account_bank.id}),
                Command.create({'debit': 0.0,       'credit': 10000.0,  'account_id': accounts[6].id}),
                Command.create({'debit': 0.0,       'credit': 400.0,    'account_id': cls.account_bank.id}),
                Command.create({'debit': 400.0,     'credit': 0.0,      'account_id': accounts[7].id}),
            ]
        })
        bank_move_2026.action_post()

        bank_move_2025 = cls.env['account.move'].create({
            'move_type': 'entry',
            'date': '2025-06-01',
            'journal_id': cls.bank_journal.id,
            'line_ids': [
                # Cash beginning of period
                Command.create({'debit': 1000.0,    'credit': 0.0,      'account_id': cls.account_bank.id}),
                Command.create({'debit': 0.0,       'credit': 1000.0,   'account_id': accounts[0].id}),
            ]
        })
        bank_move_2025.action_post()

    def test_cash_flow_indirect_full_report(self):
        options = self._generate_options(self.report, '2026-01-01', '2026-12-31')

        lines = self.report._get_lines(options)

        self.assertLinesValues(
            lines,
            #   Name                                                                   Balance
            [   0,                                                                   1],
            [
                ('Cash Flows from operating activities',                                -900.0),
                ('Net Profit',                                                         -1500.0),
                ('Adjustments to reconcile net profit/(loss) to net cash flows:',       1100.0),
                ('Depreciation and amortisation',                                       1400.0),
                ('Provisions',                                                             0.0),
                ('Gain (-)/Loss (+) on sale of intangible assets',                         0.0),
                ('Gain (-)/Loss (+) on sale of property, plant and equipment',          -300.0),
                ('Gain (-)/Loss (+) on sale of right-of-use assets',                       0.0),
                ('Gain (-)/Loss (+) on sale of financial instruments',                     0.0),
                ('Unrealized FX Gain (-)/Loss (+)',                                        0.0),
                ('Net financial result : income (-)/cost (+)',                             0.0),
                ('Total Adjustments to reconcile net profit/(loss) to net cash flows:', 1100.0),
                ('Working capital adjustments',                                         -500.0),
                ('Trade receivables',                                                   -500.0),
                ('Other receivables',                                                      0.0),
                ('Trade payables',                                                         0.0),
                ('Other payables',                                                         0.0),
                ('Inventory',                                                              0.0),
                ('Deferred revenue',                                                       0.0),
                ('Total Working capital adjustments',                                   -500.0),
                ('Income tax paid (-)/received (+)',                                       0.0),
                ('Interest paid',                                                          0.0),
                ('Total Cash Flows from operating activities',                          -900.0),
                ('Cash Flows from investing activities',                                 500.0),
                ('Intangible assets',                                                      0.0),
                ('Proceeds from sale of intangible assets',                                0.0),
                ('Purchase of intangible assets',                                          0.0),
                ('Total Intangible assets',                                                0.0),
                ('Property plant and equipment',                                           0.0),
                ('Proceeds from sale of property, plant and equipment',                    0.0),
                ('Purchase of property, plant and equipment',                              0.0),
                ('Total Property plant and equipment',                                     0.0),
                ('Proceeds from sale of right-of-use assets',                              0.0),
                ('Financial instruments',                                                  0.0),
                ('Proceeds from financial instruments',                                    0.0),
                ('Purchase of financial instruments',                                      0.0),
                ('Total Financial instruments',                                            0.0),
                ('Receipt of recoverable cash advances',                                 800.0),
                ('Cash advances made to third parties',                                 -300.0),
                ('Interest received',                                                      0.0),
                ('Total Cash Flows from investing activities',                           500.0),
                ('Cash Flows from financing activities',                               13400.0),
                ('Proceeds from share issuance',                                       10000.0),
                ('Interests/Dividends paid',                                            -400.0),
                ('Proceeds from borrowings',                                            5000.0),
                ('Repayment of borrowings',                                            -1200.0),
                ('Repayment of lease',                                                     0.0),
                ('Proceeds from recoverable advances',                                     0.0),
                ('Repayment of recoverable advances',                                      0.0),
                ('Total Cash Flows from financing activities',                         13400.0),
                ('CASH FLOW',                                                          13000.0),
                ('Cash and cash equivalents at beginning',                              1000.0),
                ('Variation',                                                          10100.0),
                ('Cash and cash equivalents at end',                                   11100.0),
            ],
            options,
        )
