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

    def test_salary_attachment_exceeded_by_child_support(self):
        # The child support is not capped by the seizable amount, the other
        # seizures only get what remains of it, possibly nothing: their lines
        # must never become a positive amount paid to the employee.
        self.payslip._set_input_value('ATTACH_SALARY', 100.0)
        self.payslip.compute_sheet()
        disposable = self.payslip._get_line_values(['DISPOSABLE_EARNINGS'], compute_sum=True)['DISPOSABLE_EARNINGS']['sum']['total']
        self.payslip._set_input_values({
            'NET_REPLACEMENT_WAGE': 2230.33 - disposable,
            'CHILD_SUPPORT': 600.0,
            'ASSIG_SALARY': 100.0,
            'ATTACH_SALARY': 100.0,
        })
        self.payslip.compute_sheet()
        values = self.payslip._get_line_values(['CHILD_SUPPORT', 'ASSIG_SALARY', 'ATTACH_SALARY'], compute_sum=True)
        self.assertAlmostEqual(values['CHILD_SUPPORT']['sum']['total'], -600.0, places=2)
        self.assertAlmostEqual(values['ASSIG_SALARY']['sum']['total'], 0.0, places=2)
        self.assertAlmostEqual(values['ATTACH_SALARY']['sum']['total'], 0.0, places=2)

    def _set_disposable_earnings(self, payslip, disposable):
        payslip.compute_sheet()
        computed = payslip._get_line_values(['DISPOSABLE_EARNINGS'], compute_sum=True)['DISPOSABLE_EARNINGS']['sum']['total']
        replacement = payslip._get_line_values(['NET_REPLACEMENT_WAGE'], compute_sum=True)['NET_REPLACEMENT_WAGE']['sum']['total']
        payslip._set_input_value('NET_REPLACEMENT_WAGE', disposable - computed + replacement)
        payslip.compute_sheet()
        values = payslip._get_line_values(['DISPOSABLE_EARNINGS', 'ATTACH_SALARY'], compute_sum=True)
        self.assertAlmostEqual(values['DISPOSABLE_EARNINGS']['sum']['total'], disposable, places=2)
        return values['ATTACH_SALARY']['sum']['total']

    def test_seizable_amount_per_calendar_month(self):
        # The brackets apply to the total of the sums paid in the calendar month (Code judiciaire,
        # art. 1409 § 1), double holiday pay included: a second payslip of the month only seizes
        # what the first one left of the seizable amount of the month.
        monthly = self._generate_payslip(date(2026, 6, 1), date(2026, 6, 30))
        monthly._set_input_value('ATTACH_SALARY', 5000.0)
        self.assertAlmostEqual(self._set_disposable_earnings(monthly, 2000.0), -292.2, places=2)
        monthly.action_payslip_done()

        double_holiday = self._generate_payslip(
            date(2026, 6, 1), date(2026, 6, 30),
            struct_id=self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id)
        double_holiday._set_input_value('ATTACH_SALARY', 5000.0)
        # The seizable amount of 3700 € is 1992.20 €, of which 292.20 € were seized on the monthly payslip
        self.assertAlmostEqual(self._set_disposable_earnings(double_holiday, 1700.0), -1700.0, places=2)

        # The payslips of another month are not taken into account
        july = self._generate_payslip(date(2026, 7, 1), date(2026, 7, 31))
        july._set_input_value('ATTACH_SALARY', 5000.0)
        self.assertAlmostEqual(self._set_disposable_earnings(july, 2000.0), -292.2, places=2)

    def test_prior_assignment_after_child_support(self):
        # The sums paid to the maintenance creditor reduce the seizable amount left to the other
        # creditors (Code judiciaire, art. 1412 al. 2), the prior assignment included.
        self.payslip._set_input_value('ASSIG_SALARY_PRIOR', 500.0)
        self._set_disposable_earnings(self.payslip, 2230.33)
        self.payslip._set_input_values({
            'CHILD_SUPPORT': 400.0,
            'ASSIG_SALARY_PRIOR': 500.0,
        })
        self.payslip.compute_sheet()
        values = self.payslip._get_line_values(['CHILD_SUPPORT', 'ASSIG_SALARY_PRIOR'], compute_sum=True)
        self.assertAlmostEqual(values['CHILD_SUPPORT']['sum']['total'], -400.0, places=2)
        self.assertAlmostEqual(values['ASSIG_SALARY_PRIOR']['sum']['total'], -122.53, places=2)

    def test_several_prior_assignments(self):
        # One line per payslip adjustment: together, the prior assignments never exceed the seizable amount
        self.env['hr.salary.attachment'].create([{
            'employee_id': self.employee.id,
            'description': description,
            'salary_rule_id': self.env.ref('l10n_be_hr_payroll.l10n_be_hr_payroll_structure_cp200_employee_salary_assignment_of_salary_prior_rule').id,
            'date_start': date(2026, 3, 1),
            'amount': 500,
            'is_recurring': True,
        } for description in ('First assignment', 'Second assignment')])
        payslip = self._generate_payslip(date(2026, 3, 1), date(2026, 3, 31))
        self._set_disposable_earnings(payslip, 2230.33)
        lines = payslip.line_ids.filtered(lambda line: line.code == 'ASSIG_SALARY_PRIOR').sorted('id')
        self.assertRecordValues(lines, [
            {'name': 'Assignment of Salary (Prior) - First assignment', 'total': -500.0},
            {'name': 'Assignment of Salary (Prior) - Second assignment', 'total': -22.53},
        ])

    def test_seizable_amount_dependent_children_of_payslip_version(self):
        # The dependent children are the ones of the version of the payslip, not of the current one
        self.employee.create_version({
            'date_version': date(2026, 6, 1),
            'l10n_be_dependent_children_attachment': 2,
        })
        may = self._generate_payslip(date(2026, 5, 1), date(2026, 5, 31))
        june = self._generate_payslip(date(2026, 6, 1), date(2026, 6, 30), version_id=self.employee._get_version(date(2026, 6, 1)).id)
        self.assertAlmostEqual(may._get_l10n_be_max_seizable_amount(2230.33), 522.53, places=2)
        self.assertAlmostEqual(june._get_l10n_be_max_seizable_amount(2230.33), 346.53, places=2)

    def test_refund_of_payslip_closing_attachment(self):
        # The refund of the payslip that paid an attachment gives the amount back to the attachment
        attachment = self.env['hr.salary.attachment'].create({
            'employee_id': self.employee.id,
            'description': 'Attachment of 500',
            'salary_rule_id': self.env.ref('l10n_be_hr_payroll.l10n_be_hr_payroll_structure_cp200_employee_salary_attachment_of_salary_rule').id,
            'date_start': date(2026, 3, 1),
            'amount': 500,
            'is_recurring': False,
        })
        payslip = self._generate_payslip(date(2026, 3, 1), date(2026, 3, 31))
        self.assertAlmostEqual(self._set_disposable_earnings(payslip, 3000.0), -500.0, places=2)
        payslip.action_payslip_done()
        payslip.action_payslip_paid()
        self.assertEqual((attachment.state, attachment.paid_amount, attachment.remaining_amount), ('2_close', 500, 0))

        refund = payslip._action_refund_payslips()
        self.assertIn(attachment, refund.salary_attachment_ids)
        refund.action_payslip_paid()
        self.assertEqual((attachment.state, attachment.paid_amount, attachment.remaining_amount), ('1_open', 0, 500))
