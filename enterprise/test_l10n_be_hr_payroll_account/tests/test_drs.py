# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests import freeze_time, tagged

from .common_drs import TestDRSCommon


@tagged('post_install', '-at_install', 'drs')
class TestDRS(TestDRSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Youth: age at Dec 31, 2025 = 22 (< 25 → youth risk, code 001)
        # Senior: age at Dec 31, 2025 = 60 (>= 50 → senior risk, code 002)
        cls.employee_youth = cls._create_drs_employee('Youth Worker', birthday=date(2003, 6, 1), wage=2000.0)
        cls.employee_senior = cls._create_drs_employee('Senior Worker', birthday=date(1965, 6, 1), wage=2000.0, lang='nl_NL')
        cls.employee_impulsion_12mo = cls._create_drs_employee('Impulsion 12mo Worker', l10n_be_impulsion_plan='12mo')
        cls.employee_impulsion_25yo_young = cls._create_drs_employee(
            'Impulsion 25yo Young Worker', birthday=date(2003, 6, 1), l10n_be_impulsion_plan='25yo')
        cls.employee_impulsion_25yo_old = cls._create_drs_employee('Impulsion 25yo Old Worker', l10n_be_impulsion_plan='25yo')

    @freeze_time('2026-10-20 10:00:00')
    def test_drs_invalid_file_not_sent(self):
        self._create_validated_leave(self.employee_senior, 'l10n_be_work_entry_type_senior_time_off', date(2026, 9, 14), date(2026, 9, 14))
        drs = self._get_declarations(self.employee_senior, 'WECH009')
        self._get_drs_dict(drs)
        # The validation of the file against the schema of the ONSS failed
        drs.error_message = "Error upon generating the declaration: Element 'HolidayHours': [facet 'maxInclusive']"
        self.assertEqual(drs.state, 'error')
        self.assertIn(drs.error_message, drs.with_context(onss_skip_signature=True)._pre_submit_checks())

    @freeze_time('2026-10-20 10:00:00')
    def test_drs_common_errors(self):
        self._create_validated_leave(self.employee_senior, 'l10n_be_work_entry_type_senior_time_off', date(2026, 9, 14), date(2026, 9, 14))
        drs = self._get_declarations(self.employee_senior, 'WECH009')
        version = self.employee_senior.version_id
        # The workers not subject to the social security aren't declared
        version.l10n_be_worker_code_id = self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00000')
        with self.assertRaisesRegex(ValidationError, "The worker code 000 can't be declared to the unemployment sector"):
            self._get_drs_dict(drs)
        version.l10n_be_worker_code_id = self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00495')
        # The weekly hours of the worker can't exceed the ones of the full-time reference worker
        calendar_40h = self.calendar_38h.copy({'name': 'Standard 40 hours/week', 'reference_calendar_id': self.calendar_38h.id})
        calendar_40h.attendance_ids.filtered(lambda attendance: attendance.hour_to > 12).hour_to = 17
        version.resource_calendar_id = calendar_40h
        with self.assertRaisesRegex(ValidationError, 'more hours per week than the full-time reference schedule'):
            self._get_drs_dict(drs)
        version.resource_calendar_id = self.calendar_38h
        # The third-party payers can't declare the social risks
        payroll_config = self.belgian_company.current_payroll_config_id
        employer_category = payroll_config.l10n_be_employer_category_id
        payroll_config.l10n_be_employer_category_id = self.env['l10n.be.employer.category'].search([('dmfa_code', '=', '099')], limit=1)
        with self.assertRaisesRegex(ValidationError, 'third-party payers'):
            self._get_drs_dict(drs)
        payroll_config.l10n_be_employer_category_id = employer_category
        self.assertTrue(self._get_drs_dict(drs))

        # An expired risk can't be declared anymore
        expired = self._create_drs(self.employee_senior, 'drs_risk_wech008_002', 2026, 9)
        with self.assertRaisesRegex(ValidationError, "can't be declared for that month anymore"):
            self._get_drs_dict(expired)

    @freeze_time('2026-10-20 10:00:00')
    def test_drs_form(self):
        self._create_validated_leave(self.employee_senior, 'l10n_be_work_entry_type_senior_time_off', date(2026, 9, 14), date(2026, 9, 14))
        drs = self._get_declarations(self.employee_senior, 'WECH009')
        drs_dict = self._get_drs_dict(drs)
        # The type of the file is the type of the batch declarations, the identification is in the form
        self.assertEqual(drs.xml_filename.split('.')[1], 'WECH')
        root = drs_dict['WECH009']
        self.assertEqual(root['@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation'], 'WECH009_20263.xsd')
        form = root['Form']
        self.assertEqual(form['FormCreationDate'], '2026-10-20')
        self.assertEqual(form['FormCreationHour'], '12:00:00.000', "Belgian time")
        self.assertEqual(form['AttestationStatus'], '0')
        self.assertEqual(form['DclInformation']['LanguageCodePdf'], '1')
        self.assertEqual(form['Reference'], {'ReferenceType': '1', 'ReferenceOrigin': '1', 'ReferenceNbr': drs.name})
        natural_person = form['EmployerDeclarationLink']['NaturalPerson']
        self.assertEqual(natural_person['INSS'], self.employee_senior.niss)
        self.assertNotIn('CoordinatesContactPerson', form, "The contact person is only declared to the INAMI")

    @freeze_time('2026-10-20 10:00:00')
    def test_drs_modification_cancellation(self):
        self._create_validated_leave(self.employee_senior, 'l10n_be_work_entry_type_senior_time_off', date(2026, 9, 14), date(2026, 9, 14))
        original = self._get_declarations(self.employee_senior, 'WECH009')
        self.assertFalse(original._get_ticket_number())
        with self.assertRaises(UserError):
            original.action_modify_declaration()

        # A refused declaration is sent again as an original one
        self._notify_drs(original, '3400048ENN00A', accepted=False)
        self.assertFalse(original._get_ticket_number())
        retry = self._create_drs(self.employee_senior, 'drs_risk_wech009_002', 2026, 9)
        self.assertEqual(self._get_drs_dict(retry)['WECH009']['Form']['AttestationStatus'], '0')

        # The modification of an accepted declaration refers to its ticket
        self._notify_drs(retry, '3400048ENN00C')
        self.assertEqual(retry._get_ticket_number(), '3400048ENN00C')
        modification = self.env['l10n.be.drs'].browse(retry.action_modify_declaration()['res_id'])
        self.assertFalse(modification.xml_file)
        form = self._get_drs_dict(modification)['WECH009']['Form']
        self.assertEqual(form['AttestationStatus'], '1')
        self.assertEqual(form['Reference'], [
            {'ReferenceType': '1', 'ReferenceOrigin': '1', 'ReferenceNbr': modification.name},
            {'ReferenceType': '3', 'ReferenceOrigin': '2', 'ReferenceNbr': '3400048ENN00C'},
        ])
        self.assertIn('WorkerRecordLink', form['EmployerDeclarationLink']['NaturalPerson'])

        # The cancellation refers to the last accepted declaration, and only identifies the worker
        self._notify_drs(modification, '3400048ENN00D')
        cancellation = self.env['l10n.be.drs'].browse(modification.action_cancel_declaration()['res_id'])
        self.assertTrue(cancellation.xml_file)
        form = self._get_drs_dict(cancellation)['WECH009']['Form']
        self.assertEqual(form['AttestationStatus'], '3', "A cancellation stays a cancellation when generated again")
        self.assertEqual(form['Reference'][1]['ReferenceNbr'], '3400048ENN00D')
        self.assertNotIn('WorkerRecordLink', form['EmployerDeclarationLink']['NaturalPerson'])

        # After the cancellation, a new declaration is an original one
        self._notify_drs(cancellation, '3400048ENN00E')
        new_declaration = self._create_drs(self.employee_senior, 'drs_risk_wech009_002', 2026, 9)
        self.assertEqual(self._get_drs_dict(new_declaration)['WECH009']['Form']['AttestationStatus'], '0')

    def test_drs_allowed_risks(self):
        drs = self._create_drs(self.employee_senior, 'drs_risk_wech008_001', 2026, 9)
        self.assertIn(self.env.ref('l10n_be_hr_payroll.drs_risk_wech008_001'), drs.allowed_risk_ids)
        self.assertNotIn(self.env.ref('l10n_be_hr_payroll.drs_risk_wech008_002'), drs.allowed_risk_ids, "Expired since 2010")
        self.assertNotIn(self.env.ref('l10n_be_hr_payroll.drs_risk_zima005_001'), drs.allowed_risk_ids)
        self.assertTrue(self.env.ref('l10n_be_hr_payroll.drs_risk_wech001_001', raise_if_not_found=False))

    def test_drs_create_missing_declarations(self):
        risk = self.env.ref('l10n_be_hr_payroll.drs_risk_wech010_002')
        values = {'employee_id': self.employee_senior.id, 'risk_id': risk.id, 'sector': 'unemployment', 'year': 2026}
        declarations = self.env['l10n.be.drs']._create_missing_declarations([
            dict(values, month=3),
            dict(values, month='3'),
            dict(values, month=4),
        ])
        self.assertEqual(declarations.mapped('month'), ['3', '4'])
        self.assertTrue(all(declarations.mapped('is_automatically_created')))
        self.assertFalse(self.env['l10n.be.drs']._create_missing_declarations([dict(values, month=4), dict(values, month='3')]))

    def test_drs_module_update_required(self):
        drs = self._create_drs(self.employee_senior, 'drs_risk_wech009_002', 2026, 9)
        self.env.ref('l10n_be_hr_payroll.drs_xml_form').unlink()
        with self.assertRaises(UserError):
            drs.with_context(onss_skip_signature=True).generate_declaration_xml_report()

    @freeze_time('2026-06-26 10:00:00')
    def test_wech009_wech010_automation(self):
        # Legal holidays in February, then youth holidays in March and from March to April
        self._create_validated_leave(self.employee_youth, 'be_work_entry_type_legal_leave', date(2026, 2, 2), date(2026, 2, 3))
        self._create_validated_leave(self.employee_youth, 'l10n_be_work_entry_type_youth_time_off', date(2026, 3, 10), date(2026, 3, 12))
        self._create_validated_leave(self.employee_youth, 'l10n_be_work_entry_type_youth_time_off', date(2026, 3, 30), date(2026, 4, 1))
        self._create_validated_leave(self.employee_senior, 'l10n_be_work_entry_type_senior_time_off', date(2026, 5, 4), date(2026, 5, 5))

        # The first month of youth holidays is declared once, the hours of each month
        wech009_youth = self._get_declarations(self.employee_youth, 'WECH009')
        self.assertRecordValues(wech009_youth, [{'code': '001', 'year': 2026, 'month': '3', 'holiday_hours': 15.2, 'is_automatically_created': True}])
        wech010_youth = self._get_declarations(self.employee_youth, 'WECH010')
        self.assertRecordValues(wech010_youth, [
            {'code': '001', 'year': 2026, 'month': '3'},
            {'code': '001', 'year': 2026, 'month': '4'},
        ])
        self.assertRecordValues(self._get_declarations(self.employee_senior, 'WECH009') | self._get_declarations(self.employee_senior, 'WECH010'), [
            {'identification': 'WECH009', 'code': '002', 'month': '5', 'holiday_hours': 0},
            {'identification': 'WECH010', 'code': '002', 'month': '5', 'holiday_hours': 0},
        ])

        self._assertDRSEqual(self._get_drs_dict(wech009_youth), label='wech009_youth')
        self._assertDRSEqual(self._get_drs_dict(wech010_youth[0]), label='wech010_youth_march')
        self._assertDRSEqual(self._get_drs_dict(wech010_youth[1]), label='wech010_youth_april')

        # Youth holidays approved later in an earlier month move the first month, without duplicates
        leave = self._create_validated_leave(self.employee_youth, 'l10n_be_work_entry_type_youth_time_off', date(2026, 2, 16), date(2026, 2, 16))
        leave.action_refuse()
        leave.action_back_to_approval()
        leave.action_approve()
        # Only the legal holidays taken in the previous months are declared
        self.assertRecordValues(self._get_declarations(self.employee_youth, 'WECH009'), [{'month': '2', 'holiday_hours': 0, 'state': 'draft'}])
        self.assertEqual(self._get_declarations(self.employee_youth, 'WECH010').mapped('month'), ['2', '3', '4'])

    @freeze_time('2026-06-26 10:00:00')
    def test_wech009_wech010_errors(self):
        # Legal holidays after youth holidays in the same month
        self._create_validated_leave(self.employee_youth, 'l10n_be_work_entry_type_youth_time_off', date(2026, 3, 10), date(2026, 3, 10))
        self._create_validated_leave(self.employee_youth, 'be_work_entry_type_legal_leave', date(2026, 3, 11), date(2026, 3, 11))
        with self.assertRaisesRegex(ValidationError, 'the legal holidays must be taken first'):
            self._get_drs_dict(self._get_declarations(self.employee_youth, 'WECH010'))

        # The age is checked at the end of the holiday year
        self._create_validated_leave(self.employee_senior, 'l10n_be_work_entry_type_youth_time_off', date(2026, 3, 10), date(2026, 3, 10))
        with self.assertRaisesRegex(ValidationError, 'not entitled to youth holidays'):
            self._get_drs_dict(self._get_declarations(self.employee_senior, 'WECH009'))

        # A month without youth or senior holidays
        wech010 = self._create_drs(self.employee_youth, 'drs_risk_wech010_001', 2026, 1)
        with self.assertRaisesRegex(ValidationError, 'thus a declaration for that month is unnecessary'):
            self._get_drs_dict(wech010)

    @freeze_time('2026-06-26 10:00:00')
    def test_wech008(self):
        risk_010 = self.env.ref('l10n_be_hr_payroll.drs_risk_wech008_010')
        risk_011 = self.env.ref('l10n_be_hr_payroll.drs_risk_wech008_011')
        # The fixed-term contract of the old worker ends after the month of the declaration
        self.employee_impulsion_25yo_old.version_id.contract_date_end = date(2026, 4, 30)

        employees = (
            self.employee_impulsion_12mo,
            self.employee_impulsion_25yo_young,
            self.employee_impulsion_25yo_old,
        )
        payslips = self.env['hr.payslip'].create([
            {
                'name': f'Payslip 03/2026 {employee.name}',
                'version_id': employee.version_id.id,
                'date_from': date(2026, 3, 1),
                'date_to': date(2026, 3, 31),
                'employee_id': employee.id,
                'company_id': self.belgian_company.id,
            }
            for employee in employees
        ])
        payslips.compute_sheet()
        payslips.action_payslip_done()
        # Validating the payslips again doesn't duplicate the declarations
        payslips._check_create_wech008()

        declarations = self.env['l10n.be.drs'].search([('identification', '=', 'WECH008'), ('employee_id', 'in', [employee.id for employee in employees])])
        self.assertEqual(len(declarations), 3)
        self.assertTrue(all(declarations.mapped('is_automatically_created')))
        drs_12mo, drs_25_young, drs_25_old = (
            declarations.filtered(lambda declaration, employee=employee: declaration.employee_id == employee)
            for employee in employees
        )
        self.assertRecordValues(drs_12mo + drs_25_young + drs_25_old, [
            {'risk_id': risk_010.id, 'month': '3', 'year': 2026, 'payslip_id': payslips[0].id, 'work_accident_indicator': False},
            {'risk_id': risk_011.id, 'month': '3', 'year': 2026, 'payslip_id': payslips[1].id, 'work_accident_indicator': False},
            {'risk_id': risk_011.id, 'month': '3', 'year': 2026, 'payslip_id': payslips[2].id, 'work_accident_indicator': False},
        ])

        # The allowance isn't limited, it's the monthly amount prorated on the hours with a salary due:
        # 4 weeks of a full time worker (38 hours * 4), rounded to the 4th decimal
        monthly_amount = payslips[0]._get_impulsion_plan_amount()[0]
        self.assertTrue(monthly_amount)
        self.assertEqual(drs_12mo.paid_hours, 167.2)
        self.assertAlmostEqual(drs_12mo.work_allowance, round(monthly_amount * 167.2 / 152, 4), places=4)
        self.assertGreater(drs_12mo.work_allowance, monthly_amount)
        drs_12mo_dict = self._get_drs_dict(drs_12mo, skip_signature=False)
        self._assertDRSEqual(drs_12mo_dict)
        activation = drs_12mo_dict['WECH008']['Form']['EmployerDeclarationLink']['NaturalPerson']['WorkerRecordLink']['OccupationLink']
        self.assertEqual(
            activation['MonthlyDeclarationOfWorkInProgramActivationOfUnemploymentAllowance']['WorkAllowance']['WorkAllowanceAmount'],
            str(round(drs_12mo.work_allowance * 10000)), "In hundredths of cent")
        self.assertNotIn('OccupationEndingDate', activation)

        self.assertGreater(drs_25_young.work_allowance, 0)
        self.assertTrue(self._get_drs_dict(drs_25_young))

        # No allowance after 25 years old: the social security refuses an allowance of 0 when a salary is due
        self.assertEqual(drs_25_old.work_allowance, 0)
        with self.assertRaisesRegex(ValidationError, 'no right to a work allowance'):
            self._get_drs_dict(drs_25_old)

    @freeze_time('2026-06-26 10:00:00')
    def test_wech008_errors(self):
        # Without validated payslip, and for a risk of an other activation program
        drs = self._create_drs(self.employee_impulsion_12mo, 'drs_risk_wech008_003', 2026, 3)
        with self.assertRaisesRegex(ValidationError, 'A validated payslip'):
            self._get_drs_dict(drs)
        with self.assertRaisesRegex(ValidationError, 'Only the work allowance of the Impulsion plans'):
            self._get_drs_dict(drs)

    def test_drs_validation_warnings(self):
        # 1. Test "Start Date prior to CBE registration"
        self.belgian_company.l10n_be_cbe_inscription = date(2026, 1, 1)  # CBE in 2026, contract in 2025
        drs_cbe = self._create_drs(self.employee_youth, 'drs_risk_wech002_001', 2026, 9)
        drs_cbe._compute_issues()
        self.assertTrue(drs_cbe.issues)
        issues_values_cbe = list(drs_cbe.issues.values())
        self.assertTrue(any("prior to the employer's registration date" in issue['message'] for issue in issues_values_cbe))
        with self.assertRaises(UserError):
            drs_cbe.generate_declaration_xml_report()
        self.belgian_company.l10n_be_cbe_inscription = date(2000, 1, 1)

        # 2. Test "Missing Dimona for DRS"
        # Dimona period cancelled at the ONSS
        youth_period = self.env['l10n.be.dimona.period'].search([('employee_id', '=', self.employee_youth.id)])
        youth_period.content = dict(youth_period.content, isCanceled=True, lastDimonaType='cancel')
        drs_dimona = self._create_drs(self.employee_youth, 'drs_risk_wech002_001', 2026, 9)
        drs_dimona._compute_issues()
        self.assertTrue(drs_dimona.issues)
        issues_values_dimona = list(drs_dimona.issues.values())
        self.assertTrue(any("does not have a DIMONA covering the period" in issue['message'] for issue in issues_values_dimona))
        with self.assertRaises(UserError):
            drs_dimona.generate_declaration_xml_report()
        youth_period.content = dict(youth_period.content, isCanceled=False, lastDimonaType='in')

        # Dimona period (starting 2025-01-01) not covering the declaration period
        drs_dimona_period = self._create_drs(self.employee_youth, 'drs_risk_wech002_001', 2024, 5)
        drs_dimona_period._compute_issues()
        issues_values_dimona_period = list((drs_dimona_period.issues or {}).values())
        self.assertTrue(any("does not have a DIMONA covering the period" in issue['message'] for issue in issues_values_dimona_period))

        # 3. Test "Invalid Remuneration Basis for DRS" (Wage = 0)
        self.employee_youth.version_ids.write({'wage': 0.0})
        drs_wage = self._create_drs(self.employee_youth, 'drs_risk_wech002_001', 2026, 9)
        drs_wage._compute_issues()
        self.assertTrue(drs_wage.issues)
        issues_values_wage = list(drs_wage.issues.values())
        self.assertTrue(any("Basic Remuneration is equal to 0" in issue['message'] for issue in issues_values_wage))
        with self.assertRaises(UserError):
            drs_wage.generate_declaration_xml_report()

        # Negative wage and wage rounded to 0 cent in the XML :
        for wage in (-100.0, 0.004):
            self.employee_youth.version_ids.write({'wage': wage})
            drs_wage = self._create_drs(self.employee_youth, 'drs_risk_wech002_001', 2026, 9)
            issues_values_wage = list((drs_wage.issues or {}).values())
            self.assertTrue(any("Basic Remuneration is equal to 0" in issue['message'] for issue in issues_values_wage))
        self.employee_youth.version_ids.write({'wage': 2000.0})

    def test_drs_period_version(self):
        # Contract until 31/01, then a new contract starting 04/02: a DRS for February uses the February version
        employee = self._create_drs_employee(
            'Rehired Worker', contract_date_start=date(2026, 1, 1), contract_date_end=date(2026, 1, 31),
            date_version=date(2026, 1, 1), wage=2000.0)
        with patch.object(self.env.registry['hr.version'], '_l10n_be_dimona_autodeclare'):
            february_version = employee.create_version({
                'date_version': date(2026, 2, 4),
                'contract_date_start': date(2026, 2, 4),
                'contract_date_end': False,
                'wage': 2500.0,
            })
        drs = self._create_drs(employee, 'drs_risk_wech002_001', 2026, 2)
        self.assertEqual(drs._get_period_version(), february_version)

    def test_drs_risk_deletion(self):
        risk = self.env['l10n.be.drs.risk'].create({
            'name': 'Removed Risk',
            'sector': 'unemployment',
            'identification': 'WECH999',
            'code': '001',
            'scenario': 'Scenario 999',
            'date_start': date(2026, 1, 1),
        })
        with self.assertRaisesRegex(UserError, 'not allowed to delete a DRS Risk'):
            risk.unlink()
        # The risks removed from the data of the module are deleted at its update
        risk.with_context(force_delete=True).unlink()
        self.assertFalse(risk.exists())
