from datetime import date

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import new_test_user, tagged

from odoo.addons.geo_payroll.tests.common import GeoPayrollCase

SELF_PAYING_NOTE = "Tax was withheld from a recipient who pays their own tax"


@tagged('post_install', '-at_install')
class TestReviewFixes(GeoPayrollCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env['account.account']
        cls.accounts = {code: Account.create({
            'name': f'Form30 Test {code}',
            'code': f'F{code}',
            'account_type': account_type,
            'reconcile': account_type == 'liability_payable',
        }) for code, account_type in [
            ('7410', 'expense'),
            ('7490', 'expense'),
            ('3130', 'liability_payable'),
            ('3181', 'liability_payable'),
            ('3182', 'liability_payable'),
            ('3320', 'liability_payable'),
            ('1410', 'asset_current'),
        ]}
        cls.bank_journal = cls.env['account.journal'].create({
            'name': 'Form30 Test Bank',
            'code': 'F30B',
            'type': 'bank',
            'company_id': cls.company.id,
        })
        cls.misc_journal = cls.env['account.journal'].create({
            'name': 'Form30 Test Misc',
            'code': 'F30M',
            'type': 'general',
            'company_id': cls.company.id,
        })
        cls.bank_journal.outbound_payment_method_line_ids.payment_account_id = Account.create({
            'name': 'Form30 Test Outstanding',
            'code': 'F1210OUT',
            'account_type': 'asset_current',
            'reconcile': True,
        })
        structure = cls.structures['monthly']
        structure.with_company(cls.company).journal_id = cls.env['account.journal'].create({
            'name': 'Form30 Test Salaries',
            'code': 'F30S',
            'type': 'general',
            'company_id': cls.company.id,
        })
        for rule in structure.rule_ids.with_company(cls.company):
            if rule.code in ('GROSS', 'LOAN'):
                continue
            if rule.code == 'NET':
                rule.account_credit = cls.accounts['3130']
            elif rule.code == 'PENSION_ER':
                rule.account_debit, rule.account_credit = cls.accounts['7490'], cls.accounts['3181']
            elif rule.code == 'PENSION_EE':
                rule.account_debit = cls.accounts['3182']
            elif rule.code == 'PIT':
                rule.account_debit = cls.accounts['3320']
            else:
                rule.account_debit = cls.accounts['7410']
        cls.feb, cls.mar, cls.apr = cls.env['rs.form30.declaration'].create(
            [{'company_id': cls.company.id, 'date_from': date(2026, month, 1)} for month in (2, 3, 4)])
        cls.feb.export_warned_rows = True
        cls.manager = new_test_user(cls.env, login='form30_manager', groups='base.group_user,account.group_account_manager')
        cls.tax = cls.env['account.tax'].create({
            'name': 'Form30 test WHT',
            'amount': 5.0,
            'type_tax_use': 'purchase',
            'rs_form30_service_type_id': cls.env.ref('gec_income_tax_report.service_type_1').id,
        })
        cls.provider = cls.env['res.partner'].create({'name': 'Form30 Test Provider'})

    def _validated_slip(self, employee, structure=None):
        slip = self._make_payslip(employee, structure=structure, worked_hours=self.period_hours, worked_days=self.period_days)
        slip.compute_sheet()
        slip.action_payslip_done()
        slip.move_id.filtered(lambda move: move.state == 'draft').action_post()
        return slip

    def _pay(self, slip, day):
        action = slip.with_context(hr_payroll_payment_register=True).action_register_payment()
        self.env['account.payment.register'].with_context(**action['context']).create(
            {'journal_id': self.bank_journal.id, 'payment_date': day})._create_payments()

    def _pay_net(self, slip, amount, day):
        """A part of the net pay, reconciled by hand: the payment wizard refuses a line that is already part paid."""
        net = self.accounts['3130']
        payment = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': slip.employee_id.work_contact_id.id,
            'amount': amount,
            'date': day,
            'journal_id': self.bank_journal.id,
            'destination_account_id': net.id,
        })
        payment.action_post()
        (slip._gec_net_payable_lines() | payment.move_id.line_ids.filtered(lambda line: line.account_id == net)).reconcile()

    def _offset(self, slip, day, account):
        """The net pay closed by an entry: Dr the NET account of the slip, Cr ``account``, reconciled with the net line."""
        net = self.accounts['3130']
        partner = slip.employee_id.work_contact_id
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.misc_journal.id,
            'date': day,
            'line_ids': [
                Command.create({'account_id': net.id, 'partner_id': partner.id, 'debit': slip.net_wage}),
                Command.create({'account_id': account.id, 'partner_id': partner.id, 'credit': slip.net_wage}),
            ],
        })
        move.action_post()
        (slip._gec_net_payable_lines() | move.line_ids.filtered(lambda line: line.account_id == net and line.debit)).reconcile()
        return move

    def _correct(self, origin, wage, day=date(2026, 2, 20)):
        """The entries are dated ``day``, not today: a payment counts no earlier than the entry it settles."""
        origin.version_id.wage = wage
        refund, correction = self._make_correction_pair(origin)
        slips = (refund | correction).filtered(lambda slip: slip.state == 'draft')
        slips.action_payslip_done()
        slips.move_id.filtered(lambda move: move.state == 'draft').action_post()
        slips.move_id.button_draft()
        slips.move_id.write({'name': '/', 'date': day})
        slips.move_id.action_post()
        return correction

    def _employee_and_origin(self):
        employee = self._make_employee('fixed', wage=1000.0, pension_fund_member=True, identification_id='01008057135')
        employee.work_contact_id.rs_form30_category_id = self.env.ref('gec_income_tax_report.category_4')
        return employee, self._validated_slip(employee)

    def _gross_tax_pension(self, slip):
        return [self._line_total(slip, 'GROSS'), -self._line_total(slip, 'PIT'), -self._line_total(slip, 'PENSION_EE')]

    def test_correction_lowering_tax_after_filing_makes_no_row(self):
        employee, origin = self._employee_and_origin()
        self._pay(origin, date(2026, 2, 10))
        self.feb.action_generate()
        self.feb.action_export()
        self.assertTrue(self.feb.line_ids.filtered('in_file'))
        self.env['hr.payroll.tax.exemption'].create({
            'name': 'Form30 test',
            'yearly_limit': 1000000.0,
            'employee_ids': [Command.set(employee.ids)],
        })
        correction = self._correct(origin, 1000.0)
        self.assertEqual(self._gross_tax_pension(correction)[1], 0.0)
        self._pay(correction, date(2026, 3, 10))

        self.mar.action_generate()

        self.assertFalse(self.mar.line_ids)
        self.assertIn("changes figures already declared", self.mar.generation_warnings)

    def test_correction_raising_gross_after_filing_declares_the_difference(self):
        _employee, origin = self._employee_and_origin()
        self._pay(origin, date(2026, 2, 10))
        self.feb.action_generate()
        self.feb.action_export()
        filed = self.feb.line_ids
        self.assertEqual(len(filed), 1)
        correction = self._correct(origin, 1100.0)
        self._pay(correction, date(2026, 3, 10))

        self.mar.action_generate()

        line = self.mar.line_ids
        self.assertEqual(len(line), 1)
        gross, tax, pension = self._gross_tax_pension(correction)
        self.assertAlmostEqual(line.amount, gross - filed.amount, places=2)
        self.assertAlmostEqual(line.tax_amount, tax - filed.tax_amount, places=2)
        self.assertAlmostEqual(line.pension_amount, pension - filed.pension_amount, places=2)
        self.assertGreater(line.amount, 0.0)
        self.assertIn("after earlier months were filed", line.warning)

    def test_correction_waits_for_the_export_of_an_earlier_month(self):
        _employee, origin = self._employee_and_origin()
        self._pay_net(origin, 400.0, date(2026, 2, 10))
        self.feb.action_generate()
        self.feb.action_export()
        self._pay_net(origin, origin.net_wage - 400.0, date(2026, 3, 10))
        self.mar.action_generate()
        self.assertEqual(len(self.mar.line_ids), 1)
        self.assertFalse(self.mar.line_ids.in_file)
        correction = self._correct(origin, 1100.0)
        self._pay(correction, date(2026, 4, 10))

        self.apr.action_generate()

        self.assertFalse(self.apr.line_ids)
        self.assertIn("export the declaration of 2026/03", self.apr.generation_warnings)

    def test_net_pay_closed_by_an_offset_entry_is_declared_in_the_month_of_the_offset(self):
        _employee, origin = self._employee_and_origin()
        offset = self._offset(origin, date(2026, 2, 10), self.accounts['1410'])

        self.feb.action_generate()

        row = self.feb.line_ids
        self.assertEqual(len(row), 1)
        self.assertEqual(row.payslip_id, origin)
        self.assertEqual(row.date, date(2026, 2, 10))
        self.assertEqual(row.settlement_move_ids, offset)
        self.assertIn("Settled by an offset entry", row.warning)

    def test_exported_offset_row_is_not_declared_again_next_month_or_after_a_reset(self):
        _employee, origin = self._employee_and_origin()
        self._offset(origin, date(2026, 2, 10), self.accounts['1410'])
        self.feb.action_generate()
        self.feb.action_export()

        self.mar.action_generate()
        self.feb.action_draft()
        self.feb.action_generate()

        self.assertFalse(self.mar.line_ids)
        self.assertEqual(len(self.feb.line_ids), 1)
        self.assertTrue(self.feb.line_ids.in_file)

    def test_reclass_entry_on_a_liability_account_is_not_declared_as_an_offset(self):
        _employee, origin = self._employee_and_origin()
        self._offset(origin, date(2026, 2, 10), self.accounts['3181'])

        self.feb.action_generate()

        self.assertFalse(self.feb.line_ids)

    def test_reclass_entry_on_the_same_account_is_not_an_offset(self):
        _employee, origin = self._employee_and_origin()
        self._offset(origin, date(2026, 2, 10), self.accounts['3130'])

        self.feb.action_generate()

        self.assertFalse(self.feb.line_ids)
        parts = origin._rs_form30_net_lines()._rs_form30_cash_parts()
        self.assertFalse([part for item in parts.values() for part in item['cash']])
        self.assertTrue([part for item in parts.values() for part in item['other']])

    def test_unreconciling_the_offset_after_export_blocks_the_filed_row(self):
        _employee, origin = self._employee_and_origin()
        offset = self._offset(origin, date(2026, 2, 10), self.accounts['1410'])
        self.feb.action_generate()
        self.feb.action_export()
        offset.line_ids.remove_move_reconcile()

        self.feb.action_draft()
        self.feb.action_generate()

        row = self.feb.line_ids
        self.assertEqual(len(row), 1)
        self.assertTrue(row.in_file)
        self.assertIn("Filed, but its payment or source changed after the export", row.warning)
        self.assertEqual(row.issue_level, 'blocker')

    def test_payment_before_the_payslip_entry_is_declared_in_the_month_of_the_entry(self):
        december, january = self.env['rs.form30.declaration'].create(
            [{'company_id': self.company.id, 'date_from': date(*month, 1)} for month in ((2025, 12), (2026, 1))])
        _employee, origin = self._employee_and_origin()
        self._pay_net(origin, origin.net_wage, date(2025, 12, 20))

        december.action_generate()
        january.action_generate()

        self.assertFalse(december.line_ids)
        self.assertEqual(january.line_ids.payslip_id, origin)
        self.assertEqual(january.line_ids.date, origin.move_id.date)
        self.assertIn("Paid in advance", january.line_ids.warning)

    def test_payment_matched_with_a_bank_line_keeps_the_bank_month_when_the_payment_is_dated_later(self):
        _employee, origin = self._employee_and_origin()
        self._pay_net(origin, origin.net_wage, date(2026, 3, 10))
        payment = origin._rs_form30_net_lines().matched_debit_ids.debit_move_id.payment_id
        statement_line = self.env['account.bank.statement.line'].create({
            'payment_ref': payment.name,
            'journal_id': self.bank_journal.id,
            'partner_id': payment.partner_id.id,
            'amount': -payment.amount,
            'date': date(2026, 2, 20),
        })
        suspense = statement_line._seek_for_lines()[1]
        outstanding = payment._seek_for_lines()[0]
        suspense.account_id = outstanding.account_id
        (suspense + outstanding).reconcile()
        self.assertEqual(payment.reconciled_statement_line_ids, statement_line)

        parts = origin._rs_form30_net_lines()._rs_form30_cash_parts()

        self.assertEqual([part['date'] for item in parts.values() for part in item['cash']], [date(2026, 2, 20)])
        self.feb.action_generate()
        self.assertEqual(self.feb.line_ids.payslip_id, origin)
        self.assertEqual(self.feb.line_ids.date, date(2026, 2, 20))

    def _assert_edit_keeps_shipped_record(self, record, vals):
        data = self.env['ir.model.data'].search([('module', '=', 'gec_income_tax_report'), ('model', '=', record._name), ('res_id', '=', record.id)])
        self.assertEqual(len(data), 1)
        data.noupdate = False
        record.with_user(self.manager).write(vals)
        self.assertTrue(data.noupdate)

    def test_manager_edit_of_shipped_engine_band_is_kept_and_delete_is_refused(self):
        engine = self.env.ref('gec_income_tax_report.car_engine_1')
        self._assert_edit_keeps_shipped_record(engine, {'amount': 350.0})
        self.assertEqual(engine.amount, 350.0)
        with self.assertRaises(AccessError):
            engine.with_user(self.manager).unlink()

    def test_manager_edit_of_shipped_rate_rule_is_kept_and_delete_is_refused(self):
        rule = self.env.ref('gec_income_tax_report.rate_rule_4_1_20')
        self._assert_edit_keeps_shipped_record(rule, {'note': 'edited'})
        with self.assertRaises(AccessError):
            rule.with_user(self.manager).unlink()

    def _entry_service_vals(self, row):
        row = {'date': date(2026, 2, 10), 'gross': 1000.0, 'payment_ids': [], 'statement_ids': [], 'move_ids': [], **row}
        return self.feb._rs_form30_entry_service_vals(self.env['account.move'], {'taxes': self.tax}, self.provider, row, [])

    def test_entry_service_row_notes_tax_withheld_from_self_paying_recipient(self):
        vals = self._entry_service_vals({'tax': 50.0})
        self.assertIn(SELF_PAYING_NOTE, vals['warning'])
        self.assertEqual(vals['issue_level'], 'note')

    def test_entry_service_row_without_tax_has_no_note(self):
        for row in ({'tax': 0.0}, {}):
            vals = self._entry_service_vals(row)
            self.assertNotIn(SELF_PAYING_NOTE, vals['warning'])
            self.assertFalse(vals['issue_level'])

    def test_explanation_workbook_runs_for_a_user_without_fleet_access(self):
        user = new_test_user(self.env, login='form30_accountant', groups='base.group_user,account.group_account_user')
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'Form30 Brand'})
        model = self.env['fleet.vehicle.model'].create({'name': 'Form30 Model', 'brand_id': brand.id})
        vehicle = self.env['fleet.vehicle'].create({'model_id': model.id, 'license_plate': 'F30-001'})
        self.env['rs.form30.car.line'].create({
            'declaration_id': self.feb.id,
            'vehicle_id': vehicle.id,
            'engine_id': self.env.ref('gec_income_tax_report.car_engine_1').id,
        })
        self.assertFalse(vehicle.with_user(user).has_access('read'))
        declaration = self.feb.with_user(user)
        self.assertFalse(declaration.env.su)
        self.assertEqual(declaration.env.user, user)

        self.assertTrue(declaration._explanation_workbook())

    def _refund(self, slip, day):
        refund = slip._action_refund_payslips()
        refund.move_id.button_draft()
        refund.move_id.write({'name': '/', 'date': day})
        refund.move_id.action_post()
        return refund

    def test_row_of_a_refunded_payslip_warns_reversed_after_payment(self):
        _employee, origin = self._employee_and_origin()
        self._pay(origin, date(2026, 2, 10))
        self.feb.action_generate()
        self.assertNotIn("Reversed after payment", self.feb.line_ids.warning)
        self._refund(origin, date(2026, 2, 20))

        self.feb.action_generate()

        self.assertEqual(len(self.feb.line_ids), 1)
        self.assertIn("Reversed after payment: correct the declaration.", self.feb.line_ids.warning)
        self.assertEqual(self.feb.line_ids.issue_level, 'warning')

    def test_refund_dated_after_filing_warns_on_the_later_declaration(self):
        _employee, origin = self._employee_and_origin()
        self._pay(origin, date(2026, 2, 10))
        self.feb.action_generate()
        self.feb.action_export()
        refund = self._refund(origin, date(2026, 3, 5))

        self.mar.action_generate()

        self.assertIn("changes figures already declared for", self.mar.generation_warnings)
        self.assertIn(refund.name, self.mar.generation_warnings)

    def test_exemption_relief_stops_when_the_yearly_allowance_is_used_up(self):
        employee = self._make_employee('fixed', wage=1000.0, identification_id='01008057135')
        self.env['hr.payroll.tax.exemption'].create({'name': 'Form30 test', 'yearly_limit': 1.0, 'employee_ids': [Command.set(employee.ids)]})
        first = self._validated_slip(employee)
        self._pay(first, date(2026, 2, 10))
        second = self._make_payslip(employee, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28), worked_hours=160.0)
        second.compute_sheet()
        second.action_payslip_done()
        second.move_id.filtered(lambda move: move.state == 'draft').action_post()
        self._pay(second, date(2026, 3, 10))

        self.feb.action_generate()
        self.mar.action_generate()

        self.assertEqual(self.feb.line_ids.payslip_id, first)
        self.assertGreater(self.feb.line_ids.other_relief, 0.0)
        self.assertIn("Relief derived", self.feb.line_ids.warning)
        self.assertEqual(self.mar.line_ids.payslip_id, second)
        self.assertEqual(self.mar.line_ids.other_relief, 0.0)
        self.assertNotIn("Relief derived", self.mar.line_ids.warning)

    def test_car_line_amount_keeps_the_band_amount_it_was_filed_with(self):
        engine, other_engine = self.env.ref('gec_income_tax_report.car_engine_1'), self.env.ref('gec_income_tax_report.car_engine_2')
        line = self.env['rs.form30.car.line'].create({'declaration_id': self.feb.id, 'engine_id': engine.id})
        amount = engine.amount
        self.assertEqual(line.amount, amount)

        engine.amount = amount + 50.0
        self.assertEqual(line.amount, amount)

        line.engine_id = other_engine
        self.assertEqual(line.amount, other_engine.amount)

    def test_car_line_refuses_an_employee_of_another_company(self):
        other_company = self.env['res.company'].create({'name': 'Form30 Other Company'})
        stranger = self.env['hr.employee'].create({'name': 'Form30 Stranger', 'company_id': other_company.id, 'identification_id': '01008057136'})
        employee = self._make_employee('fixed', identification_id='01008057135')
        vals = {'declaration_id': self.feb.id, 'engine_id': self.env.ref('gec_income_tax_report.car_engine_1').id}
        with self.assertRaises(UserError):
            self.env['rs.form30.car.line'].create({**vals, 'employee_id': stranger.id})
        line = self.env['rs.form30.car.line'].create(vals)
        with self.assertRaises(UserError):
            line.write({'employee_id': stranger.id})

        foreign = self.env['rs.form30.car.line'].new({**vals, 'employee_id': stranger.id})
        foreign._onchange_employee_id()
        self.assertFalse(foreign.name)
        self.assertFalse(foreign.identification)
        own = self.env['rs.form30.car.line'].new({**vals, 'employee_id': employee.id})
        own._onchange_employee_id()
        self.assertEqual(own.identification, '01008057135')

    def test_tax_change_rewrites_the_rate_in_label_and_description_of_every_language(self):
        self.env['res.lang']._activate_lang('ka_GE')
        tax = self.env['account.tax'].create({
            'name': 'Form30 label tax 20%',
            'amount': -20,
            'amount_type': 'percent',
            'type_tax_use': 'purchase',
            'is_withholding_tax': False,
            'gec_is_withholding': True,
            'price_include_override': 'tax_excluded',
            'withholding_sequence_id': self.env['ir.sequence'].create({'name': 'Form30 label WHT'}).id,
            'rs_form30_income_type_id': self.env['rs.form30.income.type'].create({'code': 'TEST_LABEL', 'name': 'Test income'}).id,
            'invoice_label': 'WHT 20% (RES roy)',
            'description': '<div>WHT 20%</div>',
        })
        tax.update_field_translations('description', {'ka_GE': {'WHT 20%': 'წყაროსთან დაკავება 20%'}})
        wizard = self.env['rs.form30.tax.change'].create({
            'tax_id': tax.id,
            'change_kind': 'tax',
            'old_rate': 20,
            'new_rate': 12,
            'effective_date': date(2026, 10, 1),
            'new_tax_name': 'Form30 label tax 12%',
        })

        wizard.action_apply()

        new, old = wizard.result_tax_id, tax
        self.assertEqual(new.with_context(lang='en_US').invoice_label, 'WHT 12% (RES roy)')
        self.assertEqual(new.with_context(lang='en_US').description, '<div>WHT 12%</div>')
        self.assertEqual(new.with_context(lang='ka_GE').description, '<div>წყაროსთან დაკავება 12%</div>')
        self.assertEqual(old.with_context(lang='en_US').invoice_label, 'WHT 20% (RES roy)')
        self.assertEqual(old.with_context(lang='en_US').description, '<div>WHT 20%</div>')
        self.assertEqual(old.with_context(lang='ka_GE').description, '<div>წყაროსთან დაკავება 20%</div>')

    def _exported_february(self):
        _employee, origin = self._employee_and_origin()
        self._pay(origin, date(2026, 2, 10))
        self.feb.action_generate()
        self.feb.action_export()

    def _flush_tracking(self):
        self.env.flush_all()
        self.env.cr.flush()

    def test_only_an_accounting_manager_resets_an_exported_declaration(self):
        self._exported_february()
        accountant = new_test_user(self.env, login='form30_reset_accountant', groups='base.group_user,account.group_account_user')

        with self.assertRaises(UserError):
            self.feb.with_user(accountant).action_draft()
        with self.assertRaises(UserError):
            self.feb.with_user(accountant).write({'state': 'draft'})
        self.assertEqual(self.feb.state, 'exported')

        self.feb.with_user(self.manager).action_draft()
        self.assertEqual(self.feb.state, 'draft')

    def test_export_and_reset_are_recorded_in_the_chatter(self):
        self._flush_tracking()
        self._exported_february()
        self._flush_tracking()
        self.feb.action_draft()
        self._flush_tracking()

        tracking = self.feb.message_ids.filtered(lambda message: message.message_type == 'tracking')

        self.assertEqual(len(tracking), 2)
        self.assertIn("Exported", tracking[0].body)
        self.assertIn("Draft", tracking[0].body)

    def test_salary_rows_come_only_from_payslips_on_payroll_structure_types_of_geo_payroll(self):
        geo_structure = self.structures['monthly']
        foreign_type = self.env['hr.payroll.structure.type'].create({'name': 'Form30 Foreign Type'})
        foreign_structure = geo_structure.copy({'name': 'Form30 Foreign Structure', 'type_id': foreign_type.id})
        duplicated_structure = geo_structure.copy({'name': 'Form30 Duplicated Structure'})
        slips = self.env['hr.payslip']
        for index, structure in enumerate((geo_structure, foreign_structure, duplicated_structure)):
            employee = self._make_employee('fixed', wage=1000.0, pension_fund_member=True, identification_id=f'0100805713{index}')
            employee.work_contact_id.rs_form30_category_id = self.env.ref('gec_income_tax_report.category_4')
            slips |= self._validated_slip(employee, structure)
            self._pay(slips[-1], date(2026, 2, 10))
        geo_slip, foreign_slip, duplicated_slip = slips

        self.feb.action_generate()

        self.assertEqual(self.feb.line_ids.payslip_id, geo_slip | duplicated_slip)
        row = self.feb.line_ids.filtered(lambda line: line.payslip_id == geo_slip)
        self.assertEqual([row.amount, row.tax_amount, row.pension_amount], self._gross_tax_pension(geo_slip))
        self.assertNotIn(foreign_slip, self.feb.line_ids.payslip_id)
