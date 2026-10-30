# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from freezegun import freeze_time

from odoo.tests import tagged

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
                employee.version_id.write({'transport_mode_car': True, 'car_id': car.id})
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

    def test_private_car_reimbursement_declared_in_box_14(self):
        employee = self._create_employee({'private_car_employee_kilometer': 25})
        payslips, values = self._get_281_10(employee)

        gross = self._total(payslips, list(payslips._get_gross_wage_line_codes()))
        car_priv = self._total(payslips, ['CAR.PRIV'])
        self.assertTrue(car_priv, "The private car reimbursement should be paid")

        self.assertEqual(values['f10_2088_andervervoermiddel'], self._eurocent(car_priv))
        self.assertEqual(values['f10_2060_gewonebezoldiginge'], self._eurocent(gross - car_priv),
            "The reimbursement is part of the taxable salary of the payslip but is declared in box 14")

    def test_withholding_tax(self):
        employee = self._create_employee({})
        payslips, values = self._get_281_10(employee)

        self.assertEqual(values['f10_2074_bedrijfsvoorheffing'], self._eurocent(self._total(payslips, ['PPTOTAL'])))
        self.assertEqual(values['f10_2131_bedrijfsvoorheffingvanwerkgever'], values['f10_2074_bedrijfsvoorheffing'])

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

    def _add_overtime(self, employee, days, work_entry_type_xmlid='hr_work_entry.be_work_entry_type_overtime'):
        self.env['hr.leave'].sudo().create([{
            'employee_id': employee.id,
            'request_date_from': day,
            'request_date_to': day,
            'request_hour_from': 17,
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

    def test_part_time_additional_hours_overtime(self):
        # Box 18: a part-timer's additional hours paid with a premium of 50 % (003.12) are overtime, as for the
        # 274.44 exemption
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

    def test_student_remuneration(self):
        # Box 26h: the whole remuneration of the student contracts, taxable or not, the commuting reimbursements
        # included
        employee = self._create_employee({'l10n_be_dimona_category': 'stu', 'bike_transport_employee_kilometer': 5})
        payslips, values = self._get_281_10(employee)

        gross = self._total(payslips, list(payslips._get_gross_wage_line_codes()))
        cycle = self._total(payslips, ['CYCLE'])
        self.assertTrue(cycle, "The bike reimbursement should be paid")
        self.assertEqual(values['f10_2136_amountcontractofstudent'], self._eurocent(gross + cycle))
        # The commuting reimbursements of the box 26h are the ones of the boxes 14a and 14d
        self.assertAlmostEqual(
            values['f10_2136_amountcontractofstudent'] - self._eurocent(gross),
            values['f10_2086_openbaargemeenschap'] + values['f10_2207_travelbicycleorspeedpedelec'], delta=1)

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
