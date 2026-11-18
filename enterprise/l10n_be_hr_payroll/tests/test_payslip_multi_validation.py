# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from dateutil.relativedelta import relativedelta
from freezegun import freeze_time

from odoo.tests import tagged

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestPayslipMultiValidation(TestPayrollCommon):

    def test_multi_payslips_validation(self):
        """
        Ensure that validating several draft payslips at once from the list view
        validates them all instead of silently leaving them in draft.
        """
        self.env['res.lang']._activate_lang('fr_BE')
        with freeze_time('2026-08-03'):
            structure = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
            slips = self.env['hr.payslip']
            # Three consecutive monthly payslips for the same employee.
            for month in (3, 4, 5):
                date_from = date(2026, month, 1)
                slips |= self.env['hr.payslip'].create({
                    'employee_id': self.employee_georges.id,
                    'struct_id': structure.id,
                    'version_id': self.employee_georges.version_id.id,
                    'date_from': date_from,
                    'date_to': date_from + relativedelta(months=1, day=1, days=-1),
                })
            slips.compute_sheet()
            self.employee_georges.lang = 'en_US'

            slips.action_validate()
            self.assertEqual(set(slips.mapped('state')), {'validated'}, "Every selected payslip should be validated.")
            self.assertEqual(self.employee_georges.lang, 'en_US', "The employee language should be left untouched.")

    def test_payslip_validation_units_with_different_languages(self):
        """
        When the company's DmfA units have different payslip languages, the validation of the payslip of an
        employee without a Belgian language neither crashes nor changes the language of the employee.
        """
        self.env['res.lang']._activate_lang('fr_BE')
        self.env['res.lang']._activate_lang('nl_BE')
        for lang, bce_code in (('fr_BE', '8888888770'), ('nl_BE', '8888888572')):
            self.env['hr.work.location'].create({
                'name': f'Unit {lang}',
                'bce_code': bce_code,
                'location_type': 'dmfa_unit',
                'company_id': self.belgian_company.id,
                'address_id': self.env['res.partner'].create({'name': f'Address {lang}'}).id,
                'payslip_language_id': self.env['res.lang']._lang_get(lang).id,
            })
        with freeze_time('2026-08-03'):
            slip = self.env['hr.payslip'].create({
                'employee_id': self.employee_georges.id,
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
                'version_id': self.employee_georges.version_id.id,
                'date_from': date(2026, 3, 1),
                'date_to': date(2026, 3, 31),
            })
            slip.compute_sheet()
            self.employee_georges.lang = 'en_US'
            slip.action_validate()
            self.assertEqual(slip.state, 'validated')
            self.assertEqual(self.employee_georges.lang, 'en_US')
            # The legal language is read on the version, not on the units of the company
            self.assertIn(slip, slip._get_payslips_pdf_lang())
