# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import Form, tagged

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestPayslipMissingInformation(TestPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, hr_payroll_force_compute_issue=True))
        cls.employee = cls.create_employee({
            'name': 'Test Employee',
            'employee_type_id': cls.env.ref('hr.contract_type_employee').id,
            'l10n_be_salary_scale_id': False,
            'date_version': date(2026, 1, 1),
            'contract_date_start': date(2026, 1, 1),
        }).with_env(cls.env)

    def _create_payslip(self):
        return self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.employee.version_id.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
            'date_from': date(2026, 3, 1),
            'date_to': date(2026, 3, 31),
        })

    def _get_issues(self, payslip):
        payslip._compute_issues()
        return list((payslip.issues or {}).values())

    def test_salary_scale_not_required_on_employee_form(self):
        # scale should not be blocking on employee form
        self.assertTrue(self.employee.version_id.display_l10n_be_scale)
        with Form(self.employee) as employee_form:
            employee_form.name = 'Employee without salary scale'
        self.assertFalse(self.employee.l10n_be_salary_scale_id)

    def test_missing_salary_scale_blocks_payslip(self):
        payslip = self._create_payslip()
        scale_issues = [issue for issue in self._get_issues(payslip) if 'Salary scale is required' in issue['message']]
        self.assertEqual(len(scale_issues), 1)
        self.assertEqual(scale_issues[0]['level'], 'danger')
        with self.assertRaises(ValidationError):
            payslip.action_payslip_done()

        self.employee.l10n_be_salary_scale_id = self.env.ref('l10n_be_hr_payroll.cp200_b')
        self.assertFalse(any('Salary scale is required' in issue['message'] for issue in self._get_issues(payslip)))

    def test_no_salary_scale_issue_without_scales_for_joint_committee(self):
        joint_committee = self.env['l10n.be.joint.committee'].create({'name': 'No scales CP', 'egov3_code': '999.99'})
        self.employee.l10n_be_joint_committee_id = joint_committee
        self.assertFalse(self.employee.version_id.display_l10n_be_scale)
        payslip = self._create_payslip()
        self.assertFalse(any('Salary scale is required' in issue['message'] for issue in self._get_issues(payslip)))

    def test_no_salary_scale_issue_without_scales_for_employer_category(self):
        payroll_config = self.employee.version_id.payroll_config_id
        payroll_config.l10n_be_employer_category_id = self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00254')
        # cp322 only has salary scales for the employer category 00097, but the category 00254 also allows cp322.
        # The allowed joint committees follow the employer category and skip archived ones, so cp322 must be
        # active and the category set before the joint committee, otherwise the version loses cp322
        cp322 = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_322')
        cp322.active = True
        self.employee.l10n_be_joint_committee_id = cp322
        self.assertEqual(self.employee.version_id.l10n_be_joint_committee_id, cp322)
        self.assertFalse(self.employee.version_id.display_l10n_be_scale)
        payslip = self._create_payslip()
        self.assertFalse(any('Salary scale is required' in issue['message'] for issue in self._get_issues(payslip)))

        payroll_config.l10n_be_employer_category_id = self.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00097')
        self.assertEqual(self.employee.version_id.l10n_be_joint_committee_id, cp322)
        self.assertTrue(self.employee.version_id.display_l10n_be_scale)
        self.assertTrue(any('Salary scale is required' in issue['message'] for issue in self._get_issues(payslip)))

    def test_invalid_email_format(self):
        self.employee.write({
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_b').id,
            'private_email': 'some.guy@example',
            'work_email': 'some.guy example.com',
        })
        payslip = self._create_payslip()
        messages = {issue['message']: issue['level'] for issue in self._get_issues(payslip)}
        self.assertEqual(messages.get('Private email some.guy@example has an invalid format'), 'warning')
        self.assertEqual(messages.get('Work email some.guy example.com has an invalid format'), 'warning')

        self.employee.write({
            'private_email': 'some.guy@example.com',
            'work_email': 'some.guy@company.example.com',
        })
        messages = [issue['message'] for issue in self._get_issues(payslip)]
        self.assertFalse(any('has an invalid format' in message for message in messages))
