from datetime import date

from lxml import etree

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, HttpCase, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.geo_payroll.tests.common import GeoPayrollCase

NS = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}


@tagged('post_install', '-at_install')
class TestForm30Salary(GeoPayrollCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.declaration = cls.env['rs.form30.declaration'].create({
            'company_id': cls.company.id,
            'date_from': date(2026, 2, 1),
        })
        cls.georgia = cls.env.ref('base.ge')
        cls.employed = cls.env.ref('gec_income_tax_report.category_4')
        cls.salary = cls.env.ref('gec_income_tax_report.income_type_1')

    def _paid_slip(self, employee, paid_on):
        slip = self._make_payslip(employee, worked_hours=160.0)
        slip.compute_sheet()
        slip.action_payslip_done()
        slip.write({'state': 'paid', 'paid_date': paid_on})
        return slip

    def _manual_line(self, **values):
        vals = {
            'declaration_id': self.declaration.id,
            'identification': '01008057135',
            'first_name': 'ნუცა',
            'last_name': 'თორაძე',
            'address': 'თბილისი',
            'country_id': self.georgia.id,
            'category_id': self.employed.id,
            'income_type_id': self.salary.id,
            'amount': 250.0,
            'date': date(2026, 2, 28),
            'rate': 20.0,
        }
        vals.update(values)
        return self.env['rs.form30.line'].create(vals)

    def test_salary_row(self):
        employee = self._make_employee('fixed')
        employee.pension_fund_member = True
        slip = self._paid_slip(employee, date(2026, 2, 10))
        self.declaration.action_generate()
        line = self.declaration.line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.source, 'payslip')
        self.assertEqual(line.payslip_id, slip)
        self.assertEqual(line.category_id, self.employed)
        self.assertEqual(line.income_type_id, self.salary)
        self.assertEqual(line.country_id, self.georgia)
        self.assertEqual(line.rate, 20.0)
        self.assertEqual(line.date, date(2026, 2, 10))
        self.assertAlmostEqual(line.amount, self._line_total(slip, 'GROSS'), places=2)
        self.assertAlmostEqual(line.tax_amount, -self._line_total(slip, 'PIT'), places=2)
        self.assertAlmostEqual(line.pension_amount, -self._line_total(slip, 'PENSION_EE'), places=2)
        self.assertEqual(line.other_relief, 0.0)

    def test_salary_id_falls_back_to_work_contact_vat(self):
        employee = self._make_employee('fixed')
        employee.identification_id = False
        if not employee.work_contact_id:
            employee.work_contact_id = self.env['res.partner'].create({'name': employee.name})
        employee.work_contact_id.vat = 'GE 0100 8057 135'
        slip = self._paid_slip(employee, date(2026, 2, 10))
        self.assertFalse(slip.version_id.identification_id)

        self.declaration.action_generate()

        line = self.declaration.line_ids
        self.assertEqual(line.identification, '01008057135')
        self.assertIn('work contact Tax ID', line.warning)

    def test_exempt_employee_relief(self):
        employee = self._make_employee('fixed')
        self.env['hr.payroll.tax.exemption'].create({
            'name': 'Test exemption',
            'yearly_limit': 3000.0,
            'employee_ids': [Command.set(employee.ids)],
        })
        self._paid_slip(employee, date(2026, 2, 10))
        self.declaration.action_generate()
        line = self.declaration.line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.tax_amount, 0.0)
        self.assertAlmostEqual(line.other_relief, line.amount, places=2)
        self.assertIn('Relief', line.warning)

    def _exempt_pension_member_line(self, yearly_limit):
        employee = self._make_employee('fixed')
        employee.pension_fund_member = True
        self.env['hr.payroll.tax.exemption'].create({
            'name': 'Test exemption',
            'yearly_limit': yearly_limit,
            'employee_ids': [Command.set(employee.ids)],
        })
        self._paid_slip(employee, date(2026, 2, 10))
        self.declaration.action_generate()
        return self.declaration.line_ids

    def test_exempt_pension_member_declares_withheld_tax(self):
        """Allowance partly used: the portal tax on the row equals the tax payroll withheld."""
        line = self._exempt_pension_member_line(1000.0)
        self.assertEqual(len(line), 1)
        self.assertGreater(line.tax_amount, 0.0)
        self.assertGreater(line.pension_amount, 0.0)
        self.assertAlmostEqual(line._portal_tax(), line.tax_amount, places=2)
        self.assertAlmostEqual(line.other_relief, line.amount - line.pension_amount - line.tax_amount / 0.20, places=2)

    def test_fully_exempt_pension_member_row_has_zero_base(self):
        line = self._exempt_pension_member_line(1000000.0)
        self.assertEqual(line.tax_amount, 0.0)
        self.assertAlmostEqual(line.other_relief, line.amount - line.pension_amount, places=2)
        self.assertAlmostEqual(line._taxable_base(), 0.0, places=2)
        self.assertEqual(line._portal_tax(), 0.0)

    def test_salary_residency_from_nationality(self):
        employee = self._make_employee('fixed')
        employee.version_id.country_id = self.env.ref('base.de')
        self._paid_slip(employee, date(2026, 2, 10))
        self.declaration.action_generate()
        self.assertEqual(self.declaration.line_ids.country_id.rs_form30_code, '276')

    def test_export_rejects_country_without_rs_code(self):
        employee = self._make_employee('fixed')
        employee.work_contact_id.country_id = self.env.ref('base.xk')
        self._paid_slip(employee, date(2026, 2, 10))
        self.declaration.action_generate()
        with self.assertRaises(UserError):
            self.declaration.action_export()

    def test_slip_paid_outside_month_is_ignored(self):
        self._paid_slip(self._make_employee('fixed'), date(2026, 3, 10))
        self.declaration.action_generate()
        self.assertFalse(self.declaration.line_ids)

    def test_manual_lines_survive_regeneration(self):
        manual = self._manual_line()
        self._paid_slip(self._make_employee('fixed'), date(2026, 2, 10))
        self.declaration.action_generate()
        self.assertIn(manual, self.declaration.line_ids)
        self.assertEqual(len(self.declaration.line_ids), 2)
        self.declaration.action_generate()
        self.assertEqual(len(self.declaration.line_ids), 2)

    def test_export_xml(self):
        self._manual_line()
        self.declaration.action_export()
        self.assertEqual(self.declaration.state, 'exported')
        root = etree.fromstring(self.declaration.export_file.content)
        self.assertEqual(root.find('ss:Worksheet', NS).get('{%s}Name' % NS['ss']), 'data')
        rows = root.findall('.//ss:Row', NS)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0].findall('ss:Cell/ss:Data', NS)), 14)
        cells = rows[1].findall('ss:Cell/ss:Data', NS)
        self.assertEqual(
            [(cell.text or '').strip() for cell in cells],
            ['01008057135', 'ნუცა', 'თორაძე', 'თბილისი', '268', '4', '1', '250', '0', '28.02.2026', '20', '0', '0', ''])
        self.assertTrue(all(cell.get('{%s}Type' % NS['ss']) == 'String' for cell in cells))

    def test_line_rejects_rate_outside_matrix(self):
        with self.assertRaises(ValidationError):
            self._manual_line(rate=7.0)
        self.assertFalse(self.declaration.line_ids)

    def test_line_rejects_pair_outside_matrix(self):
        with self.assertRaises(ValidationError):
            self._manual_line(category_id=self.env.ref('gec_income_tax_report.category_42').id)

    def test_line_rejects_income_type_outside_period(self):
        with self.assertRaises(ValidationError):
            abolished = self.env['rs.form30.income.type'].create({'code': '99', 'name': 'Abolished', 'valid_to': 202411})
            self._manual_line(income_type_id=abolished.id)

    def test_generate_flags_pair_outside_matrix(self):
        employee = self._make_employee('fixed')
        if not employee.work_contact_id:
            employee.work_contact_id = self.env['res.partner'].create({'name': employee.name})
        employee.work_contact_id.rs_form30_category_id = self.env.ref('gec_income_tax_report.category_2')
        self._paid_slip(employee, date(2026, 2, 10))
        self.declaration.action_generate()
        line = self.declaration.line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.issue_level, 'blocker')
        self.assertIn("The rs.ge classifier does not allow this category, income type and rate for the month.", line.warning)

    def test_export_rejects_bad_georgian_id(self):
        self._manual_line(identification='12345')
        with self.assertRaises(UserError):
            self.declaration.action_export()

    def test_name_split_and_identification(self):
        Line = self.env['rs.form30.line']
        self.assertEqual(Line._split_name('ნუცა თორაძე', False), ('ნუცა', 'თორაძე'))
        self.assertEqual(Line._split_name('შპს ჯეკ ენდ ქო', True), ('შპს', 'ჯეკ ენდ ქო'))
        self.assertEqual(Line._split_name('ჯეკ ენდ ქო', True), ('', 'ჯეკ ენდ ქო'))
        self.assertEqual(Line._clean_identification('GE 0100 8057 135'), '01008057135')
        self.assertEqual(Line._clean_identification('204512345'), '204512345')

    def test_warning_keeps_canonical_source_and_has_localized_display(self):
        line = self._manual_line(warning='Relief derived from the withheld tax, verify on the portal.')
        self.assertEqual(line.warning, 'Relief derived from the withheld tax, verify on the portal.')
        self.assertEqual(line.with_context(lang='en_US').warning_display, line.warning)


