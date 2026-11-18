# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date, timedelta
from freezegun import freeze_time
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import format_amount

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'l10n_be_281_10')
class TestL10nBe28110(TestPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'Audi'})
        cls.car_model = cls.env['fleet.vehicle.model'].create({'name': 'A3', 'brand_id': brand.id})

    @classmethod
    def _create_employee(cls, values, car_atn=0.0):
        with freeze_time('2025-01-01'):
            employee = cls.create_employee({
                'name': 'Declaration Employee',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'niss': '/',
                'private_street': 'Rue du Test 1',
                'private_zip': '1000',
                'private_city': 'Brussels',
                **values,
            })
            if car_atn:
                car = cls.env['fleet.vehicle'].create({
                    'model_id': cls.car_model.id,
                    'company_id': cls.belgian_company.id,
                    'atn': car_atn,
                    'driver_employee_id': employee.id,
                })
                # The company car and the private car rides reset each other: write them together for an employee
                # who also uses their own car on some days
                employee.version_id.write({
                    'transport_mode_car': True,
                    'car_id': car.id,
                    'private_car_employee_kilometer': values.get('private_car_employee_kilometer', 0),
                })
        return employee

    def _get_281_10(self, employee, payslips_months=(1, 2, 3)):
        with freeze_time('2025-04-15'):
            payslips = self.create_and_validate_payslips(employee, 2025, list(payslips_months))
        with freeze_time('2026-02-01'):
            declaration = self.env['l10n_be.281_xx'].create({
                'year': '2025',
                'company_id': employee.company_id.id,
            })
            sheet = declaration.l10n_be_281_10_ids[:1]
            sheet.action_generate_declarations()
            values = sheet.with_context(round_281=True)._get_rendering_data(employee)['employees_data'][0]
        return payslips, values

    @staticmethod
    def _eurocent(amount):
        return round(amount * 100)

    @staticmethod
    def _total(payslips, codes):
        line_values = payslips._get_line_values(codes, compute_sum=True)
        return sum(line_values[code]['sum']['total'] for code in codes)

    def test_benefits_in_kind_not_declared_twice(self):
        # The benefits in kind are part of the taxable salary of the payslip: they are declared in 6b and 14c
        # (company car up to the yearly commuting exemption), never a second time in 6a.
        employee = self._create_employee({'internet': 38.0, 'mobile': 30.0}, car_atn=2400.0)
        payslips, values = self._get_281_10(employee, payslips_months=range(1, 7))

        gross = self._total(payslips, list(payslips._get_gross_wage_line_codes()))
        atn = self._total(payslips, list(self.env['l10n_be.281_10']._get_atn_code_mapping()))
        car_atn = self._total(payslips, ['ATN.CAR', 'ATNCARREGUL'])
        self.assertTrue(self._total(payslips, ['ATN.INT', 'ATN.MOB']), "The internet and phone benefits should be computed")
        self.assertGreater(car_atn, 490, "The company car benefit should exceed the yearly commuting exemption")

        self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(gross - atn))
        self.assertEqual(values['f10_2088_andervervoermiddel'], self._eurocent(490))
        self.assertEqual(values['f10_2076_voordelenaardbedrag'], self._eurocent(atn - 490))
        self.assertEqual(values['f10_2062_totaal'], values['f10_2060_gewonebezoldiginge'] + values['f10_2076_voordelenaardbedrag'])
        self.assertIn('F', values['f10_2099_aard'])

    def test_small_company_car_benefit_keeps_other_benefits(self):
        # A company car benefit below the yearly exemption is entirely declared in 14c: only that amount is
        # taken out of the benefits in kind, the other benefits stay in 6b.
        employee = self._create_employee({'internet': 38.0}, car_atn=1600.0)
        payslips, values = self._get_281_10(employee)

        car_atn = self._total(payslips, ['ATN.CAR', 'ATNCARREGUL'])
        internet_atn = self._total(payslips, ['ATN.INT'])
        self.assertLess(car_atn, 490)
        self.assertTrue(internet_atn)

        self.assertEqual(values['f10_2088_andervervoermiddel'], self._eurocent(car_atn))
        self.assertEqual(values['f10_2076_voordelenaardbedrag'], self._eurocent(internet_atn))
        # The nature of the benefits in kind is the one of the benefits declared in 6b
        self.assertEqual(values['f10_2099_aard'], 'I')

    def test_small_company_car_benefit_alone(self):
        # A company car benefit entirely declared in 14c leaves no benefit in kind in 6b, nor its nature
        employee = self._create_employee({}, car_atn=1600.0)
        payslips, values = self._get_281_10(employee)

        self.assertTrue(self._total(payslips, ['ATN.CAR']))
        self.assertEqual(values['f10_2076_voordelenaardbedrag'], 0)
        self.assertEqual(values['f10_2099_aard'], '')

    def test_benefits_in_kind_without_remuneration(self):
        # An employee on unpaid leave keeps his benefits in kind: the ONSS on them can't be deducted from a
        # remuneration that doesn't exist, it is deducted from the benefits in kind instead of declaring a negative
        # remuneration, which Belcotax refuses.
        employee = self._create_employee({'internet': 38.0, 'mobile': 30.0})
        self.env['hr.leave'].sudo().create({
            'employee_id': employee.id,
            'request_date_from': date(2025, 1, 1),
            'request_date_to': date(2025, 3, 31),
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
        })
        payslips, values = self._get_281_10(employee)

        gross = self._total(payslips, list(payslips._get_gross_wage_line_codes()))
        atn = self._total(payslips, list(self.env['l10n_be.281_10']._get_atn_code_mapping()))
        self.assertTrue(0 < gross < atn, "The benefits in kind should be the only remuneration, ONSS deducted")

        self.assertEqual(values['f10_2060_gewonebezoldiginge'], 0)
        self.assertEqual(values['f10_2076_voordelenaardbedrag'], self._eurocent(gross))
        self.assertEqual(values['f10_2062_totaal'], self._eurocent(gross))

    def test_negative_remuneration_warning(self):
        # A negative remuneration that the benefits in kind of box 6b can't absorb either is not declared: Belcotax
        # refuses a negative amount. The declaration warns about the amount left out, without blocking it.
        employee = self._create_employee({'internet': 38.0, 'mobile': 30.0})
        self.env['hr.leave'].sudo().create({
            'employee_id': employee.id,
            'request_date_from': date(2025, 1, 1),
            'request_date_to': date(2025, 4, 30),
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
        })
        with freeze_time('2025-04-15'):
            deduction_payslip = self.create_and_validate_payslips(employee, 2025, [4])
            deduction_payslip.action_payslip_cancel()
            deduction_payslip.action_payslip_draft()
            deduction_payslip._set_input_value('TAXABLE_NO_ONSS_DED', 500)
            deduction_payslip.compute_sheet()
            deduction_payslip.action_payslip_done()
        payslips, values = self._get_281_10(employee)

        gross = self._total(payslips + deduction_payslip, list(payslips._get_gross_wage_line_codes()))
        self.assertLess(gross, 0)
        self.assertEqual(values['f10_2060_gewonebezoldiginge'], 0)
        self.assertEqual(values['f10_2076_voordelenaardbedrag'], 0)

        declaration = self.env['l10n_be.281_xx'].search([('year', '=', '2025')], order='id desc', limit=1)
        with freeze_time('2026-02-01'):
            declaration.action_generate_xml()
        self.assertEqual(declaration.state, 'ready', declaration.error_message)
        self.assertIn(employee.name, declaration.declaration_warning)
        self.assertIn(format_amount(self.env, -gross, employee.company_id.currency_id), declaration.declaration_warning)

    def test_company_bike_benefit(self):
        # The benefit of a company bike is declared in box 14 e (2208), at its monthly cost for the employer
        employee = self._create_employee({})
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'Bike Brand'})
        bike_model = self.env['fleet.vehicle.model'].create({
            'name': 'City Bike',
            'brand_id': brand.id,
            'vehicle_type': 'bike',
            'default_recurring_cost_amount_depreciated': 45.5,
        })
        bike = self.env['fleet.vehicle'].create({'model_id': bike_model.id, 'company_id': self.belgian_company.id})
        employee.bike_id = bike
        self.assertEqual(employee.version_id.company_bike_depreciated_cost, 45.5)
        payslips, values = self._get_281_10(employee)
        self.assertEqual(self._total(payslips, ['BIKE_BENEFIT']), 3 * 45.5)
        self.assertEqual(values['f10_2208_benefitprovisionbicycleorspeedpedelec'], self._eurocent(3 * 45.5))
        # out of the pay: the taxable remuneration is the one of the payslips, without the benefit
        self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(
            self._total(payslips, list(payslips._get_gross_wage_line_codes()))))

    def test_taxable_gift_vouchers(self):
        # The taxable gift vouchers and the miscellaneous benefits without ONSS are benefits in kind (box 6b, other
        # benefits)
        employee = self._create_employee({})
        with freeze_time('2025-04-15'):
            voucher_payslip = self.env['hr.payslip'].create({
                'name': 'Gift vouchers',
                'employee_id': employee.id,
                'version_id': employee.version_id.id,
                'company_id': employee.company_id.id,
                'date_from': date(2025, 4, 1),
                'date_to': date(2025, 4, 30),
            })
            voucher_payslip._set_input_value('GIFT_VOUCHER_ONSS_PP', 100)
            voucher_payslip._set_input_value('GIFT_VOUCHER_NO_ONSS', 50)
            voucher_payslip._set_input_value('ATN_MISC_NO_ONSS', 30)
            voucher_payslip.compute_sheet()
            voucher_payslip.action_payslip_done()
        payslips, values = self._get_281_10(employee)
        payslips |= voucher_payslip

        self.assertEqual(values['f10_2076_voordelenaardbedrag'], self._eurocent(180))
        self.assertEqual(values['f10_2099_aard'], 'Z')
        self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(
            self._total(payslips, list(payslips._get_gross_wage_line_codes())) - 180))

    def test_mobility_budget_and_commuting_warning(self):
        # The commuting reimbursements of an employee with a mobility budget are declared otherwise, but for
        # exceptions: the declaration warns about them
        employee = self._create_employee({
            'bike_transport_employee_kilometer': 5,
            'l10n_be_mobility_budget': True,
            'l10n_be_mobility_budget_amount': 500.0,
        })
        payslips, values = self._get_281_10(employee)
        self.assertTrue(self._total(payslips, ['CYCLE']))
        self.assertTrue(values['f10_2134_totaalbedragmobiliteitsbudget'])

        declaration = self.env['l10n_be.281_xx'].search([('year', '=', '2025')], order='id desc', limit=1)
        with freeze_time('2026-02-01'):
            declaration.action_generate_xml()
        self.assertIn('mobility budget', declaration.declaration_warning)
        self.assertIn(employee.name, declaration.declaration_warning)

    def test_mobility_budget_prorated_to_the_days_of_participation(self):
        # Zone 2134: the mobility budget the worker is entitled to in the year, i.e. the yearly budget prorated to the
        # calendar days of participation in the mobility budget system in the year (circular 2024/C/16 n° 61-62): a
        # change of budget weighs each budget by its days, a stop keeps the days before it
        budget = {'l10n_be_mobility_budget': True, 'l10n_be_mobility_budget_amount': 6000.0}
        entry = {'date_version': date(2025, 7, 1), 'contract_date_start': date(2025, 7, 1)}
        entry_april = {'date_version': date(2025, 4, 1), 'contract_date_start': date(2025, 4, 1)}
        for name, employee_values, new_versions, months, expected in (
            ('entry during the year', entry, [], (7, 8), 6000.0 * 184 / 365),
            ('budget raised during the year', {}, [{'date_version': date(2025, 2, 1), 'l10n_be_mobility_budget_amount': 7200.0}],
             (1, 2, 3), (6000.0 * 31 + 7200.0 * 334) / 365),
            ('budget stopped during the year', {}, [{'date_version': date(2025, 2, 1), 'l10n_be_mobility_budget': False}],
             (1, 2, 3), 6000.0 * 31 / 365),
            ('entry and budget raised during the year', entry_april,
             [{'date_version': date(2025, 10, 1), 'l10n_be_mobility_budget_amount': 7200.0}],
             (4, 5), (6000.0 * 183 + 7200.0 * 92) / 365),
        ):
            with self.subTest(name):
                employee = self._create_employee({**budget, **employee_values})
                for version_values in new_versions:
                    employee.create_version(version_values)
                _payslips, values = self._get_281_10(employee, payslips_months=months)
                self.assertEqual(values['f10_2134_totaalbedragmobiliteitsbudget'], self._eurocent(expected))

    def test_private_car_reimbursement_declared_in_box_14(self):
        employee = self._create_employee({'private_car_employee_kilometer': 25})
        payslips, values = self._get_281_10(employee)

        gross = self._total(payslips, list(payslips._get_gross_wage_line_codes()))
        car_priv = self._total(payslips, ['CAR.PRIV'])
        self.assertTrue(car_priv, "The private car reimbursement should be paid")

        self.assertEqual(values['f10_2088_andervervoermiddel'], self._eurocent(car_priv))
        self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(gross - car_priv),
            "The reimbursement is part of the taxable salary of the payslip but is declared in box 14")

        # The 274.10 declares the same taxable amount as the 281.10 it adds up to: without the reimbursement
        march = payslips.filtered(lambda p: p.date_from == date(2025, 3, 1))
        sheet_274 = self.env['l10n_be.274_xx'].with_company(employee.company_id).create({'year': 2025, 'month': '3'})
        line_274_10 = sheet_274.line_274_10_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_10.taxable_amount, self._total(
            march, list(march._get_gross_wage_line_codes())) - self._total(march, ['CAR.PRIV']), places=2)

    def test_private_car_reimbursement_and_company_car(self):
        # Box 14c: the company car benefit up to the yearly limit, the private car reimbursement doesn't reduce it
        # ("avis aux débiteurs", annex 6)
        employee = self._create_employee({'private_car_employee_kilometer': 25}, car_atn=1600.0)
        payslips, values = self._get_281_10(employee)

        car_priv = self._total(payslips, ['CAR.PRIV'])
        car_atn = self._total(payslips, ['ATN.CAR', 'ATNCARREGUL'])
        self.assertTrue(car_priv)
        self.assertGreater(car_priv + car_atn, 490)
        self.assertLess(car_atn, 490)
        self.assertEqual(values['f10_2088_andervervoermiddel'], self._eurocent(car_priv + car_atn))
        self.assertEqual(values['f10_2076_voordelenaardbedrag'], 0)

    def test_private_car_reimbursement_of_arrears(self):
        # The private car reimbursement of an arrear payslip is declared in box 14 with the other ones, neither in
        # the arrears of box 7b nor taken out of the remuneration of box 6a a second time
        employee = self._create_employee({
            'date_version': date(2024, 1, 1),
            'contract_date_start': date(2024, 1, 1),
            'private_car_employee_kilometer': 25,
        })
        with freeze_time('2025-04-15'):
            arrear_payslip = self.env['hr.payslip'].create({
                'name': 'Arrears',
                'employee_id': employee.id,
                'version_id': employee.version_id.id,
                'company_id': employee.company_id.id,
                'date_from': date(2024, 7, 1),
                'date_to': date(2024, 7, 31),
                'l10n_be_arrear_salary': True,
            })
            arrear_payslip.compute_sheet()
            arrear_payslip.action_payslip_done()
        self.assertTrue(self._total(arrear_payslip, ['CAR.PRIV']), "The arrears should reimburse the private car")
        payslips, values = self._get_281_10(employee)

        gross_codes = list(payslips._get_gross_wage_line_codes())
        self.assertEqual(values['f10_2064_afzbelachterstall'], self._eurocent(
            self._total(arrear_payslip, gross_codes) - self._total(arrear_payslip, ['CAR.PRIV'])))
        self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(
            self._total(payslips, gross_codes) - self._total(payslips, ['CAR.PRIV'])))
        self.assertEqual(values['f10_2088_andervervoermiddel'], self._eurocent(
            self._total(payslips + arrear_payslip, ['CAR.PRIV'])))

    def _create_arrear_payslip(self, employee, struct_xmlid='l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary', inputs=None):
        # Arrears of July 2024 paid in 2025
        with freeze_time('2025-04-15'):
            arrear_payslip = self.env['hr.payslip'].create({
                'name': 'Arrears',
                'employee_id': employee.id,
                'version_id': employee.version_id.id,
                'company_id': employee.company_id.id,
                'struct_id': self.env.ref(struct_xmlid).id,
                'date_from': date(2024, 7, 1),
                'date_to': date(2024, 7, 31),
                'l10n_be_arrear_salary': True,
            })
            for code, amount in (inputs or {}).items():
                arrear_payslip._set_input_value(code, amount)
            arrear_payslip.compute_sheet()
            arrear_payslip.action_payslip_done()
        return arrear_payslip

    def test_benefits_in_kind_of_arrears(self):
        # The benefits in kind paid with arrears are arrears: declared in box 7b with the rest of the arrear payslip,
        # in the year the arrears are paid, neither in box 6b nor in its nature
        employee = self._create_employee({
            'date_version': date(2024, 1, 1),
            'contract_date_start': date(2024, 1, 1),
            'internet': 38.0,
        })
        arrear_payslip = self._create_arrear_payslip(employee, inputs={'ATN_MISC': 100})
        self.assertAlmostEqual(self._total(arrear_payslip, ['ATN_MISC']), 100, 2)
        payslips, values = self._get_281_10(employee)

        gross_codes = list(payslips._get_gross_wage_line_codes())
        atn_codes = list(self.env['l10n_be.281_10']._get_atn_code_mapping())
        atn = self._total(payslips, atn_codes)
        self.assertEqual(values['f10_2064_afzbelachterstall'], self._eurocent(self._total(arrear_payslip, gross_codes)))
        self.assertEqual(values['f10_2076_voordelenaardbedrag'], self._eurocent(atn))
        self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(self._total(payslips, gross_codes) - atn))
        self.assertEqual(values['f10_2099_aard'], 'I')

    def test_arrears_of_all_structures(self):
        # An arrear payslip is declared in box 7b whatever its structure. The yearly limit of the non recurring
        # benefits is shared proportionally between the benefits of the year (box 9a) and their arrears (box 9b), the
        # excess going to box 6a and box 7b respectively, as in the example of the "avis aux débiteurs".
        employee = self._create_employee({'date_version': date(2023, 1, 1), 'contract_date_start': date(2023, 1, 1)})
        cct90_xmlid = 'l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_cct90'
        double_holiday_arrears = self._create_arrear_payslip(
            employee, struct_xmlid='l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday')
        cct90_arrears = self._create_arrear_payslip(employee, struct_xmlid=cct90_xmlid, inputs={'CCT90BONUSPLAN': 2300})
        with freeze_time('2025-04-15'):
            cct90_payslip = self.env['hr.payslip'].create({
                'name': 'Non recurring benefits',
                'employee_id': employee.id,
                'version_id': employee.version_id.id,
                'company_id': employee.company_id.id,
                'struct_id': self.env.ref(cct90_xmlid).id,
                'date_from': date(2025, 3, 1),
                'date_to': date(2025, 3, 31),
            })
            cct90_payslip._set_input_value('CCT90BONUSPLAN', 4600)
            cct90_payslip.compute_sheet()
            cct90_payslip.action_payslip_done()
        payslips, values = self._get_281_10(employee)

        def bonus(payslip):
            # the bonus net of ONSS: the gross wage line, before the exemption applied on its payslip
            return self._total(payslip, ['BONUS_GROSS'])

        double_holiday = self._total(double_holiday_arrears, ['DH_GROSS'])
        self.assertTrue(double_holiday)
        limit = self.env['hr.rule.parameter']._get_parameter_from_code('cct90_employee_pp_threshold', date(2025, 1, 1))
        self.assertGreater(bonus(cct90_payslip) + bonus(cct90_arrears), limit)
        exempted = limit * bonus(cct90_payslip) / (bonus(cct90_payslip) + bonus(cct90_arrears))
        arrears_exempted = limit * bonus(cct90_arrears) / (bonus(cct90_payslip) + bonus(cct90_arrears))
        self.assertAlmostEqual(values['f10_2117_nonrecurrentadvantages'], self._eurocent(exempted), delta=1)
        self.assertAlmostEqual(values['f10_2127_nonrecurrentadvantagesoutdated'], self._eurocent(arrears_exempted), delta=1)
        self.assertAlmostEqual(values['f10_2064_afzbelachterstall'], self._eurocent(
            double_holiday + bonus(cct90_arrears) - arrears_exempted), delta=1)
        self.assertAlmostEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(
            self._total(payslips, ['GROSS']) + bonus(cct90_payslip) - exempted), delta=1)

    def _check_termination_compensation(self, code, weeks):
        # A compensation of the CCT 109 is paid with the termination fees and taxed as them (box 7c). It is no
        # remuneration for the ONSS.
        employee = self._create_employee({})
        with freeze_time('2025-04-15'):
            termination_payslip = self.env['hr.payslip'].create({
                'name': 'Termination Fees',
                'employee_id': employee.id,
                'version_id': employee.version_id.id,
                'company_id': employee.company_id.id,
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees').id,
                'date_from': date(2025, 3, 1),
                'date_to': date(2025, 3, 31),
            })
            termination_payslip._set_input_value('ND_MONTH', 1)
            termination_payslip.compute_sheet()
            net_without_compensation = self._total(termination_payslip, ['NET'])
            withholding_without_compensation = self._total(termination_payslip, ['TERM_PP'])
            termination_payslip._set_input_value(code, weeks)
            termination_payslip.compute_sheet()
            termination_payslip.action_payslip_done()

        compensation = self._total(termination_payslip, [code])
        # the weeks of remuneration granted, at the weekly pay of the reference salary
        compensation_line = termination_payslip.line_ids.filtered(lambda line: line.code == code)
        self.assertEqual(compensation_line.quantity, weeks)
        self.assertAlmostEqual(compensation, weeks * self._total(termination_payslip, ['REFERENCE_SALARY_REVALUED']) * 3 / (12 * 13), 2)
        # paid with the net and part of the taxable termination fees (box 7c), out of the ONSS
        self.assertIn(self.env.ref('l10n_be_hr_payroll.TERMINATION_WITHHOLDING_BASE'), compensation_line.salary_rule_id.category_ids)
        self.assertNotIn(self.env.ref('l10n_be_hr_payroll.TERM_ONSS_BASE'), compensation_line.salary_rule_id.category_ids)
        self.assertAlmostEqual(self._total(termination_payslip, ['TERM_BASIC']), self._total(termination_payslip, ['TOTALFEES']), 2,
            "The compensation is no remuneration for the ONSS")
        self.assertAlmostEqual(self._total(termination_payslip, ['TERM_GROSS']), self._total(
            termination_payslip, ['TOTALFEES', 'ONSS_TERM', code]), 2)
        withholding = self._total(termination_payslip, ['TERM_PP'])
        self.assertLess(withholding, withholding_without_compensation, "The compensation should be taxed")
        self.assertAlmostEqual(self._total(termination_payslip, ['NET']) - net_without_compensation,
            compensation + withholding - withholding_without_compensation, 2)

        _payslips, values = self._get_281_10(employee)
        self.assertEqual(values['f10_2065_opzeggingsreclasseringsverg'], self._eurocent(self._total(termination_payslip, ['TERM_GROSS'])))

    def _create_commute_allowance_payslip(self, paid_as_expenses=False):
        self.env.ref('l10n_be_hr_payroll.employees_salary_car_travel').active = True
        self.env.ref('l10n_be_hr_payroll.employees_salary_bike_travel').active = True
        employee = self._create_employee({'l10n_be_lsa_car_travel_amount': 0.4, 'l10n_be_lsa_bike_travel_amount': 0.25})
        with freeze_time('2025-04-15'):
            allowance_payslip = self.env['hr.payslip'].create({
                'name': 'Commute allowances',
                'employee_id': employee.id,
                'version_id': employee.version_id.id,
                'company_id': employee.company_id.id,
                'date_from': date(2025, 4, 1),
                'date_to': date(2025, 4, 30),
            })
            allowance_payslip._set_input_value('LSA_CAR_TRAVEL_KM', 100)
            allowance_payslip._set_input_value('LSA_BIKE_TRAVEL_KM', 120)
            allowance_payslip.compute_sheet()
            if paid_as_expenses:
                # A payslip computed before the allowances were commuting reimbursements paid them as expenses of the
                # employer, with the lump sum allowances, out of the taxable salary
                allowances = allowance_payslip.line_ids.filtered(lambda line: line.code in ('LSA_CAR_TRAVEL_KM', 'LSA_BIKE_TRAVEL_KM'))
                allowance_payslip.line_ids.filtered(lambda line: line.code == 'REP.FEES').total += sum(allowances.mapped('total'))
                allowance_payslip.line_ids.filtered(lambda line: line.code == 'GROSS').total -= 40
            allowance_payslip.action_payslip_done()
        payslips, values = self._get_281_10(employee)
        return payslips | allowance_payslip, values

    def test_commute_allowances(self):
        # The lump sum commute allowances are declared with the commuting reimbursements: the car one in box 14c, the
        # bike one in box 14d with its kilometers, not as expenses of the employer (box 26a)
        payslips, values = self._create_commute_allowance_payslip()

        self.assertAlmostEqual(self._total(payslips, ['LSA_CAR_TRAVEL_KM']), 40, 2)
        self.assertAlmostEqual(self._total(payslips, ['LSA_BIKE_TRAVEL_KM', 'LSA_BIKE_TRAVEL_KM.TAX']), 30, 2)
        self.assertEqual(values['f10_2088_andervervoermiddel'], self._eurocent(40))
        self.assertEqual(values['f10_2207_travelbicycleorspeedpedelec'], self._eurocent(self._total(payslips, ['LSA_BIKE_TRAVEL_KM'])))
        self.assertEqual(values['f10_2226_kmzone2207'], 120)
        self.assertEqual(values['f10_2200_compensationwithstandards'], 0)
        self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(
            self._total(payslips, list(payslips._get_gross_wage_line_codes())) - 40))

    def test_commute_allowances_paid_as_expenses(self):
        # The allowances paid as expenses of the employer by the payslips computed before they were commuting
        # reimbursements stay declared as they were paid, in box 26a
        payslips, values = self._create_commute_allowance_payslip(paid_as_expenses=True)

        self.assertEqual(values['f10_2088_andervervoermiddel'], 0)
        self.assertEqual(values['f10_2207_travelbicycleorspeedpedelec'], 0)
        self.assertEqual(values['f10_2226_kmzone2207'], 0)
        self.assertEqual(values['f10_2200_compensationwithstandards'], self._eurocent(self._total(payslips, ['REP.FEES'])))
        self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(
            self._total(payslips, list(payslips._get_gross_wage_line_codes()))))

    def test_unreasonable_dismissal_compensation(self):
        # The compensation for a manifestly unreasonable dismissal (CCT 109)
        self._check_termination_compensation('UNREASONABLE_DISMISSAL', 10)

    def test_non_respect_motivation_fine(self):
        # The civil fine of 2 weeks of remuneration for not giving the reasons of the dismissal (CCT 109)
        self._check_termination_compensation('NON_RESPECT_MOTIVATION', 2)

    def test_holiday_pay_regularization_on_termination_fees(self):
        # The regularization of the simple holiday pay recovered from the previous employer is ordinary holiday pay:
        # on the termination fees payslip, it is declared in box 6a, net of its ONSS, not with the termination fees.
        employee = self._create_employee({'date_version': date(2024, 1, 1), 'contract_date_start': date(2024, 1, 1)})
        explanation = {'recovered': 0, 'total_100_pct_wage': 1200, 'amount_to_recover': 1200, 'max_amount': 1200}
        with freeze_time('2025-04-15'), \
                patch.object(self.registry['hr.employee'], '_get_simple_holiday_pay_recoverable_amount', return_value=1200), \
                patch.object(self.registry['hr.payslip'], '_get_holiday_pay_regularization', return_value=(-1200, explanation)):
            termination_payslip = self.env['hr.payslip'].create({
                'name': 'Termination Fees',
                'employee_id': employee.id,
                'version_id': employee.version_id.id,
                'company_id': employee.company_id.id,
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees').id,
                'date_from': date(2025, 3, 1),
                'date_to': date(2025, 3, 31),
            })
            termination_payslip._set_input_value('ND_MONTH', 1)
            termination_payslip.compute_sheet()
            termination_payslip.action_payslip_done()
        self.assertAlmostEqual(self._total(termination_payslip, ['HolPayReg']), -1200, 2)
        onss_rate = termination_payslip.line_ids.filtered(lambda line: line.code == 'ONSS_TERM').rate
        self.assertTrue(onss_rate)
        regularization = -1200 * (1 + onss_rate / 100)
        payslips, values = self._get_281_10(employee)

        term_gross = self._total(termination_payslip, ['TERM_GROSS'])
        self.assertEqual(values['f10_2065_opzeggingsreclasseringsverg'], self._eurocent(term_gross - regularization))
        self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(
            self._total(payslips, list(payslips._get_gross_wage_line_codes())) + regularization))

        # The 274.10 declares the taxable salary of the month as a whole: the regularization is counted once
        sheet_274 = self.env['l10n_be.274_xx'].with_company(employee.company_id).create({'year': 2025, 'month': '3'})
        line_274_10 = sheet_274.line_ids.filtered(lambda line: line.nature_code == '274.10' and line.employee_id == employee)
        self.assertAlmostEqual(sum(line_274_10.mapped('taxable_amount')), term_gross + self._total(
            payslips.filtered(lambda p: p.date_from.month == 3), ['GROSS']), 2)

    def test_manual_expense_reimbursement(self):
        # The manual expense reimbursement only reports the expenses reimbursed outside of the payroll (box 26a): it
        # is not paid, and the user is told not to enter the expense reports reimbursed by the payslip
        rule = self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_expense_reimbursement_manual')
        self.assertIn('outside of the payroll', rule.user_instructions)
        employee = self._create_employee({})
        with freeze_time('2025-04-15'):
            payslip = self.env['hr.payslip'].create({
                'name': 'Manual expenses',
                'employee_id': employee.id,
                'version_id': employee.version_id.id,
                'company_id': employee.company_id.id,
                'date_from': date(2025, 4, 1),
                'date_to': date(2025, 4, 30),
            })
            payslip.compute_sheet()
            net = self._total(payslip, ['NET'])
            payslip._set_input_value('EXPENSE_MANUAL', 75)
            payslip.compute_sheet()
            payslip.action_payslip_done()
        self.assertAlmostEqual(self._total(payslip, ['NET']), net, 2)
        _payslips, values = self._get_281_10(employee)
        self.assertEqual(values['f10_2201_compensationwithdocuments'], self._eurocent(75))

    def test_relaunch_overtime_of_2023_until_2025(self):
        # The voluntary overtime of the relaunch worked in 2023 can be carried over 2 years: its zones are declared
        # until the income of 2025, not on the 281.10 of 2026
        for year, expected in (('2025', True), ('2026', False)):
            tags = self.env['l10n_be.281_10'].new()._get_mapping_lines(year).mapped('tag')
            self.assertEqual('f10_2079_covidovertimeremuneration2023' in tags, expected)
            self.assertEqual('f10_2138_covidovertimehours2023' in tags, expected)

    def test_cross_border_worker(self):
        # A cross-border worker has no Belgian withholding tax, but gets a 281.10 for his remuneration, as French
        # cross-border worker
        employee = self._create_employee({'l10n_be_resident_situation': 'cross_border'})
        self.assertTrue(employee.version_id.no_withholding_taxes)
        payslips, values = self._get_281_10(employee)

        self.assertFalse(self._total(payslips, ['PPTOTAL']))
        self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(
            self._total(payslips, list(payslips._get_gross_wage_line_codes()))))
        self.assertEqual(values['f10_2036_inwonersdeenfr'], 1)
        self.assertEqual(values['f10_2074_bedrijfsvoorheffing'], 0)
        declaration = self.env['l10n_be.281_xx'].search([('year', '=', '2025')], order='id desc', limit=1)
        self.assertIn(employee, declaration.l10n_be_281_10_line_ids.employee_id)

    def test_student_without_withholding_taxes(self):
        # A student without withholding taxes is declared as on the 274.10: on a 281.10, and not as an untaxed
        # employee of the declaration (the 281 forms add up the 274)
        employee = self._create_employee({
            'l10n_be_dimona_category': 'stu',
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00841').id,
            'wage': 800.0,
        })
        employee.version_id.no_withholding_taxes = True
        payslips, values = self._get_281_10(employee)

        self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(
            self._total(payslips, list(payslips._get_gross_wage_line_codes()))))
        self.assertEqual(values['f10_2074_bedrijfsvoorheffing'], 0)
        declaration = self.env['l10n_be.281_xx'].search([('year', '=', '2025')], order='id desc', limit=1)
        self.assertIn(employee, declaration.l10n_be_281_10_line_ids.employee_id)
        self.assertNotIn(employee, declaration.untaxed_employee_ids)

    def test_contributions_without_remuneration(self):
        # Without a 281.18, a 281.10 holding only the contributions withheld (special social security contribution,
        # group insurance), without any remuneration, is created as the social secretariats do: nothing is transferred
        employee = self._create_employee({})
        self.env['hr.leave'].sudo().create({
            'employee_id': employee.id,
            'request_date_from': date(2025, 1, 1),
            'request_date_to': date(2025, 3, 31),
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
        })
        with freeze_time('2025-04-15'):
            payslips = self.create_and_validate_payslips(employee, 2025, [1, 2, 3])
        self.assertFalse(self._total(payslips, list(payslips._get_gross_wage_line_codes())))
        # a regularization of the special social security contribution withheld on the last payslip
        special_contribution_rule = self.env['hr.salary.rule'].search([('code', '=', 'M.ONSS')], limit=1)
        self.env['hr.payslip.line'].create({
            'slip_id': payslips[-1].id,
            'salary_rule_id': special_contribution_rule.id,
            'name': special_contribution_rule.name,
            'code': 'M.ONSS',
            'amount': -10,
            'quantity': 1,
            'rate': 100,
            'total': -10,
        })
        with freeze_time('2026-02-01'):
            declaration = self.env['l10n_be.281_xx'].create({'year': '2025', 'company_id': employee.company_id.id})
            sheet = declaration.l10n_be_281_10_ids[:1]
            sheet.action_generate_declarations()
            self.assertIn(employee, sheet.line_ids.employee_id)
            values = sheet._get_rendering_data(employee)['employees_data'][0]
        self.assertAlmostEqual(values['f10_2075_bijzonderbijdrage'], 10, 2)
        all_line_values = payslips._get_line_values(
            sheet._get_line_codes(), vals_list=['total', 'quantity'], extra_domain=sheet._get_fiscal_line_domain())
        self.assertFalse(sheet._get_amounts_to_transfer_to_281_18(payslips.grouped('employee_id'), all_line_values))

    def test_mapping_of_the_year(self):
        # Each income year declares the zones of its own Belcotax schema: a zone created later (bicycle zones 2207
        # and 2208 in 2024, kilometers 2226 in 2025) is not declared for an earlier year (a correction), the control
        # totals do without it and the PDF of the form shows it empty
        declaration = self.env['l10n_be.281_xx'].create({'year': '2023', 'company_id': self.belgian_company.id})
        sheet = declaration.l10n_be_281_10_ids[:1]
        tags_by_year = {year: set(sheet._get_mapping_lines(year).mapped('tag')) for year in ('2023', '2024', '2025')}
        self.assertNotIn('f10_2207_travelbicycleorspeedpedelec', tags_by_year['2023'])
        self.assertIn('f10_2207_travelbicycleorspeedpedelec', tags_by_year['2024'])
        self.assertNotIn('f10_2226_kmzone2207', tags_by_year['2024'])
        self.assertIn('f10_2226_kmzone2207', tags_by_year['2025'])
        plan = sheet._get_mapping_lines('2023')._get_evaluation_plan()
        control_tags = next(data for _line, tag, _monetary, kind, data in plan if tag == 'f10_2077_totaal')
        self.assertIn('f10_2086_openbaargemeenschap', control_tags)
        self.assertNotIn('f10_2207_travelbicycleorspeedpedelec', control_tags)
        rendering_data = sheet._get_employees_rendering_data(self.env['hr.employee'])
        self.assertFalse(rendering_data['employees_data'])
        self.assertNotIn('f10_2207_travelbicycleorspeedpedelec', rendering_data['mapping_lines'].mapped('tag'))

    def test_281_10_of_an_apprentice(self):
        # The pay of an apprentice in alternating training (Dimona ALT) is a taxable remuneration declared on the
        # 281.10, as the social secretariats do
        employee = self._create_employee({'employee_type_id': self.env.ref('hr.contract_type_apprenticeship').id})
        self.assertEqual(employee.l10n_be_dimona_category, 'alt')
        payslips, values = self._get_281_10(employee)
        self.assertTrue(values['f10_2060_gewonebezoldiginge'])
        self.assertEqual(values['f10_2074_bedrijfsvoorheffing'], self._eurocent(self._total(payslips, ['PPTOTAL'])))

    def test_no_281_10_without_any_amount(self):
        # Payslips without any amount (a whole quarter of unpaid leave, nothing withheld) make no 281.10, as the
        # social secretariats do, and nothing is transferred to a 281.18 either
        employee = self._create_employee({})
        self.env['hr.leave'].sudo().create({
            'employee_id': employee.id,
            'request_date_from': date(2025, 1, 1),
            'request_date_to': date(2025, 3, 31),
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
        })
        with freeze_time('2025-04-15'):
            payslips = self.create_and_validate_payslips(employee, 2025, [1, 2, 3])
        self.assertFalse(self._total(payslips, list(payslips._get_gross_wage_line_codes()) + ['PPTOTAL', 'M.ONSS']))
        with freeze_time('2026-02-01'):
            declaration = self.env['l10n_be.281_xx'].create({'year': '2025', 'company_id': employee.company_id.id})
            declaration.l10n_be_281_10_ids.action_generate_declarations()
            sheet_281_18 = declaration.l10n_be_281_18_ids[:1]
            sheet_281_18.action_generate_declarations()
        self.assertNotIn(employee, declaration.l10n_be_281_10_ids.line_ids.employee_id)
        self.assertNotIn(employee, sheet_281_18.line_ids.employee_id)

    def test_contributions_transferred_to_the_281_18(self):
        # Without any remuneration on the 281.10, the special social security contribution and the personal
        # contributions to the group insurance are declared on the 281.18 the employee has (zones 2071 and 2068)
        employee = self._create_employee({})
        self.env['hr.leave'].sudo().create({
            'employee_id': employee.id,
            'request_date_from': date(2025, 1, 1),
            'request_date_to': date(2025, 3, 31),
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_unpaid_leave').id,
        })
        with freeze_time('2025-04-15'):
            payslips = self.create_and_validate_payslips(employee, 2025, [1, 2, 3])
        self.assertFalse(self._total(payslips, list(payslips._get_gross_wage_line_codes())))
        rules = {
            code: self.env['hr.salary.rule'].search([('code', '=', code)], limit=1) for code in ('M.ONSS', 'GI.EMP.CONT')
        }
        self.env['hr.payslip.line'].create([{
            'slip_id': payslips[-1].id,
            'salary_rule_id': rules[code].id,
            'name': rules[code].name,
            'code': code,
            'amount': amount,
            'quantity': 1,
            'rate': 100,
            'total': amount,
        } for code, amount in [('M.ONSS', -10), ('GI.EMP.CONT', 25)]])
        # sickness indemnities of the employer, declared on his 281.18
        replacement_rule = self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_replacement_revenue')
        self.env['hr.payslip.line'].create({
            'slip_id': payslips[-1].id,
            'salary_rule_id': replacement_rule.id,
            'name': replacement_rule.name,
            'code': replacement_rule.code,
            'amount': 100,
            'quantity': 1,
            'rate': 100,
            'total': 100,
        })
        with freeze_time('2026-02-01'):
            declaration = self.env['l10n_be.281_xx'].create({'year': '2025', 'company_id': employee.company_id.id})
            declaration.l10n_be_281_10_ids.action_generate_declarations()
            sheet_281_18 = declaration.l10n_be_281_18_ids[:1]
            sheet_281_18.action_generate_declarations()
            self.assertNotIn(employee, declaration.l10n_be_281_10_ids.line_ids.employee_id)
            self.assertIn(employee, sheet_281_18.line_ids.employee_id)
            values = sheet_281_18._get_rendering_data(employee)['employees_data'][0]
        self.assertAlmostEqual(values['f18_2071_bijzonderebijdrage'], 10, 2)
        self.assertAlmostEqual(values['f18_2068_gewonebijdragen'], 25, 2)
        self.assertAlmostEqual(values['f18_2064_ziekteofinvaliditeit'], 100, 2)
        self.assertAlmostEqual(values['f18_2059_totaalcontrole'], 135, 2)
        self.assertFalse(sheet_281_18._get_declaration_warnings())

    def test_employee_contribution_of_each_employee(self):
        # Zone 2257: the personal contributions to the group insurance of the employee, not the total of the company
        employees = self._create_employee({}) | self._create_employee({'name': 'Other Employee'})
        with freeze_time('2025-04-15'):
            payslips = self.create_and_validate_payslips(employees, 2025, [1])
        rule = self.env['hr.salary.rule'].search([('code', '=', 'GI.EMP.CONT')], limit=1)
        self.env['hr.payslip.line'].create([{
            'slip_id': payslip.id,
            'salary_rule_id': rule.id,
            'name': rule.name,
            'code': 'GI.EMP.CONT',
            'amount': amount,
            'quantity': 1,
            'rate': 100,
            'total': amount,
        } for payslip, amount in zip(payslips.sorted(lambda p: p.employee_id.id), (25, 40))])
        with freeze_time('2026-02-01'):
            declaration = self.env['l10n_be.281_xx'].create({'year': '2025', 'company_id': employees.company_id.id})
            sheet = declaration.l10n_be_281_10_ids[:1]
            sheet.action_generate_declarations()
            data = {
                values['employee']: values['f10_2257_employeecontribution']
                for values in sheet._get_rendering_data(employees)['employees_data']
            }
        self.assertEqual(data, {employees.sorted('id')[0]: 25, employees.sorted('id')[1]: 40})

    def test_withholding_tax(self):
        employee = self._create_employee({})
        payslips, values = self._get_281_10(employee)

        self.assertEqual(values['f10_2074_bedrijfsvoorheffing'], self._eurocent(self._total(payslips, ['PPTOTAL'])))
        self.assertEqual(values['f10_2131_bedrijfsvoorheffingvanwerkgever'], values['f10_2074_bedrijfsvoorheffing'])

    def test_presence_tokens_of_an_employee(self):
        # The presence tokens of an employee not flagged for the 281.30 are part of its remuneration (box 6a), with
        # their withholding taxes, on the 281.10 as on the 274.10
        employee = self._create_employee({})
        with freeze_time('2025-04-15'):
            payslips = self.env['hr.payslip'].create([{
                'name': f'Payslip {month}',
                'employee_id': employee.id,
                'company_id': employee.company_id.id,
                'version_id': employee.version_id.id,
                'date_from': date(2025, month, 1),
                'date_to': date(2025, month, 28),
            } for month in (1, 2, 3)])
            for payslip in payslips:
                payslip._set_input_value('PRESENCE_TOKEN', 500.0)
            payslips.compute_sheet()
            payslips.action_payslip_done()
        token_withholding = -self._total(payslips, ['PRESENCE_TOKEN_WITHHOLDING_TAX'])
        self.assertAlmostEqual(token_withholding, 3 * 500 * 0.2725, 2)
        _payslips, values = self._get_281_10(employee, payslips_months=())

        reference = self._create_employee({'name': 'Reference Employee'})
        _reference_payslips, reference_values = self._get_281_10(reference)
        self.assertEqual(
            values['f10_2060_gewonebezoldiginge'], reference_values['f10_2060_gewonebezoldiginge'] + self._eurocent(1500))
        self.assertEqual(values['f10_2131_bedrijfsvoorheffingvanwerkgever'], self._eurocent(self._total(payslips, ['PPTOTAL'])))
        self.assertEqual(values['f10_2074_bedrijfsvoorheffing'], values['f10_2131_bedrijfsvoorheffingvanwerkgever'])

        sheet_274 = self.env['l10n_be.274_xx'].with_company(employee.company_id).create({'year': 2025, 'month': '2'})
        line_274_10 = sheet_274.line_ids.filtered(lambda line: line.nature_code == '274.10' and line.employee_id == employee)
        february = payslips.filtered(lambda p: p.date_from.month == 2)
        self.assertAlmostEqual(sum(line_274_10.mapped('withholding_amount')), self._total(february, ['PPTOTAL']), 2)
        self.assertAlmostEqual(
            sum(line_274_10.mapped('taxable_amount')),
            self._total(february, ['GROSS']) + 500.0, 2)

    def test_voluntary_withholding_tax(self):
        # The withholding tax the employee asked to withhold on top of the legal one (fiscal voluntarism) is a
        # withholding tax as the other ones, declared with them on the 274.10 and the 281.10
        employee = self._create_employee({'fiscal_voluntarism_type': 'fixed', 'fiscal_voluntarism_amount': 100.0})
        payslips, values = self._get_281_10(employee)

        self.assertAlmostEqual(self._total(payslips, ['FISC_VOL']), -300, 2)
        withholding = self._total(payslips, ['PPTOTAL']) + 300
        self.assertEqual(values['f10_2131_bedrijfsvoorheffingvanwerkgever'], self._eurocent(withholding))
        self.assertEqual(values['f10_2074_bedrijfsvoorheffing'], self._eurocent(withholding))

        sheet_274 = self.env['l10n_be.274_xx'].with_company(employee.company_id).create({'year': 2025, 'month': '2'})
        line_274_10 = sheet_274.line_ids.filtered(lambda line: line.nature_code == '274.10' and line.employee_id == employee)
        self.assertAlmostEqual(sum(line_274_10.mapped('withholding_amount')), self._total(payslips.filtered(
            lambda p: p.date_from.month == 2), ['PPTOTAL']) + 100, 2)

    def test_double_holiday_withholding_tax(self):
        # The withholding taxes on the double holiday pay are declared with the other ones.
        employee = self._create_employee({'date_version': date(2024, 1, 1), 'contract_date_start': date(2024, 1, 1)})
        with freeze_time('2025-07-15'):
            double_holiday_payslips = self.create_and_validate_payslips(employee, 2025, [6], vals={
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
            })
        self.assertTrue(self._total(double_holiday_payslips, ['DH_PP']), "The double holiday pay should be taxed")
        payslips, values = self._get_281_10(employee)

        withholding = self._total(payslips | double_holiday_payslips, ['PPTOTAL'])
        self.assertEqual(values['f10_2074_bedrijfsvoorheffing'], self._eurocent(withholding))
        self.assertEqual(values['f10_2131_bedrijfsvoorheffingvanwerkgever'], self._eurocent(withholding))

    def test_european_leaves_deduction_declared_once(self):
        # The European leaves deduction belongs to the double holiday pay and to the holiday pay on departure: a
        # double holiday payslip counts it in its double holiday taxable salary only, so does the declaration.
        employee = self._create_employee({'date_version': date(2024, 1, 1), 'contract_date_start': date(2024, 1, 1)})
        with freeze_time('2025-07-15'):
            double_holiday_payslip = self.env['hr.payslip'].create({
                'name': 'Double Holiday Pay',
                'employee_id': employee.id,
                'version_id': employee.version_id.id,
                'company_id': employee.company_id.id,
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
                'date_from': date(2025, 6, 1),
                'date_to': date(2025, 6, 30),
            })
            double_holiday_payslip._set_input_value('EU_LEAVE_DEDUC', 600.0)
            double_holiday_payslip.compute_sheet()
            double_holiday_payslip.action_payslip_done()
        self.assertTrue(self._total(double_holiday_payslip, ['EU_LEAVE_DEDUC_ONSS']), "The European leaves should be deducted")
        payslips, values = self._get_281_10(employee)

        self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(self._total(
            payslips + double_holiday_payslip, list(payslips._get_gross_wage_line_codes()))))

        sheet_274 = self.env['l10n_be.274_xx'].with_company(employee.company_id).create({'year': 2025, 'month': '6'})
        line_274_10 = sheet_274.line_ids.filtered(lambda line: line.nature_code == '274.10' and line.employee_id == employee)
        self.assertAlmostEqual(sum(line_274_10.mapped('taxable_amount')), self._total(double_holiday_payslip, ['DH_GROSS']), 2)

    def _add_overtime(self, employee, days, work_entry_type_xmlid='hr_work_entry.be_work_entry_type_overtime', hour_from=17):
        return self.env['hr.leave'].sudo().create([{
            'employee_id': employee.id,
            'request_date_from': day,
            'request_date_to': day,
            'request_hour_from': hour_from,
            'request_hour_to': 21,
            'work_entry_type_id': self.env.ref(work_entry_type_xmlid).id,
        } for day in days])

    def test_overtime(self):
        # Box 18: the overtime counts for the limit of 180 hours (code 305), or of 360 hours (code 317) in the
        # hotel industry. Its base is declared with the 57.75% reduction in both cases (code 234).
        overtime_type = self.env.ref('hr_work_entry.be_work_entry_type_overtime')
        for joint_committee, worker_code, hours_tag in [
            ('l10n_be_joint_committee_200', 'l10n_be_worker_code_00495', 'f10_2142_totalovertimehours180'),
            ('l10n_be_joint_committee_302', 'l10n_be_worker_code_00015', 'f10_2110_aantaloveruren360'),
        ]:
            with self.subTest(joint_committee=joint_committee):
                employee = self._create_employee({
                    'l10n_be_joint_committee_id': self.env.ref(f'l10n_be_hr_payroll.{joint_committee}').id,
                    'l10n_be_worker_code_id': self.env.ref(f'l10n_be_hr_payroll.{worker_code}').id,
                })
                self._add_overtime(employee, [date(2025, 2, 4), date(2025, 2, 5)])
                payslips, values = self._get_281_10(employee)

                overtime = payslips.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == overtime_type)
                self.assertEqual(sum(overtime.mapped('number_of_hours')), 8)
                self.assertEqual(values[hours_tag], 800)
                self.assertEqual(values['f10_2110_aantaloveruren360'] + values['f10_2142_totalovertimehours180'], 800)
                self.assertEqual(values['f10_2118_overtimehours180'], values['f10_2142_totalovertimehours180'])
                self.assertEqual(values['f10_2097_aantaluren'], 800)
                self.assertEqual(values['f10_2068_rechtvermindering57_75'], self._eurocent(sum(
                    wd.amount / overtime_type.amount_rate for wd in overtime)))

    def test_overtime_hours_on_pdf(self):
        # The overtime hours and the kilometers are no amounts
        employee = self._create_employee({'bike_transport_employee_kilometer': 5})
        self._add_overtime(employee, [date(2025, 2, 4), date(2025, 2, 5)])
        self._get_281_10(employee)
        sheet = self.env['l10n_be.281_xx'].search([('year', '=', '2025')], order='id desc', limit=1).l10n_be_281_10_ids
        rendering_data = sheet._get_rendering_data(employee)
        pdf_values = sheet._post_process_rendering_data_pdf(rendering_data)[employee]

        self.assertEqual(pdf_values['f10_2142_totalovertimehours180'], '8.00 hours')
        self.assertEqual(pdf_values['f10_2097_aantaluren'], '8.00 hours')
        self.assertEqual(pdf_values['f10_2110_aantaloveruren360'], '0.00 hours')
        self.assertNotIn('€', pdf_values['f10_2226_kmzone2207'])
        self.assertIn('€', pdf_values['f10_2068_rechtvermindering57_75'])

    def test_overtime_other_joint_committee(self):
        # Box 18: the limit of 180 hours is the one of all the employers outside the hotel industry, the overtime of
        # the other joint committees is declared there, and its withholding tax exemption on the 274.44
        employee = self._create_employee({
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_100').id,
        })
        self._add_overtime(employee, [date(2025, 2, 4), date(2025, 2, 5)])
        payslips, values = self._get_281_10(employee)

        overtime_type = self.env.ref('hr_work_entry.be_work_entry_type_overtime')
        overtime = payslips.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == overtime_type)
        self.assertEqual(sum(overtime.mapped('number_of_hours')), 8)
        self.assertEqual(values['f10_2142_totalovertimehours180'], 800)
        self.assertEqual(values['f10_2097_aantaluren'], 800)
        self.assertEqual(values['f10_2068_rechtvermindering57_75'], self._eurocent(sum(
            wd.amount / overtime_type.amount_rate for wd in overtime)))

        sheet_274 = self.env['l10n_be.274_xx'].with_company(employee.company_id).create({'year': 2025, 'month': '2'})
        natures = sheet_274.line_274_extra_hours_ids.filtered(lambda line: line.employee_id == employee).mapped('nature_code')
        self.assertEqual(natures, ['274.44'])

    def test_overtime_base_without_premium_rate(self):
        # Box 18: the base is the normal hourly wage of the overtime hours, whatever the rate the hours are paid at.
        # The overtime to recover only pays its premium, at a rate that the databases installed before it was set
        # still have at 0.
        overtime_type = self.env.ref('hr_work_entry.l10n_be_work_entry_type_overtime_recoverable')
        overtime_type.amount_rate = 0.0
        employee = self._create_employee({})
        self._add_overtime(employee, [date(2025, 2, 4)], 'hr_work_entry.l10n_be_work_entry_type_overtime_recoverable')
        _payslips, values = self._get_281_10(employee)

        version = employee.version_id
        hourly_wage = version._get_contract_wage() * 3 / (13 * version.resource_calendar_id.hours_per_week)
        self.assertEqual(values['f10_2097_aantaluren'], 400)
        self.assertEqual(values['f10_2068_rechtvermindering57_75'], self._eurocent(4 * hourly_wage))

        sheet_274 = self.env['l10n_be.274_xx'].with_company(employee.company_id).create({'year': 2025, 'month': '2'})
        line_274_44 = sheet_274.line_274_extra_hours_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_44.taxable_amount, 4 * hourly_wage, 2)

    def test_part_time_additional_hours_overtime(self):
        # Box 18: a part-timer's additional hours paid with a premium of 50 % (003.12) are overtime giving right to
        # the tax relief, as for the 274.44 exemption
        employee = self._create_employee({'resource_calendar_id': self.resource_calendar_mid_time.id})
        additional_hours_type = self.env.ref('hr_work_entry.be_work_entry_type_additional_hours_50')
        self.env['hr.leave'].sudo().create({
            'employee_id': employee.id,
            'request_date_from': date(2025, 2, 4),
            'request_date_to': date(2025, 2, 4),
            'request_hour_from': 17,
            'request_hour_to': 18,
            'work_entry_type_id': additional_hours_type.id,
        })
        payslips, values = self._get_281_10(employee)

        additional_hours = payslips.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == additional_hours_type)
        self.assertEqual(sum(additional_hours.mapped('number_of_hours')), 1)
        self.assertEqual(values['f10_2142_totalovertimehours180'], 100)
        self.assertEqual(values['f10_2068_rechtvermindering57_75'], self._eurocent(sum(
            wd.amount / additional_hours_type.amount_rate for wd in additional_hours)))

    def test_copied_overtime_work_entry_type(self):
        # Box 18: the overtime is recognized by the category of its work entry type, a copy of the overtime work
        # entry type with another code is overtime too
        employee = self._create_employee({})
        overtime_type = self.env.ref('hr_work_entry.be_work_entry_type_overtime').copy({'code': 'OVERTIME_COPY'})
        self.env['hr.leave'].sudo().create({
            'employee_id': employee.id,
            'request_date_from': date(2025, 2, 4),
            'request_date_to': date(2025, 2, 4),
            'request_hour_from': 17,
            'request_hour_to': 18,
            'work_entry_type_id': overtime_type.id,
        })
        payslips, values = self._get_281_10(employee)

        overtime = payslips.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == overtime_type)
        self.assertEqual(sum(overtime.mapped('number_of_hours')), 1)
        self.assertEqual(values['f10_2142_totalovertimehours180'], 100)
        self.assertEqual(values['f10_2068_rechtvermindering57_75'], self._eurocent(sum(
            wd.amount / overtime_type.amount_rate for wd in overtime)))

    def test_overtime_paid_without_premium(self):
        # Box 18, 274.44 and the reduction of the payslip: the overtime paid at 100% (a copy of the overtime work
        # entry type at the rate 1.0, without premium) gives right to nothing and consumes no cap: only the overtime
        # paid with its premium is declared
        employee = self._create_employee({})
        plain_type = self.env.ref('hr_work_entry.be_work_entry_type_overtime').copy({
            'code': 'OVERTIME_100', 'amount_rate': 1.0})
        self._add_overtime(employee, [date(2025, 2, 4)], hour_from=19)
        self.env['hr.leave'].sudo().create({
            'employee_id': employee.id,
            'request_date_from': date(2025, 2, 5),
            'request_date_to': date(2025, 2, 5),
            'request_hour_from': 17,
            'request_hour_to': 20,
            'work_entry_type_id': plain_type.id,
        })
        self.assertFalse(self.env['hr.payslip']._is_extra_hours_qualifying(plain_type))
        payslips, values = self._get_281_10(employee)

        overtime_type = self.env.ref('hr_work_entry.be_work_entry_type_overtime')
        overtime = payslips.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == overtime_type)
        plain = payslips.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == plain_type)
        self.assertEqual(sum(overtime.mapped('number_of_hours')), 2)
        self.assertEqual(sum(plain.mapped('number_of_hours')), 3)
        self.assertEqual(values['f10_2142_totalovertimehours180'], 200)
        self.assertEqual(values['f10_2097_aantaluren'], 200)
        self.assertEqual(values['f10_2068_rechtvermindering57_75'], self._eurocent(sum(
            wd.amount / overtime_type.amount_rate for wd in overtime)))

        sheet_274 = self.env['l10n_be.274_xx'].with_company(employee.company_id).create({'year': 2025, 'month': '2'})
        line_274_44 = sheet_274.line_274_extra_hours_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_44.taxable_amount, sum(wd.amount / 1.5 for wd in overtime), 2)
        self.assertEqual(payslips._l10n_be_get_overtime_hours_consumed(employee.company_id, date(2025, 3, 1))[
            employee, '200'], 2)

    def test_overtime_premium_rate(self):
        # Box 18: the overtime with a premium from 20% to 50% is declared with the reduction of 66.81% (codes 233),
        # as the payslip reduces its withholding tax
        employee = self._create_employee({})
        overtime_type = self.env['hr.work.entry.type'].create({
            'name': 'Overtime 125%',
            'code': 'OVERTIME125',
            'amount_rate': 1.25,
            'requires_allocation': False,
            'request_unit': 'hour',
            'category_ids': [(6, 0, [
                self.env.ref('hr_payroll.EXTRA_HOURS').id,
                self.env.ref('l10n_be_hr_payroll.REMUNERATION_BASE').id,
                self.env.ref('l10n_be_hr_payroll.ONSS_BASE').id,
                self.env.ref('l10n_be_hr_payroll.WITHHOLDING_BASE').id,
                self.env.ref('l10n_be_hr_payroll.OVERTIME_TAX_RELIEF').id,
            ])],
        })
        self.env['hr.leave'].sudo().create({
            'employee_id': employee.id,
            'request_date_from': date(2025, 2, 4),
            'request_date_to': date(2025, 2, 4),
            'request_hour_from': 17,
            'request_hour_to': 19,
            'work_entry_type_id': overtime_type.id,
        })
        self._add_overtime(employee, [date(2025, 2, 5)])
        payslips, values = self._get_281_10(employee)

        overtime = payslips.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == overtime_type)
        self.assertEqual(sum(overtime.mapped('number_of_hours')), 2)
        self.assertEqual(values['f10_2095_aantaluren'], 200)
        self.assertEqual(values['f10_2067_rechtvermindering66_81'], self._eurocent(sum(
            wd.amount / overtime_type.amount_rate for wd in overtime)))
        self.assertEqual(values['f10_2097_aantaluren'], 400)
        self.assertTrue(values['f10_2068_rechtvermindering57_75'])
        self.assertEqual(values['f10_2142_totalovertimehours180'], 600)

    def test_overtime_of_the_fiscal_year(self):
        # The overtime of a December payslip paid in January is declared with its remuneration, the next year
        employee = self._create_employee({'date_version': date(2024, 12, 1), 'contract_date_start': date(2024, 12, 1)})
        self._add_overtime(employee, [date(2024, 12, 3)])
        with freeze_time('2025-01-15'):
            december_payslip = self.create_and_validate_payslips(employee, 2024, [12])
        december_payslip.l10n_be_fiscal_date = date(2025, 1, 10)
        payslips, values = self._get_281_10(employee, payslips_months=[1])

        self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(self._total(
            payslips + december_payslip, list(payslips._get_gross_wage_line_codes()))))
        self.assertEqual(values['f10_2142_totalovertimehours180'], 400)
        self.assertTrue(values['f10_2068_rechtvermindering57_75'])

    def test_overtime_declared_once(self):
        # The overtime of a December payslip paid in January is declared with its remuneration the next year only,
        # not also on the declaration of its pay period
        employee = self._create_employee({
            'date_version': date(2024, 12, 1),
            'contract_date_start': date(2024, 12, 1),
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id,
        })
        self._add_overtime(employee, [date(2024, 12, 3)])
        self._add_overtime(employee, [date(2024, 12, 4)], 'hr_work_entry.l10n_be_work_entry_type_overtime_no_onss')
        with freeze_time('2025-01-15'):
            december_payslip = self.create_and_validate_payslips(employee, 2024, [12])
        december_payslip.l10n_be_fiscal_date = date(2025, 1, 10)
        _payslips, values = self._get_281_10(employee, payslips_months=[1])
        with freeze_time('2025-02-01'):
            declaration = self.env['l10n_be.281_xx'].create({'year': '2024', 'company_id': employee.company_id.id})
            sheet = declaration.l10n_be_281_10_ids[:1]
            sheet.action_generate_declarations()
            values_2024 = sheet.with_context(round_281=True)._get_rendering_data(employee)['employees_data'][0]

        self.assertEqual(values['f10_2110_aantaloveruren360'], 400)
        self.assertEqual(values['f10_2167_aantaloveruren300horeca'], 400)
        self.assertTrue(values['f10_2061_bedragoveruren300horeca'])
        for tag in ('f10_2110_aantaloveruren360', 'f10_2068_rechtvermindering57_75', 'f10_2167_aantaloveruren300horeca',
                    'f10_2061_bedragoveruren300horeca'):
            self.assertEqual(values_2024[tag], 0, tag)

    def test_overtime_joint_committee_of_the_payslip(self):
        # The overtime is declared under the joint committee of the payslip, also on the 274, when the employee
        # changes of joint committee afterwards
        employee = self._create_employee({
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00495').id,
        })
        self._add_overtime(employee, [date(2025, 2, 4), date(2025, 2, 5)])
        _payslips, values = self._get_281_10(employee)
        employee.create_version({
            'date_version': date(2025, 6, 1),
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
        })
        self.assertEqual(employee.l10n_be_joint_committee_id.egov3_code, '302')
        self.assertEqual(values['f10_2142_totalovertimehours180'], 800)

        sheet_274 = self.env['l10n_be.274_xx'].with_company(employee.company_id).create({'year': 2025, 'month': '2'})
        natures = sheet_274.line_274_extra_hours_ids.filtered(lambda line: line.employee_id == employee).mapped('nature_code')
        self.assertEqual(natures, ['274.44'])

    def test_hotel_industry_net_overtime(self):
        # Box 17: the overtime of the hotel industry paid net is declared with its hours, within the limit of 360
        # hours with a registered cash system, of 300 hours without one. It is neither a remuneration nor an
        # overtime giving right to the tax reduction of box 18.
        net_overtime_xmlid = 'hr_work_entry.l10n_be_work_entry_type_overtime_no_onss'
        net_overtime_type = self.env.ref(net_overtime_xmlid)
        # The registered cash system is set in the payroll settings, or with the deprecated white cash register
        for cash_register_field, amount_tag, hours_tag, other_tag in [
            (False, 'f10_2061_bedragoveruren300horeca', 'f10_2167_aantaloveruren300horeca', 'f10_2143_bedragoveruren360horeca'),
            ('l10n_be_cash_register_active', 'f10_2143_bedragoveruren360horeca', 'f10_2169_aantaloveruren360horeca', 'f10_2061_bedragoveruren300horeca'),
            ('l10n_be_has_white_cash_register', 'f10_2143_bedragoveruren360horeca', 'f10_2169_aantaloveruren360horeca', 'f10_2061_bedragoveruren300horeca'),
        ]:
            with self.subTest(cash_register_field=cash_register_field):
                self.belgian_company.write({'l10n_be_cash_register_active': False, 'l10n_be_has_white_cash_register': False})
                if cash_register_field:
                    self.belgian_company[cash_register_field] = True
                employee = self._create_employee({
                    'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
                    'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id,
                })
                self._add_overtime(employee, [date(2025, 2, 4), date(2025, 2, 5)], net_overtime_xmlid)
                payslips, values = self._get_281_10(employee)

                overtime = payslips.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == net_overtime_type)
                self.assertTrue(sum(overtime.mapped('amount')), "The net overtime should be paid")
                self.assertEqual(values[amount_tag], self._eurocent(sum(overtime.mapped('amount'))))
                self.assertEqual(values[hours_tag], 800)
                self.assertEqual(values[other_tag], 0)
                self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(self._total(
                    payslips, list(payslips._get_gross_wage_line_codes()))))
                self.assertEqual(values['f10_2110_aantaloveruren360'], 0)

    def test_hotel_industry_net_overtime_of_a_branch(self):
        # Box 17: the limit of 360 hours depends on the registered cash system of the company the employee works for,
        # a branch of the declaring company
        root, branch = self.create_multibranch_company(2)
        self.env.user.company_ids |= root | branch
        root.write({'l10n_be_cash_register_active': False, 'l10n_be_has_white_cash_register': False})
        branch.l10n_be_cash_register_active = True
        net_overtime_xmlid = 'hr_work_entry.l10n_be_work_entry_type_overtime_no_onss'
        employee = self._create_employee({
            'company_id': branch.id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id,
        })
        self._add_overtime(employee, [date(2025, 2, 4), date(2025, 2, 5)], net_overtime_xmlid)
        with freeze_time('2025-04-15'):
            payslips = self.create_and_validate_payslips(employee, 2025, [1, 2, 3])
        with freeze_time('2026-02-01'):
            declaration = self.env['l10n_be.281_xx'].with_company(root).create({'year': '2025', 'company_id': root.id})
            sheet = declaration.l10n_be_281_10_ids[:1]
            sheet.action_generate_declarations()
            values = sheet.with_context(round_281=True)._get_rendering_data(employee)['employees_data'][0]

        overtime = payslips.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == self.env.ref(net_overtime_xmlid))
        self.assertTrue(sum(overtime.mapped('amount')))
        self.assertEqual(values['f10_2169_aantaloveruren360horeca'], 800)
        self.assertEqual(values['f10_2143_bedragoveruren360horeca'], self._eurocent(sum(overtime.mapped('amount'))))
        self.assertEqual(values['f10_2167_aantaloveruren300horeca'], 0)

    def _get_net_overtime_days(self, count):
        days = []
        day = date(2025, 1, 6)
        while len(days) < count:
            if day.weekday() < 5:
                days.append(day)
            day += timedelta(days=1)
        return days

    def test_hotel_industry_net_overtime_limit(self):
        # Box 17: only the net overtime within the yearly limit (300 hours without a registered cash system) enters
        # into account for the exemption, the excess is remuneration (box 6a)
        self.belgian_company.write({'l10n_be_cash_register_active': False, 'l10n_be_has_white_cash_register': False})
        net_overtime_xmlid = 'hr_work_entry.l10n_be_work_entry_type_overtime_no_onss'
        employee = self._create_employee({
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id,
        })
        # 20 days of 16 hours, 320 hours, validated before the limit was checked
        with patch.object(self.registry['hr.leave'], '_l10n_be_check_horeca_net_overtime_threshold', return_value=None):
            self._add_overtime(employee, self._get_net_overtime_days(20), net_overtime_xmlid, hour_from=5)
        payslips, values = self._get_281_10(employee)

        overtime = payslips.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == self.env.ref(net_overtime_xmlid))
        hours = sum(overtime.mapped('number_of_hours'))
        amount = sum(overtime.mapped('amount'))
        self.assertAlmostEqual(hours, 320, 2)
        self.assertEqual(values['f10_2167_aantaloveruren300horeca'], 30000)
        self.assertAlmostEqual(values['f10_2061_bedragoveruren300horeca'], self._eurocent(amount * 300 / 320), delta=1)
        self.assertAlmostEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(self._total(
            payslips, list(payslips._get_gross_wage_line_codes())) + amount * 20 / 320), delta=1)

    def test_hotel_industry_net_overtime_limit_on_validation(self):
        # The net overtime can't exceed the yearly limit of the hotel industry
        self.belgian_company.write({'l10n_be_cash_register_active': False, 'l10n_be_has_white_cash_register': False})
        net_overtime_xmlid = 'hr_work_entry.l10n_be_work_entry_type_overtime_no_onss'
        employee = self._create_employee({
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015').id,
        })
        days = self._get_net_overtime_days(19)
        leaves = self._add_overtime(employee, days[:18], net_overtime_xmlid, hour_from=5)
        self.assertEqual(set(leaves.mapped('state')), {'validate'})
        with self.assertRaises(ValidationError):
            self._add_overtime(employee, days[18:], net_overtime_xmlid, hour_from=5)

    def test_hotel_industry_occasional_worker_holiday_pay(self):
        # Box 10a: the pay of the days of a Horeca occasional worker taxed at the flat rate, with the holiday pay for
        # these days: the early holiday pay is split prorata the pay of these days and the other pay
        employee = self._create_employee({
            'contract_date_end': date(2025, 3, 31),
            'l10n_be_dimona_category': 'ext',
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00495').id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
        })
        employee.company_id._get_payroll_config(date(2025, 1, 1)).l10n_be_employer_category_id = self.env.ref(
            'l10n_be_hr_payroll.l10n_be_employer_category_00317')
        with freeze_time('2025-04-15'):
            monthly_payslips = self.create_and_validate_payslips(employee, 2025, [1, 2, 3])
            employee.departure_date = date(2025, 3, 31)
            holiday_payslip = self.env['hr.payslip'].create({
                'name': 'Holiday pay on departure',
                'employee_id': employee.id,
                'version_id': employee.version_id.id,
                'company_id': employee.company_id.id,
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays').id,
                'date_from': date(2025, 3, 1),
                'date_to': date(2025, 3, 31),
            })
            # the gross reference remuneration of the year, as the departure wizard computes it
            holiday_payslip._set_input_value('GROSS_REF', 3000)
            holiday_payslip.compute_sheet()
            holiday_payslip.action_payslip_done()
        occasional_pay = self._total(monthly_payslips, ['HORECA_OCC_TAXABLE'])
        monthly_pay = self._total(monthly_payslips, ['GROSS'])
        holiday_pay = self._total(holiday_payslip, ['HOLIDAY_TERM_GROSS'])
        self.assertTrue(occasional_pay)
        self.assertTrue(monthly_pay, "Beyond the 50 days, the pay follows the scale")
        self.assertTrue(holiday_pay)
        _payslips, values = self._get_281_10(employee, payslips_months=[])
        share = holiday_pay * occasional_pay / (occasional_pay + monthly_pay)
        self.assertAlmostEqual(values['f10_2132_horeca'], self._eurocent(occasional_pay + share), delta=1)
        self.assertAlmostEqual(values['f10_2063_vervroegdvakantieg'], self._eurocent(holiday_pay - share), delta=1)

    def _create_profit_sharing_payslip(self, employee, amount):
        with freeze_time('2025-04-15'):
            payslip = self.env['hr.payslip'].create({
                'name': 'Profit Sharing Bonus',
                'employee_id': employee.id,
                'version_id': employee.version_id.id,
                'company_id': employee.company_id.id,
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_profit_sharing_bonus').id,
                'date_from': date(2025, 3, 1),
                'date_to': date(2025, 3, 31),
            })
            payslip._set_input_value('PROFITSHARINGLOW', amount)
            payslip.compute_sheet()
            payslip.action_payslip_done()
            payslip.action_payslip_paid()
        return payslip

    def test_profit_sharing_bonus_withholding_tax(self):
        # The tax on the profit sharing bonus is a withholding tax on movable income, declared on the 273S: it is
        # neither declared on the 274.10 nor on the 281.10.
        employee = self._create_employee({})
        bonus_payslip = self._create_profit_sharing_payslip(employee, 1000.0)
        self.assertTrue(self._total(bonus_payslip, ['PROFITSHARINGLOW.PP']), "The profit sharing bonus should be taxed")
        payslips, values = self._get_281_10(employee)

        withholding = self._total(payslips, ['PPTOTAL'])
        self.assertEqual(values['f10_2074_bedrijfsvoorheffing'], self._eurocent(withholding))
        self.assertEqual(values['f10_2131_bedrijfsvoorheffingvanwerkgever'], self._eurocent(withholding))

        # Box 26e: the net profit sharing bonus
        self.assertEqual(values['f10_2177_winstpremies'], self._eurocent(self._total(bonus_payslip, ['NET'])))
        self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(self._total(
            payslips, list(payslips._get_gross_wage_line_codes()))), "The profit sharing bonus is not a remuneration")

        sheet_274 = self.env['l10n_be.274_xx'].with_company(employee.company_id).create({'year': 2025, 'month': '3'})
        line_274_10 = sheet_274.line_ids.filtered(lambda line: line.nature_code == '274.10' and line.employee_id == employee)
        self.assertAlmostEqual(sum(line_274_10.mapped('withholding_amount')), self._total(payslips.filtered(
            lambda p: p.date_from.month == 3), ['PPTOTAL']), 2)

    def test_non_recurring_benefits_of_2024(self):
        # The non recurring benefits of 2024, paid on time or as arrears, are exempt up to the limit of 2024
        employee = self._create_employee({'date_version': date(2024, 1, 1), 'contract_date_start': date(2024, 1, 1)})
        with freeze_time('2024-07-15'):
            bonus_payslip = self.env['hr.payslip'].create({
                'name': 'CCT90',
                'employee_id': employee.id,
                'version_id': employee.version_id.id,
                'company_id': employee.company_id.id,
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_cct90').id,
                'date_from': date(2024, 7, 1),
                'date_to': date(2024, 7, 31),
            })
            bonus_payslip._set_input_value('CCT90BONUSPLAN', 5000)
            bonus_payslip.compute_sheet()
        self.assertAlmostEqual(self._total(bonus_payslip, ['PP_EXEMP']), -3496, 2)

    def test_student_remuneration(self):
        # Box 26h: the whole remuneration of the student contracts, taxable or not, the commuting reimbursements
        # included
        employee = self._create_employee({'l10n_be_dimona_category': 'stu', 'bike_transport_employee_kilometer': 5})
        # The bonuses are part of it, their exempt part included
        with freeze_time('2025-04-15'):
            bonus_payslip = self.env['hr.payslip'].create({
                'name': 'CCT90',
                'employee_id': employee.id,
                'version_id': employee.version_id.id,
                'company_id': employee.company_id.id,
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_cct90').id,
                'date_from': date(2025, 3, 1),
                'date_to': date(2025, 3, 31),
            })
            bonus_payslip._set_input_value('CCT90BONUSPLAN', 500)
            bonus_payslip.compute_sheet()
            bonus_payslip.action_payslip_done()
        self.assertTrue(self._total(bonus_payslip, ['BONUS_GROSS']), "The bonus should be taxable")
        payslips, values = self._get_281_10(employee)

        # The gross wage line of the bonus is the taxable bonus before its withholding tax exemption
        gross = self._total(payslips + bonus_payslip, list(payslips._get_gross_wage_line_codes()))
        cycle = self._total(payslips, ['CYCLE'])
        self.assertTrue(cycle, "The bike reimbursement should be paid")
        self.assertEqual(values['f10_2136_amountcontractofstudent'], self._eurocent(gross + cycle))
        # The commuting reimbursements of the box 26h are the ones of the boxes 14a and 14d
        self.assertAlmostEqual(
            values['f10_2136_amountcontractofstudent'] - self._eurocent(gross),
            values['f10_2086_openbaargemeenschap'] + values['f10_2207_travelbicycleorspeedpedelec'], delta=1)

    def test_student_withholding_tax(self):
        # The withholding tax withheld on a student's bonus is declared (code 286) and on the 274.10
        employee = self._create_employee({'l10n_be_dimona_category': 'stu'})
        with freeze_time('2025-04-15'):
            bonus_payslip = self.env['hr.payslip'].create({
                'name': 'CCT90',
                'employee_id': employee.id,
                'version_id': employee.version_id.id,
                'company_id': employee.company_id.id,
                'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_cct90').id,
                'date_from': date(2025, 3, 1),
                'date_to': date(2025, 3, 31),
            })
            bonus_payslip._set_input_value('CCT90BONUSPLAN', 6000)
            bonus_payslip.compute_sheet()
            bonus_payslip.action_payslip_done()
        # The withholding taxes are in the categories of their 274 nature, children of PP
        withholding = -sum(bonus_payslip.line_ids.filtered(
            lambda line: 'PP' in (line.salary_rule_id.category_ids | line.salary_rule_id.category_ids.parent_id).mapped('code')
        ).mapped('total'))
        self.assertTrue(withholding, "The bonus above the exempt limit should be taxed")
        self.assertAlmostEqual(self._total(bonus_payslip, ['PPTOTAL']), withholding, 2)
        payslips, values = self._get_281_10(employee)
        self.assertEqual(values['f10_2074_bedrijfsvoorheffing'], self._eurocent(self._total(payslips + bonus_payslip, ['PPTOTAL'])))

        sheet_274 = self.env['l10n_be.274_xx'].with_company(employee.company_id).create({'year': 2025, 'month': '3'})
        line_274_10 = sheet_274.line_ids.filtered(lambda line: line.nature_code == '274.10' and line.employee_id == employee)
        self.assertAlmostEqual(sum(line_274_10.mapped('withholding_amount')), self._total(
            payslips.filtered(lambda p: p.date_from.month == 3) + bonus_payslip, ['PPTOTAL']), 2)

    def test_bike_kilometers(self):
        # Box 14d: the kilometers of the bike reimbursement, the ones of the bike part of the commute only
        employee = self._create_employee({'bike_transport_employee_kilometer': 5, 'distance_home_work': 20})
        payslips, values = self._get_281_10(employee)

        cycle_days = sum(payslips.line_ids.filtered(lambda line: line.code == 'CYCLE').mapped('quantity'))
        self.assertTrue(cycle_days, "The bike reimbursement should be paid")
        self.assertEqual(employee.version_id.km_home_work, 20)
        self.assertEqual(values['f10_2226_kmzone2207'], round(cycle_days * 5 * 2))

    def test_flexi_job_exemption_cap_of_the_income_year(self):
        # The yearly cap of the flexi-job exemption is the one of the year the remuneration is paid in (fiscal date),
        # as declared on the 281.10: a payslip attached to the next year doesn't consume the cap of its pay period
        employee = self._create_employee({
            'l10n_be_dimona_category': 'flx',
            'contract_date_end': date(2025, 3, 31),
            'l10n_be_flexi_monthly_wage': 1000.0,
        })
        cap = self.env['hr.rule.parameter']._get_parameter_from_code('flexi_cap_std', date(2025, 1, 31))
        with freeze_time('2025-04-15'):
            january_payslip = self.create_and_validate_payslips(employee, 2025, [1])
            # paid late, after the declaration of its period: attached to the next year, it nearly reached the cap
            january_payslip.l10n_be_fiscal_date = date(2026, 1, 10)
            january_payslip.line_ids.filtered(lambda line: line.code == 'FLEXI_EXEMPTION').total = -(cap - 100)
            february_payslip = self.create_and_validate_payslips(employee, 2025, [2])
        self.assertGreater(-self._total(february_payslip, ['FLEXI_EXEMPTION']), 100)

    def test_flexi_job_exemption_pensioner(self):
        # Box 26d (2166) and 20 (2198): the exempt flexi-job remuneration, split between the legal pensioners and
        # the other workers. The early retirement status (career shorter than 45 years) is not a pension.
        flexi_values = {
            'l10n_be_dimona_category': 'flx',
            'contract_date_end': date(2025, 3, 31),
            'l10n_be_flexi_monthly_wage': 1000.0,
        }
        for version_values, pensioner in [
            ({'l10n_be_is_retired': True}, True),
            ({'l10n_be_early_retirement_status': True}, False),
        ]:
            with self.subTest(pensioner=pensioner):
                employee = self._create_employee({**flexi_values, **version_values})
                payslips, values = self._get_281_10(employee)

                exemption = -self._total(payslips, ['FLEXI_EXEMPTION'])
                self.assertTrue(exemption, "The flexi-job remuneration should be exempt")
                self.assertEqual(values['f10_2166_flexi_job'], self._eurocent(exemption) if pensioner else 0)
                self.assertEqual(values['f10_2198_flexijobnotpension'], 0 if pensioner else self._eurocent(exemption))

    def test_entry_date_only_during_the_year(self):
        new_employee = self._create_employee({})
        _payslips, values = self._get_281_10(new_employee)
        self.assertEqual(values['f10_2055_datumvanindienstt'], '01-01-2025')
        self.assertEqual(values['f10_2056_datumvanvertrek'], '')

        former_employee = self._create_employee({'date_version': date(2024, 3, 1), 'contract_date_start': date(2024, 3, 1)})
        _payslips, values = self._get_281_10(former_employee)
        self.assertEqual(values['f10_2055_datumvanindienstt'], '')

    def test_legal_names(self):
        employee = self._create_employee({'name': 'Johnny Doe'})
        employee.write({'l10n_be_legal_first_name': 'Jean Pierre', 'l10n_be_legal_last_name': 'Van den Berg'})
        _payslips, values = self._get_281_10(employee)

        self.assertEqual(values['f2013_naam'], 'Van den Berg')
        self.assertEqual(values['f2114_voornamen'], 'Jean Pierre')

    def test_language_code(self):
        for lang in ('nl_BE', 'fr_FR'):
            self.env['res.lang']._activate_lang(lang)
        employee = self._create_employee({})
        self._get_281_10(employee, payslips_months=[1])
        sheet = self.env['l10n_be.281_xx'].search([('year', '=', '2025')], order='id desc', limit=1).l10n_be_281_10_ids
        for lang, code in (('fr_BE', 2), ('nl_BE', 1), ('fr_FR', 2), ('en_US', 0)):
            with self.subTest(lang=lang):
                employee.lang = lang
                values = sheet._get_rendering_data(employee)['employees_data'][0]
                self.assertEqual(values['f2027_taalcode'], code)

    def test_xml_valid_against_belcotax_schema(self):
        employee = self._create_employee({'internet': 38.0, 'private_car_employee_kilometer': 25}, car_atn=2400.0)
        with freeze_time('2025-04-15'):
            self.create_and_validate_payslips(employee, 2025, [1, 2, 3])
        with freeze_time('2026-02-01'):
            declaration = self.env['l10n_be.281_xx'].create({
                'year': '2025',
                'company_id': employee.company_id.id,
            })
            declaration.l10n_be_281_10_ids.action_generate_declarations()
            declaration.action_generate_xml()
        self.assertEqual(declaration.state, 'ready', declaration.error_message)
