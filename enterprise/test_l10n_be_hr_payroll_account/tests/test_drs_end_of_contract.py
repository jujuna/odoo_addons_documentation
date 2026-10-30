# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date, datetime
from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo.exceptions import ValidationError
from odoo.tests import freeze_time, tagged

from .common_drs import TestDRSCommon


@tagged('post_install', '-at_install', 'drs')
class TestDRSEndOfContract(TestDRSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls._create_drs_employee('Leaving Worker')

    def _create_departure(self, xmlid, dismissal_date, departure_date=None, **values):
        with patch.object(self.env.registry['hr.version'], '_l10n_be_dimona_autodeclare'):
            return self.env['hr.employee.departure'].create({
                'employee_id': self.employee.id,
                'departure_reason_id': self.env.ref(xmlid).id,
                'dismissal_date': dismissal_date,
                **({'departure_date': departure_date} if departure_date else {}),
                **values,
            })

    def _get_occupations(self, drs_dict):
        return [
            (employer_declaration['Quarter'], employer_declaration['NaturalPerson']['WorkerRecord']['Occupation'])
            for employer_declaration in drs_dict['WECH001']['Form']['EmployerDeclaration']
        ]

    @freeze_time('2026-06-26 10:00:00')
    def test_wech001_fixed_term(self):
        self._create_validated_leave(self.employee, 'be_work_entry_type_legal_leave', date(2026, 3, 2), date(2026, 3, 3))
        self._create_validated_leave(self.employee, 'be_work_entry_type_legal_leave', date(2026, 5, 4), date(2026, 5, 4))
        self._create_departure('l10n_be_hr_payroll.departure_contract_end_fixed_term', date(2026, 6, 30), departure_date=date(2026, 6, 30))

        wech001 = self._get_declarations(self.employee, 'WECH001')
        self.assertRecordValues(wech001, [{'code': '001', 'month': '6', 'year': 2026, 'is_automatically_created': True}])
        drs_dict = self._get_drs_dict(wech001)
        self._assertDRSEqual(drs_dict)

        # The previous quarter isn't declared in a DmfA yet
        (previous_quarter, previous_occupation), (end_quarter, end_occupation) = self._get_occupations(drs_dict)
        self.assertEqual((previous_quarter, end_quarter), ('20261', '20262'))
        self.assertNotIn('OccupationEndingDate', previous_occupation)
        self.assertNotIn('DclEndContractOrFTEarlyPension', previous_occupation)
        self.assertEqual(end_occupation['OccupationEndingDate'], '2026-06-30')
        self.assertEqual(end_occupation['OccupationFeatures'], {'OccupationInterruption': '0', 'DeviationFromQ': '0'})
        self.assertEqual(end_occupation['DclEndContractOrFTEarlyPension'], {
            'CompensatoryRecoveryServiceDay': '0',
            'PaymentIndicator': '0',
            'CalculationBaseAllowance': {'RemunerationTimeUnit': '4', 'RemunerationBasisAmount': '250000'},
            # 3 days of legal holidays in a regime of 5 days are 3.6 days in a regime of 6 days, rounded to the half day
            'HolidaysSector': {'HolidaySectorIndicator': '1', 'HolidayDetail': {'HolidayCode': '1', 'HolidayDaysNumber': '35'}},
        })

    @freeze_time('2026-07-10 10:00:00')
    def test_wech001_dismissal_without_notice(self):
        departure = self._create_departure(
            'l10n_be_hr_payroll.departure_fired_termination_employer', date(2026, 7, 10), l10n_be_notice_respect='without')
        self.assertEqual(departure.departure_date, date(2026, 7, 10))
        notice_end = departure.l10n_be_notice_period_theoretical_end
        self.assertGreater(notice_end, departure.departure_date)
        # The public holidays following the period covered by the indemnity are paid by the employer, but the
        # social security only accepts the ones of the 60 days following the end of the contract
        public_holidays = self.env['resource.calendar.leaves'].create([{
            'name': 'Public Holiday',
            'company_id': self.belgian_company.id,
            'date_from': datetime.combine(day, datetime.min.time()),
            'date_to': datetime.combine(day, datetime.max.time()),
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id,
        } for day in (notice_end, date.fromordinal(notice_end.toordinal() + 10), date.fromordinal(notice_end.toordinal() + 40))])

        wech001 = self._get_declarations(self.employee, 'WECH001')
        self.assertGreater(notice_end, departure.departure_date + relativedelta(days=60))
        with self.assertRaisesRegex(ValidationError, 'more than 60 days after it'):
            self._get_drs_dict(wech001)
        public_holidays.unlink()
        occupation = self._get_occupations(self._get_drs_dict(wech001))[-1][1]
        self.assertEqual(occupation['OccupationEndingDate'], '2026-07-10')
        self.assertEqual(occupation['SeverancePayment'], {
            'SeverancePaymentStartDate': '2026-07-11',
            'SeverancePaymentEndDate': notice_end.strftime('%Y-%m-%d'),
        })
        end_block = occupation['DclEndContractOrFTEarlyPension']
        self.assertEqual(end_block['PaymentIndicator'], '0')
        self.assertNotIn('PublicHolidayIndicator', end_block)

    @freeze_time('2026-07-10 10:00:00')
    def test_wech001_public_holidays_timezone(self):
        self._create_departure('l10n_be_hr_payroll.departure_fired_termination_employer', date(2026, 6, 1), departure_date=date(2026, 7, 10))
        # The national holiday starts at midnight in Brussels, the evening before in UTC
        self.env['resource.calendar.leaves'].create({
            'name': 'National Holiday',
            'company_id': self.belgian_company.id,
            'date_from': datetime(2026, 7, 20, 22, 0),
            'date_to': datetime(2026, 7, 21, 21, 59, 59),
            'work_entry_type_id': self.env.ref('hr_work_entry.l10n_be_work_entry_type_bank_holiday').id,
        })
        end_block = self._get_occupations(self._get_drs_dict(self._get_declarations(self.employee, 'WECH001')))[-1][1]['DclEndContractOrFTEarlyPension']
        self.assertEqual(end_block['PublicHolidayIndicator'], '2026-07-21')

    @freeze_time('2026-06-26 10:00:00')
    def test_wech001_interruption(self):
        self._create_validated_leave(self.employee, 'l10n_be_work_entry_type_long_sick', date(2026, 4, 6), date(2026, 4, 10))
        self._create_departure('l10n_be_hr_payroll.departure_contract_end_fixed_term', date(2026, 6, 30), departure_date=date(2026, 6, 30))
        occupation = self._get_occupations(self._get_drs_dict(self._get_declarations(self.employee, 'WECH001')))[-1][1]
        self.assertEqual(occupation['OccupationFeatures'], {'OccupationInterruption': '1', 'DeviationFromQ': '0'})
        self.assertEqual([(service['ServiceCode'], service['ServiceNbrDays']) for service in occupation['Service']], [('001', '06000'), ('050', '00500')])

    @freeze_time('2026-06-26 10:00:00')
    def test_wech001_cancelled_departure(self):
        departure = self._create_departure('l10n_be_hr_payroll.departure_contract_end_fixed_term', date(2026, 6, 30), departure_date=date(2026, 6, 30))
        self.assertTrue(self._get_declarations(self.employee, 'WECH001'))
        self.employee.version_id.contract_date_end = False
        departure.unlink()
        self.assertFalse(self._get_declarations(self.employee, 'WECH001'))

    @freeze_time('2026-06-26 10:00:00')
    def test_wech001_cancelled_departure_contract_end(self):
        departure = self._create_departure('l10n_be_hr_payroll.departure_contract_end_fixed_term', date(2026, 6, 30), departure_date=date(2026, 6, 30))
        declaration = self._get_declarations(self.employee, 'WECH001')
        # The contract still ends during the month
        departure.unlink()
        self.assertEqual(self._get_declarations(self.employee, 'WECH001'), declaration)
        self.assertFalse(declaration.departure_id)

    @freeze_time('2026-06-26 10:00:00')
    def test_wech001_other_risks(self):
        # The early retirements need data unknown by Odoo
        self._create_departure('l10n_be_hr_payroll.departure_fired_early_retirement', date(2026, 6, 30), departure_date=date(2026, 6, 30))
        early_retirement = self._get_declarations(self.employee, 'WECH001')
        self.assertEqual(early_retirement.code, '002')
        with self.assertRaisesRegex(ValidationError, 'company supplement'):
            self._get_drs_dict(early_retirement)

        # The proof of work only declares the occupation
        other_employee = self._create_drs_employee('Working Worker')
        proof_of_work = self._create_drs(other_employee, 'drs_risk_wech001_004', 2026, 5)
        occupations = self._get_occupations(self._get_drs_dict(proof_of_work))
        self.assertEqual([quarter for quarter, occupation in occupations], ['20261', '20262'])
        self.assertNotIn('DclEndContractOrFTEarlyPension', occupations[-1][1])
        self.assertNotIn('OccupationEndingDate', occupations[-1][1])