@tagged('post_install', '-at_install')
class TestForm30Grid(HttpCase):

    def test_grid_renders_without_owl_error(self):
        declaration = self.env['rs.form30.declaration'].create({
            'company_id': self.env.company.id,
            'date_from': date(2026, 2, 1),
        })
        self.env['rs.form30.line'].create({
            'declaration_id': declaration.id,
            'source': 'manual',
            'identification': '01008057135',
            'first_name': 'ნუცა',
            'last_name': 'თორაძე',
            'amount': 250.0,
            'date': date(2026, 2, 28),
        })
        action = self.env.ref('gec_income_tax_report.action_rs_form30_declaration')
        url = f'/odoo/action-{action.id}/{declaration.id}?debug=assets'
        self.browser_js(
            url,
            """
                const checkGrid = () => {
                    const grid = document.querySelector('.o_rs_form30_grid');
                    if (!grid) {
                        setTimeout(checkGrid, 100);
                        return;
                    }
                    if (!grid.querySelector('.o_rsf30_table tbody tr')) {
                        throw new Error('The Form 30 grid rendered without its declaration line.');
                    }
                    console.log('Form 30 grid rendered successfully');
                };
                checkGrid();
            """,
            ready='odoo.isReady === true',
            login='admin',
            timeout=60,
            success_signal='Form 30 grid rendered successfully',
        )


