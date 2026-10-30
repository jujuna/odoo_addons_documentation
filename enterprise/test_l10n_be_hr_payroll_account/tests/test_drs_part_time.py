# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import freeze_time, tagged

from .common_drs import TestDRSCommon


@tagged('post_install', '-at_install', 'drs')
class TestDRSPartTime(TestDRSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.part_time = cls._create_drs_employee(
            'Part-time Worker', resource_calendar_id=cls.calendar_19h.id, wage=1750.0,
            contract_date_start=date(2026, 3, 1), date_version=date(2026, 3, 1))

    def _validate_payslip(self, employee, date_from, date_to):
        payslip = self.env['hr.payslip'].create({
            'name': f'Payslip {employee.name}',
            'employee_id': employee.id,
            'version_id': employee.version_id.id,
            'date_from': date_from,
            'date_to': date_to,
            'company_id': self.belgian_company.id,
        })
        payslip.compute_sheet()
        payslip.action_payslip_done()
        return payslip

    @freeze_time('2026-06-26 10:00:00')
    def test_wech003_wech006(self):
        # Without declaration of the start of the part-time occupation, the months aren't declared
        self._validate_payslip(self.part_time, date(2026, 3, 1), date(2026, 3, 31))
        self.assertFalse(self._get_declarations(self.part_time, 'WECH006'))

        # The start of the part-time occupation is declared on the request of the worker
        wech003 = self._create_drs(self.part_time, 'drs_risk_wech003_001', 2026, 3)
        self.assertEqual(wech003.version_id, self.part_time.version_id)
        wech003_dict = self._get_drs_dict(wech003)
        self._assertDRSEqual(wech003_dict, label='wech003')
        occupation = wech003_dict['WECH003']['Form']['EmployerDeclarationLink']['NaturalPerson']['WorkerRecordLink']['OccupationLink']
        self.assertEqual(occupation['OccupationStartingDate'], '2026-03-01')
        self.assertNotIn('OccupationEndingDate', occupation)
        self.assertEqual(occupation['DeclarationPartTimeWorkWithMaintenanceRights'], {
            'DBRIndicatorInEntrepriseCadreMap': '0',
            'FullTimeOccupationRequest': '1',
            'TheoreticalSalary': {'MonthlyTheoreticalSalaryAmount': '175000'},
        })

        # Then each month of part-time work is declared at the validation of the payslip
        payslip = self._validate_payslip(self.part_time, date(2026, 4, 1), date(2026, 4, 30))
        wech006 = self._get_declarations(self.part_time, 'WECH006')
        self.assertRecordValues(wech006, [{'month': '4', 'year': 2026, 'payslip_id': payslip.id, 'is_automatically_created': True}])
        wech006_dict = self._get_drs_dict(wech006)
        self._assertDRSEqual(wech006_dict, label='wech006')
        occupation = wech006_dict['WECH006']['Form']['EmployerDeclarationLink']['NaturalPerson']['WorkerRecordLink']['OccupationLink']
        self.assertEqual((occupation['OccupationStartingDate'], occupation['OccupationEndingDate']), ('2026-04-01', '2026-04-30'))
        self.assertEqual(occupation['OccupationFeatures'], {'OccupationInterruption': '2', 'WorkScheduleCode': '10'})
        monthly_declaration = occupation['MonthlyDeclarationPartTimeWork']
        self.assertEqual(monthly_declaration['OccupationRefused'], '0')
        self.assertEqual(monthly_declaration['ReferencePeriod']['ExactSalary']['ExactSalaryCode'], '33')
        self.assertEqual(
            monthly_declaration['ReferencePeriod']['ExactSalary']['ExactSalaryAmount'],
            str(round(payslip._get_line_values(['SALARY'])['SALARY'][payslip.id]['total'] * 100)))

    @freeze_time('2026-06-26 10:00:00')
    def test_wech003_wech006_errors(self):
        full_time = self._create_drs_employee('Full-time Worker')
        with self.assertRaisesRegex(ValidationError, "doesn't work part-time"):
            self._get_drs_dict(self._create_drs(full_time, 'drs_risk_wech003_001', 2026, 3))

        wech006 = self._create_drs(self.part_time, 'drs_risk_wech006_001', 2026, 6)
        with self.assertRaisesRegex(ValidationError, 'A validated payslip') as error:
            self._get_drs_dict(wech006)
        self.assertIn('once the month is over', str(error.exception))

    @freeze_time('2026-06-26 10:00:00')
    def test_wech007(self):
        sheltered_worker = self._create_drs_employee(
            'Sheltered Workshop Worker',
            l10n_be_joint_committee_id=self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_327').id,
            l10n_be_worker_code_id=self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00012').id,
        )
        self._create_validated_leave(sheltered_worker, 'be_work_entry_type_legal_leave', date(2026, 4, 14), date(2026, 4, 15))
        # The first month is declared manually, then each month at the validation of the payslip
        april = self._create_drs(sheltered_worker, 'drs_risk_wech007_001', 2026, 4)
        self._validate_payslip(sheltered_worker, date(2026, 5, 1), date(2026, 5, 31))
        self.assertRecordValues(self._get_declarations(sheltered_worker, 'WECH007'), [
            {'month': '4', 'is_automatically_created': False},
            {'month': '5', 'is_automatically_created': True},
        ])
        drs_dict = self._get_drs_dict(april)
        self._assertDRSEqual(drs_dict)
        monthly_declaration = drs_dict['WECH007']['Form']['EmployerDeclarationLink']['NaturalPerson']['WorkerRecordLink']['OccupationLink']['MonthlyWorkDeclarationOfEmployeeWorkingInShelteredIndustry']
        self.assertEqual(monthly_declaration['TotalHoursOfPayedHoliday'], '1520')
        self.assertEqual(monthly_declaration['WorkerSituationIndicator'], '0')
        natures = {(day['DayIndicator'], day['DayNatureCode']) for day in monthly_declaration['ReferencePeriod']['NatureOfDay']}
        self.assertIn(('--04-14', '3.1'), natures)
        self.assertIn(('--04-06', '1'), natures, "Public holidays are paid days")

        # Only the sheltered workshops can declare it
        with self.assertRaisesRegex(ValidationError, 'joint committee 327'):
            self._get_drs_dict(self._create_drs(self.part_time, 'drs_risk_wech007_001', 2026, 4))
