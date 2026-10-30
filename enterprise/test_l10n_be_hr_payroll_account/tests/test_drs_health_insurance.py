# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import freeze_time, tagged

from .common_drs import TestDRSCommon


@tagged('post_install', '-at_install', 'drs')
class TestDRSHealthInsurance(TestDRSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls._create_drs_employee('Sick Employee', sex='male')
        cls.mother = cls._create_drs_employee('Mother', sex='female', birthday=date(1992, 3, 3))

    def _get_reference_period(self, drs_dict):
        employer_declaration = drs_dict['ZIMA001']['Form']['EmployerDeclaration']
        return employer_declaration['NaturalPerson']['WorkerRecord']['Occupation']['RiskDetailOccupation'].get('ReferencePeriod')

    @freeze_time('2026-07-20 10:00:00')
    def test_zima001_incapacity(self):
        # The incapacity covered by the guaranteed salary isn't declared
        self._create_validated_leave(self.employee, 'be_work_entry_type_sick_leave', date(2026, 5, 4), date(2026, 5, 8))
        self.assertFalse(self._get_declarations(self.employee, 'ZIMA001'))

        # It's declared once the guaranteed salary is over
        self._create_validated_leave(self.employee, 'be_work_entry_type_sick_leave', date(2026, 6, 1), date(2026, 7, 12))
        incapacity = self._get_declarations(self.employee, 'ZIMA001')
        self.assertRecordValues(incapacity, [{
            'code': '001', 'month': '6', 'year': 2026, 'risk_start_date': date(2026, 6, 1), 'risk_end_date': date(2026, 7, 12)}])
        drs_dict = self._get_drs_dict(incapacity)
        self._assertDRSEqual(drs_dict)
        form = drs_dict['ZIMA001']['Form']
        self.assertEqual(form['CoordinatesContactPerson']['Communication']['EmailAddress'], 'hr@example.com')
        self.assertEqual(form['RiskDetail'], {'RiskStartingDate': '2026-06-01'})
        self.assertEqual(form['EmployerDeclaration']['Quarter'], '20262')
        # Only the days paid by the employer are declared
        reference_period = self._get_reference_period(drs_dict)
        self.assertEqual((reference_period['RefStartingDate'], reference_period['RefEndingDate']), ('2026-06-01', '2026-06-30'))
        self.assertEqual({day['DayNatureCode'] for day in reference_period['NatureOfDay']}, {'2.6'})

        # A relapse within 14 days is the same risk
        self._create_validated_leave(self.employee, 'be_work_entry_type_sick_leave', date(2026, 7, 20), date(2026, 7, 31))
        self.assertEqual(self._get_declarations(self.employee, 'ZIMA001'), incapacity)
        incapacity.invalidate_recordset(['risk_end_date'])
        self.assertEqual(incapacity.risk_end_date, date(2026, 7, 31))

    @freeze_time('2026-07-20 10:00:00')
    def test_zima001_birth_leave(self):
        # The days paid by the employer alone aren't declared
        self._create_validated_leave(self.employee, 'l10n_be_work_entry_type_paternity_company', date(2026, 6, 1), date(2026, 6, 3))
        self.assertFalse(self._get_declarations(self.employee, 'ZIMA001'))

        self._create_validated_leave(self.employee, 'l10n_be_work_entry_type_paternity_legal', date(2026, 6, 4), date(2026, 6, 12))
        birth_leave = self._get_declarations(self.employee, 'ZIMA001')
        self.assertRecordValues(birth_leave, [{'code': '006', 'risk_start_date': date(2026, 6, 1), 'risk_end_date': date(2026, 6, 12)}])
        reference_period = self._get_reference_period(self._get_drs_dict(birth_leave))
        self.assertEqual((reference_period['RefStartingDate'], reference_period['RefEndingDate']), ('2026-06-01', '2026-06-12'))
        self.assertEqual(
            [day['DayNatureCode'] for day in reference_period['NatureOfDay']],
            ['1.6', '1.6', '1.6', '6.10', '6.10', '6.10', '6.10', '6.10', '6.10', '6.10'])

    @freeze_time('2026-07-20 10:00:00')
    def test_zima001_adoption_leave(self):
        # The days paid by the employer alone aren't declared
        self._create_validated_leave(self.employee, 'l10n_be_work_entry_type_adoption_company', date(2026, 6, 1), date(2026, 6, 3))
        self.assertFalse(self._get_declarations(self.employee, 'ZIMA001'))

    @freeze_time('2026-07-20 10:00:00')
    def test_zima001_location_unit(self):
        self._create_validated_leave(self.employee, 'be_work_entry_type_sick_leave', date(2026, 6, 1), date(2026, 7, 12))
        incapacity = self._get_declarations(self.employee, 'ZIMA001')
        location_unit = self.env['hr.work.location'].search([('address_id', '=', self.walloon_partner.id)])
        location_unit.bce_code = '2123456789'
        with self.assertRaisesRegex(ValidationError, 'has an invalid check digit'):
            self._get_drs_dict(incapacity)
        location_unit.write({'bce_code': '2123456791', 'date_end': date(2026, 5, 31)})
        with self.assertRaisesRegex(ValidationError, "isn't valid at the start of the risk"):
            self._get_drs_dict(incapacity)
        location_unit.date_end = False
        location_unit.location_type = 'office'
        with self.assertRaisesRegex(ValidationError, "isn't linked to a location unit"):
            self._get_drs_dict(incapacity)

    @freeze_time('2026-07-20 10:00:00')
    def test_zima001_maternity(self):
        self._create_validated_leave(self.mother, 'l10n_be_work_entry_type_maternity', date(2026, 6, 1), date(2026, 9, 13))
        maternity = self._get_declarations(self.mother, 'ZIMA001')
        self.assertRecordValues(maternity, [{'code': '002', 'risk_start_date': date(2026, 6, 1)}])
        # The health insurance pays all the days
        self.assertFalse(self._get_reference_period(self._get_drs_dict(maternity)))

        # The maternity rest is reserved to women
        with self.assertRaisesRegex(ValidationError, "doesn't match the sex"):
            self._get_drs_dict(self._create_drs(self.employee, 'drs_risk_zima001_002', 2026, 6))

    @freeze_time('2026-07-20 10:00:00')
    def test_zima006(self):
        self._create_validated_leave(self.employee, 'be_work_entry_type_sick_leave', date(2026, 6, 1), date(2026, 7, 12))
        incapacity = self._get_declarations(self.employee, 'ZIMA001')
        # The employee resumes the work on the monday following the incapacity
        work_recovery = self._get_declarations(self.employee, 'ZIMA006')
        self.assertRecordValues(work_recovery, [{
            'month': '7', 'year': 2026, 'work_recovery_date': date(2026, 7, 13), 'origin_drs_id': incapacity.id, 'is_automatically_created': True}])
        # The return to work refers to a risk known by the health insurance
        with self.assertRaisesRegex(ValidationError, 'must be accepted by the social security first'):
            self._get_drs_dict(work_recovery)
        self._notify_drs(incapacity, '3400048ENN00A')
        drs_dict = self._get_drs_dict(work_recovery)
        self._assertDRSEqual(drs_dict)
        self.assertEqual(drs_dict['ZIMA006']['Form']['EmployerDeclarationLink']['NaturalPerson']['WorkRecovery'], {'WorkRecoveryDate': '2026-07-13'})

        # A relapse postpones the return to work
        work_recovery.xml_file = False
        self._create_validated_leave(self.employee, 'be_work_entry_type_sick_leave', date(2026, 7, 20), date(2026, 7, 31))
        self.assertFalse(work_recovery.exists())
        work_recovery = self._get_declarations(self.employee, 'ZIMA006')
        self.assertRecordValues(work_recovery, [{'month': '8', 'work_recovery_date': date(2026, 8, 3)}])
        with self.assertRaisesRegex(ValidationError, 'once the work resumed'):
            self._get_drs_dict(work_recovery)

    @freeze_time('2026-07-20 10:00:00')
    def test_zima006_birth_leave(self):
        self._create_validated_leave(self.employee, 'l10n_be_work_entry_type_paternity_legal', date(2026, 6, 4), date(2026, 6, 12))
        self.assertTrue(self._get_declarations(self.employee, 'ZIMA001'))
        self.assertFalse(self._get_declarations(self.employee, 'ZIMA006'))

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

    @freeze_time('2026-04-10 10:00:00')
    def test_zima002_medical_part_time(self):
        # Medical part-time: the employee works 3 days a week, the 2 others are adapted work absences
        partial_incapacity = self.env.ref('hr_work_entry.l10n_be_work_entry_type_partial_incapacity')
        calendar = self.env['resource.calendar'].create({
            'name': 'Medical part-time',
            'company_id': self.belgian_company.id,
            'hours_per_day': 7.6,
            'reference_calendar_id': self.calendar_38h.id,
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'dayofweek': str(day), 'hour_from': hour_from, 'hour_to': hour_to,
                        **({'work_entry_type_id': partial_incapacity.id} if day >= 3 else {})})
                for day in range(5) for hour_from, hour_to in ((8, 12), (13, 16.6))
            ],
        })
        employee = self._create_drs_employee('Medical Part-time Worker', resource_calendar_id=calendar.id)
        self._validate_payslip(employee, date(2026, 3, 1), date(2026, 3, 31))
        adapted_work = self._get_declarations(employee, 'ZIMA002')
        self.assertRecordValues(adapted_work, [{'code': '001', 'month': '3', 'year': 2026, 'is_automatically_created': True}])
        drs_dict = self._get_drs_dict(adapted_work)
        self._assertDRSEqual(drs_dict)
        occupation = drs_dict['ZIMA002']['Form']['EmployerDeclarationLink']['NaturalPerson']['WorkerRecordLink']['OccupationLink']
        # The occupation includes the medical part-time, not the adapted work
        self.assertEqual((occupation['MeanWorkingHours'], occupation['WorkingDaysSystem'], occupation['ContractType']), ('3800', '500', '0'))
        self.assertEqual(occupation['ExceptSituationCalculBase'], {'ExceptSituationMeanWorkingHours': '2280', 'ExceptSituationWorkingDaysSystem': '300'})
        services = occupation['ReferencePeriod']['Service']
        self.assertEqual([service['ServiceCode'] for service in services], ['001', '050'])
        self.assertNotIn('ExactSalary', occupation['ReferencePeriod'])

    @freeze_time('2026-04-10 10:00:00')
    def test_zima002_maternity_protection(self):
        # Partial removal from work: the mother works in the morning
        maternity_protection = self.env.ref('hr_work_entry.l10n_be_work_entry_type_prophylactic_time_off_maternity_protection')
        calendar = self.env['resource.calendar'].create({
            'name': 'Partial removal from work',
            'company_id': self.belgian_company.id,
            'hours_per_day': 7.6,
            'reference_calendar_id': self.calendar_38h.id,
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'dayofweek': str(day), 'hour_from': hour_from, 'hour_to': hour_to,
                        **({'work_entry_type_id': maternity_protection.id} if hour_from == 13 else {})})
                for day in range(5) for hour_from, hour_to in ((8, 12), (13, 16.6))
            ],
        })
        self.mother.version_id.resource_calendar_id = calendar
        payslip = self._validate_payslip(self.mother, date(2026, 3, 1), date(2026, 3, 31))
        adapted_work = self._get_declarations(self.mother, 'ZIMA002')
        self.assertRecordValues(adapted_work, [{'code': '002', 'month': '3', 'payslip_id': payslip.id}])
        reference_period = self._get_drs_dict(adapted_work)['ZIMA002']['Form']['EmployerDeclarationLink']['NaturalPerson']['WorkerRecordLink']['OccupationLink']['ReferencePeriod']
        self.assertEqual(reference_period['ExactSalary'], {
            'ExactSalaryCode': '001',
            'ExactSalaryAmount': str(round(payslip._get_line_values(['SALARY'])['SALARY'][payslip.id]['total'] * 100)),
        })
        self.assertNotIn('Service', reference_period)

    @freeze_time('2026-04-10 10:00:00')
    def test_zima003(self):
        # The mother takes 2 breastfeeding pauses of half an hour each day
        breast_feeding = self.env.ref('hr_work_entry.l10n_be_work_entry_type_breast_feeding')
        calendar = self.env['resource.calendar'].create({
            'name': 'Breastfeeding',
            'company_id': self.belgian_company.id,
            'hours_per_day': 7.6,
            'reference_calendar_id': self.calendar_38h.id,
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'dayofweek': str(day), 'hour_from': hour_from, 'hour_to': hour_to,
                        **({'work_entry_type_id': breast_feeding.id} if is_pause else {})})
                for day in range(5) for hour_from, hour_to, is_pause in ((8, 12, False), (13, 15.6, False), (15.6, 16.6, True))
            ],
        })
        self.mother.version_id.write({'resource_calendar_id': calendar.id, 'wage': 4200})
        self._validate_payslip(self.mother, date(2026, 3, 1), date(2026, 3, 31))
        breastfeeding = self._get_declarations(self.mother, 'ZIMA003')
        self.assertRecordValues(breastfeeding, [{'month': '3', 'year': 2026, 'is_automatically_created': True}])
        drs_dict = self._get_drs_dict(breastfeeding)
        self._assertDRSEqual(drs_dict)
        reference_period = drs_dict['ZIMA003']['Form']['EmployerDeclarationLink']['NaturalPerson']['WorkerRecordLink']['OccupationLink']['ReferencePeriod']
        # 22 days of March, the hourly salary in hundredths of cent (4200 * 12 / (52 * 38) = 25.5061)
        self.assertEqual(reference_period, {
            'RefStartingDate': '2026-03-01',
            'RefEndingDate': '2026-03-31',
            'BreastFeedingPause': {'BreastFeedingPauseNbr': '44', 'BreastFeedingHourlyGrossSalary': '255061'},
        })

        with self.assertRaisesRegex(ValidationError, 'reserved to women'):
            self._get_drs_dict(self._create_drs(self.employee, 'drs_risk_zima003_001', 2026, 3))
