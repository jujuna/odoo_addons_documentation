from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import UserError
from odoo.tests import Form, tagged
from odoo.tools import mute_logger


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestReviewFixes(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country('ge')
    def setUpClass(cls):
        super().setUpClass()
        cls.Template = cls.env['account.chart.template']
        Tax = cls.env['account.tax']
        cls.product_tax = Tax.create({
            'name': 'Product purchase tax',
            'type_tax_use': 'purchase',
            'amount': 18,
        })
        cls.hand_tax = Tax.create({
            'name': 'Hand picked purchase tax',
            'type_tax_use': 'purchase',
            'amount': 5,
        })
        cls.default_tax = Tax.create({
            'name': 'Default purchase tax',
            'type_tax_use': 'purchase',
            'amount': 10,
        })
        cls.product = cls._create_product(name='Review product', list_price=100.0, supplier_taxes_id=cls.product_tax)
        cls.vendor = cls.env['res.partner'].create({'name': 'Vendor without default'})
        cls.other = cls.env['res.partner'].create({'name': 'Vendor with default'})
        cls.other.with_company(cls.env.company).property_purchase_tax_id = cls.default_tax

    def _bill(self, post=False):
        return self._create_invoice(
            move_type='in_invoice', partner_id=self.vendor, post=post,
            invoice_line_ids=[self._prepare_invoice_line(product_id=self.product, price_unit=100.0, tax_ids=self.hand_tax)],
        )

    def test_partner_change_on_posted_bill_keeps_line_taxes(self):
        bill = self._bill(post=True)
        bill.with_context(skip_readonly_check=True).write({'partner_id': self.other.id})
        self.assertEqual(bill.invoice_line_ids.tax_ids, self.hand_tax)

    def test_partner_change_in_form_proposes_default_tax(self):
        bill = self._bill()
        with Form(bill) as form:
            form.partner_id = self.other
        self.assertEqual(bill.invoice_line_ids.tax_ids, self.default_tax)

    def test_partner_write_on_draft_bill_keeps_line_taxes(self):
        bill = self._bill()
        bill.write({'partner_id': self.other.id})
        self.assertEqual(bill.invoice_line_ids.tax_ids, self.hand_tax)

    def test_maintenance_links_hand_made_account_and_renames_hand_made_tax(self):
        company = self.env.company
        Account = self.env['account.account']
        account = self.Template.ref('gec_account_120300')
        tax = self.Template.ref('ge_tax_p_vat_18_fixed_assets')
        name = tax.with_context(lang='en_US').name
        self.env['ir.model.data'].search([('module', '=', 'account'), ('res_id', 'in', (account.id, tax.id)),
            ('model', 'in', ('account.account', 'account.tax'))]).unlink()
        self.assertFalse(self.Template.ref('gec_account_120300', raise_if_not_found=False))

        self.Template._ge_gec_apply_maintenance(company)

        self.assertEqual(self.Template.ref('gec_account_120300'), account)
        self.assertEqual(Account.search_count([('code', '=', account.code), *Account._check_company_domain(company)]), 1)
        self.assertEqual(tax.with_context(lang='en_US').name, f'[old] {name}')
        new_tax = self.Template.ref('ge_tax_p_vat_18_fixed_assets')
        self.assertNotEqual(new_tax, tax)
        self.assertEqual(new_tax.with_context(lang='en_US').name, name)

    def _treasury(self, code='101001000', name='State Treasury'):
        return self.env['res.partner'].create({'name': name, 'gec_treasury_code': code})

    def test_state_treasury_ignores_other_treasury_codes(self):
        self.env['res.partner'].search([('gec_treasury_code', '!=', False)]).gec_treasury_code = False
        treasury = self._treasury()
        self._treasury('300773150', 'Other budget recipient')
        self.assertEqual(self.env['account.payment.register']._gec_state_treasury(self.env.company), treasury)

    def test_state_treasury_refuses_two_contacts_with_the_code(self):
        self.env['res.partner'].search([('gec_treasury_code', '!=', False)]).gec_treasury_code = False
        self._treasury()
        self._treasury(name='Second treasury')
        with self.assertRaises(UserError):
            self.env['account.payment.register']._gec_state_treasury(self.env.company)

    def _entry(self, *partners, amount=100.0):
        payable = self.company_data['default_account_payable']
        lines = [self._prepare_entry_line(payable, credit=amount, partner_id=partner) for partner in partners]
        lines.append(self._prepare_entry_line(self.company_data['default_account_expense'], debit=amount * len(partners)))
        entry = self.env['account.move'].create({'move_type': 'entry', 'journal_id': self.company_data['default_journal_misc'].id, 'line_ids': lines})
        entry.action_post()
        return entry.line_ids.filtered(lambda line: line.account_id == payable)

    def _pay(self, lines, ctx=None, **vals):
        context = {'active_model': 'account.move.line', 'active_ids': lines.ids, **(ctx or {})}
        return self.env['account.payment.register'].with_context(**context).create(vals)._create_payments()

    def test_entry_line_paid_through_core_without_outstanding_account_is_refused_or_settled(self):
        line = self._entry(self.vendor)
        self.company_data['default_journal_bank'].outbound_payment_method_line_ids.payment_account_id = False
        if self.env['account.move']._get_invoice_in_payment_state() != 'in_payment':
            # Without the Accounting app core gives the payment an outstanding account itself (account_payment.py create).
            self.assertTrue(self._pay(line).move_id)
            self.assertTrue(line.reconciled)
            return
        payments = self.env['account.payment'].search([])
        with self.assertRaisesRegex(UserError, 'no Outstanding account'):
            self._pay(line)
        self.assertEqual(self.env['account.payment'].search([]), payments)
        self.assertFalse(line.reconciled)

    def test_entry_line_paid_through_core_with_outstanding_account_is_reconciled(self):
        line = self._entry(self.vendor)
        payments = self._pay(line)
        self.assertEqual(len(payments), 1)
        self.assertTrue(payments.move_id)
        self.assertTrue(line.reconciled)

    def test_entry_lines_of_one_partner_are_not_forced_into_one_payment(self):
        lines = self._entry(self.vendor) | self._entry(self.vendor)
        self.assertEqual(len(self._pay(lines, group_payment=False)), 2)

    def test_entry_lines_of_two_partners_keep_two_payments(self):
        self.assertEqual(len(self._pay(self._entry(self.vendor, self.other), group_payment=True)), 2)

    def _wht_tax(self, account):
        tax = self.env['account.tax'].create({
            'name': f'Review withholding 5% {account.code}',
            'type_tax_use': 'purchase',
            'amount': -5,
            'gec_is_withholding': True,
            'price_include_override': 'tax_excluded',
        })
        tax_lines = (tax.invoice_repartition_line_ids | tax.refund_repartition_line_ids).filtered(lambda line: line.repartition_type == 'tax')
        tax_lines.account_id = account
        return tax

    def _wht_bill(self, tax, discount=False):
        term = self.env['account.payment.term'].create({
            'name': 'Review early discount',
            'early_discount': True,
            'discount_percentage': 10,
            'discount_days': 10,
            'line_ids': [Command.create({'value': 'percent', 'nb_days': 30, 'value_amount': 100})],
        }) if discount else False
        return self._create_invoice(
            move_type='in_invoice', partner_id=self.vendor, post=True, invoice_payment_term_id=term,
            invoice_line_ids=[self._prepare_invoice_line(price_unit=1000.0, tax_ids=tax)])

    def _pay_tax(self, bills, **vals):
        self.env['res.partner'].search([('gec_treasury_code', '!=', False)]).gec_treasury_code = False
        self._treasury()
        return self._pay(bills.line_ids._gec_withholding_tax_lines(), {'gec_wht_tax_line_payment': True}, **vals)

    def test_withholding_tax_payment_before_the_discount_date_is_refused(self):
        bill = self._wht_bill(self._wht_tax(self.Template.ref('ge_account_331310')), discount=True)
        with self.assertRaisesRegex(UserError, 'early payment discount'):
            self._pay_tax(bill)

    def test_withholding_tax_payment_after_the_discount_date_is_made(self):
        bill = self._wht_bill(self._wht_tax(self.Template.ref('ge_account_331310')), discount=True)
        payments = self._pay_tax(bill, payment_date=fields.Date.today() + timedelta(days=11))
        self.assertEqual(len(payments), 1)
        self.assertTrue(payments.move_id)

    def test_withholding_tax_payment_of_two_batches_refuses_the_one_with_discount(self):
        discounted = self._wht_bill(self._wht_tax(self.Template.ref('ge_account_331310')), discount=True)
        other_account = self.env['account.account'].create(
            {'name': 'Other WHT', 'code': '331999', 'account_type': 'liability_current', 'reconcile': True})
        plain = self._wht_bill(self._wht_tax(other_account))
        with self.assertRaisesRegex(UserError, discounted.name):
            self._pay_tax(discounted | plain)

    def _wht_bill_of(self, partner, tax, price, move_type='in_invoice', **vals):
        return self._create_invoice(move_type=move_type, partner_id=partner, post=True, **vals,
            invoice_line_ids=[self._prepare_invoice_line(price_unit=price, tax_ids=tax)])

    def _wht_wizard(self, lines):
        action = lines._gec_action_pay_withholding()
        return self.env['account.payment.register'].with_context(**action['context']).create({})

    def test_withholding_left_by_a_credit_note_is_used_up_by_the_next_treasury_payment_of_another_vendor(self):
        tax = self._wht_tax(self.Template.ref('ge_account_331310'))
        bill_a = self._wht_bill_of(self.vendor, tax, 2000.0)
        self._pay_tax(bill_a)
        credit_note = self._wht_bill_of(self.vendor, tax, 600.0, move_type='in_refund', reversed_entry_id=bill_a.id)
        refund_line = credit_note.line_ids._gec_withholding_tax_lines()
        self.assertEqual(refund_line.balance, 30)
        self.assertFalse(refund_line.reconciled)
        tax_line_b = self._wht_bill_of(self.other, tax, 1000.0).line_ids._gec_withholding_tax_lines()
        wizard = self._wht_wizard(tax_line_b)
        self.assertEqual(wizard.amount, 20)
        self.assertTrue(refund_line.reconciled)
        wizard._create_payments()
        self.assertTrue(tax_line_b.reconciled)

    def test_withholding_payment_with_no_credit_note_proposes_the_whole_tax(self):
        tax = self._wht_tax(self.Template.ref('ge_account_331310'))
        tax_line = self._wht_bill_of(self.vendor, tax, 1000.0).line_ids._gec_withholding_tax_lines()
        self.env['res.partner'].search([('gec_treasury_code', '!=', False)]).gec_treasury_code = False
        self._treasury()
        self.assertEqual(self._wht_wizard(tax_line).amount, 50)

    def test_withholding_tax_of_usd_and_eur_bills_is_paid_in_one_gel_payment_of_the_booked_tax(self):
        usd = self.setup_other_currency('USD', rates=[('2026-01-01', 0.4), ('2026-01-15', 0.3125)])
        eur = self.setup_other_currency('EUR', rates=[('2026-01-01', 0.5), ('2026-01-15', 0.4)])
        tax = self._wht_tax(self.Template.ref('ge_account_331310'))
        bills = self.env['account.move'].concat(self._wht_bill_of(self.vendor, tax, 1000.0, currency_id=currency.id, invoice_date='2026-01-10')
            for currency in (usd, eur))
        tax_lines = bills.line_ids._gec_withholding_tax_lines()
        self.assertEqual(tax_lines.mapped('balance'), [-125.0, -100.0])
        payments = self._pay_tax(bills, payment_date='2026-01-20')
        self.assertEqual(len(payments), 1)
        self.assertEqual(payments.currency_id, self.env.company.currency_id)
        self.assertEqual(payments.amount, 225.0)
        self.assertTrue(all(tax_lines.mapped('reconciled')))

    def _cit_wizard(self, **vals):
        ref = self.Template.ref
        return self.env['l10n.ge.cit.wizard'].create({
            'journal_id': self.company_data['default_journal_misc'].id,
            'partner_id': self.vendor.id,
            'treasury_partner_id': self._treasury().id,
            'net_amount': 850,
            'distribution_account_id': ref('ge_account_530110').id,
            'cit_account_id': ref('ge_account_331110').id,
            'payable_account_id': ref('ge_account_340120').id,
            **vals,
        })

    def test_cit_wizard_needs_a_shareholder_and_a_state_treasury(self):
        for field in ('partner_id', 'treasury_partner_id'):
            with self.subTest(field=field), self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
                self._cit_wizard(**{field: False})

    def test_cit_wizard_with_no_withholding_tax_books_it_as_a_label_only(self):
        no_wht = self.env['account.tax'].create({
            'name': 'Review no withholding',
            'type_tax_use': 'none',
            'amount': 0,
            'gec_is_withholding': True,
            'price_include_override': 'tax_excluded',
        })
        wizard = self._cit_wizard(apply_dividend_wht=True, dividend_wht_tax_id=no_wht.id)
        move = self.env['account.move'].browse(wizard.action_post_cit()['res_id'])
        self.assertEqual(move.state, 'posted')
        self.assertEqual(len(move.line_ids), 3)
        self.assertEqual(move.line_ids.filtered(lambda line: line.account_id == wizard.distribution_account_id).tax_ids, no_wht)
        self.assertFalse(move.line_ids.filtered(lambda line: line.account_id == wizard.dividend_wht_account_id))

    def test_cit_wizard_books_the_dividend_tax_on_331210_with_the_treasury_as_partner(self):
        account = self.Template.ref('ge_account_331210')
        wizard = self._cit_wizard(apply_dividend_wht=True)
        self.assertEqual(wizard.dividend_wht_account_id, account)
        self.assertTrue(wizard.dividend_wht_amount)
        move = self.env['account.move'].browse(wizard.action_post_cit()['res_id'])
        line = move.line_ids.filtered(lambda line: line.account_id == account)
        self.assertEqual((line.credit, line.partner_id), (wizard.dividend_wht_amount, wizard.treasury_partner_id))

    def _partner_taxes(self, partner, company=None):
        return self.env['account.tax']._ge_partner_product_taxes(
            self.product_tax, partner, self.product, company or self.env.company, 'purchase', self.env['account.fiscal.position'])

    def _branch(self):
        company = self.env.company
        return self.env['res.company'].create({'name': 'Review branch', 'parent_id': company.id, 'country_id': company.country_id.id})

    def test_branch_gets_the_default_purchase_tax_set_on_the_parent_company(self):
        branch = self._branch()
        self.assertFalse(self.other.with_company(branch).property_purchase_tax_id)
        self.assertEqual(self._partner_taxes(self.other, branch), self.default_tax)

    def test_branch_only_user_gets_the_default_purchase_tax_set_on_the_parent_company(self):
        branch = self._branch()
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Branch user',
            'login': 'review_branch_user',
            'company_id': branch.id,
            'company_ids': [Command.set(branch.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('account.group_account_invoice').id])],
        })
        taxes = self._partner_taxes(self.other.with_user(user), branch)
        self.assertEqual(taxes.id, self.default_tax.id)

    def test_archived_default_purchase_tax_is_not_proposed(self):
        self.default_tax.action_archive()
        self.assertEqual(self._partner_taxes(self.other), self.product_tax)
