import io
from datetime import date

from odoo.tests import HttpCase, tagged
from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'social_balance_sheet')
class TestPayrollSocialBalanceSheet(TestPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_include_child_branches_in_report(self):
        companies = self.belgian_company | self.multibranch_company
        # company 0 -> root / no child
        # company 1 (is parent of) company 2 (is parent of) company 3
        target_company = companies[1]

        sexes = ['male'] + ['female'] * 3
        employees = self.create_employee([
            {
                'name': f'Employee {company.name}',
                'company_id': company.id,
                'contract_date_start': date(2025, 1, 1),
                # relevant for social balance sheet
                'certificate': 'master',
                'sex': emp_sex,
                'work_time_rate': 1.,
            } for company, emp_sex in zip(companies, sexes)
        ])

        self.create_and_validate_payslips(employees=employees, year=2025, months=[1])
        balance_sheet_data = self.env['l10n.be.social.balance.sheet'].with_company(target_company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2026, 1, 1),
        })._get_report_data()

        self.assertEqual(balance_sheet_data['1003_female'], 3, "The 3 women of the branches are in contract the whole year")
        self.assertEqual(balance_sheet_data['1003_male'], 0., "The man works in another company")

    def test_full_and_part_time_workers(self):
        """ Each worker is counted as full or part time according to its own version. """
        employees = self.create_employee([{
            'name': 'Full Time Employee',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'certificate': 'master',
            'sex': 'male',
        }, {
            'name': 'Part Time Employee',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'resource_calendar_id': self.resource_calendar_mid_time.id,
            'certificate': 'master',
            'sex': 'female',
        }])
        self.assertEqual(employees.version_id.mapped('work_time_rate'), [1.0, 0.5])
        self.create_and_validate_payslips(employees=employees, year=2025, months=[1])
        balance_sheet_data = self.env['l10n.be.social.balance.sheet'].with_company(self.belgian_company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })._get_report_data()

        self.assertFalse(balance_sheet_data['102']['total']['male']['part'])
        self.assertTrue(balance_sheet_data['102']['total']['male']['full'])
        self.assertFalse(balance_sheet_data['102']['total']['female']['full'])
        self.assertTrue(balance_sheet_data['102']['total']['female']['part'])
        self.assertEqual(balance_sheet_data['105'], {'full': 1, 'part': 1, 'fte': 1.5})
        self.assertEqual(balance_sheet_data['205'], {'full': 1, 'part': 1, 'fte': 1.5})

    def test_belgian_education_levels(self):
        """ The primary and secondary certificate levels of the Belgian companies have their education codes. """
        employees = self.create_employee([{
            'name': f'Employee {certificate}',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'certificate': certificate,
            'sex': sex,
        } for certificate, sex in [('primary', 'male'), ('lower_secondary', 'female'), ('higher_secondary', 'female')]])
        self.create_and_validate_payslips(employees=employees, year=2025, months=[1])
        balance_sheet_data = self.env['l10n.be.social.balance.sheet'].with_company(self.belgian_company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })._get_report_data()

        self.assertEqual(balance_sheet_data['1200'], {'full': 1, 'part': 0, 'fte': 1.0})
        self.assertEqual(balance_sheet_data['1211'], {'full': 2, 'part': 0, 'fte': 2.0})

    def test_other_company_employees_are_not_checked(self):
        """ The sex of the employees of the other companies doesn't block the report """
        other_company = self.create_belgian_company({'name': 'Other Company'})
        employees = self.create_employee([{
            'name': 'Declared Employee',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2025, 1, 1),
            'certificate': 'master',
            'sex': 'male',
        }, {
            'name': 'Other Company Employee',
            'company_id': other_company.id,
            'contract_date_start': date(2025, 1, 1),
            'certificate': 'master',
            'sex': False,
        }])
        self.create_and_validate_payslips(employees=employees, year=2025, months=[1])
        balance_sheet_data = self.env['l10n.be.social.balance.sheet'].with_company(self.belgian_company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })._get_report_data()
        self.assertEqual(balance_sheet_data['105']['full'], 1)

    def test_company_directors_are_excluded(self):
        """ The company directors (joint committee 999) have no employment contract: they aren't workers """
        employees = self.create_employee([{
            'name': 'Worker',
            'contract_date_start': date(2025, 1, 1),
            'certificate': 'master',
            'sex': 'male',
        }, {
            'name': 'Director',
            'contract_date_start': date(2025, 1, 1),
            'certificate': 'master',
            'sex': 'female',
            'employee_type_id': self.env.ref("hr.contract_type_company_executive").id,
            'l10n_be_joint_committee_id': self.env['l10n.be.joint.committee'].search([('egov3_code', '=', '999')], limit=1).id,
        }])
        self.create_and_validate_payslips(employees=employees, year=2025, months=[12])
        balance_sheet_data = self.env['l10n.be.social.balance.sheet'].with_company(self.belgian_company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })._get_report_data()
        self.assertEqual(balance_sheet_data['105']['full'], 1)
        self.assertEqual(balance_sheet_data['121']['full'], 0)
        self.assertFalse(balance_sheet_data['102']['total']['female']['full'])

    def test_departure_reasons(self):
        """ The departures are declared by reason: pension (340), unemployment with company supplement (341),
        dismissal (342) or another reason (343), of which the workers who became self-employed (350) """
        reasons = {
            'departure_resigned_anticipated_retirement': '340',
            'departure_fired_early_retirement': '341',
            'departure_fired_serious_misconduct': '342',
            'departure_fired_notice_employer': '342',
            'departure_freelance': '343',
            'departure_mutual_agreement': '343',
        }
        employees = self.create_employee([{
            'name': f'Leaver {reason}',
            'contract_date_start': date(2024, 1, 1),
            'certificate': 'master',
            'sex': 'male',
        } for reason in reasons])
        self.create_and_validate_payslips(employees=employees, year=2025, months=[1])
        for employee, reason in zip(employees, reasons):
            self.env['hr.employee.departure'].create({
                'employee_id': employee.id,
                'departure_reason_id': self.env.ref(f'l10n_be_hr_payroll.{reason}').id,
                'dismissal_date': date(2025, 1, 31),
            }).action_register()
        balance_sheet_data = self.env['l10n.be.social.balance.sheet'].with_company(self.belgian_company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })._get_report_data()
        self.assertEqual(
            {code: balance_sheet_data[code]['full'] for code in ('305', '340', '341', '342', '343', '350')},
            {'305': 6, '340': 1, '341': 1, '342': 2, '343': 2, '350': 1})

    def test_report_rendering(self):
        employees = self.create_employee([{
            'name': 'Rendered Employee',
            'contract_date_start': date(2025, 1, 1),
            'certificate': 'master',
            'sex': 'female',
        }])
        self.create_and_validate_payslips(employees=employees, year=2025, months=[1])
        wizard = self.env['l10n.be.social.balance.sheet'].with_company(self.belgian_company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })
        report_data = wizard._get_report_data()
        self.assertEqual(report_data['joint_committees'], ['200'])
        html, _ = self.env['ir.actions.report']._render_qweb_html(
            'l10n_be_hr_payroll.action_report_social_balance', wizard.ids, data={'sbs_data': report_data})
        self.assertIn('350', str(html))
        self.assertIn('Numbers of joint committees: 200<', str(html))
        # The personnel costs are in euros, without cents
        costs = report_data['102']['total']['female']['full']
        self.assertIn(f'{round(costs):,}', str(html))
        self.assertNotIn(f'{costs:,.2f}', str(html))

    def test_professional_categories(self):
        """ The workers at the closing date are declared by professional category: the manual workers (132), the
        employees (134) and the other workers (133): the apprentices, interns and trainees. The students are
        declared as manual workers or employees, according to their status. """
        worker_codes = {code: self.env['l10n.be.worker.code'].search([('dmfa_code', '=', code)]) for code in ('015', '495', '840', '841', '439')}
        employees = self.create_employee([{
            'name': f'Worker {code} {category}',
            # the flexi-job contracts end with their quarter
            'contract_date_start': date(2025, 10, 1) if category == 'flx' else date(2025, 1, 1),
            'certificate': 'master',
            'sex': 'male',
            'l10n_be_worker_code_id': worker_codes[code].id,
            'l10n_be_dimona_category': category,
        } for code, category in [('015', 'oth'), ('495', 'oth'), ('840', 'stu'), ('841', 'stu'), ('439', 'alt'), ('495', 'flx')]])
        self.create_and_validate_payslips(employees=employees, year=2025, months=[12])
        balance_sheet_data = self.env['l10n.be.social.balance.sheet'].with_company(self.belgian_company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })._get_report_data()
        self.assertEqual(
            {code: balance_sheet_data[code]['full'] + balance_sheet_data[code]['part'] for code in ('105', '130', '132', '133', '134')},
            {'105': 6, '130': 0, '132': 2, '133': 1, '134': 3})

    def test_average_number_of_workers(self):
        """ The average number of workers is the average of the workers in the register at the end of each month:
        the workers who left during a month aren't counted for it, the suspended workers are """
        company = self.create_belgian_company({'name': 'Headcount Company'})
        employees = self.create_employee([{
            'name': 'Leaver',
            'company_id': company.id,
            'contract_date_start': date(2025, 1, 1),
            'contract_date_end': date(2025, 3, 15),
            'certificate': 'master',
            'sex': 'male',
        }, {
            'name': 'Suspended',
            'company_id': company.id,
            'contract_date_start': date(2025, 1, 1),
            'certificate': 'master',
            'sex': 'female',
        }])
        # The suspended worker has no payslip after January
        self.create_and_validate_payslips(employees=employees, year=2025, months=[1])
        self.create_and_validate_payslips(employees=employees[0], year=2025, months=[2, 3])
        balance_sheet_data = self.env['l10n.be.social.balance.sheet'].with_company(company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })._get_report_data()
        self.assertEqual(balance_sheet_data['1001_male'], round(2 / 12, 2))
        self.assertEqual(balance_sheet_data['1001_female'], 1)

    def test_personnel_costs(self):
        """ The personnel costs are the gross remuneration, before the worker social contributions and without the
        benefits in kind, with the employer social contributions, the transport and representation fees and the meal
        vouchers paid by the employer. 1021 + 1022 = 1023. """
        company = self.create_belgian_company({'name': 'Costs Company'})
        employees = self.create_employee([{
            'name': 'Full Time Worker',
            'company_id': company.id,
            'contract_date_start': date(2025, 1, 1),
            'certificate': 'master',
            'sex': 'male',
            'wage': 3000,
            'internet': 38,
            'mobile': 30,
            'private_car_employee_kilometer': 20,
        }, {
            'name': 'Part Time Worker',
            'company_id': company.id,
            'contract_date_start': date(2025, 1, 1),
            'certificate': 'master',
            'sex': 'female',
            'wage': 1500,
            'resource_calendar_id': self.resource_calendar_mid_time.id,
        }])
        payslips = self.create_and_validate_payslips(employees=employees, year=2025, months=[1])
        balance_sheet_data = self.env['l10n.be.social.balance.sheet'].with_company(company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })._get_report_data()

        for payslip, sex, contract_type in [(payslips[0], 'male', 'full'), (payslips[1], 'female', 'part')]:
            values = payslip._get_line_values(['SALARY', 'CAR.PRIV', 'ONSSEMPLOYER', 'MEAL_V_EMP'], vals_list=['total', 'quantity'])
            expected = (
                values['SALARY'][payslip.id]['total']  # gross before the worker contributions
                - sum(line.total for line in payslip.line_ids if 'BIK' in line.salary_rule_id.category_ids.mapped('code'))
                + values['CAR.PRIV'][payslip.id]['total']
                + values['ONSSEMPLOYER'][payslip.id]['total']
                + payslip.version_id.meal_voucher_paid_by_employer * values['MEAL_V_EMP'][payslip.id]['quantity']
            )
            self.assertAlmostEqual(balance_sheet_data['102']['total'][sex][contract_type], expected, places=2)

    def test_entries_and_departures(self):
        """ Each contract starting or ending in the period is an entry or a departure, except when it follows another
        contract without interruption """
        company = self.create_belgian_company({'name': 'Movements Company'})
        renewed, rehired = self.create_employee([{
            'name': 'Renewed Fixed Term',
            'company_id': company.id,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'contract_date_end': date(2025, 6, 30),
            'certificate': 'master',
            'sex': 'male',
        }, {
            'name': 'Hired Again',
            'company_id': company.id,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'contract_date_end': date(2025, 3, 31),
            'certificate': 'master',
            'sex': 'female',
        }])
        # A permanent contract following the fixed term one: neither a departure nor an entry
        renewed.create_version({
            'date_version': date(2025, 7, 1),
            'contract_date_start': date(2025, 7, 1),
            'contract_date_end': False,
        })
        # Hired again in September, until the end of November
        rehired.create_version({
            'date_version': date(2025, 9, 1),
            'contract_date_start': date(2025, 9, 1),
            'contract_date_end': date(2025, 11, 30),
        })
        self.create_and_validate_payslips(employees=renewed | rehired, year=2025, months=[1])
        balance_sheet_data = self.env['l10n.be.social.balance.sheet'].with_company(company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })._get_report_data()
        self.assertEqual(balance_sheet_data['205']['full'], 3)
        self.assertEqual(balance_sheet_data['305']['full'], 2)

    def test_xlsx_export(self):
        """ The social balance sheet can be exported as a spreadsheet, with the codes of the model """
        import openpyxl  # noqa: PLC0415
        company = self.create_belgian_company({'name': 'Spreadsheet Company'})
        employees = self.create_employee([{
            'name': 'Spreadsheet Worker',
            'company_id': company.id,
            'contract_date_start': date(2025, 1, 1),
            'certificate': 'master',
            'sex': 'female',
        }])
        self.create_and_validate_payslips(employees=employees, year=2025, months=[1])
        wizard = self.env['l10n.be.social.balance.sheet'].with_company(company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })
        report_data = wizard._get_report_data()
        filename, content = wizard._get_xlsx_file()
        self.assertTrue(filename.endswith('.xlsx'))
        sheet = openpyxl.load_workbook(io.BytesIO(content)).active
        rows = {row[0]: row[2:5] for row in sheet.iter_rows(values_only=True) if row[0]}
        female_costs = report_data['102']['total']['female']['full'] + report_data['102']['total']['female']['part']
        self.assertTrue(female_costs)
        self.assertNotEqual(female_costs, round(female_costs), "The personnel costs have cents")
        # The amounts are in euros, without cents
        self.assertEqual(rows['1023'], (round(female_costs), 0, round(female_costs)))
        self.assertEqual(rows['105'], (1, 0, 1))
        # The temporary staff and the trainings, not known by the payroll, are to be completed by hand
        self.assertEqual(rows['152'], (None, None, None))
        self.assertEqual(rows['5803 / 5813'], (None, None, None))
        self.assertEqual(rows['1003'], (1, 0, 1))

    def test_previous_exercise(self):
        """ The totals of the previous exercise are given with the ones of the exercise """
        import openpyxl  # noqa: PLC0415
        company = self.create_belgian_company({'name': 'Previous Exercise Company'})
        employees = self.create_employee([{
            'name': 'Previous Exercise Worker',
            'company_id': company.id,
            'date_version': date(2024, 1, 1),
            'contract_date_start': date(2024, 1, 1),
            'sex': 'male',
        }])
        self.create_and_validate_payslips(employees=employees, year=2024, months=[1, 2])
        self.create_and_validate_payslips(employees=employees, year=2025, months=[1])
        wizards = self.env['l10n.be.social.balance.sheet'].with_company(company).create([{
            'date_from': date(year, 1, 1),
            'date_to': date(year, 12, 31),
        } for year in (2024, 2025)])
        previous_data, data = (wizard._get_report_data() for wizard in wizards)
        [(_title, _columns, previous_lines), *_sections] = wizards[0]._get_report_sections(previous_data)
        previous_totals = {code: values[0] for code, _label, values in previous_lines}
        self.assertTrue(previous_totals['1023'])
        self.assertTrue(previous_totals['1013'])
        self.assertEqual(data['previous_exercise'], {code: previous_totals[code] for code in ('1003', '1013', '1023', '1033')})
        sheet = openpyxl.load_workbook(io.BytesIO(wizards[1]._get_xlsx_file()[1])).active
        rows = {row[0]: row[2:6] for row in sheet.iter_rows(values_only=True) if row[0]}
        self.assertEqual(rows['1023'][3], previous_totals['1023'])
        self.assertIsNone(rows['1021'][3])
        html, _ = self.env['ir.actions.report']._render_qweb_html(
            'l10n_be_hr_payroll.action_report_social_balance', wizards[1].ids, data={'sbs_data': data})
        self.assertIn(f"{previous_totals['1023']:,}", str(html))

    def test_previous_exercise_without_sex(self):
        """ The workers of the previous exercise without sex don't block the social balance sheet of the exercise: the
        totals of the previous exercise are left to be completed by hand """
        company = self.create_belgian_company({'name': 'Previous Exercise Without Sex Company'})
        former_worker, worker = self.create_employee([{
            'name': 'Former Worker Without Sex',
            'company_id': company.id,
            'date_version': date(2024, 1, 1),
            'contract_date_start': date(2024, 1, 1),
            'contract_date_end': date(2024, 3, 31),
            'sex': False,
        }, {
            'name': 'Worker With Sex',
            'company_id': company.id,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'sex': 'female',
        }])
        self.create_and_validate_payslips(employees=former_worker, year=2024, months=[1])
        self.create_and_validate_payslips(employees=worker, year=2025, months=[1])
        wizard = self.env['l10n.be.social.balance.sheet'].with_company(company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })
        data = wizard._get_report_data()
        self.assertEqual(data['previous_exercise'], {})
        wizard.print_report()
        self.assertTrue(wizard.social_balance_sheet)
        self.assertTrue(wizard._get_xlsx_file()[1])


