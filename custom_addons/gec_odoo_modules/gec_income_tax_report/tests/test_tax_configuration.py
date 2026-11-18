from datetime import date

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestForm30TaxConfiguration(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.income = cls.env['rs.form30.income.type'].create({'code': 'TEST_CONFIG', 'name': 'Test income'})
        cls.category = cls.env.ref('gec_income_tax_report.category_30')
        cls.tax = cls.env['account.tax'].create({
            'name': 'Test configuration 5%', 'amount': -5, 'amount_type': 'percent',
            'type_tax_use': 'purchase', 'is_withholding_tax': False,
            'gec_is_withholding': True, 'price_include_override': 'tax_excluded',
            'withholding_sequence_id': cls.env['ir.sequence'].create({'name': 'Configuration WHT'}).id,
            'rs_form30_income_type_id': cls.income.id,
        })
        cls.rule = cls.env['rs.form30.rate.rule'].create({
            'category_id': cls.category.id, 'income_type_id': cls.income.id, 'rate': 5,
        })

    def _wizard(self, **values):
        return self.env['rs.form30.tax.change'].create({
            'tax_id': self.tax.id, 'old_rate': 5, 'new_rate': 10,
            'effective_date': date(2026, 10, 1), 'new_tax_name': 'Test replacement 10%',
            'category_ids': [Command.set(self.category.ids)], **values,
        })

    def _rates(self, period):
        return self.env['rs.form30.rate.rule']._allowed_rates(period).get((self.category.id, self.income.id), [])

    def test_combined_change_preserves_tax_and_old_period(self):
        wizard = self._wizard()
        action = wizard.action_apply()
        replacement = wizard.result_tax_id
        self.assertEqual(action['res_id'], replacement.id)
        self.assertEqual(self.tax.amount, -5)
        self.assertEqual(replacement.amount, -10)
        self.assertEqual(replacement.rs_form30_previous_tax_id, self.tax)
        self.assertEqual(self.tax.rs_form30_date_to, date(2026, 9, 30))
        self.assertEqual(replacement.rs_form30_date_from, date(2026, 10, 1))
        self.assertEqual(self._rates(202609), [5])
        self.assertEqual(self._rates(202610), [10])
        self.assertEqual(replacement.tax_group_id, self.tax.tax_group_id)
        self.assertEqual(replacement.withholding_sequence_id, self.tax.withholding_sequence_id)
        self.assertEqual(len(replacement.repartition_line_ids), len(self.tax.repartition_line_ids))
        self.assertEqual(replacement.repartition_line_ids.mapped('account_id'), self.tax.repartition_line_ids.mapped('account_id'))
        self.assertEqual(replacement.repartition_line_ids.mapped('tag_ids'), self.tax.repartition_line_ids.mapped('tag_ids'))
        for tax, expected in [(replacement, -100), (self.tax, -50)]:
            self.assertEqual([item['amount'] for item in tax.compute_all(1000)['taxes']], [expected])
            base = tax._prepare_base_line_for_taxes_computation(
                None, tax_ids=tax, currency_id=tax.company_id.currency_id,
                price_unit=1000, quantity=1, calculate_withholding_taxes=True)
            tax._add_tax_details_in_base_line(base, tax.company_id)
            tax._round_base_lines_tax_details([base], tax.company_id)
            self.assertAlmostEqual(base['tax_details']['taxes_data'][0]['tax_amount_currency'], expected)
        with self.assertRaises(UserError):
            wizard.action_apply()

    def test_tax_only_leaves_matrix_unchanged(self):
        self._wizard(change_kind='tax').action_apply()
        self.assertEqual(self._rates(202610), [5])
        self.assertEqual(self.rule.valid_to, 0)

    def test_rules_only_preserves_all_accounting_taxes(self):
        other = self.tax.copy({'name': 'Other shared tax'})
        self._wizard(change_kind='rules').action_apply()
        self.assertEqual(self.tax.amount, -5)
        self.assertEqual(other.amount, -5)
        self.assertFalse(self.tax.rs_form30_date_to)
        self.assertEqual(other.rs_form30_rule_ids, self.tax.rs_form30_rule_ids)
        self.assertEqual(self._rates(202610), [10])

    def test_allow_and_stop_category_eligibility(self):
        self._wizard(change_kind='rules', rule_action='allow').action_apply()
        self.assertEqual(sorted(self._rates(202610)), [5, 10])
        self._wizard(change_kind='rules', rule_action='stop', effective_date=date(2026, 11, 1)).action_apply()
        self.assertEqual(self._rates(202611), [10])
        self.assertEqual(sorted(self._rates(202610)), [5, 10])

    def test_finite_validity_is_preserved(self):
        self.rule.valid_to = 202612
        self._wizard().action_apply()
        self.assertEqual(self._rates(202612), [10])
        self.assertEqual(self._rates(202701), [])

    def test_existing_allowed_rate_is_reused(self):
        self.rule.copy({'rate': 10})
        self._wizard().action_apply()
        self.assertEqual(self._rates(202610), [10])
        self.assertEqual(len(self.tax.rs_form30_rule_ids), 2)

    def test_conflicting_future_rule_rejects_whole_change(self):
        self.rule.copy({'rate': 10, 'valid_from': 202612})
        wizard = self._wizard()
        with self.assertRaises(UserError), self.cr.savepoint():
            wizard.action_apply()
        self.assertFalse(wizard.applied)
        self.assertFalse(self.tax.rs_form30_date_to)
        self.assertEqual(self.rule.valid_to, 0)

    def test_normal_tax_edit_does_not_authorize_rs_rate(self):
        self.tax.amount = -17
        self.assertEqual(self._rates(202610), [5])

    def test_manual_rule_edit_survives_csv_reload(self):
        rule = self.env.ref('gec_income_tax_report.rate_rule_30_2_5')
        rule.with_context(install_mode=False).write({'valid_to': 202609})
        xmlid = self.env['ir.model.data'].search([
            ('module', '=', 'gec_income_tax_report'), ('name', '=', 'rate_rule_30_2_5')])
        self.assertTrue(xmlid.noupdate)
        self.env.flush_all()  # Simulate a later upgrade reading the committed flag through SQL.
        self.env['rs.form30.rate.rule']._load_records([{
            'xml_id': 'gec_income_tax_report.rate_rule_30_2_5',
            'values': {'valid_to': 0},
        }], update=True)
        self.assertEqual(rule.valid_to, 202609)

    def test_invalid_month_and_ranges(self):
        with self.assertRaises(UserError):
            self._wizard(effective_date=date(2026, 10, 2)).action_apply()
        for values in ({'valid_from': 202613}, {'valid_from': 202610, 'valid_to': 202609}, {'rate': -1}):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.rule.write(values)

    def test_wizard_form_defaults_and_preview(self):
        with Form(self.env['rs.form30.tax.change'].with_context(default_tax_id=self.tax.id)) as form:
            form.effective_date = date(2026, 10, 1)
            form.new_rate = 10
            self.assertEqual(form.old_rate, 5)
            self.assertIn('10%', form.new_tax_name)
            self.assertIn('shared', form.preview)
            wizard = form.save()
        self.assertEqual(wizard.category_ids, self.category)
        wizard.action_apply()

    def test_non_manager_cannot_apply(self):
        user = self.env['res.users'].create({
            'name': 'Form 30 accountant', 'login': 'form30_config_accountant',
            'group_ids': [Command.set([self.env.ref('account.group_account_user').id])],
            'company_id': self.env.company.id, 'company_ids': [Command.set(self.env.company.ids)],
        })
        with self.assertRaises(AccessError):
            self.tax.with_user(user).action_rs_form30_change()
        with self.assertRaises(AccessError):
            self._wizard().with_user(user).action_apply()

    def test_history_boundaries_and_shared_resolver(self):
        partner = self.env['res.partner'].create({
            'name': 'Historical recipient', 'rs_form30_category_id': self.category.id})
        salary_category = self.env.ref('gec_income_tax_report.category_4')
        declaration = self.env['rs.form30.declaration'].new({'date_from': date(2026, 9, 1)})
        self.assertEqual(partner._rs_form30_category_on(date(2026, 1, 1)), self.category)
        partner.rs_form30_category_history_ids = [
            Command.create({'category_id': self.category.id, 'date_from': False, 'date_to': date(2026, 9, 14)}),
            Command.create({'category_id': salary_category.id, 'date_from': date(2026, 9, 15)}),
        ]
        for payment_date, category in [(date(2026, 9, 14), self.category), (date(2026, 9, 15), salary_category)]:
            for salary in (True, False):
                values, warnings = declaration._recipient_classification(partner, payment_date, salary=salary)
                self.assertEqual(values['category_id'], category.id)

    def test_history_gap_never_uses_salary_default(self):
        partner = self.env['res.partner'].create({
            'name': 'Gap recipient', 'rs_form30_category_id': self.category.id,
            'rs_form30_category_history_ids': [Command.create({
                'category_id': self.category.id, 'date_from': date(2026, 10, 1)})],
        })
        declaration = self.env['rs.form30.declaration'].new({'date_from': date(2026, 9, 1)})
        for salary in (True, False):
            values, warnings = declaration._recipient_classification(partner, date(2026, 9, 30), salary=salary)
            self.assertFalse(values['category_id'])
            self.assertTrue(any('covers the payment date' in w for w in warnings))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            partner.rs_form30_category_history_ids = [Command.create({
                'category_id': self.category.id, 'date_from': date(2026, 10, 1)})]