@tagged('post_install', '-at_install')
class TestForm30Payments(AccountTestInvoicingCommon):

    def _withholding_payment(self, rate, income_type, category, country=None):
        company = self.company_data['company']
        company.withholding_tax_base_account_id = self.env['account.account'].create({
            'code': 'WHTB',
            'name': 'Withholding Tax Base',
            'reconcile': True,
            'account_type': 'asset_current',
        })
        sequence = self.env['ir.sequence'].create({'name': 'WHT', 'padding': 4})
        tax = self.percent_tax(
            -rate, type_tax_use='purchase', is_withholding_tax=True,
            withholding_sequence_id=sequence.id,
            rs_form30_income_type_id=self.env.ref(f'gec_income_tax_report.{income_type}').id)
        self.partner_a.write({
            'name': 'ნუცა თორაძე',
            'is_company': False,
            'vat': 'GE01008057135',
            'rs_form30_category_id': self.env.ref(f'gec_income_tax_report.{category}').id,
            'country_id': (country or self.env.ref('base.ge')).id,
        })
        bill = self.init_invoice(
            'in_invoice', partner=self.partner_a, amounts=[1000.0], invoice_date=date(2026, 2, 5), post=True)
        register = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids).create({'payment_date': date(2026, 2, 10)})
        with Form(register) as form:
            form.withhold = 'withhold_pay'
            with form.withholding_line_ids.new() as line:
                line.tax_id = tax
                line.base_amount = 1000.0
        register._create_payments()
        return self.env['rs.form30.declaration'].create({'company_id': company.id, 'date_from': date(2026, 2, 1)})

    def test_payment_row(self):
        declaration = self._withholding_payment(5, 'income_type_2', 'category_30')
        declaration.action_generate()
        self.assertRecordValues(declaration.line_ids, [{
            'source': 'payment',
            'identification': '01008057135',
            'first_name': 'ნუცა',
            'last_name': 'თორაძე',
            'amount': 1000.0,
            'tax_amount': 50.0,
            'rate': 5.0,
            'date': date(2026, 2, 10),
        }])
        line = declaration.line_ids
        self.assertEqual(line.category_id.code, '30')
        self.assertEqual(line.income_type_id.code, '2')
        self.assertEqual(line.country_id.rs_form30_code, '268')
        declaration.action_export()
        self.assertEqual(declaration.state, 'exported')

    def test_payment_residency_from_partner_country(self):
        declaration = self._withholding_payment(5, 'income_type_2', 'category_34', country=self.env.ref('base.us'))
        declaration.action_generate()
        self.assertEqual(declaration.line_ids.country_id.rs_form30_code, '840')

    def test_generate_flags_rate_outside_matrix(self):
        declaration = self._withholding_payment(5, 'income_type_17', 'category_4')
        declaration.action_generate()
        line = declaration.line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.issue_level, 'blocker')
        self.assertIn("The rs.ge classifier does not allow this category, income type and rate for the month.", line.warning)
        with self.assertRaisesRegex(UserError, 'Nothing selected for the file'):
            declaration.action_export()


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestForm30ProfitDistribution(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country('ge')
    def setUpClass(cls):
        super().setUpClass()
        cls.Template = cls.env['account.chart.template']

    def test_dividend_entry_of_the_profit_wizard_is_seen_under_income_type_2(self):
        wizard = self.env['l10n.ge.cit.wizard'].create({
            'journal_id': self.company_data['default_journal_misc'].id,
            'partner_id': self.partner_a.id,
            'treasury_partner_id': self.env['res.partner'].create({'name': 'State Treasury', 'gec_treasury_code': '101001000'}).id,
            'net_amount': 850,
            'distribution_account_id': self.Template.ref('ge_account_530110').id,
            'cit_account_id': self.Template.ref('ge_account_331110').id,
            'payable_account_id': self.Template.ref('ge_account_340120').id,
            'apply_dividend_wht': True,
        })
        self.assertEqual(wizard.dividend_wht_account_id, self.Template.ref('ge_account_331210'))
        move = self.env['account.move'].browse(wizard.action_post_cit()['res_id'])
        tax_line = move.line_ids.filtered(lambda line: line.account_id == wizard.dividend_wht_account_id)
        self.assertEqual(len(tax_line), 1)
        tax_lines, matched = move._rs_form30_match(move._rs_form30_get_rules())
        self.assertEqual(tax_lines, tax_line)
        self.assertEqual(matched.income_type_id.code, '2')
        self.assertEqual(move.line_ids._gec_withholding_tax_lines(), tax_line)
