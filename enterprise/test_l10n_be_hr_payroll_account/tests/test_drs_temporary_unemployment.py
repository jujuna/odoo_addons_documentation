# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import freeze_time, new_test_user, tagged

from .common_drs import TestDRSCommon


@tagged('post_install', '-at_install', 'drs')
class TestDRSTemporaryUnemployment(TestDRSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.worker = cls._create_drs_employee(
            'Blue-collar Worker',
            l10n_be_joint_committee_id=cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_111').id,
            l10n_be_worker_code_id=cls.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id,
            wage_type='hourly',
            hourly_wage=18.4512,
        )
        cls.white_collar = cls._create_drs_employee('White-collar Worker', wage=3500.0)

    def _get_wech002(self, employee):
        return self._get_declarations(employee, 'WECH002').sorted(lambda drs: (drs.unemployment_start_date, drs.id))

    @freeze_time('2026-10-20 10:00:00')
    def test_wech002(self):
        self._create_validated_leave(self.worker, 'l10n_be_work_entry_type_temporary_unemployment_bad_weather', date(2026, 10, 5), date(2026, 10, 6))
        self._create_validated_leave(
            self.worker, 'l10n_be_work_entry_type_temporary_unemployment_force_majeure_medical', date(2026, 10, 12), date(2026, 10, 13))
        self._create_validated_leave(
            self.white_collar, 'l10n_be_work_entry_type_temporary_economic_unemployement_employee', date(2026, 10, 7), date(2026, 10, 9))

        bad_weather, medical_force_majeure = self._get_wech002(self.worker)
        self.assertRecordValues(bad_weather + medical_force_majeure, [
            {'code': '002', 'month': '10', 'year': 2026, 'unemployment_start_date': date(2026, 10, 5), 'is_automatically_created': True},
            {'code': '005', 'month': '10', 'year': 2026, 'unemployment_start_date': date(2026, 10, 12), 'is_automatically_created': True},
        ])
        suspension = self._get_wech002(self.white_collar)
        self.assertRecordValues(suspension, [{'code': '011', 'unemployment_start_date': date(2026, 10, 7)}])

        self._assertDRSEqual(self._get_drs_dict(bad_weather), label='bad_weather')
        self._assertDRSEqual(self._get_drs_dict(medical_force_majeure), label='medical_force_majeure')
        self._assertDRSEqual(self._get_drs_dict(suspension), label='suspension')

        # The hourly wage is declared in hundredths of cent
        calculation_base = self._get_drs_dict(bad_weather)['WECH002']['Form']['EmployerDeclarationLink']['NaturalPerson']['WorkerRecordLink']['OccupationLink']['AnnualDclTempUnemployment']['CalculationBaseAllowance']
        self.assertEqual(calculation_base, {'RemunerationTimeUnit': '1', 'PieceTaskServicesCommissionRemunerationBasisAmount': '184512'})

    @freeze_time('2026-10-20 10:00:00')
    def test_wech002_force_majeure(self):
        leave = self._create_validated_leave(
            self.worker, 'l10n_be_work_entry_type_temporary_unemployment_force_majeure', date(2026, 10, 5), date(2026, 10, 6))
        force_majeure = self._get_wech002(self.worker)
        self.assertEqual(force_majeure.code, '004')
        with self.assertRaisesRegex(ValidationError, 'it\'s the reason of the force majeure'):
            self._get_drs_dict(force_majeure)

        leave.private_name = 'Flooding of the workshop'
        force_majeure.invalidate_recordset(['major_force_reason'])
        annual_declaration = self._get_drs_dict(force_majeure)['WECH002']['Form']['EmployerDeclarationLink']['NaturalPerson']['WorkerRecordLink']['OccupationLink']['AnnualDclTempUnemployment']
        self.assertEqual(annual_declaration['MajorForceReason'], 'Flooding of the workshop')

    @freeze_time('2026-10-20 10:00:00')
    def test_wech002_errors(self):
        # Bad weather is reserved to the blue-collar workers
        self._create_validated_leave(
            self.white_collar, 'l10n_be_work_entry_type_temporary_unemployment_bad_weather', date(2026, 10, 5), date(2026, 10, 5))
        with self.assertRaisesRegex(ValidationError, 'reserved to the blue-collar workers'):
            self._get_drs_dict(self._get_wech002(self.white_collar))

        # A declaration without temporary unemployment starting in the month
        drs = self._create_drs(self.worker, 'drs_risk_wech002_002', 2026, 9)
        with self.assertRaisesRegex(ValidationError, 'no temporary unemployment to declare'):
            self._get_drs_dict(drs)

    @freeze_time('2026-10-20 10:00:00')
    def test_wech002_start_date_errors(self):
        # The temporary unemployment is declared from the month before
        self._create_validated_leave(self.worker, 'l10n_be_work_entry_type_temporary_unemployment_bad_weather', date(2026, 12, 7), date(2026, 12, 7))
        with self.assertRaisesRegex(ValidationError, 'it can only be declared from the month before'):
            self._get_drs_dict(self._get_wech002(self.worker))

    @freeze_time('2026-10-20 10:00:00')
    def test_wech002_cancellation(self):
        leave = self._create_validated_leave(self.worker, 'l10n_be_work_entry_type_temporary_unemployment_bad_weather', date(2026, 10, 5), date(2026, 10, 6))
        wech002 = self._get_wech002(self.worker)
        self._notify_drs(wech002, '3400048ENN00A')
        # The time off is cancelled: the declaration accepted by the social security is cancelled
        leave.action_refuse()
        self.assertFalse(wech002.unemployment_start_date)
        cancellation = self.env['l10n.be.drs'].browse(wech002.action_cancel_declaration()['res_id'])
        form = self._get_drs_dict(cancellation)['WECH002']['Form']
        self.assertEqual(form['AttestationStatus'], '3')
        self.assertEqual(form['Reference'][1]['ReferenceNbr'], '3400048ENN00A')
        self.assertNotIn('WorkerRecordLink', form['EmployerDeclarationLink']['NaturalPerson'])

    @freeze_time('2026-10-20 10:00:00')
    def test_wech005_occupations_of_the_month(self):
        # The occupation of the worker ends in the middle of the month, a new one starts after a gap
        self.worker.version_id.contract_date_end = date(2026, 9, 10)
        new_version = self.worker.create_version({
            'date_version': date(2026, 9, 21),
            'contract_date_start': date(2026, 9, 21),
            'contract_date_end': False,
        })
        self.assertEqual(new_version._get_occupation_dates()[-1][1], date(2026, 9, 21))
        self._create_validated_leave(self.worker, 'l10n_be_work_entry_type_temporary_unemployment_bad_weather', date(2026, 9, 7), date(2026, 9, 7))
        self._create_validated_leave(self.worker, 'l10n_be_work_entry_type_temporary_unemployment_bad_weather', date(2026, 9, 22), date(2026, 9, 22))
        with self.assertRaisesRegex(ValidationError, 'outside of their last occupation of the month'):
            self._get_drs_dict(self._get_declarations(self.worker, 'WECH005'))

    def test_wech002_needed_declarations(self):
        employee = self._create_drs_employee(
            'Unemployed Worker',
            l10n_be_joint_committee_id=self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_111').id,
            l10n_be_worker_code_id=self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id,
        )
        with patch.object(self.env.registry['hr.version'], '_l10n_be_dimona_autodeclare'):
            employee.create_version({'date_version': date(2027, 2, 1), 'resource_calendar_id': self.calendar_19h.id})

        # Each leave is validated separately, so it is compared against the declarations already created
        for xmlid, date_from, date_to, expected_drs, reason in [
            ('l10n_be_work_entry_type_temporary_unemployment_bad_weather', date(2026, 10, 5), date(2026, 10, 5), [('002', date(2026, 10, 5))], "First unemployment in the company"),
            ('l10n_be_work_entry_type_temporary_unemployment_bad_weather', date(2026, 11, 2), date(2026, 11, 2), [], "Already declared since October 1st"),
            ('l10n_be_work_entry_type_temporary_unemployment_incident', date(2026, 12, 7), date(2026, 12, 7), [], "A different risk doesn't require a new declaration"),
            ('l10n_be_work_entry_type_temporary_unemployment_force_majeure_medical', date(2026, 12, 14), date(2026, 12, 14), [('005', date(2026, 12, 14))], "Risk 005 is always declared separately"),
            ('l10n_be_work_entry_type_temporary_unemployment_dismissal', date(2027, 1, 4), date(2027, 1, 4), [('010', date(2027, 1, 4))], "Risk 010 is always declared separately"),
            ('l10n_be_work_entry_type_temporary_unemployment_bad_weather', date(2027, 2, 8), date(2027, 2, 8), [('002', date(2027, 2, 8))], "Contract hours changed since the last declaration"),
            ('l10n_be_work_entry_type_temporary_unemployment_bad_weather', date(2027, 3, 1), date(2027, 3, 1), [], "Already declared with the current contract hours"),
            ('l10n_be_work_entry_type_temporary_unemployment_bad_weather', date(2027, 9, 27), date(2027, 10, 4), [('002', date(2027, 10, 1))], "New period starting on October 1st"),
        ]:
            with self.subTest(reason):
                existing_drs = self._get_wech002(employee)
                self._create_validated_leave(employee, xmlid, date_from, date_to)
                new_drs = self._get_wech002(employee) - existing_drs
                self.assertEqual([(drs.code, drs.unemployment_start_date) for drs in new_drs], expected_drs)

        # The declarations of a refused time off are removed, if they weren't generated yet
        leave = self.env['hr.leave'].search([('employee_id', '=', employee.id), ('request_date_from', '=', date(2027, 1, 4))])
        leave.action_refuse()
        self.assertEqual(self._get_wech002(employee).mapped('code'), ['002', '005', '002', '002'])

    def test_wech002_validated_by_time_off_officer(self):
        officer = new_test_user(self.env, login='time_off_officer', groups='base.group_user,hr_holidays.group_hr_holidays_user', company_id=self.belgian_company.id)
        self._create_validated_leave(
            self.worker, 'l10n_be_work_entry_type_temporary_unemployment_bad_weather', date(2026, 10, 5), date(2026, 10, 5), approver=officer)
        self.assertEqual(self._get_wech002(self.worker).unemployment_start_date, date(2026, 10, 5))

    @freeze_time('2026-10-20 10:00:00')
    def test_wech005(self):
        self._create_validated_leave(self.worker, 'l10n_be_work_entry_type_temporary_unemployment_bad_weather', date(2026, 9, 7), date(2026, 9, 8))
        self._create_validated_leave(self.worker, 'l10n_be_work_entry_type_temporary_unemployment_incident', date(2026, 9, 15), date(2026, 9, 15))
        self._create_validated_leave(self.worker, 'l10n_be_work_entry_type_temporary_unemployment_strike', date(2026, 9, 29), date(2026, 10, 1))

        # One declaration by month, with all the risks of the month
        september, october = self._get_declarations(self.worker, 'WECH005')
        self.assertRecordValues(september + october, [
            {'month': '9', 'year': 2026, 'is_automatically_created': True},
            {'month': '10', 'year': 2026, 'is_automatically_created': True},
        ])
        september_dict = self._get_drs_dict(september)
        self._assertDRSEqual(september_dict, label='september')
        form = september_dict['WECH005']['Form']
        self.assertEqual([risk['IdentificationOfRisk'] for risk in form['RiskIdentification']], ['002', '003', '009'])
        monthly_declaration = form['EmployerDeclarationLink']['NaturalPerson']['WorkerRecordLink']['OccupationLink']['MonthlyDclTempUnemploymentHours']
        self.assertEqual(
            [(day['DayIndicator'], day['DayNatureCode'], day['HoursNumber']) for day in monthly_declaration['ReferencePeriod']['NatureOfDay']],
            [('--09-07', '5.2', '760'), ('--09-08', '5.2', '760'), ('--09-15', '5.3', '760'), ('--09-29', '5.9', '760'), ('--09-30', '5.9', '760')])

        # The month must be over
        with self.assertRaisesRegex(ValidationError, 'once the month is over'):
            self._get_drs_dict(october)

    @freeze_time('2026-10-20 10:00:00')
    def test_wech005_part_time(self):
        part_time = self._create_drs_employee('Part-time White-collar Worker', resource_calendar_id=self.calendar_19h.id, wage=1750.0)
        self._create_validated_leave(
            part_time, 'l10n_be_work_entry_type_temporary_economic_unemployement_employee', date(2026, 9, 14), date(2026, 9, 15))
        wech005 = self._get_declarations(part_time, 'WECH005')
        drs_dict = self._get_drs_dict(wech005)
        self._assertDRSEqual(drs_dict)
        # The occupation of a part-time worker is limited to the month
        occupation = drs_dict['WECH005']['Form']['EmployerDeclarationLink']['NaturalPerson']['WorkerRecordLink']['OccupationLink']
        self.assertEqual(occupation['OccupationStartingDate'], '2026-09-01')
        self.assertEqual(occupation['OccupationEndingDate'], '2026-09-30')
        self.assertEqual(occupation['OccupationFeatures'], {'OccupationInterruption': '2', 'WorkScheduleCode': '10'})

        # The declaration is removed when the time off is cancelled
        self.env['hr.leave'].search([('employee_id', '=', part_time.id)]).action_refuse()
        self.assertTrue(wech005.exists(), "Generated declarations are kept")

    @freeze_time('2026-10-20 10:00:00')
    def test_wech005_errors(self):
        self._create_validated_leave(self.worker, 'l10n_be_work_entry_type_temporary_unemployment_force_majeure', date(2026, 9, 7), date(2026, 9, 7))
        wech005 = self._get_declarations(self.worker, 'WECH005')
        with self.assertRaisesRegex(ValidationError, 'reason of the force majeure'):
            self._get_drs_dict(wech005)

        drs = self._create_drs(self.worker, 'drs_risk_wech005_001', 2026, 8)
        with self.assertRaisesRegex(ValidationError, 'thus a declaration for that month is unnecessary'):
            self._get_drs_dict(drs)
