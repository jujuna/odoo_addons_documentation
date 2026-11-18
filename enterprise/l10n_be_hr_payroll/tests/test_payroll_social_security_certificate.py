# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from unittest.mock import patch

from odoo.tests import tagged

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'social_security_certificate')
class TestPayrollSocialSecurityCertificate(TestPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.create_belgian_company({'name': 'Certificate Company'})
        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'Certificate Brand'})
        model = cls.env['fleet.vehicle.model'].create({'brand_id': brand.id, 'name': 'Certificate Model'})
        cls.car = cls.env['fleet.vehicle'].create({
            'model_id': model.id,
            'license_plate': 'CERT-001',
            'company_id': cls.company.id,
            'car_value': 25000.0,
            'fuel_type': 'diesel',
            'co2': 120.0,
            'co2_emission_unit': 'g/km',
            'acquisition_date': date(2022, 1, 1),
        })
        cls.employee_with_car, cls.employee_without_car = cls.create_employee([{
            'name': 'Employee With Car',
            'company_id': cls.company.id,
            'contract_date_start': date(2025, 1, 1),
            'transport_mode_car': True,
            'car_id': cls.car.id,
        }, {
            'name': 'Employee Without Car',
            'company_id': cls.company.id,
            'contract_date_start': date(2025, 1, 1),
        }])
        cls.car.driver_id = cls.employee_with_car.work_contact_id

    def _get_certificate_data(self, aggregation_level='company'):
        wizard = self.env['l10n.be.social.security.certificate'].with_company(self.company).create({
            'company_id': self.company.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
            'aggregation_level': aggregation_level,
        })
        return wizard._get_report_data()

    def _get_line_total(self, payslips, code):
        return payslips._get_line_values([code], compute_sum=True)[code]['sum']['total']

    def test_co2_fees(self):
        """ The solidarity contribution on the company cars is the one of the payslips, already in the employer
        contributions """
        payslips = self.create_and_validate_payslips(employees=self.employee_with_car | self.employee_without_car, year=2025, months=[1])
        [(_name, data)] = self._get_certificate_data()
        co2_fee = self._get_line_total(payslips, 'CO2FEE')
        self.assertTrue(co2_fee)
        self.assertAlmostEqual(data['co2_fees'][0], co2_fee, 2)
        self.assertAlmostEqual(data['emp_onss'][0], self._get_line_total(payslips, 'ONSSEMPLOYER'), 2)

    def test_employer_cost(self):
        """ The employer cost is the employer contributions, of which the closure fund and the structural reduction,
        and the meal vouchers paid by the employer """
        payslips = self.create_and_validate_payslips(employees=self.employee_with_car | self.employee_without_car, year=2025, months=[1])
        [(_name, data)] = self._get_certificate_data()
        employer_contributions = self._get_line_total(payslips, 'ONSSEMPLOYER')
        self.assertAlmostEqual(data['emp_onss'][0], employer_contributions, 2)
        self.assertAlmostEqual(
            data['closure_fund'][0],
            self._get_line_total(payslips, 'ONSSEMPLOYER_809') + self._get_line_total(payslips, 'ONSSEMPLOYER_810'), 2)
        self.assertTrue(data['closure_fund'][0])
        self.assertAlmostEqual(data['structural_reductions'][0], self._get_line_total(payslips, 'ONSS_STRUCTURAL'), 2)
        self.assertAlmostEqual(data['total_employer_cost'][0], employer_contributions + data['meal_voucher_employer'][0], 2)

    def test_students(self):
        """ The students, paid with the monthly salary structure, are counted once """
        student = self.create_employee([{
            'name': 'Student',
            'company_id': self.company.id,
            'contract_date_start': date(2025, 7, 1),
            'contract_date_end': date(2025, 7, 31),
            'l10n_be_dimona_category': 'stu',
            'l10n_be_worker_code_id': self.env['l10n.be.worker.code'].search([('dmfa_code', '=', '841')]).id,
        }])
        payslips = self.create_and_validate_payslips(employees=student, year=2025, months=[7])
        [(_name, data)] = self._get_certificate_data()
        self.assertTrue(data['student'][0])
        self.assertAlmostEqual(data['student'][0], self._get_line_total(payslips, 'BASIC'), 2)
        self.assertEqual(data['gross_before_onss'][0], 0)
        self.assertEqual(data['onss_cotisation'][0], 0)
        self.assertAlmostEqual(data['onss_student'][0], -self._get_line_total(payslips, 'ONSSTOTAL'), 2)
        self.assertAlmostEqual(data['total_gross_before_onss'][0], data['student'][0], 2)

    def test_withholding_taxes(self):
        """ The withholding taxes of all the structures are declared """
        payslips = self.create_and_validate_payslips(employees=self.employee_without_car, year=2025, months=[1])
        payslips |= self.create_and_validate_payslips(employees=self.employee_without_car, year=2025, months=[12], vals={
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month').id,
        })
        self.assertTrue(self._get_line_total(payslips[1], 'PPTOTAL'))
        [(_name, data)] = self._get_certificate_data()
        self.assertAlmostEqual(data['withholding_taxes'][0], -self._get_line_total(payslips, 'PPTOTAL'), 2)

    def test_public_transport(self):
        """ The train is a public transport """
        employee = self.create_employee([{
            'name': 'Train Commuter',
            'company_id': self.company.id,
            'contract_date_start': date(2025, 1, 1),
            'train_transport_employee_kilometer': 30,
        }])
        payslips = self.create_and_validate_payslips(employees=employee, year=2025, months=[1])
        self.assertTrue(self._get_line_total(payslips, 'TRAIN'))
        [(_name, data)] = self._get_certificate_data()
        self.assertAlmostEqual(data['public_transport'][0], self._get_line_total(payslips, 'TRAIN'), 2)

    def test_meal_vouchers_of_refunds(self):
        """ The meal vouchers paid by the employer are the ones of the payslips: a refund cancels them """
        employee = self.create_employee([{
            'name': 'Meal Vouchers',
            'company_id': self.company.id,
            'contract_date_start': date(2025, 1, 1),
            'meal_voucher_amount': 8,
        }])
        payslip = self.create_and_validate_payslips(employees=employee, year=2025, months=[1])
        meal_vouchers = self._get_line_total(payslip, 'MEAL_VOUCHER_EMPLOYER')
        self.assertTrue(meal_vouchers)
        payslip.refund_sheet()
        refund = self.env['hr.payslip'].search([('origin_payslip_id', '=', payslip.id)])
        self.assertIn(refund.state, ('validated', 'paid'))
        [(_name, data)] = self._get_certificate_data()
        self.assertAlmostEqual(data['meal_voucher_employer'][0], 0, 2)

    def test_double_holiday_pay(self):
        """ The double holiday pay is declared once: the part subject to the ONSS and the rest """
        employee = self.create_employee([{
            'name': 'Double Holiday Pay',
            'company_id': self.company.id,
            'date_version': date(2023, 1, 1),
            'contract_date_start': date(2023, 1, 1),
        }])
        payslips = self.create_and_validate_payslips(employees=employee, year=2025, months=[6], vals={
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
        })
        double_holiday_pay = self._get_line_total(payslips, 'DH_BASIC')
        self.assertTrue(double_holiday_pay)
        [(_name, data)] = self._get_certificate_data()
        self.assertAlmostEqual(data['double_pay'][0], self._get_line_total(payslips, 'DH_SALARY'), 2)
        self.assertAlmostEqual(data['double_pay'][0] + data['double_gross'][0], double_holiday_pay, 2)

    def test_departments(self):
        """ The payslips are grouped by department of their version, the ones without department included """
        department = self.env['hr.department'].create({'name': 'Certificate Department', 'company_id': self.company.id})
        self.employee_with_car.department_id = department
        payslips = self.create_and_validate_payslips(employees=self.employee_with_car | self.employee_without_car, year=2025, months=[1])
        [(_name, company_data)] = self._get_certificate_data()
        department_data = dict(self._get_certificate_data('department'))
        self.assertEqual(set(department_data), {department.complete_name, 'Without Department'})
        self.assertAlmostEqual(sum(data['net'][0] for data in department_data.values()), company_data['net'][0], 2)
        self.assertAlmostEqual(company_data['net'][0], self._get_line_total(payslips, 'NET'), 2)

    def test_double_holiday_pay_by_employee(self):
        """ The double holiday payslips of each employee are declared as double holiday pay """
        employees = self.create_employee([{
            'name': f'Double Holiday Pay {i}',
            'company_id': self.company.id,
            'date_version': date(2023, 1, 1),
            'contract_date_start': date(2023, 1, 1),
        } for i in range(2)])
        payslips = self.create_and_validate_payslips(employees=employees, year=2025, months=[6], vals={
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
        })
        employee_data = dict(self._get_certificate_data('employee'))
        for employee in employees:
            employee_payslip = payslips.filtered(lambda p: p.employee_id == employee)
            onss = self._get_line_total(employee_payslip, 'ONSSTOTAL')
            self.assertTrue(onss)
            self.assertAlmostEqual(employee_data[employee.legal_name]['onss_double'][0], -onss, 2)
            self.assertEqual(employee_data[employee.legal_name]['onss_cotisation'][0], 0)

    def test_xlsx_export_of_homonyms(self):
        """ Two employees may have the same name: each one has its own sheet """
        employees = self.create_employee([{
            'name': 'Jean Dupont',
            'company_id': self.company.id,
            'contract_date_start': date(2025, 1, 1),
            'l10n_be_legal_first_name': 'Jean',
            'l10n_be_legal_last_name': 'Dupont',
        } for _ in range(2)])
        self.create_and_validate_payslips(employees=employees, year=2025, months=[1])
        wizard = self.env['l10n.be.social.security.certificate'].with_company(self.company).create({
            'company_id': self.company.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
            'aggregation_level': 'employee',
        })
        wizard.export_report_xlsx()
        self.assertTrue(wizard.social_security_xlsx)

    def test_withholding_tax_exemptions_computed_once(self):
        """ The 274 declarations are computed once per month, whatever the number of employees """
        self.create_and_validate_payslips(employees=self.employee_with_car | self.employee_without_car, year=2025, months=[1])
        Declaration = self.env.registry['l10n_be.274_xx']
        with patch.object(Declaration, '_compute_line_ids', autospec=True, side_effect=Declaration._compute_line_ids) as compute:
            data = self._get_certificate_data('employee')
        self.assertEqual(len(data), 2)
        self.assertEqual(compute.call_count, 12)

    def test_withholding_tax_exemptions_of_the_months_of_the_payslips(self):
        """ The 274 declarations cover the whole months of the payslips, even for a period of partial months """
        wizard = self.env['l10n.be.social.security.certificate'].with_company(self.company).create({
            'company_id': self.company.id,
            'date_from': date(2025, 1, 10),
            'date_to': date(2025, 3, 20),
        })
        periods = []
        Declaration = self.env.registry['l10n_be.274_xx']
        compute_line_ids = Declaration._compute_line_ids

        def _compute_line_ids(declarations):
            periods.extend((declaration.date_start, declaration.date_end) for declaration in declarations)
            return compute_line_ids(declarations)

        with patch.object(Declaration, '_compute_line_ids', autospec=True, side_effect=_compute_line_ids):
            wizard._get_report_data()
        self.assertEqual(periods, [
            (date(2025, 1, 1), date(2025, 1, 31)),
            (date(2025, 2, 1), date(2025, 2, 28)),
            (date(2025, 3, 1), date(2025, 3, 31)),
        ])

    def test_joint_committees(self):
        """ The certificate mentions the joint committees of the employees """
        self.create_and_validate_payslips(employees=self.employee_without_car, year=2025, months=[1])
        wizard = self.env['l10n.be.social.security.certificate'].with_company(self.company).create({
            'company_id': self.company.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })
        self.assertEqual(wizard._get_joint_committees(), ['200'])
        html, _ = self.env['ir.actions.report']._render_qweb_html(
            'l10n_be_hr_payroll.action_report_social_security_certificate', wizard.ids,
            data={'report_data': wizard._get_report_data()})
        self.assertIn('Numbers of joint committees: 200<', str(html))

    def test_validate_saves_the_files(self):
        """ The generated files are saved when the wizard is validated """
        self.create_and_validate_payslips(employees=self.employee_without_car, year=2025, months=[1])
        for model in ('l10n.be.social.security.certificate', 'l10n.be.social.balance.sheet'):
            with self.subTest(model=model):
                wizard = self.env[model].with_company(self.company).create({
                    'company_id': self.company.id,
                    'date_from': date(2025, 1, 1),
                    'date_to': date(2025, 12, 31),
                })
                wizard.export_report_xlsx()
                with patch.object(self.registry[model], '_post_process_generated_file', autospec=True) as post_process:
                    wizard.action_validate()
                post_process.assert_called_once()
                self.assertTrue(post_process.call_args.args[2].endswith('.xlsx'))

    def test_file_names(self):
        """ The files of the certificate are not named as the social balance sheet """
        wizard = self.env['l10n.be.social.security.certificate'].with_company(self.company).create({
            'company_id': self.company.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })
        wizard.export_report_xlsx()
        self.assertTrue(wizard.social_security_filename_xlsx.startswith('SocialSecurityCertificate-'))

    def test_employees_and_workers(self):
        """ The certificate splits the employees and the workers (blue collars) """
        worker = self.create_employee([{
            'name': 'Blue Collar',
            'company_id': self.company.id,
            'contract_date_start': date(2025, 1, 1),
            'l10n_be_worker_code_id': self.env['l10n.be.worker.code'].search([('dmfa_code', '=', '015')]).id,
        }])
        self.assertTrue(worker.version_id.is_worker())
        worker_payslip = self.create_and_validate_payslips(employees=worker, year=2025, months=[1])
        employee_payslip = self.create_and_validate_payslips(employees=self.employee_without_car, year=2025, months=[1])
        [(_name, data)] = self._get_certificate_data()
        total, employees, workers = data['net']
        self.assertAlmostEqual(employees, self._get_line_total(employee_payslip, 'NET'), 2)
        self.assertAlmostEqual(workers, self._get_line_total(worker_payslip, 'NET'), 2)
        self.assertAlmostEqual(total, employees + workers, 2)

    def test_non_recurring_and_profit_sharing_bonuses(self):
        """ The CCT 90 and profit sharing bonuses are in the gross salary, with their solidarity contribution, and
        the salary advances are not salaries """
        bonuses = {
            'l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_cct90': ('CCT90BONUSPLAN', 3000.0),
            'l10n_be_hr_payroll.hr_payroll_structure_cp200_profit_sharing_bonus': ('PROFITSHARINGLOW', 2000.0),
            'l10n_be_hr_payroll.hr_payroll_structure_cp200_salary_advance': ('SALARYADV', 500.0),
        }
        payslips = self.env['hr.payslip']
        for month, (structure, (code, amount)) in enumerate(bonuses.items(), start=3):
            payslip = self.env['hr.payslip'].create({
                'name': structure,
                'employee_id': self.employee_without_car.id,
                'company_id': self.company.id,
                'version_id': self.employee_without_car.version_id.id,
                'struct_id': self.env.ref(structure).id,
                'date_from': date(2025, month, 1),
                'date_to': date(2025, month, 28),
            })
            payslip._set_input_value(code, amount)
            payslip.compute_sheet()
            payslips |= payslip
        payslips.action_payslip_done()
        cct90, profit_sharing, advance = payslips
        [(_name, data)] = self._get_certificate_data()
        self.assertAlmostEqual(data['cct90_bonus'][0], 3000, 2)
        self.assertAlmostEqual(data['profit_sharing'][0], 2000, 2)
        self.assertAlmostEqual(data['total_gross_before_onss'][0], 5000, 2)
        cct90_onss = self._get_line_total(cct90, 'ONSS_BONUS') + self._get_line_total(cct90, 'ONSS_SOLIDARITY_BONUS')
        self.assertTrue(cct90_onss)
        self.assertAlmostEqual(data['onss_cct90'][0], cct90_onss, 2)
        self.assertAlmostEqual(data['onss_profit_sharing'][0], -self._get_line_total(profit_sharing, 'ONSSTOTAL'), 2)
        self.assertAlmostEqual(data['onss_cotisation'][0], 0, 2)
        self.assertAlmostEqual(data['emp_onss'][0], self._get_line_total(cct90, 'ONSSEMPLOYER'), 2)
        self.assertAlmostEqual(data['salary_advance'][0], self._get_line_total(advance, 'NET'), 2)
        self.assertAlmostEqual(data['total_net'][0], self._get_line_total(payslips, 'NET'), 2)

    def test_gross_salary_before_onss(self):
        """ The gross salary before ONSS is the ONSS base of the monthly payslips, whatever their salary rules, without
        the benefits in kind, which are split between the ones subject to the ONSS or not """
        payslips = self.env['hr.payslip'].create([{
            'name': employee.name,
            'employee_id': employee.id,
            'company_id': self.company.id,
            'version_id': employee.version_id.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
        } for employee in self.employee_with_car | self.employee_without_car])
        for payslip in payslips:
            payslip._set_input_value('ATN_MISC', 100.0)
        payslips.compute_sheet()
        payslips.action_payslip_done()
        [(_name, data)] = self._get_certificate_data()
        self.assertAlmostEqual(data['atn'][0], 200, 2)
        self.assertAlmostEqual(data['gross_before_onss'][0] + data['atn'][0], self._get_line_total(payslips, 'SALARY'), 2)
        self.assertAlmostEqual(data['gross_before_onss'][0], self._get_line_total(payslips, 'BASIC'), 2)
        self.assertTrue(data['atn_without_onss'][0])
        self.assertAlmostEqual(data['atn_without_onss'][0], self._get_line_total(payslips, 'ATN.CAR'), 2)

    def test_signs_of_the_deductions(self):
        """ The deductions of the workers are negative, as on the payslips: the net salary is the sum of the gross
        salary and of the deductions """
        payslips = self.create_and_validate_payslips(employees=self.employee_with_car | self.employee_without_car, year=2025, months=[1])
        [(_name, data)] = self._get_certificate_data()
        deductions = ['onss_cotisation', 'withholding_taxes', 'misc_onss', 'atn_deduction', 'meal_voucher_employee']
        for deduction in deductions:
            self.assertLessEqual(data[deduction][0], 0, deduction)
        self.assertTrue(data['onss_cotisation'][0])
        self.assertAlmostEqual(
            data['subtotal_gross'][0] + sum(data[deduction][0] for deduction in deductions),
            self._get_line_total(payslips, 'NET'), 2)
