# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from unittest.mock import patch

from odoo.tests import tagged
from odoo.addons.l10n_be_hr_payroll.models.hr_employee_departure import HrEmployeeDeparture
from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestTerminationDocumentsPayrun(TestPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.be_monthly_structure = cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
        cls.termination_structures = (
            cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees')
            + cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month')
            + cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays')
        )

    def _create_departure(self, employee, departure_date, reason='hr.departure_fired'):
        departure = self.env['hr.employee.departure'].create({
            'employee_id': employee.id,
            'dismissal_date': departure_date,
            'departure_reason_id': self.env.ref(reason).id,
            'l10n_be_notice_respect': 'without',
            'departure_description': 'Test',
        })
        departure.action_register()
        return departure

    def test_generate_payslips_in_payrun_creates_termination_documents_in_same_run(self):
        """ Generating the payslips of a monthly payrun that contains an employee's last
        payslip should generate the termination documents right away, in the same payrun,
        instead of waiting for that payslip to be validated. """
        employee = self.create_employee({
            'name': 'Termination On Payrun Creation',
            'wage': 3000.0,
            'contract_date_start': date(2020, 1, 1),
        })
        departure = self._create_departure(employee, date(2026, 6, 15))

        payrun = self.env['hr.payslip.run'].create({
            'name': 'June 2026',
            'date_start': date(2026, 6, 1),
            'date_end': date(2026, 6, 30),
            'company_id': self.belgian_company.id,
            'structure_id': self.be_monthly_structure.id,
            'version_ids': [(6, 0, employee.version_id.ids)],
        })
        payrun._generate_payslips()

        self.assertTrue(departure.l10n_be_termination_documents_generated,
            "The termination documents should be marked as generated once the payrun creates the last payslip.")

        generated_payslips = self.env['hr.payslip'].search([
            ('employee_id', '=', employee.id),
            ('struct_id', 'in', self.termination_structures.ids),
        ])
        self.assertEqual(len(generated_payslips), 3,
            "The termination fees, holiday attest and 13th month payslips should all be generated.")
        self.assertEqual(set(generated_payslips.payslip_run_id.ids), {payrun.id},
            "The generated termination documents should be added to the same payrun as the main payslip.")

        main_payslip = payrun.slip_ids - generated_payslips
        main_payslip.action_validate()

        self.assertEqual(
            self.env['hr.payslip'].search_count([
                ('employee_id', '=', employee.id),
                ('struct_id', 'in', self.termination_structures.ids),
            ]),
            len(generated_payslips),
            "Validating the main payslip afterwards should not regenerate or duplicate the termination documents.")

    def test_no_termination_fees_on_resignation_without_notice(self):
        """ The notice indemnity is owed by the party ending the contract without notice: an employee who
        resigns without working his notice doesn't get termination fees from the employer. """
        employee = self.create_employee({
            'name': 'Resignation Without Notice',
            'wage': 3000.0,
            'contract_date_start': date(2016, 1, 1),
        })
        departure = self._create_departure(employee, date(2026, 6, 15), reason='hr.departure_resigned')
        self.assertTrue(departure.l10n_be_notice_duration_week_after_2014)

        payrun = self.env['hr.payslip.run'].create({
            'name': 'June 2026',
            'date_start': date(2026, 6, 1),
            'date_end': date(2026, 6, 30),
            'company_id': self.belgian_company.id,
            'structure_id': self.be_monthly_structure.id,
            'version_ids': [(6, 0, employee.version_id.ids)],
        })
        payrun._generate_payslips()

        self.assertTrue(departure.l10n_be_termination_documents_generated)
        self.assertFalse(self.env['hr.payslip'].search_count([
            ('employee_id', '=', employee.id),
            ('struct_id', '=', self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees').id),
        ]))

    def test_add_missing_employee_to_holiday_attest_payrun(self):
        """ Adding a missing employee to a holiday attest payrun only generates his payslips,
        not those of the other employees of the payrun. """
        employees = self.env['hr.employee']
        for name in ('Attest Missing', 'Attest Other'):
            employee = self.create_employee({
                'name': name,
                'wage': 3000.0,
                'contract_date_start': date(2020, 1, 1),
            })
            self._create_departure(employee, date(2026, 6, 15))
            employees |= employee
        payrun = self.env['hr.payslip.run'].create({
            'name': 'Holiday Attests',
            'date_start': date(2026, 6, 1),
            'date_end': date(2026, 6, 30),
            'company_id': self.belgian_company.id,
            'structure_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays').id,
            'version_ids': [(6, 0, employees.version_id.ids)],
        })

        generated_for = []

        def _generate_termination_holidays(departures, payrun_id=False):
            generated_for.append(departures.employee_id)
            return self.env['hr.payslip']

        with patch.object(HrEmployeeDeparture, '_generate_termination_holidays', _generate_termination_holidays):
            payrun._generate_payslips(versions=employees[0].version_id)
        self.assertEqual(generated_for, [employees[0]])

    def test_validating_last_payslip_refreshes_holiday_attest_gross_reference(self):
        """
        The holiday attests generated with the payrun are computed while the departure-month
        payslips are still drafts. Validating those payslips together must add each one's
        remuneration to the gross reference of its employee's N holiday attest.
        """
        employees = self.env["hr.employee"]
        for name, wage in (("Gross Reference Refresh A", 3000.0), ("Gross Reference Refresh B", 4000.0)):
            employees |= self.create_employee({
                "name": name,
                "wage": wage,
                "contract_date_start": date(2020, 1, 1),
            })
        departures = self._create_departure(employees[0], date(2026, 6, 10)) | self._create_departure(employees[1], date(2026, 6, 19))

        payrun = self.env["hr.payslip.run"].create({
            "name": "June 2026",
            "date_start": date(2026, 6, 1),
            "date_end": date(2026, 6, 30),
            "company_id": self.belgian_company.id,
            "structure_id": self.be_monthly_structure.id,
            "version_ids": [(6, 0, employees.version_id.ids)],
        })
        payrun._generate_payslips()

        struct_n = self.env.ref("l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays")
        holiday_attests = payrun.slip_ids.filtered(lambda p: p.struct_id == struct_n)
        main_payslips = payrun.slip_ids.filtered(lambda p: p.struct_id == self.be_monthly_structure)
        self.assertEqual(len(holiday_attests), 2)
        self.assertEqual(len(main_payslips), 2)
        gross_ref_before = {attest: attest._get_input_line_amount("GROSS_REF") for attest in holiday_attests}

        main_payslips.action_validate()

        for departure in departures:
            holiday_attest = holiday_attests.filtered(lambda p: p.employee_id == departure.employee_id)
            gross_ref_after = holiday_attest._get_input_line_amount("GROSS_REF")
            self.assertGreater(
                gross_ref_after,
                gross_ref_before[holiday_attest],
                "The departure-month remuneration should be added to the gross reference once validated.",
            )
            self.assertAlmostEqual(gross_ref_after, departure.l10n_be_gross_reference_remuneration_n, places=2)
