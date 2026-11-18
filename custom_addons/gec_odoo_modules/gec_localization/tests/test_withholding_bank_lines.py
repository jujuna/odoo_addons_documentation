from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


class WithholdingBankLinesCommon(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country('ge')
    def setUpClass(cls):
        super().setUpClass()
        Tax = cls.env['account.tax']
        cls.vat = Tax.create({'name': 'Bank line VAT 18', 'type_tax_use': 'purchase', 'amount': 18})
        cls.vat_10 = Tax.create({'name': 'Bank line VAT 10', 'type_tax_use': 'purchase', 'amount': 10})
        cls.wht = Tax.create({
            'name': 'Bank line withholding 5',
            'type_tax_use': 'purchase',
            'amount': -5,
            'gec_is_withholding': True,
            'price_include_override': 'tax_excluded',
        })


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestWithholdingBaseLines(WithholdingBankLinesCommon):

    def test_entry_line_deleted_before_taxes_are_computed_still_leaves_withholding_out(self):
        entry = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                Command.create({
                    'account_id': self.company_data['default_account_expense'].id,
                    'debit': 100.0,
                    'tax_ids': [Command.set((self.vat | self.wht).ids)],
                }),
                Command.create({'account_id': self.company_data['default_account_payable'].id, 'credit': 100.0}),
            ],
        })
        self.assertEqual(entry.line_ids.tax_line_id, self.vat, "the withholding tax books no line on a manual entry")
        AccountTax = self.env['account.tax']
        base_line = AccountTax._prepare_base_line_for_taxes_computation(entry.line_ids.filtered('tax_ids'))
        entry.unlink()
        AccountTax._add_tax_details_in_base_lines([base_line], self.env.company)
        self.assertEqual(AccountTax.concat(*(data['tax'] for data in base_line['tax_details']['taxes_data'])), self.vat)

    def test_invoice_lines_keep_withholding_taxes_computed_as_core_does(self):
        for move_type in ('out_invoice', 'in_invoice'):
            with self.subTest(move_type=move_type):
                invoice = self._create_invoice(move_type=move_type, invoice_line_ids=[self._prepare_invoice_line(price_unit=100.0)])
                base_line = invoice._prepare_product_base_line_for_taxes_computation(invoice.invoice_line_ids)
                self.assertNotIn('calculate_withholding_taxes', base_line)


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestWithholdingBankReconciliation(WithholdingBankLinesCommon):

    def setUp(self):
        super().setUp()
        if self.env['ir.module.module']._get('account_accountant').state != 'installed':
            self.skipTest("Bank reconciliation needs the Accounting app.")

    def _statement_line(self, *taxes):
        """A -100 bank statement line moved from the suspense account to a purchase account, with `taxes` on it."""
        account = self.env['account.account'].create({'name': 'Bank line expense', 'code': '599999', 'account_type': 'expense'})
        st_line = self.env['account.bank.statement.line'].create({
            'amount': -100.0,
            'date': '2019-01-01',
            'payment_ref': 'Bank line withholding',
            'journal_id': self.company_data['default_journal_bank'].id,
        })
        st_line.set_account_bank_statement_line(st_line.line_ids[-1].id, account.id)
        if taxes:
            st_line.edit_reconcile_line(st_line.line_ids[-1].id, {'tax_ids': [Command.link(tax.id) for tax in taxes]})
        return st_line

    def _base_line(self, st_line):
        return st_line.line_ids.filtered('tax_ids')

    def _assert_entry_balanced_on_the_statement_amount(self, st_line):
        self.assertAlmostEqual(sum(st_line.line_ids.mapped('balance')), 0.0, places=2)
        self.assertEqual(st_line.line_ids.filtered(lambda line: line.account_id == st_line.journal_id.default_account_id).balance, -100.0)

    def test_deleting_a_taxed_line_leaves_the_bank_and_suspense_lines(self):
        st_line = self._statement_line(self.vat)
        st_line.delete_reconciled_line(self._base_line(st_line).id)
        self.assertRecordValues(st_line.line_ids.sorted('balance'), [
            {'account_id': st_line.journal_id.default_account_id.id, 'balance': -100.0},
            {'account_id': st_line.journal_id.suspense_account_id.id, 'balance': 100.0},
        ])

    def test_changing_the_tax_of_a_taxed_line_keeps_the_statement_amount(self):
        st_line = self._statement_line(self.vat)
        st_line.edit_reconcile_line(self._base_line(st_line).id, {'tax_ids': [Command.unlink(self.vat.id), Command.link(self.vat_10.id)]})
        self.assertEqual(self._base_line(st_line).tax_ids, self.vat_10)
        self.assertEqual(st_line.line_ids.filtered('tax_line_id').tax_line_id, self.vat_10)
        self._assert_entry_balanced_on_the_statement_amount(st_line)

    def test_withholding_tax_on_a_bank_line_stays_a_label_and_the_line_deletes_cleanly(self):
        st_line = self._statement_line(self.vat, self.wht)
        self.assertEqual(self._base_line(st_line).tax_ids, self.vat | self.wht)
        self.assertEqual(st_line.line_ids.filtered('tax_line_id').tax_line_id, self.vat)
        self._assert_entry_balanced_on_the_statement_amount(st_line)
        st_line.delete_reconciled_line(self._base_line(st_line).id)
        self.assertEqual(len(st_line.line_ids), 2)
