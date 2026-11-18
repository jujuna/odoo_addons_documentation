# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from freezegun import freeze_time
from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo.tests import tagged

from odoo.addons.l10n_be_hr_payroll.models.utils import xml_str_to_dict
from odoo.addons.l10n_be_hr_payroll.tests.common import TestPayrollCommon


@tagged('post_install', '-at_install', 'post_install_l10n')
class TestDmfaUnexperiencedReduction(TestPayrollCommon):
    """Tests for the ONSS reduction for unexperienced employees (Flanders).

    The declaration computes the reduction per occupation line under the
    deduction code 6340. The ONSSUNEXPERIENCED salary rule computes it the same
    way on the last payslip of the quarter, as Partena does, regularised against
    the earlier payslips (a correction after the last payslip), so that the
    payslips of the quarter add up to what is declared."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.belgian_company.current_payroll_config_id.write({
            'l10n_be_employer_category_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00000').id,
            'onss_registration_number': '125482497',
            'onss_importance_code': '3',
        })
        fl_address = cls.env['res.partner'].create({
            'name': 'FL Work Address',
            'street': 'Main Street 1',
            'zip': '1000',
            'city': 'Brussels',
            'country_id': cls.env.ref('base.be').id,
        })

        cls.fl_employee = cls.create_employee({
            'name': 'Employee',
            'niss': '85073003328',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'contract_date_end': False,
            'wage': 2000.0,
            'address_id': fl_address.id,
            'l10n_be_worker_code_id': cls.worker_code_id.id,
            'l10n_be_dimona_category': 'oth',
            'l10n_be_onss_reduction_unexperienced_employees_flander': True,
        })

        cls.env['hr.work.location'].create({
            'address_id': cls.fl_employee.address_id.id,
            'bce_code': '8888888572',
            'location_type': 'dmfa_unit',
            'competence': 'fl',
            'company_id': cls.belgian_company.id,
        })

        wa_address = cls.env['res.partner'].create({
            'name': 'WA Work Address',
            'street': 'Main Street 2',
            'zip': '4000',
            'city': 'Liège',
            'country_id': cls.env.ref('base.be').id,
        })

        cls.wa_employee = cls.create_employee({
            'name': 'Employee',
            'niss': '85073003328',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'contract_date_end': False,
            'wage': 2500.0,
            'address_id': wa_address.id,
            'l10n_be_worker_code_id': cls.worker_code_id.id,
            'l10n_be_dimona_category': 'oth',
            'l10n_be_onss_reduction_unexperienced_employees_flander': False,
        })

        cls.env['hr.work.location'].create({
            'address_id': cls.wa_employee.address_id.id,
            'bce_code': '8888888671',
            'location_type': 'dmfa_unit',
            'competence': 'wa',
            'company_id': cls.belgian_company.id,
        })

    def _generate_dmfa_declaration(self, environment='S', declaration_type='original', year='2025', quarter='1', parent=None, return_declaration=False, skip_signature=True):
        dmfa = self.env['l10n_be.dmfa'].with_user(self.env.user).create({
            'name': 'TESTDMFA',
            'company_id': self.belgian_company.id,
            'year': year,
            'quarter': quarter,
            'declaration_method': 'batch',
            'declaration_type': declaration_type,
            'environment': environment,
            'parent_id': parent.id if parent else False,
        })
        with patch('time.strftime', return_value='10:00:00.000'):
            dmfa.with_context(onss_skip_signature=skip_signature).generate_declaration_xml_report()
        self.assertFalse(dmfa.error_message)
        self.assertEqual(dmfa.state, 'ready')
        if return_declaration:
            return dmfa
        return xml_str_to_dict(dmfa.xml_file.content)

    def _create_payslip(self, employee, date_from, date_to):
        slip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'company_id': employee.company_id.id,
            'version_id': employee._get_version(date_from).id,
            'date_from': date_from,
            'date_to': date_to,
        })
        slip.compute_sheet()
        return slip

    def _create_and_validate_payslip(self, employee, date_from, date_to):
        slip = self._create_payslip(employee, date_from, date_to)
        slip.action_payslip_done()
        return slip

    def _create_and_validate_quarter(self, employee, year, quarter):
        """The 3 validated monthly payslips of the quarter, in chronological order."""
        payslips = self.env['hr.payslip']
        for month in range((quarter - 1) * 3 + 1, quarter * 3 + 1):
            date_from = date(year, month, 1)
            payslips |= self._create_and_validate_payslip(
                employee, date_from, date_from + relativedelta(months=1, days=-1))
        return payslips

    def _create_fl_employee(self, contract_date_start):
        """An eligible employee entering service on contract_date_start, sharing
        the Flemish work address (and its location unit) of self.fl_employee.
        Another person than self.fl_employee: the engagements are looked up by
        NISS."""
        return self.create_employee({
            'name': 'Employee',
            'niss': '85073003427',
            'date_version': contract_date_start,
            'contract_date_start': contract_date_start,
            'contract_date_end': False,
            'wage': 2000.0,
            'address_id': self.fl_employee.address_id.id,
            'l10n_be_worker_code_id': self.worker_code_id.id,
            'l10n_be_dimona_category': 'oth',
            'l10n_be_onss_reduction_unexperienced_employees_flander': True,
        })

    def _declared_starting_dates(self, year, quarter):
        """The dates of the start of the right of the 6340 deductions declared
        for the quarter."""
        dmfa = self._generate_dmfa_declaration(year=year, quarter=quarter, return_declaration=True)
        occupations = xml_str_to_dict(dmfa.xml_file.content)['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']
        deductions = [
            deduction
            for occupation in (occupations if isinstance(occupations, list) else [occupations])
            for deduction in (occupation['OccupationDeduction'] if isinstance(occupation['OccupationDeduction'], list) else [occupation['OccupationDeduction']])
        ]
        return {d.get('DeductionRightStartingDate') for d in deductions if d.get('DeductionCode') == '6340'}

    def _reduction_amount(self, payslips):
        """The reduction granted by those payslips. The lines are signed as a
        reduction of the employer contributions, so the granted amount is their
        opposite."""
        return -sum(payslips.line_ids.filtered(lambda line: line.code == 'ONSSUNEXPERIENCED').mapped('total'))

    def test_standard_eligible_employee(self):
        """Flag=True, FL address, wage below ceiling → the whole quarterly amount
        is granted on the last payslip of the quarter, as Partena does."""
        payslips = self._create_and_validate_quarter(self.fl_employee, 2025, 1)

        self.assertEqual([self._reduction_amount(payslip) for payslip in payslips], [0.0, 0.0, 1000.0])

    def test_nothing_granted_when_no_longer_eligible(self):
        """The employee stops qualifying during the quarter, before its last
        payslip: nothing is granted for the quarter."""
        january = self._create_and_validate_payslip(
            self.fl_employee, date(2025, 1, 1), date(2025, 1, 31))
        self.fl_employee.version_id.l10n_be_onss_reduction_unexperienced_employees_flander = False
        february = self._create_and_validate_payslip(
            self.fl_employee, date(2025, 2, 1), date(2025, 2, 28))
        march = self._create_and_validate_payslip(
            self.fl_employee, date(2025, 3, 1), date(2025, 3, 31))

        self.assertEqual(self._reduction_amount(january | february | march), 0.0)

    def test_reduction_lowers_the_employer_onss(self):
        """The line belongs to the ONSSEMPLOYERDETAIL category and is signed
        negative, so it lowers ONSSEMPLOYER, the total of that category."""
        employer_detail = self.env.ref('l10n_be_hr_payroll.ONSSEMPLOYERDETAIL')
        payslips = self._create_and_validate_quarter(self.fl_employee, 2025, 1)

        self.assertFalse(payslips[:2].line_ids.filtered(lambda line: line.code == 'ONSSUNEXPERIENCED'))
        for payslip in payslips[2:]:
            lines = payslip.line_ids
            reduction = lines.filtered(lambda line: line.code == 'ONSSUNEXPERIENCED')
            self.assertTrue(reduction)
            self.assertLess(reduction.total, 0.0)
            self.assertIn(employer_detail, reduction.salary_rule_id.category_ids)
            detail = lines.filtered(lambda line: employer_detail in line.salary_rule_id.category_ids)
            self.assertAlmostEqual(
                lines.filtered(lambda line: line.code == 'ONSSEMPLOYER').total,
                sum(detail.mapped('total')), places=2)

    def test_declaration_declares_the_payslip_amount(self):
        """The 6340 deduction declared is the amount found on the payslips."""
        payslips = self._create_and_validate_quarter(self.fl_employee, 2025, 1)

        dmfa = self._generate_dmfa_declaration(year=2025, quarter='1', return_declaration=True)
        dmfa_dict = xml_str_to_dict(dmfa.xml_file.content)
        unexperienced_line = dmfa.unexperienced_reduction_line_ids.filtered(lambda l: l.employee_id == self.fl_employee)
        self.assertTrue(unexperienced_line)
        self.assertAlmostEqual(unexperienced_line.amount, self._reduction_amount(payslips))
        occupation_deductions = dmfa_dict['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']['OccupationDeduction']
        # the only deduction of the occupation: no structural reduction block without an amount
        self.assertEqual(occupation_deductions, {
            'DeductionCode': '6340', 'DeductionAmount': '00000100000', 'DeductionRightStartingDate': '2025-01-01'})

    def test_declaration_without_payslip_lines(self):
        """The payslips computed before the reduction was computed on the payslips
        have no ONSSUNEXPERIENCED line: the declaration still declares the 6340
        deduction, computed from the declared occupation, and the mismatch is
        reported on the declaration."""
        self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_onss_unexperienced').active = False
        payslips = self._create_and_validate_quarter(self.fl_employee, 2025, 1)
        self.assertEqual(self._reduction_amount(payslips), 0.0)

        dmfa = self._generate_dmfa_declaration(year=2025, quarter='1', return_declaration=True)
        unexperienced_line = dmfa.unexperienced_reduction_line_ids.filtered(lambda l: l.employee_id == self.fl_employee)
        self.assertAlmostEqual(unexperienced_line.amount, 1000.0)
        occupation_deductions = xml_str_to_dict(dmfa.xml_file.content)['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']['OccupationDeduction']
        # the only deduction of the occupation: no structural reduction block without an amount
        self.assertEqual(occupation_deductions, {
            'DeductionCode': '6340', 'DeductionAmount': '00000100000', 'DeductionRightStartingDate': '2025-01-01'})

        warning = self.env.ref('l10n_be_hr_payroll.hr_payroll_warning_unexperienced_reduction_mismatch')
        self.assertIn(dmfa, warning._get_warning_python_records({'records': dmfa})[0])

    def _create_quarter_with_amendment_in_march(self, version_values, previous_version_values=None):
        """Validated payslips of Q1 2025, with an amendment on 1/3/2025 changing
        the working schedule, which opens a second occupation line, and the
        declaration of the quarter."""
        payslips = self._create_and_validate_payslip(self.fl_employee, date(2025, 1, 1), date(2025, 1, 31))
        payslips |= self._create_and_validate_payslip(self.fl_employee, date(2025, 2, 1), date(2025, 2, 28))
        if previous_version_values:
            self.fl_employee.version_id.write(previous_version_values)
        self.fl_employee.create_version({
            'date_version': date(2025, 3, 1),
            'resource_calendar_id': self.resource_calendar_4_5.id,
            **version_values,
        })
        payslips |= self._create_and_validate_payslip(self.fl_employee, date(2025, 3, 1), date(2025, 3, 31))
        dmfa = self._generate_dmfa_declaration(year=2025, quarter='1', return_declaration=True)
        occupations = xml_str_to_dict(dmfa.xml_file.content)['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']
        self.assertIsInstance(occupations, list)
        self.assertEqual(len(occupations), 2)
        return payslips, dmfa.unexperienced_reduction_line_ids.filtered(lambda l: l.employee_id == self.fl_employee)

    def test_split_over_the_occupation_lines(self):
        """The employee qualifies on both occupation lines: both get a deduction,
        adding up to the amount of the payslips. Together they are worked more
        than 80% of a full time, so the whole 1.000 EUR is granted."""
        payslips, declared_lines = self._create_quarter_with_amendment_in_march({})

        self.assertAlmostEqual(self._reduction_amount(payslips), 1000.0, delta=0.02)
        self.assertEqual(len(declared_lines), 2)
        self.assertTrue(all(line.amount > 0.0 for line in declared_lines), declared_lines.mapped('amount'))
        self.assertAlmostEqual(sum(declared_lines.mapped('amount')), self._reduction_amount(payslips), places=2)

    def test_earlier_occupation_line_keeps_its_share(self):
        """The reduction is computed per occupation line: the second line does
        not qualify anymore, which does not take back what the first one earned."""
        payslips, declared_lines = self._create_quarter_with_amendment_in_march({
            'l10n_be_onss_reduction_unexperienced_employees_flander': False,
        })

        granted = self._reduction_amount(payslips)
        self.assertTrue(0.0 < granted < 1000.0, granted)
        self.assertEqual(len(declared_lines), 1)
        self.assertAlmostEqual(declared_lines.amount, granted, places=2)

    def test_only_the_later_occupation_line_qualifies(self):
        """The first occupation line does not qualify (its version is corrected)
        and the second one does: the March payslip grants the share of the
        second line only, the amount declared for it."""
        payslips, declared_lines = self._create_quarter_with_amendment_in_march(
            {'l10n_be_onss_reduction_unexperienced_employees_flander': True},
            previous_version_values={'l10n_be_onss_reduction_unexperienced_employees_flander': False},
        )

        granted = self._reduction_amount(payslips)
        self.assertEqual(granted, self._reduction_amount(payslips[2]))
        self.assertTrue(0.0 < granted < 1000.0, granted)
        self.assertEqual(len(declared_lines), 1)
        self.assertAlmostEqual(declared_lines.amount, granted, places=2)

    def test_two_qualifying_occupation_lines(self):
        """Full time until 28/2, 4/5 from 1/3 with a 4/5 wage: two occupation
        lines, both qualifying. The last payslip of the quarter grants what the
        declaration declares for both lines."""
        employee = self.fl_employee
        payslips = self._create_and_validate_payslip(employee, date(2025, 1, 1), date(2025, 1, 31))
        payslips |= self._create_and_validate_payslip(employee, date(2025, 2, 1), date(2025, 2, 28))
        employee.create_version({
            'date_version': date(2025, 3, 1),
            'resource_calendar_id': self.resource_calendar_4_5.id,
            'wage': 1600.0,
        })
        payslips |= self._create_and_validate_payslip(employee, date(2025, 3, 1), date(2025, 3, 31))

        dmfa = self._generate_dmfa_declaration(year=2025, quarter='1', return_declaration=True)
        occupations = xml_str_to_dict(dmfa.xml_file.content)['DmfAOriginal']['Form']['EmployerDeclaration']['NaturalPerson']['WorkerRecord']['Occupation']
        self.assertIsInstance(occupations, list)
        self.assertEqual(len(occupations), 2)
        declared_lines = dmfa.unexperienced_reduction_line_ids.filtered(lambda l: l.employee_id == employee)
        self.assertEqual(len(declared_lines), 2)
        self.assertTrue(all(line.amount > 0.0 for line in declared_lines), declared_lines.mapped('amount'))

        self.assertEqual(self._reduction_amount(payslips[:-1]), 0.0)  # only the last payslip of the quarter
        self.assertAlmostEqual(self._reduction_amount(payslips[-1]), sum(declared_lines.mapped('amount')), places=2)

    def test_non_flanders_address(self):
        """Flag=True but work address is Wallonia → no reduction."""
        payslips = self._create_and_validate_quarter(self.wa_employee, 2025, 1)

        self.assertEqual(self._reduction_amount(payslips), 0.0)

    def test_flag_not_set(self):
        """Work address is FL but flag is False → no reduction."""
        self.fl_employee.version_id.l10n_be_onss_reduction_unexperienced_employees_flander = False
        payslips = self._create_and_validate_quarter(self.fl_employee, 2025, 1)

        self.assertEqual(self._reduction_amount(payslips), 0.0)

    def test_reference_wage_above_ceiling(self):
        """Quarterly reference wage above the ceiling → no reduction."""
        self.fl_employee.version_id.wage = 4000.0
        payslips = self._create_and_validate_quarter(self.fl_employee, 2025, 1)

        self.assertEqual(self._reduction_amount(payslips), 0.0)

    def test_pension_age_reached_at_engagement(self):
        """Entry into service on 1/1/2025, the legal pension age on the last day
        of that quarter, 31/3/2025, is 66: the employee turns 66 on 15/3/2025,
        during the quarter of entry into service → no reduction."""
        self.fl_employee.birthday = date(1959, 3, 15)
        payslips = self._create_and_validate_quarter(self.fl_employee, 2025, 1)

        self.assertEqual(self._reduction_amount(payslips), 0.0)

    def test_below_pension_age_at_engagement(self):
        """Same, but the employee only turns 66 on 15/4/2025, after the quarter
        of entry into service → the reduction is granted."""
        self.fl_employee.birthday = date(1959, 4, 15)
        payslips = self._create_and_validate_quarter(self.fl_employee, 2025, 1)

        self.assertEqual(self._reduction_amount(payslips), 1000.0)

    def test_granted_once_per_quarter(self):
        """The quarter is fully covered, so a correction on top of it finds the
        whole amount already granted → nothing more is granted."""
        payslips = self._create_and_validate_quarter(self.fl_employee, 2025, 1)
        correction = self._create_payslip(self.fl_employee, date(2025, 2, 1), date(2025, 2, 28))

        self.assertEqual(self._reduction_amount(correction), 0.0)  # nothing left to grant
        self.assertEqual(self._reduction_amount(payslips | correction), 1000.0)

    def test_rehired_within_the_window(self):
        """Entry Q1 2025, quit Q2 2025, back Q4 2025 → the two employment periods
        are a single one, so the right still ends with Q4 2025: nothing is
        granted in Q1 2026, even though only 3 quarters were ever paid."""
        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(self.fl_employee, 2025, 1)), 1000.0)
        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(self.fl_employee, 2025, 2)), 1000.0)

        self.fl_employee.version_id.contract_date_end = date(2025, 6, 30)
        self.fl_employee.create_version({
            'date_version': date(2025, 10, 1),
            'contract_date_start': date(2025, 10, 1),
            'contract_date_end': False,
        })

        # Q3 2025 has no occupation at all, but still counts towards the 4 quarters.
        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(self.fl_employee, 2025, 4)), 1000.0)
        # Back within the 4 quarters: the same right, still started at the first engagement
        self.assertEqual(self._declared_starting_dates(2025, '4'), {'2025-01-01'})
        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(self.fl_employee, 2026, 1)), 0.0)

    def test_official_example_rehired_within_the_window(self):
        """Example from the Flemish administration: engagement in Q4, departure
        during that same quarter, back during the 4th quarter of the right ->
        'the reduction period continues as normal. In practice, the employer
        will receive the reduction for the 4th quarter of 2023 and (partially)
        for the 3rd quarter of 2024.'
        https://www.vlaanderen.be/doelgroepvermindering-voor-personen-zonder-recente-duurzame-werkervaring
        """
        employee = self._create_fl_employee(date(2025, 10, 1))

        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(employee, 2025, 4)), 1000.0)

        employee.version_id.contract_date_end = date(2025, 12, 31)
        employee.create_version({
            'date_version': date(2026, 7, 1),
            'contract_date_start': date(2026, 7, 1),
            'contract_date_end': False,
        })

        # Q1 and Q2 2026 are quarters without occupation: nothing is paid, but
        # they are counted as quarters with the target group reduction.
        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(employee, 2026, 3)), 1000.0)
        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(employee, 2026, 4)), 0.0)

    def test_official_example_rehired_after_the_window(self):
        """Same example, but back after the 4 quarters: 'the employer may,
        provided the employee still meets the conditions, apply the reduction
        again for 4 quarters.'"""
        employee = self._create_fl_employee(date(2025, 10, 1))

        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(employee, 2025, 4)), 1000.0)

        employee.version_id.contract_date_end = date(2025, 12, 31)
        employee.create_version({
            'date_version': date(2027, 1, 1),
            'contract_date_start': date(2027, 1, 1),
            'contract_date_end': False,
        })

        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(employee, 2027, 1)), 1000.0)
        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(employee, 2027, 4)), 1000.0)
        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(employee, 2028, 1)), 0.0)

    def test_reduction_not_applied_after_the_4_quarters(self):
        """Entry Q1 2025, so the right ends with Q4 2025 → no reduction in Q2 2026."""
        payslips = self._create_and_validate_quarter(self.fl_employee, 2026, 2)

        self.assertEqual(self._reduction_amount(payslips), 0.0)

    @freeze_time('2027-07-15')  # The quarters up to Q2 2027 must be ended to be declared
    def test_reduction_applied_after_leaving_and_reentering_after_more_than_4_quarters(self):
        """Entry Q1 2025, quit Q1 2025, back Q2 2026 → a new right starts, so the
        reduction is granted again from Q2 2026 to Q1 2027, but not in Q2 2027."""
        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(self.fl_employee, 2025, 1)), 1000.0)

        self.fl_employee.version_id.contract_date_end = date(2025, 3, 31)
        self.fl_employee.create_version({
            'date_version': date(2026, 4, 1),
            'contract_date_start': date(2026, 4, 1),
            'contract_date_end': False,
        })

        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(self.fl_employee, 2026, 2)), 1000.0)
        # A new right, started at the new engagement
        self.assertEqual(self._declared_starting_dates(2026, '2'), {'2026-04-01'})
        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(self.fl_employee, 2026, 3)), 1000.0)
        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(self.fl_employee, 2026, 4)), 1000.0)
        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(self.fl_employee, 2027, 1)), 1000.0)
        # 5th quarter of the new right
        self.assertEqual(self._reduction_amount(self._create_and_validate_quarter(self.fl_employee, 2027, 2)), 0.0)
