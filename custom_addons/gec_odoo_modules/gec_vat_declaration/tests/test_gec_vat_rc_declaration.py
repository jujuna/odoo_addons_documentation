from datetime import date

from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestGecVatRcDeclaration(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country('ge')
    def setUpClass(cls):
        super().setUpClass()
        ref = cls.env['account.chart.template'].ref
        cls.rc_tax = ref('ge_tax_p_rc_18_nonvatreg')
        cls.exempt_tax = ref('ge_tax_p_vat_exempt')
        cls.expense = cls.company_data['default_account_expense']
        Partner = cls.env['res.partner']
        cls.foreign_vendor = Partner.create({'name': 'US vendor', 'country_id': cls.env.ref('base.us').id})
        cls.georgian_vendor = Partner.create({'name': 'GE vendor', 'country_id': cls.env.ref('base.ge').id})
        cls.stateless_vendor = Partner.create({'name': 'Vendor without country'})
        cls.service = cls.env['product.product'].create({'name': 'Consulting', 'type': 'service'})
        cls.goods = cls.env['product.product'].create({'name': 'Widgets', 'type': 'consu'})
        cls.service_line = (cls.service, 1000.0, cls.rc_tax)

    def _bill(self, date, *lines, partner=None):
        invoice_lines = [
            self._prepare_invoice_line(product_id=product, price_unit=price, tax_ids=tax, account_id=self.expense)
            for product, price, tax in lines]
        return self._create_invoice(
            move_type='in_invoice', partner_id=partner or self.foreign_vendor, invoice_date=date, post=True,
            invoice_line_ids=invoice_lines)

    def _calc(self, month, **vals):
        declaration = self.env['gec.vat.rc.declaration'].create({'date_from': month, **vals})
        declaration.action_generate()
        return declaration

    def _reversal(self, bill, date):
        return self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=bill.ids).create(
            {'date': date, 'reason': 'test', 'journal_id': bill.journal_id.id})

    def _cancel(self, bill, date):
        self._reversal(bill, date).refund_moves()
        credit_note = bill.reversal_move_ids
        credit_note.action_post()
        return credit_note

    def _correct(self, bill, date, price, post=True):
        wizard = self._reversal(bill, date)
        wizard.modify_moves()
        new_bill = wizard.new_move_ids
        new_bill.write({
            'invoice_date': date,
            'date': date,
            'invoice_line_ids': [Command.update(line.id, {'price_unit': price}) for line in new_bill.invoice_line_ids],
        })
        if post:
            new_bill.action_post()
        return new_bill

    def _warnings(self, declaration):
        return declaration.generation_warnings or ''

    def test_part1_row_from_foreign_service_bill(self):
        bill = self._bill('2026-09-10', self.service_line)
        self._bill('2026-09-12', self.service_line, partner=self.georgian_vendor)
        self._bill('2026-09-14', (self.goods, 1000.0, self.rc_tax))
        declaration = self._calc('2026-09-01')
        self.assertRecordValues(declaration.services_line_ids, [{
            'move_id': bill.id, 'partner_name': 'US vendor', 'description': 'Consulting', 'amount': 1000.0,
            'vat': 180.0}])
        self.assertRecordValues(declaration, [{
            'services_vat_total': 180.0, 'services_vat_payable': 180.0, 'vat_accrued': 180.0}])

    def test_exempt_tax_line_gives_no_row(self):
        bill = self._bill('2026-09-10', (self.service, 500.0, self.exempt_tax), self.service_line)
        declaration = self._calc('2026-09-01')
        self.assertRecordValues(declaration.services_line_ids, [{'move_id': bill.id, 'amount': 1000.0, 'vat': 180.0}])

    def test_out_of_scope_purchase_excluded_from_bill_and_correction(self):
        out_of_scope = self.env['account.chart.template'].ref('ge_tax_p_out_of_scope')
        bill = self._bill('2026-09-10', self.service_line, (self.service, 500.0, out_of_scope))
        self._correct(bill, '2026-09-25', 1100.0)

        declaration = self._calc('2026-09-01')
        self.assertRecordValues(declaration.services_line_ids, [
            {'move_id': bill.id, 'amount': 1000.0, 'vat': 180.0}])
        self.assertRecordValues(declaration, [
            {'services_vat_before': 180.0, 'services_vat_after': 198.0, 'services_vat_payable': 198.0}])

    def test_vendor_without_country_is_left_out_with_a_warning(self):
        bill = self._bill('2026-09-10', self.service_line, partner=self.stateless_vendor)
        declaration = self._calc('2026-09-01')
        self.assertFalse(declaration.services_line_ids)
        self.assertIn('Left out of Part I', self._warnings(declaration))
        self.assertIn('%s (vendor has no country)' % bill.name, self._warnings(declaration))

    def test_vat_rows_formulas(self):
        declaration = self._calc(
            '2026-09-01', services_line_ids=[Command.create({'amount': 1000.0})],
            services_vat_before=180.0, services_vat_after=190.0)
        self.assertRecordValues(declaration, [{
            'services_amount_total': 1000.0, 'services_vat_total': 180.0, 'services_vat_increase': 10.0,
            'services_vat_decrease': 0.0, 'services_vat_payable': 190.0, 'services_vat_refund': 0.0}])
        declaration.write({'services_vat_before': -50.0, 'services_vat_after': 100.0})
        self.assertRecordValues(declaration, [{
            'services_vat_increase': 100.0, 'services_vat_decrease': 0.0, 'services_vat_payable': 280.0}])
        decrease = self._calc('2026-10-01', services_vat_before=190.0, services_vat_after=180.0)
        self.assertRecordValues(decrease, [{
            'services_vat_total': 0.0, 'services_vat_increase': 0.0, 'services_vat_decrease': 10.0,
            'services_vat_payable': 0.0, 'services_vat_refund': 10.0, 'vat_accrued': 0.0, 'vat_reduced': 10.0}])

    def test_cancellation_in_same_month_leaves_part1(self):
        bill = self._bill('2026-09-10', self.service_line)
        self._cancel(bill, '2026-09-25')
        declaration = self._calc('2026-09-01')
        self.assertFalse(declaration.services_line_ids)
        self.assertEqual(declaration.services_vat_total, 0.0)

    def test_cancellation_in_later_month_warns_in_the_credit_note_month(self):
        bill = self._bill('2026-09-10', self.service_line)
        self._cancel(bill, '2026-10-15')
        self.assertFalse(self._calc('2026-09-01').services_line_ids)
        october = self._calc('2026-10-01')
        self.assertFalse(october.services_line_ids)
        self.assertIn('was cancelled', self._warnings(october))
        self.assertIn(bill.display_name, self._warnings(october))

    def test_correction_in_same_month(self):
        bill = self._bill('2026-09-10', self.service_line)
        self._correct(bill, '2026-09-25', 1100.0)
        declaration = self._calc('2026-09-01')
        self.assertRecordValues(declaration.services_line_ids, [{'move_id': bill.id, 'amount': 1000.0, 'vat': 180.0}])
        self.assertRecordValues(declaration, [{
            'services_vat_before': 180.0, 'services_vat_after': 198.0, 'services_vat_payable': 198.0}])

    def test_correction_in_later_month(self):
        bill = self._bill('2026-09-10', self.service_line)
        self._correct(bill, '2026-10-20', 1100.0)
        september = self._calc('2026-09-01')
        self.assertRecordValues(september.services_line_ids, [{'move_id': bill.id, 'amount': 1000.0}])
        self.assertRecordValues(september, [{'services_vat_before': 0.0, 'services_vat_after': 0.0}])
        october = self._calc('2026-10-01')
        self.assertFalse(october.services_line_ids)
        self.assertRecordValues(october, [{'services_vat_before': 180.0, 'services_vat_after': 198.0}])

    def test_typed_rows_4_5_survive_generate(self):
        bill = self._bill('2026-09-10', self.service_line)
        self._correct(bill, '2026-09-25', 1100.0)
        declaration = self._calc('2026-09-01')
        declaration.services_vat_after = 200.0
        declaration.action_generate()
        self.assertRecordValues(declaration, [{
            'services_vat_before': 180.0, 'services_vat_before_proposed': 180.0,
            'services_vat_after': 200.0, 'services_vat_after_proposed': 198.0}])

    def test_correction_with_draft_new_bill_counts_as_cancelled(self):
        bill = self._bill('2026-09-10', self.service_line)
        self._correct(bill, '2026-09-25', 1100.0, post=False)
        declaration = self._calc('2026-09-01')
        self.assertFalse(declaration.services_line_ids)

    def test_adjusted_type_when_the_month_has_a_filed_calculation(self):
        first = self._calc('2026-09-01')
        self.assertEqual(first.decl_type, 'primary')
        first.action_mark_filed()
        self.assertEqual(self._calc('2026-09-01').decl_type, 'adjusted')
        self.assertEqual(self._calc('2026-10-01').decl_type, 'primary')

    def test_open_correction_lines(self):
        bill = self._bill('2026-09-10', self.service_line)
        new_bill = self._correct(bill, '2026-09-25', 1100.0)
        declaration = self._calc('2026-09-01')
        Line = self.env['account.move.line']
        self.assertEqual(Line.search(declaration.action_gec_open_before()['domain']), bill.invoice_line_ids)
        self.assertEqual(Line.search(declaration.action_gec_open_after()['domain']), new_bill.invoice_line_ids)
        october = self._calc('2026-10-01')
        self.assertEqual(october.action_gec_open_before()['domain'], [('id', 'in', [])])
        self.assertEqual(october.action_gec_open_after()['domain'], [('id', 'in', [])])

    def test_open_correction_lines_access(self):
        declaration = self._calc('2026-09-01')
        groups = self.env.ref('base.group_user') | self.env.ref('account.group_account_readonly')
        other = self.setup_other_company()['company']
        user = self.env['res.users'].create({
            'name': 'rc_other', 'login': 'rc_other', 'group_ids': [Command.set(groups.ids)],
            'company_id': other.id, 'company_ids': [Command.set(other.ids)]})
        for action in ('action_gec_open_before', 'action_gec_open_after'):
            with self.assertRaises(AccessError):
                getattr(declaration.with_user(user), action)()

    def test_typed_goods_row(self):
        self._bill('2026-09-10', self.service_line)
        declaration = self._calc('2026-09-01')
        declaration.write({'goods_line_ids': [Command.create({'part': 'goods', 'amount': 1000.0})]})
        self.assertRecordValues(declaration, [{
            'goods_vat_total': 180.0, 'goods_vat_payable': 180.0, 'vat_accrued': 360.0}])
        self.assertEqual(declaration.goods_line_ids.vat, 180.0)
        declaration.action_generate()
        self.assertEqual(declaration.goods_vat_total, 180.0)

    def test_filed_calculation_cannot_be_generated_or_deleted(self):
        declaration = self._calc('2026-09-01')
        declaration.action_mark_filed()
        with self.assertRaises(UserError):
            declaration.action_generate()
        with self.assertRaises(UserError):
            declaration.unlink()
        declaration.action_draft()
        declaration.unlink()
        self.assertFalse(declaration.exists())

    def _typed_goods(self, amount=500.0):
        return self._calc('2026-09-01', goods_line_ids=[Command.create({'part': 'goods', 'amount': amount})])

    def test_filed_calculation_refuses_changes(self):
        self._bill('2026-09-10', self.service_line)
        declaration = self._typed_goods()
        row = declaration.goods_line_ids
        declaration.action_mark_filed()
        declaration.write({'portal_number': 'X'})
        self.assertEqual(declaration.portal_number, 'X')
        with self.assertRaises(UserError):
            declaration.write({'services_vat_before': 5.0})
        with self.assertRaises(UserError):
            row.write({'amount': 600.0})
        with self.assertRaises(UserError):
            self.env['gec.vat.rc.line'].create({'declaration_id': declaration.id, 'part': 'goods', 'amount': 100.0})
        with self.assertRaises(UserError):
            row.unlink()
        declaration.action_draft()
        declaration.write({'services_vat_before': 5.0})
        self.assertEqual(declaration.services_vat_before, 5.0)

    def test_bill_on_filed_calculation_cannot_be_deleted(self):
        bill = self._bill('2026-09-10', self.service_line)
        declaration = self._calc('2026-09-01')
        bill.button_draft()
        declaration.action_mark_filed()
        with self.assertRaises(UserError):
            bill.unlink()
        declaration.action_draft()
        bill.unlink()
        self.assertFalse(declaration.services_line_ids)

    def test_negative_typed_row_refused(self):
        with self.assertRaises(ValidationError):
            self._typed_goods(-100.0)

    def test_row_vat_stays_at_portal_rate(self):
        declaration = self._typed_goods()
        self.assertEqual(declaration.goods_line_ids.vat, 90.0)
        self.rc_tax.amount = 20
        self.assertEqual(declaration.goods_line_ids.vat, 90.0)
        declaration.action_mark_filed()
        self.assertEqual(declaration.goods_line_ids.vat, 90.0)
        self.assertEqual(declaration.state, 'filed')

    def test_mark_filed_without_reverse_charge_tax(self):
        declaration = self._typed_goods()
        Data = self.env['ir.model.data'].sudo()
        Data.search([('model', '=', 'account.tax'), ('res_id', '=', self.rc_tax.id)]).unlink()
        declaration.action_generate()
        self.assertIn('Reverse Charge 18% Non-Deductible is missing', self._warnings(declaration))
        declaration.action_mark_filed()
        self.assertEqual(declaration.state, 'filed')

    def test_current_month_cannot_be_marked_filed(self):
        declaration = self._calc(fields.Date.context_today(self.env.company).replace(day=1))
        lock_date = self.env.company.tax_lock_date
        with self.assertRaises(UserError):
            declaration.action_mark_filed()
        self.assertEqual(declaration.state, 'draft')
        self.assertEqual(self.env.company.tax_lock_date, lock_date)

    def test_mark_filed_locks_the_tax_month(self):
        self._calc('2026-09-01').action_mark_filed()
        self.assertEqual(self.env.company.tax_lock_date, date(2026, 9, 30))

    def test_mark_filed_keeps_a_later_tax_lock_date(self):
        self.env.company.tax_lock_date = '2026-10-31'
        self._calc('2026-09-01').action_mark_filed()
        self.assertEqual(self.env.company.tax_lock_date, date(2026, 10, 31))

    def test_mark_filed_refused_while_an_earlier_month_is_not_filed(self):
        august, september = self._calc('2026-08-01'), self._calc('2026-09-01')
        with self.assertRaises(UserError) as error:
            september.action_mark_filed()
        self.assertIn(august.name, str(error.exception))
        self.assertEqual(september.state, 'draft')
        august.action_mark_filed()
        self.assertEqual(self._calc('2026-08-01').decl_type, 'adjusted')
        september.action_mark_filed()
        self.assertEqual(september.state, 'filed')

    def test_bill_without_reverse_charge_tax_is_listed_after_generate(self):
        untaxed = self._bill('2026-09-10', (self.service, 1000.0, self.env['account.tax']))
        taxed = self._bill('2026-09-12', self.service_line)
        warning = next(line for line in self._warnings(self._calc('2026-09-01')).splitlines() if 'have no reverse-charge tax' in line)
        self.assertIn(untaxed.name, warning)
        self.assertNotIn(taxed.name, warning)
