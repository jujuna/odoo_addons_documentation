# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo.tests import tagged

from odoo.addons.hr_payroll.tests.common import TestPayrollBase
from odoo.addons.l10n_be_hr_payroll.tests.common import TestBelgiumCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestPayrollSalaryAttachment(TestPayrollBase, TestBelgiumCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_common(
            country=cls.env.ref('base.be'),
            structure=cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary'),
            structure_type=cls.env.ref('hr.structure_type_employee_cp200'),
            version_fields={
                'date_version': date(2024, 1, 1),
                'contract_date_start': date(2024, 1, 1),
                'contract_date_end': False,
                'wage': 2000.0,
            },
            tz='Europe/Brussels',
        )
        cls.payslip = cls._generate_payslip(date(2026, 1, 1), date(2026, 1, 31))

    def test_seizable_amount_brackets(self):
        for disposable, expected in [
            (-100.0, 0.0),
            (1419.0, 0.0),
            (1419.01, 0.002),
            (1524.0, 21.0),
            (1524.01, 21.003),
            (1682.0, 68.4),
            (1682.01, 68.404),
            (1839.0, 131.2),
            (1839.01, 131.21),
            (2230.33, 522.53),
        ]:
            with self.subTest(disposable=disposable):
                self.assertAlmostEqual(self.payslip._get_l10n_be_max_seizable_amount(disposable), expected, places=6)

    def test_seizable_amount_dependent_children(self):
        for children, disposable, expected in [
            (0, 2230.33, 522.53),
            (1, 2230.33, 434.53),
            (5, 2230.33, 82.53),
            (6, 2230.33, 0.0),
            (1, 1700.0, 0.0),
        ]:
            with self.subTest(children=children, disposable=disposable):
                self.employee.l10n_be_dependent_children_attachment = children
                self.assertAlmostEqual(self.payslip._get_l10n_be_max_seizable_amount(disposable), expected, places=2)

    def test_seizable_amount_uses_payslip_date(self):
        self.employee.l10n_be_dependent_children_attachment = 5
        self.payslip.write({'date_from': date(2024, 1, 1), 'date_to': date(2024, 1, 31)})
        self.assertAlmostEqual(self.payslip._get_l10n_be_max_seizable_amount(2230.33), 201.43, places=2)

    def test_salary_attachment_with_dependent_children(self):
        self.employee.l10n_be_dependent_children_attachment = 5
        self.payslip._set_input_value('ATTACH_SALARY', 1000.0)
        self.payslip.compute_sheet()
        values = self.payslip._get_line_values(['DISPOSABLE_EARNINGS', 'ATTACH_SALARY', 'NET'], compute_sum=True)
        net_before_attachment = values['NET']['sum']['total'] - values['ATTACH_SALARY']['sum']['total']
        disposable = values['DISPOSABLE_EARNINGS']['sum']['total']
        self.assertLess(disposable, 2230.33)
        self.payslip._set_input_value('NET_REPLACEMENT_WAGE', 2230.33 - disposable)

        for attachment, prior, assignment, expected_attachment in [
            (1000.0, 0.0, 0.0, 82.53),
            (50.0, 0.0, 0.0, 50.0),
            (1000.0, 20.0, 30.0, 32.53),
        ]:
            with self.subTest(attachment=attachment, prior=prior, assignment=assignment):
                self.payslip._set_input_values({
                    'ATTACH_SALARY': attachment,
                    'ASSIG_SALARY_PRIOR': prior,
                    'ASSIG_SALARY': assignment,
                })
                self.payslip.compute_sheet()
                values = self.payslip._get_line_values([
                    'DISPOSABLE_EARNINGS', 'ATTACH_SALARY', 'ASSIG_SALARY_PRIOR', 'ASSIG_SALARY', 'NET',
                ], compute_sum=True)
                self.assertAlmostEqual(values['DISPOSABLE_EARNINGS']['sum']['total'], 2230.33, places=2)
                self.assertAlmostEqual(values['ATTACH_SALARY']['sum']['total'], -expected_attachment, places=2)
                self.assertAlmostEqual(values['ASSIG_SALARY_PRIOR']['sum']['total'], -prior, places=2)
                self.assertAlmostEqual(values['ASSIG_SALARY']['sum']['total'], -assignment, places=2)
                self.assertAlmostEqual(
                    values['NET']['sum']['total'],
                    net_before_attachment - expected_attachment - prior - assignment,
                    places=2,
                )
