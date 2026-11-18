# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from lxml import etree

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'l10n_be_281_errors')
class TestL10nBe281Errors(TestPayrollCommon):
    """ The configuration errors of the employees don't block the 281 forms of the others: their PDF can
    be generated, but the file of the declaration is blocked until all the errors are fixed. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rules = {
            code: cls.env['hr.salary.rule'].search([('code', '=', code), ('country_id.code', '=', 'BE')], limit=1)
            for code in ('EUC', 'EUB', 'ECONOMIC_UNEMPLOYMENT.P.P')
        }
        cls.rules['REPLACEMENT_REVENUE'] = cls.env.ref('l10n_be_hr_payroll.cp200_employees_salary_replacement_revenue')
        cls.rules['REPLACEMENT_REVENUE.P.P'] = cls.env.ref('l10n_be_hr_payroll.cp200_employees_salary_replacement_revenue_withholding_tax')

        def employee(name, niss):
            first_name, last_name = name.split()
            return cls.create_employee({
                'name': name,
                'contract_date_start': date(2025, 1, 1),
                'niss': niss,
                'private_street': 'Rue du Test 1',
                'private_zip': '1000',
                'private_city': 'Brussels',
                'l10n_be_legal_first_name': first_name,
                'l10n_be_legal_last_name': last_name,
            })

        # 281.13
        cls.valid_13 = employee('Valid Thirteen', cls._niss('850101001'))
        cls.no_niss = employee('Without Niss', cls._niss('850101002'))
        cls.no_address = employee('Without Address', cls._niss('850101003'))
        # 281.18
        cls.valid_18 = employee('Valid Eighteen', cls._niss('850101004'))
        cls.no_legal_name = employee('Without Legal', cls._niss('850101005'))
        cls.foreign = employee('Foreign Country', cls._niss('850101006'))

        for employee in cls.valid_13 | cls.no_niss | cls.no_address:
            cls._payslip(employee, {'EUC': 300.0, 'EUB': 50.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -93.63}, unemployment_days=5)
        for employee in cls.valid_18 | cls.no_legal_name | cls.foreign:
            cls._payslip(employee, {'REPLACEMENT_REVENUE': 1000.0, 'REPLACEMENT_REVENUE.P.P': -200.0})

    @classmethod
    def _niss(cls, number):
        # Check digits of a person born before 2000
        return f'{number}{97 - int(number) % 97:02d}'

    @classmethod
    def _payslip(cls, employee, amounts, unemployment_days=0):
        unemployment_type = cls.env.ref('hr_work_entry.l10n_be_work_entry_type_economic_unemployment')
        payslip = cls.env['hr.payslip'].create({
            'name': 'Payslip',
            'employee_id': employee.id,
            'company_id': employee.company_id.id,
            'version_id': employee.version_id.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'state': 'validated',
            'worked_days_line_ids': [Command.create({
                'version_id': employee.version_id.id,
                'work_entry_type_id': unemployment_type.id,
                'number_of_days': unemployment_days,
                'number_of_hours': unemployment_days * 7.6,
            })] if unemployment_days else [],
        })
        cls.env['hr.payslip.line'].create([{
            'name': code,
            'slip_id': payslip.id,
            'salary_rule_id': cls.rules[code].id,
            'total': amount,
        } for code, amount in amounts.items()])

    def _declaration(self):
        return self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({
            'year': '2025',
            'company_id': self.belgian_company.id,
            **{f'include_281_{form}': False for form in ('10', '20', '30', '45')},
        })

    def _break_employees(self):
        self.no_niss.niss = False
        self.no_address.private_street = False
        self.no_legal_name.l10n_be_legal_first_name = False
        self.foreign.private_country_id = self.env.ref('base.aq')

    def _fix_employees(self):
        self.no_niss.niss = self._niss('850101002')
        self.no_address.private_street = 'Rue du Test 2'
        self.no_legal_name.l10n_be_legal_first_name = 'Without'
        self.foreign.private_country_id = self.env.ref('base.fr')

    def _lines_by_employee(self, declaration):
        return (declaration.l10n_be_281_13_line_ids | declaration.l10n_be_281_18_line_ids).grouped('employee_id')

    def test_employee_errors_of_all_forms(self):
        self._break_employees()
        declaration = self._declaration()
        declaration.action_generate_xml()

        self.assertEqual(declaration.state, 'error')
        self.assertFalse(declaration.xml_file)
        self.assertFalse(declaration.company_error_message)
        self.assertEqual(declaration.forms_with_error, '281.13,281.18')
        lines = self._lines_by_employee(declaration)
        self.assertEqual(set(lines), set(
            self.valid_13 | self.no_niss | self.no_address | self.valid_18 | self.no_legal_name | self.foreign))
        expected_errors = {
            self.no_niss: ('281.13', "Invalid NISS number for employee Without Niss"),
            self.no_address: ('281.13', "Employee Without Address doesn't have a valid private address"),
            self.no_legal_name: ('281.18', "Employee Without Legal doesn't have a legal first and last name defined"),
            self.foreign: ('281.18', "Unsupported country code AQ for employee Foreign Country"),
        }
        # One message lists the errors of all the forms, line by line
        for employee, (form, error) in expected_errors.items():
            self.assertIn(error, lines[employee].declaration_error)
            self.assertIn(f"- {form}: {error}", declaration.error_message)
        self.assertFalse(lines[self.valid_13].declaration_error)
        self.assertFalse(lines[self.valid_18].declaration_error)
        self.assertEqual(len(declaration.error_message.splitlines()), 2 + len(expected_errors))

        # The PDF of the valid employees are generated, not the other ones
        all_lines = declaration.l10n_be_281_13_line_ids | declaration.l10n_be_281_18_line_ids
        all_lines._generate_pdf()
        for employee, line in lines.items():
            if employee in (self.valid_13 | self.valid_18):
                self.assertTrue(line.pdf_file)
                self.assertFalse(line.declaration_error)
            else:
                self.assertFalse(line.pdf_file)
                self.assertEqual(line.state, 'error')
        with self.assertRaisesRegex(UserError, "Invalid NISS number"):
            lines[self.no_niss].action_print_pdf()

        self._fix_employees()
        lines[self.no_niss].action_print_pdf()
        self.assertTrue(lines[self.no_niss].pdf_file)

        declaration.action_generate_xml()
        self.assertEqual(declaration.state, 'ready', declaration.error_message)
        self.assertFalse(declaration.forms_with_error)
        root = etree.fromstring(bytes(declaration.xml_file))
        self.assertEqual(len(root.findall('.//Fiche28113')), 3)
        self.assertEqual(len(root.findall('.//Fiche28118')), 3)

    def test_test_xml_with_errors(self):
        # The test file is blocked the same way, without raising (the demo data generates it)
        self._break_employees()
        declaration = self._declaration()
        declaration.action_generate_test_xml()
        self.assertEqual(declaration.state, 'error')
        self.assertFalse(declaration.test_xml_file)
        self.assertIn("Invalid NISS number for employee Without Niss", declaration.error_message)

    def test_company_errors(self):
        self.belgian_company.write({'phone': 'not a phone', 'street': False})
        self.env.user.email = False
        declaration = self._declaration()
        company_errors = [
            "The street, the city or the country is not specified on your company.",
            "The phone number of your company is invalid.",
            "Your user has no email address: it is the contact email address of the declaration.",
        ]
        self.assertEqual(declaration.company_error_message, '\n'.join(company_errors))

        declaration.action_generate_xml()
        self.assertEqual(declaration.state, 'error')
        self.assertFalse(declaration.xml_file)
        for error in company_errors:
            self.assertIn(f"- {error}", declaration.error_message)
        # The employees of the company can't be declared either
        lines = self._lines_by_employee(declaration)
        self.assertIn("The company of employee Valid Thirteen is not correctly configured", lines[self.valid_13].declaration_error)
        # Without the company data, no PDF can be generated
        with self.assertRaisesRegex(UserError, "The phone number of your company is invalid"):
            lines[self.valid_13].action_print_pdf()

        self.belgian_company.write({'phone': '061928374', 'street': 'Rue du Paradis'})
        self.env.user.email = 'payroll@example.com'
        # The email of the user isn't a dependency of the field
        declaration.invalidate_recordset(['company_error_message'])
        self.assertFalse(declaration.company_error_message)
        declaration.action_generate_xml()
        self.assertEqual(declaration.state, 'ready', declaration.error_message)