@tagged('post_install_l10n', 'post_install', '-at_install', 'social_balance_sheet')
class TestPayrollSocialBalanceSheetDownload(TestPayrollCommon, HttpCase):

    def test_xlsx_download(self):
        """ The spreadsheet is downloaded from its route, without being stored on the wizard """
        import openpyxl  # noqa: PLC0415
        employee = self.create_employee([{
            'name': 'Download Worker',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'certificate': 'master',
        }])
        self.create_and_validate_payslips(employees=employee, year=2025, months=[1])
        wizard = self.env['l10n.be.social.balance.sheet'].with_company(self.belgian_company).create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })
        action = wizard.export_report_xlsx()
        self.assertEqual(action['type'], 'ir.actions.act_url')

        # the spreadsheet is generated in the company of the wizard, which must be allowed to the user
        self.env.ref('base.user_admin').company_ids |= self.belgian_company
        self.authenticate('admin', 'admin')
        response = self.url_open(action['url'])
        self.assertEqual(response.status_code, 200)
        self.assertIn('.xlsx', response.headers['Content-Disposition'])
        sheet = openpyxl.load_workbook(io.BytesIO(response.content)).active
        self.assertEqual(sheet.cell(row=1, column=1).value, 'Social Balance Sheet - Complete Scheme')

        self.assertEqual(self.url_open('/l10n_be_hr_payroll/social_balance_sheet/0/xlsx').status_code, 404)
