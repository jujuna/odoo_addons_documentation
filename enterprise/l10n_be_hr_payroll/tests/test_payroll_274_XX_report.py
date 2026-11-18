
import io
from collections import defaultdict
from datetime import date
from unittest.mock import patch

from dateutil.relativedelta import MO, relativedelta

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import Form, tagged

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'payroll_274_XX_report')
class TestPayroll274XXReport(TestPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee_a, cls.employee_b = cls.create_employee([
            {
                "name": "Employee A (Senior)",
                "company_id": cls.belgian_company.id,
                "contract_date_start": date(2022, 1, 1),
            },
            {
                "name": "Employee B (Recent)",
                "company_id": cls.belgian_company.id,
                "contract_date_start": date(2023, 4, 1),
            },
        ])
        cls.employee_a_payslip, cls.employee_b_payslip = cls.create_and_validate_payslips(
            employees=[cls.employee_a, cls.employee_b],
            year=2023,
            months=[6],
            vals={},
        )

        cls.sheet = (
            cls
            .env["l10n_be.274_xx"]
            .with_company(cls.belgian_company)
            .create([
                {
                    "year": 2023,
                    "month": 6,
                },
            ])
        )

    def test_274_56_sme_exemption(self):
        self.belgian_company._get_payroll_config(date(2023, 6, 1)).l10n_be_ipa_reduction = True
        payslips = self.employee_a_payslip | self.employee_b_payslip
        category_codes = self.env['hr.payslip']._get_child_category_ids('IPA_REDUCTION_BASE')
        # the gross amounts: without the ONSS of the employee and the employment bonus, a reduction of it
        ipa_lines = payslips.line_ids.filtered(
            lambda line: set(line.salary_rule_id.category_ids.mapped('code')) & set(category_codes)
            and not {'ONSS', 'ONSS_BASE'} & set(line.salary_rule_id.category_ids.mapped('code'))
            and line.code != 'EmpBonus.1.FALLBACK')
        self.assertTrue(ipa_lines)
        self.assertTrue(payslips.line_ids.filtered(lambda line: line.code == 'ONSS_BONUS' and line.total))

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2023, 'month': '6'})
        self.assertAlmostEqual(sheet.sme_taxable_amount, sum(ipa_lines.mapped('total')), places=2)
        self.assertEqual(sheet.line_274_56_ids.employee_id, self.employee_a | self.employee_b)
        self.assertAlmostEqual(sheet.sme_exempted_amount, round(sheet.sme_taxable_amount * sheet.sme_exemption_rate, 2), places=2)

    def test_274_56_base_with_private_car_allowance(self):
        """ The base of the 0.12 % exemption holds the taxable part of the private car commuting allowance, above its
        withholding tax exemption: the exempted part is paid net. A flexi-job, whose pay is exempted from the tax, is
        in the base for that taxable part only. """
        employee = self.create_employee([{
            'name': 'Private Car Commuter',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2026, 1, 1),
            'contract_date_end': date(2026, 1, 31),
            'private_car_employee_kilometer': 25,
        }])
        payslip = self.create_and_validate_payslips(employees=[employee], year=2026, months=[1])
        totals = {line.code: line.total for line in payslip.line_ids}
        exemption = self.env['hr.rule.parameter']._get_parameter_from_code(
            'private_car_withholding_monthly_exemption', date(2026, 1, 31))
        self.assertGreater(totals.get('CAR.PRIV', 0.0), exemption)
        taxable_private_car = totals['CAR.PRIV'] - exemption

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2026, 'month': '1'})
        line_274_56 = sheet.line_274_56_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_56.taxable_amount, totals['SALARY'] + taxable_private_car, places=2)

        payslip.version_id.l10n_be_dimona_category = 'flx'
        sheet._compute_line_ids()
        line_274_56 = sheet.line_274_56_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_56.taxable_amount, taxable_private_car, places=2)

    def test_274_56_base_of_flexi_job(self):
        """ The public transport allowance, exempted from the tax and the ONSS (paid net), is out of the base of the
        0.12 % exemption. A flexi-job, whose pay is exempted from the tax, is in the base for its taxable amounts
        without social security contributions only. """
        employee = self.create_employee([{
            'name': 'Flexi Public Transport Commuter',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2026, 1, 1),
            'contract_date_end': date(2026, 1, 31),
        }])
        employee.version_id.write({
            'bus_transport_employee_amount': 100,
            'bus_transport_periodicity': 'monthly',
            'bus_transport_employee_kilometer': 5,
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Flexi Public Transport Commuter',
            'employee_id': employee.id,
            'company_id': self.belgian_company.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'version_id': employee.version_id.id,
        })
        payslip._set_input_value('TAXABLE_NO_ONSS', 10.91)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        totals = {line.code: line.total for line in payslip.line_ids}
        self.assertTrue(totals.get('PUB.TRANS'))
        self.assertEqual(totals.get('TAXABLE_NO_ONSS'), 10.91)

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2026, 'month': '1'})
        line_274_56 = sheet.line_274_56_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_56.taxable_amount, totals['SALARY'] + 10.91, places=2)

        payslip.version_id.l10n_be_dimona_category = 'flx'
        self.assertTrue(payslip.version_id.is_flexi())
        sheet._compute_line_ids()
        line_274_56 = sheet.line_274_56_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_56.taxable_amount, 10.91, places=2)

    def test_274_56_base_with_taxable_salary_without_onss(self):
        """ The base of the 0.12 % exemption holds the taxable salary without social security contributions, as the
        social secretariats compute it """
        employee = self.create_employee([{
            'name': 'Taxable Without ONSS',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2026, 1, 1),
        }])
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Taxable Without ONSS',
            'employee_id': employee.id,
            'company_id': self.belgian_company.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'version_id': employee.version_id.id,
        })
        payslip._set_input_value('TAXABLE_NO_ONSS', 100)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        totals = {line.code: line.total for line in payslip.line_ids}
        self.assertEqual(totals.get('TAXABLE_NO_ONSS'), 100)

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2026, 'month': '1'})
        line_274_56 = sheet.line_274_56_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_56.taxable_amount, totals['SALARY'] + 100, places=2)

    def test_274_56_base_with_benefit_in_kind_and_fuel_card_without_onss(self):
        """ The base of the 0.12 % exemption holds the benefits in kind taxable but not subject to the social security
        contributions (e.g. the meal vouchers taken over by the employer) and the taxable fuel card of the commute, as
        the social secretariats compute it """
        employee = self.create_employee([{
            'name': 'Benefit Without ONSS',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2026, 1, 1),
        }])
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Benefit Without ONSS',
            'employee_id': employee.id,
            'company_id': self.belgian_company.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'version_id': employee.version_id.id,
        })
        payslip._set_input_value('ATN_MISC_NO_ONSS', 4.36)
        payslip._set_input_value('FUEL_CARD_COMMUTE', 1.82)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        totals = {line.code: line.total for line in payslip.line_ids}
        self.assertEqual(totals.get('ATN_MISC_NO_ONSS'), 4.36)
        self.assertEqual(totals.get('FUEL_CARD_COMMUTE'), 1.82)

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2026, 'month': '1'})
        line_274_56 = sheet.line_274_56_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_56.taxable_amount, totals['SALARY'] + 4.36 + 1.82, places=2)

    def test_274_56_base_with_company_car_benefit(self):
        """ The base of the 0.12 % exemption holds the company car benefit in kind (taxable, not subject to the social
        security contributions), as the social secretariats compute it """
        employee = self.create_employee([{
            'name': 'Company Car Driver',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2026, 1, 1),
        }])
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'Audi'})
        car = self.env['fleet.vehicle'].create({
            'model_id': self.env['fleet.vehicle.model'].create({'name': 'A3', 'brand_id': brand.id}).id,
            'company_id': self.belgian_company.id,
            'atn': 150.0,
            'driver_employee_id': employee.id,
        })
        employee.version_id.write({'transport_mode_car': True, 'car_id': car.id})
        payslip = self.create_and_validate_payslips(employees=[employee], year=2026, months=[1])
        totals = {line.code: line.total for line in payslip.line_ids}
        self.assertTrue(totals.get('ATN.CAR'))

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2026, 'month': '1'})
        line_274_56 = sheet.line_274_56_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_56.taxable_amount, totals['SALARY'] + totals['ATN.CAR'], places=2)

    def test_274_56_base_without_mobility_budget_paid(self):
        """ The balance of the mobility budget paid in cash (pillar 3), without withholding tax, is out of the base
        of the 0.12 % exemption """
        employee = self.create_employee([{
            'name': 'Mobility Budget',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2026, 1, 1),
            'l10n_be_mobility_budget': True,
            'l10n_be_mobility_budget_amount': 1200,
        }])
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Mobility Budget',
            'employee_id': employee.id,
            'company_id': self.belgian_company.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'version_id': employee.version_id.id,
        })
        payslip._set_input_value('MOBILITY_TO_PAY', 200)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        totals = {line.code: line.total for line in payslip.line_ids}
        self.assertEqual(totals.get('MOBILITY_TO_PAY'), 200)

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2026, 'month': '1'})
        line_274_56 = sheet.line_274_56_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_56.taxable_amount, totals['SALARY'], places=2)

    def test_274_56_base_with_holiday_pays_and_thirteenth_month(self):
        """ The base of the 0.12 % exemption holds the double holiday pay, the holiday pay on departure and the
        thirteenth month with their gross amounts (before the ONSS), as the social secretariats compute it """
        employee = self.create_employee([{
            'name': 'Holiday Pay',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2025, 1, 1),
        }])
        double_holiday = self.create_and_validate_payslips(employees=[employee], year=2026, months=[6], vals={
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_double_holiday').id,
        })
        thirteenth_month = self.create_and_validate_payslips(employees=[employee], year=2026, months=[12], vals={
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_thirteen_month').id,
        })
        leaving_employee = self.create_employee([{
            'name': 'Holiday Pay On Departure',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2025, 1, 1),
            'contract_date_end': date(2026, 9, 30),
        }])
        leaving_employee.departure_date = date(2026, 9, 30)
        departure_holiday = self.env['hr.payslip'].create({
            'name': 'Holiday pay on departure',
            'employee_id': leaving_employee.id,
            'version_id': leaving_employee.version_id.id,
            'company_id': self.belgian_company.id,
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_departure_n_holidays').id,
            'date_from': date(2026, 9, 1),
            'date_to': date(2026, 9, 30),
        })
        departure_holiday._set_input_value('GROSS_REF', 30000)
        departure_holiday.compute_sheet()
        departure_holiday.action_payslip_done()
        for payslip, gross_code, onss_codes, month in (
            (double_holiday, 'DH_GROSS', ['ONSS_DOUBLE_HOLIDAY'], '6'),
            (departure_holiday, 'HOLIDAY_TERM_GROSS', ['ONSS_HOLIDAY_TERM_SIMPLE', 'ONSS_HOLIDAY_TERM_DOUBLE'], '9'),
            (thirteenth_month, 'BONUS_GROSS', ['ONSS_BONUS'], '12'),
        ):
            employee = payslip.employee_id
            totals = defaultdict(float, {line.code: line.total for line in payslip.line_ids})
            onss = sum(totals[code] for code in onss_codes)
            self.assertTrue(totals[gross_code])
            self.assertLess(onss, 0)
            sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2026, 'month': month})
            line_274_56 = sheet.line_274_56_ids.filtered(lambda line: line.employee_id == employee)
            self.assertAlmostEqual(line_274_56.taxable_amount, totals[gross_code] - onss, places=2)

    def test_274_56_base_with_sickness_complement(self):
        """ The base of the 0.12 % exemption holds the taxable amounts of the nature 18, as the complement of sickness
        paid by the employer, as the social secretariats compute it """
        employee = self.create_employee([{
            'name': 'Sick Worker',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2026, 1, 1),
        }])
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Sick Worker',
            'employee_id': employee.id,
            'company_id': self.belgian_company.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'version_id': employee.version_id.id,
        })
        payslip._set_input_value('SICK_COMPLEMENT', 1000)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        totals = {line.code: line.total for line in payslip.line_ids}
        self.assertEqual(totals.get('REPLACEMENT_REVENUE'), 1000)

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2026, 'month': '1'})
        line_274_56 = sheet.line_274_56_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_56.taxable_amount, totals['SALARY'] + 1000, places=2)

    def test_274_56_without_company_directors(self):
        """ The 0.12 % exemption is computed on the remunerations of the employees, not on the ones of the company
        directors (274.20) """
        self.belgian_company._get_payroll_config(date(2023, 6, 1)).l10n_be_ipa_reduction = True
        director = self.create_employee([{
            'name': 'Director',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2023, 1, 1),
            'employee_type_id': self.env.ref('hr.contract_type_company_executive').id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999').id,
        }])
        self.create_and_validate_payslips(employees=[director], year=2023, months=[6])

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2023, 'month': '6'})
        self.assertIn(director, sheet.line_274_20_ids.employee_id)
        self.assertEqual(sheet.line_274_56_ids.employee_id, self.employee_a | self.employee_b)

    def test_micro_enterprise_exemption_with_separately_taxed_remunerations(self):
        """ The exemption of the starting micro-enterprises (274.61) is 20 % of the withholding tax of the workers'
        remunerations, the separately taxed ones (274.18) included, as the social secretariats declare it """
        config = self.belgian_company._get_payroll_config(date(2026, 1, 1))
        config.exemption_sme_status = 'micro'
        self.belgian_company.l10n_be_cbe_inscription = date(2025, 6, 1)
        employee = self.create_employee([{
            'name': 'Micro Enterprise Worker',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2026, 1, 1),
        }])
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Micro Enterprise',
            'employee_id': employee.id,
            'company_id': self.belgian_company.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'version_id': employee.version_id.id,
        })
        payslip._set_input_value('SICK_COMPLEMENT', 1000)
        payslip.compute_sheet()
        payslip.action_payslip_done()

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2026, 'month': '1'})
        self.assertTrue(sheet.pp_amount_10)
        self.assertTrue(sheet.pp_amount_18)
        self.assertAlmostEqual(sheet.startup_taxable_amount, sheet.taxable_amount_10 + sheet.taxable_amount_18, places=2)
        self.assertAlmostEqual(
            sheet.startup_exempted_amount, round((sheet.pp_amount_10 + sheet.pp_amount_18) * 0.2, 2), places=2)
        declaration_61 = next(
            d for d in sheet._get_rendering_data()['declarations'] if d['revenue_nature'] == 61)
        self.assertEqual(declaration_61['taxable_revenue'], sheet._to_eurocent(sheet.startup_taxable_amount))

    def test_exemptions_on_the_withholding_tax_without_voluntary_one(self):
        """ The voluntary withholding tax (fiscal voluntarism) is not part of the base and of the cap of the research
        (274.33), aid zone (274.81) and starting company (274.61) exemptions: they are computed on the withholding tax
        legally due (PPTOTAL, computed before the voluntary one) """
        self.belgian_company._get_payroll_config(date(2026, 3, 1)).exemption_sme_status = 'micro'
        self.belgian_company.l10n_be_cbe_inscription = date(2025, 6, 1)
        researcher, aid_zone_worker = self.create_employee([{
            'name': name,
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2026, 1, 1),
            'fiscal_voluntarism_type': 'fixed',
            'fiscal_voluntarism_amount': 100.0,
            **vals,
        } for name, vals in (
            ('Voluntary Researcher', {'rd_percentage': 1.0, 'certificate': 'master'}),
            ('Voluntary Aid Zone Worker', {}),
        )])
        aid_zone_worker.version_id.l10n_be_is_aid_zone = True
        payslips = self.create_and_validate_payslips(employees=researcher | aid_zone_worker, year=2026, months=[3])
        line_values = payslips._get_line_values(['PPTOTAL', 'FISC_VOL', 'WITHHOLDING_TAX_EX_274_81'])
        legal_withholding = {
            payslip.employee_id: line_values['PPTOTAL'][payslip.id]['total'] for payslip in payslips
        }
        aid_zone_payslip = payslips.filtered(lambda p: p.employee_id == aid_zone_worker)
        for payslip in payslips:
            self.assertAlmostEqual(line_values['FISC_VOL'][payslip.id]['total'], -100.0, places=2)
        self.assertAlmostEqual(
            line_values['WITHHOLDING_TAX_EX_274_81'][aid_zone_payslip.id]['total'],
            round(0.25 * legal_withholding[aid_zone_worker], 2), places=2)

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2026, 'month': '3'})
        self.assertAlmostEqual(
            sheet.pp_amount_10, sum(legal_withholding.values()) + 200, places=2,
            msg="The 274.10 declares the voluntary withholding tax")
        self.assertAlmostEqual(sheet.line_274_33_ids.withholding_amount, legal_withholding[researcher], places=2)
        self.assertAlmostEqual(sheet.line_274_33_ids.amount, 0.8 * legal_withholding[researcher], places=2)
        self.assertAlmostEqual(sheet.line_274_81_ids.amount, 0.25 * legal_withholding[aid_zone_worker], places=2)
        self.assertAlmostEqual(sheet.startup_withholding_amount, sheet.pp_amount_10 + sheet.pp_amount_18 - 200, places=2)
        self.assertAlmostEqual(
            sheet.startup_exempted_amount, sum(round(0.2 * amount, 2) for amount in legal_withholding.values()), places=2)

    def test_274_10_taxable_amount_of_a_rule_in_two_bases(self):
        """ A rule may belong to two withholding tax bases, each taxed on another structure (as the holiday pay
        regularization, on the monthly and the termination fees structures): it is declared once """
        self.env['hr.salary.rule'].create({
            'name': 'Taxable on two structures',
            'code': 'TWO_BASES',
            'struct_ids': [Command.link(self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id)],
            'country_id': self.env.ref('base.be').id,
            'category_ids': [Command.set([
                self.env.ref('l10n_be_hr_payroll.WITHHOLDING_BASE').id,
                self.env.ref('l10n_be_hr_payroll.TERMINATION_WITHHOLDING_BASE').id,
            ])],
            'sequence': 300,
            'condition_select': 'none',
            'amount_select': 'fix',
            'amount_fix': 100.0,
        })
        employee = self.create_employee([{
            'name': 'Employee Two Bases',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2024, 1, 1),
        }])
        payslip = self.create_and_validate_payslips(employees=[employee], year=2024, months=[3])
        gross = payslip.line_ids.filtered(lambda line: line.code == 'GROSS').total
        self.assertTrue(payslip.line_ids.filtered(lambda line: line.code == 'TWO_BASES').total)

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2024, 'month': '3'})
        line_274_10 = sheet.line_274_10_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_10.taxable_amount, gross, places=2)

    def test_274_10_taxable_amount_of_horeca_occasional_worker(self):
        """ The pay of the days of a Horeca occasional worker taxed at the flat rate is out of the withholding tax
        base of the scale, but it is a taxable remuneration of the 274.10, with its flat-rate withholding tax """
        employee = self.create_employee([{
            'name': 'Horeca Occasional Worker',
            'company_id': self.belgian_company.id,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'contract_date_end': date(2025, 1, 31),
            'l10n_be_dimona_category': 'ext',
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00495').id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
        }])
        self.belgian_company._get_payroll_config(date(2025, 1, 1)).l10n_be_employer_category_id = self.env.ref(
            'l10n_be_hr_payroll.l10n_be_employer_category_00317')
        payslip = self.create_and_validate_payslips(employees=[employee], year=2025, months=[1])
        totals = {line.code: line.total for line in payslip.line_ids}
        self.assertTrue(totals.get('HORECA_OCC_TAXABLE'))
        self.assertTrue(totals.get('HORECA_OCC_PP'))

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2025, 'month': '1'})
        line_274_10 = sheet.line_274_10_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_10.taxable_amount, totals['HORECA_OCC_TAXABLE'] + totals.get('GROSS', 0.0), places=2)
        self.assertAlmostEqual(line_274_10.withholding_amount, -totals['HORECA_OCC_PP'], places=2)

    def test_274_56_base_of_horeca_occasional_worker(self):
        """ The base of the 0.12 % exemption of a Horeca occasional worker is its flat wage with the premiums taxed at
        the scale it covers (taxable, without social security contributions of their own), as the social
        secretariats compute it """
        employee = self.create_employee([{
            'name': 'Horeca Occasional Worker',
            'company_id': self.belgian_company.id,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'contract_date_end': date(2025, 1, 31),
            'l10n_be_dimona_category': 'ext',
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00495').id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
        }])
        self.belgian_company._get_payroll_config(date(2025, 1, 1)).l10n_be_employer_category_id = self.env.ref(
            'l10n_be_hr_payroll.l10n_be_employer_category_00317')
        payslip = self.env['hr.payslip'].create({
            'name': 'Payslip Horeca Occasional Worker',
            'employee_id': employee.id,
            'company_id': self.belgian_company.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'version_id': employee.version_id.id,
        })
        payslip._set_input_value('HORECA_OCC_SCALE_PREMIUM', 24)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        totals = {line.code: line.total for line in payslip.line_ids}
        self.assertTrue(totals.get('HORECA_OCC_FLAT'))
        self.assertEqual(totals.get('HORECA_OCC_SCALE_PREMIUM_FLAT'), 24)

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2025, 'month': '1'})
        line_274_56 = sheet.line_274_56_ids.filtered(lambda line: line.employee_id == employee)
        self.assertAlmostEqual(line_274_56.taxable_amount, totals['SALARY'] + 24, places=2)

    def test_274_10_student_without_withholding_taxes(self):
        """ A student without withholding taxes is declared on the 274.10: their taxable remuneration with a
        withholding tax of 0. A cross-border worker without withholding taxes is not declared. """
        student, cross_border = self.create_employee([{
            'name': 'Student Without Withholding Taxes',
            'company_id': self.belgian_company.id,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'l10n_be_dimona_category': 'stu',
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00841').id,
            'wage': 800.0,
        }, {
            'name': 'Cross-Border Worker',
            'company_id': self.belgian_company.id,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'l10n_be_resident_situation': 'cross_border',
        }])
        student.version_id.no_withholding_taxes = True
        self.assertTrue(cross_border.version_id.no_withholding_taxes)
        student_payslip, _cross_border_payslip = self.create_and_validate_payslips(
            employees=[student, cross_border], year=2025, months=[1])
        gross = student_payslip.line_ids.filtered(lambda line: line.code == 'GROSS').total
        self.assertTrue(gross)

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2025, 'month': '1'})
        line_274_10 = sheet.line_274_10_ids.filtered(lambda line: line.employee_id == student)
        self.assertAlmostEqual(line_274_10.taxable_amount, gross, places=2)
        self.assertEqual(line_274_10.withholding_amount, 0.0)

        # no withholding tax, so no exemption of its payment, e.g. on the overtime
        self.env['hr.payslip.worked_days'].create({
            'payslip_id': student_payslip.id,
            'version_id': student_payslip.version_id.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_overtime').id,
            'number_of_hours': 2,
            'amount': 45.0,
        })
        sheet._compute_line_ids()
        self.assertTrue(sheet.line_274_10_ids.filtered(lambda line: line.employee_id == student))
        self.assertFalse(sheet.line_274_extra_hours_ids.filtered(lambda line: line.employee_id == student))
        self.assertFalse(sheet.line_ids.filtered(lambda line: line.employee_id == cross_border))
        self.assertEqual(sheet.untaxed_employee_ids, cross_border)

    def test_274_56_exemption_capped_to_withholding_taxes(self):
        """ The 0.12 % exemption is an exemption from the payment of the withholding tax withheld: a period
        whose only remunerations are the ones of a student without withholding taxes gets no exemption """
        self.belgian_company._get_payroll_config(date(2025, 1, 1)).l10n_be_ipa_reduction = True
        student = self.create_employee([{
            'name': 'Student Without Withholding Taxes',
            'company_id': self.belgian_company.id,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'l10n_be_dimona_category': 'stu',
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00841').id,
            'wage': 800.0,
        }])
        student.version_id.no_withholding_taxes = True
        self.create_and_validate_payslips(employees=[student], year=2025, months=[1])

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2025, 'month': '1'})
        self.assertTrue(sheet.sme_taxable_amount)
        self.assertEqual(sheet.total_pp_amount, 0.0)
        self.assertEqual(sheet.sme_exempted_amount, 0.0)
        self.assertEqual(sheet.amount_to_pay, 0.0)

        # with withholding taxes to pay, the exemption is the 0.12 % of its base
        self.assertAlmostEqual(self.sheet.sme_exempted_amount, round(
            self.sheet.sme_taxable_amount * self.sheet.sme_exemption_rate, 2), places=2)

    def test_274_56_exemption_pooled_at_the_employer_level(self):
        """ The 0.12 % exemption is the employer's: 0.12 % of the remunerations of all its workers, those without
        withholding taxes included, capped to the whole withholding tax of the declaration, not to the one of each
        worker. The base of a student without withholding taxes reduces the withholding tax of the other workers. """
        self.belgian_company._get_payroll_config(date(2025, 1, 1)).l10n_be_ipa_reduction = True
        student, employee = self.create_employee([{
            'name': 'Student Without Withholding Taxes',
            'company_id': self.belgian_company.id,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'l10n_be_dimona_category': 'stu',
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00841').id,
            'wage': 800.0,
        }, {
            'name': 'Employee With Withholding Taxes',
            'company_id': self.belgian_company.id,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'wage': 3000.0,
        }])
        student.version_id.no_withholding_taxes = True
        self.create_and_validate_payslips(employees=student | employee, year=2025, months=[1])

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2025, 'month': '1'})
        student_line = sheet.line_274_56_ids.filtered(lambda line: line.employee_id == student)
        employee_line = sheet.line_274_56_ids.filtered(lambda line: line.employee_id == employee)
        self.assertTrue(student_line.taxable_amount)
        self.assertTrue(student_line.amount)
        self.assertFalse(sheet.line_274_10_ids.filtered(lambda line: line.employee_id == student).withholding_amount)
        self.assertAlmostEqual(
            sheet.sme_taxable_amount, student_line.taxable_amount + employee_line.taxable_amount, places=2)
        self.assertGreater(sheet.total_pp_amount, sheet.sme_exempted_amount)
        self.assertAlmostEqual(sheet.sme_exempted_amount, round(
            sheet.sme_taxable_amount * sheet.sme_exemption_rate, 2), places=2)
        self.assertGreater(sheet.sme_exempted_amount, round(employee_line.amount, 2))

    def test_report_can_only_be_generated_from_root_company(self):
        companies = self.multibranch_company
        with self.assertRaises(UserError):
            self.env['l10n_be.274_xx'].with_company(companies[1]).create({})

    def test_overtime_cap_of_branch_employee(self):
        """ The overtime of the previous months on the payslips of a branch counts in the yearly cap of the
        exemption, declared on the 274 of the root company """
        root, branch = self.multibranch_company[:2]
        employee = self.create_employee([{
            'name': 'Branch Overtime Worker',
            'company_id': branch.id,
            'contract_date_start': date(2025, 1, 1),
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
        }])
        january, february = self.create_and_validate_payslips(employees=[employee], year=2026, months=[1, 2])
        overtime = self.env.ref('hr_work_entry.be_work_entry_type_overtime')
        self.env['hr.payslip.worked_days'].create([{
            'payslip_id': payslip.id,
            'version_id': payslip.version_id.id,
            'work_entry_type_id': overtime.id,
            'number_of_hours': hours,
            'amount': hours * 30,
        } for payslip, hours in [(january, 1000), (february, 10)]])
        sheet = self.env['l10n_be.274_xx'].with_company(root).create({'year': 2026, 'month': '2'})
        line_ids_vals, warning = sheet._get_extra_hours_lines_ids(
            february, date(2026, 2, 1), {'PPTOTAL': {february.id: {'total': 0}}})
        self.assertFalse(line_ids_vals)
        self.assertIn('Branch Overtime Worker', warning)

    def test_overtime_exemption_of_the_declared_taxable_amount(self):
        """ The overtime exemption is the rate of the declared (rounded) taxable amount: an hour at 150 % paid
        23.84 is a base of 15.89 (15.8933...), exempted at 41.25 %: 6.55, not 6.56 """
        employee = self.create_employee([{
            'name': 'Overtime Rounding Worker',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2025, 1, 1),
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
        }])
        payslip = self.create_and_validate_payslips(employees=[employee], year=2026, months=[1])
        overtime = self.env.ref('hr_work_entry.be_work_entry_type_overtime')
        self.assertEqual(overtime.amount_rate, 1.5)
        self.env['hr.payslip.worked_days'].create({
            'payslip_id': payslip.id,
            'version_id': payslip.version_id.id,
            'work_entry_type_id': overtime.id,
            'number_of_hours': 1,
            'amount': 23.84,
        })
        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2026, 'month': '1'})
        [line] = sheet._get_extra_hours_lines_ids(payslip, date(2026, 1, 1), {'PPTOTAL': {payslip.id: {'total': 100}}})[0]
        self.assertEqual(line['taxable_amount'], 15.89)
        self.assertEqual(line['amount'], 6.55)
        # an exemption from the payment of the withholding tax: none without withholding tax
        [line] = sheet._get_extra_hours_lines_ids(payslip, date(2026, 1, 1), {'PPTOTAL': {payslip.id: {'total': 0}}})[0]
        self.assertEqual(line['amount'], 0.0)
        [line] = sheet._get_extra_hours_lines_ids(payslip, date(2026, 1, 1), {'PPTOTAL': {payslip.id: {'total': 4.0}}})[0]
        self.assertEqual(line['amount'], 4.0)

        def overtime_line(**totals):
            line_values = {code: {payslip.id: {'total': total}} for code, total in totals.items()}
            [line] = sheet._get_extra_hours_lines_ids(payslip, date(2026, 1, 1), line_values)[0]
            return line

        # capped to the withholding tax of the salary only: the scale one is reduced to 0 by the overtime tax reduction
        # (P.P.DEDEH), the one of the double holiday pay and of the bonuses paid with the month are not part of it
        line = overtime_line(PPTOTAL=307.18, DH_PP=-307.18)
        self.assertEqual(line['amount'], 0.0)
        self.assertEqual(line['withholding_amount'], 0.0)
        self.assertEqual(overtime_line(PPTOTAL=104.0, DH_PP=-50.0, BONUS_PP=-50.0)['amount'], 4.0)
        # the voluntary withholding tax (a negative line) is part of it
        self.assertEqual(overtime_line(PPTOTAL=50.0, DH_PP=-50.0, FISC_VOL=-4.0)['amount'], 4.0)
        # the flat-rate tax of the economic unemployment supplements stays in it, as at the social secretariats
        self.assertEqual(overtime_line(**{'PPTOTAL': 4.0, 'ECONOMIC_UNEMPLOYMENT.P.P': -4.0})['amount'], 4.0)

    def test_overtime_exemption_of_recoverable_overtime_100(self):
        """ The overtime recovered later with a 100% premium (026.01) pays the premium alone: the hour at the normal
        wage is the base of the overtime exemption, and the premium of 100% gives right to the tax reduction """
        recoverable_100 = self.env.ref('l10n_be_hr_payroll.work_entry_type_overtime_recoverable_100')
        self.assertEqual(self.env['hr.payslip']._l10n_be_get_overtime_premium_rate(recoverable_100), 1.0)
        employee = self.create_employee([{
            'name': 'Recovered Overtime Worker',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2025, 1, 1),
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
        }])
        payslip = self.create_and_validate_payslips(employees=[employee], year=2026, months=[1])
        self.env['hr.payslip.worked_days'].create({
            'payslip_id': payslip.id,
            'version_id': payslip.version_id.id,
            'work_entry_type_id': recoverable_100.id,
            'number_of_hours': 2,
            'amount': 56.28,
        })
        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2026, 'month': '1'})
        [line] = sheet._get_extra_hours_lines_ids(payslip, date(2026, 1, 1), {'PPTOTAL': {payslip.id: {'total': 100}}})[0]
        self.assertEqual(line['nature_code'], '274.44')
        self.assertEqual(line['taxable_amount'], 56.28)
        self.assertEqual(line['amount'], 23.22)

    def test_no_overtime_exemption_for_flexi_jobs(self):
        """ The pay of a flexi-job is exempted from the tax: no withholding tax, so no exemption of its payment on
        its overtime """
        employee = self.create_employee([{
            'name': 'Flexi Overtime Worker',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2026, 1, 1),
            'contract_date_end': date(2026, 1, 31),
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302').id,
        }])
        payslip = self.create_and_validate_payslips(employees=[employee], year=2026, months=[1])
        self.env['hr.payslip.worked_days'].create({
            'payslip_id': payslip.id,
            'version_id': payslip.version_id.id,
            'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_overtime').id,
            'number_of_hours': 2,
            'amount': 45.0,
        })
        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2026, 'month': '1'})
        self.assertTrue(sheet.line_274_extra_hours_ids.filtered(lambda line: line.employee_id == employee))

        payslip.version_id.l10n_be_dimona_category = 'flx'
        self.assertTrue(payslip.version_id.is_flexi())
        sheet._compute_line_ids()
        self.assertFalse(sheet.line_274_extra_hours_ids.filtered(lambda line: line.employee_id == employee))

    def test_281_10_branch_employees(self):
        """ The 281.10 of the root company declares the employees of its branches """
        root, branch = self.multibranch_company[:2]
        with self.assertRaises(UserError):
            self.env['l10n_be.281_xx'].with_company(branch).create({'year': '2026'})
        employee = self.create_employee([{
            'name': 'Branch 281 Worker',
            'company_id': branch.id,
            'contract_date_start': date(2025, 1, 1),
        }])
        self.create_and_validate_payslips(employees=[employee], year=2026, months=[1])
        declaration = self.env['l10n_be.281_xx'].with_company(root).create({'year': '2026'})
        report = declaration.l10n_be_281_10_ids[:1]
        report.action_generate_declarations()
        self.assertIn(employee, report.line_ids.employee_id)

    def test_individual_accounts_of_branch_employees(self):
        """ The individual accounts of the root company are made for the employees of its branches """
        root, branch = self.multibranch_company[:2]
        employee = self.create_employee([{
            'name': 'Branch Individual Account Worker',
            'company_id': branch.id,
            'contract_date_start': date(2025, 1, 1),
        }])
        self.create_and_validate_payslips(employees=[employee], year=2026, months=[1])
        sheet = self.env['l10n_be.individual.account'].with_company(root).create({
            'name': 'Individual Accounts 2026', 'year': '2026', 'company_id': root.id})
        sheet.action_generate_declarations()
        self.assertIn(employee, sheet.line_ids.employee_id)

    def test_individual_account_joint_committee(self):
        """ The individual account shows the joint committee of the employee """
        employee = self.create_employee([{
            'name': 'Individual Account Worker',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2025, 1, 1),
        }])
        self.create_and_validate_payslips(employees=[employee], year=2026, months=[1])
        sheet = self.env['l10n_be.individual.account'].with_company(self.belgian_company).create({
            'name': 'Individual Accounts 2026', 'year': '2026', 'company_id': self.belgian_company.id})
        sheet.action_generate_declarations()
        declaration = sheet.line_ids.filtered(lambda line: line.employee_id == employee)
        declaration.action_generate_pdf()
        # The cron runs in another company than the one of the employee
        other_company = self.env['res.company'].create({'name': 'Other Company'})
        self.env['hr.payslip'].with_company(other_company)._cron_generate_pdf()
        self.assertEqual(declaration.state, 'pdf_generated', declaration.declaration_error)
        content = declaration.pdf_file.content.decode()
        # The header is the one of the company of the employee
        self.assertIn(self.belgian_company.name, content)
        self.assertNotIn(other_company.name, content)
        joint_committee = employee.version_id.l10n_be_joint_committee_id
        self.assertTrue(joint_committee)
        self.assertIn(joint_committee.name, content)
        self.assertNotIn('200.000', content)

    def test_social_security_certificate_of_branch_employees(self):
        """ The social security certificate of the root company includes the employees of its branches """
        root, branch = self.multibranch_company[:2]
        employee = self.create_employee([{
            'name': 'Branch Certificate Worker',
            'company_id': branch.id,
            'contract_date_start': date(2025, 1, 1),
        }])
        self.create_and_validate_payslips(employees=[employee], year=2026, months=[1])
        wizard = self.env['l10n.be.social.security.certificate'].with_company(root).create({
            'company_id': root.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 12, 31),
            'aggregation_level': 'employee',
        })
        self.assertIn(employee.legal_name, [name for name, _data in wizard._get_report_data()])

    def test_include_child_branches_in_report(self):
        companies = self.belgian_company | self.multibranch_company
        # company 0 -> root / no child
        # company 1 (is parent of) company 2 (is parent of) company 3
        target_company = companies[1]

        employees = self.create_employee([
            {
                "name": f'Employee {company.name}',
                "company_id": company.id,
                'contract_date_start': date(2026, 1, 1),
                # relevant for 274 XX report
                'rd_percentage': .5,
                'certificate': 'master',
            } for company in companies
        ])
        self.create_and_validate_payslips(employees=employees, year=2026, months=[1])

        report = self.env['l10n_be.274_xx'].with_company(target_company).create({
            'year': 2026,
            'month': 1,
        })
        report._compute_line_ids()

        self.assertEqual(len(report.line_274_33_ids), 3, "Report should include all 3 companies with index 1-2-3")

    def test_training_line_generated_for_selected_employee(self):
        self.sheet.training_employee_ids = self.employee_a
        self.sheet._compute_line_ids()

        gross = self.employee_a_payslip._get_line_values(["GROSS"])["GROSS"][
            self.employee_a_payslip.id
        ]["total"]
        line = self.sheet.line_274_64_ids

        self.assertEqual(len(line), 1, "One training line for the selected employee")
        self.assertEqual(self.sheet.line_274_64_ids.nature_code, "274.64")
        self.assertEqual(self.sheet.line_274_64_ids.employee_id, self.employee_a)

        self.assertAlmostEqual(
            line.taxable_amount,
            gross,
            2,
            "Taxable base is the GROSS payslip line",
        )
        self.assertAlmostEqual(
            line.amount,
            round(0.1175 * gross, 2),
            2,
            "Exemption is 11.75% of the taxable base",
        )

        self.assertGreater(self.sheet.deducted_amount_64, 0)
        self.assertAlmostEqual(
            self.sheet.deducted_amount_64,
            sum(self.sheet.line_274_64_ids.mapped("amount")),
            2,
        )
        self.assertGreaterEqual(
            self.sheet.deducted_amount,
            self.sheet.deducted_amount_64,
            "The exemption total must include the training exemption",
        )
        # Training exemption is independent from the bachelor 25% cap.
        self.assertEqual(self.sheet.capped_amount_34, 0)

    def test_training_exemption_on_capped_monthly_taxable_remuneration(self):
        """ The training exemption (274.64) is 11.75 % of the taxable remuneration of the month, capped to 3 500 EUR,
        of the employees, not of the company directors """
        trainee, director = self.create_employee([{
            'name': 'High Wage Trainee',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2022, 1, 1),
            'wage': 8000.0,
        }, {
            'name': 'Trained Director',
            'company_id': self.belgian_company.id,
            'contract_date_start': date(2022, 1, 1),
            'employee_type_id': self.env.ref('hr.contract_type_company_executive').id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_999').id,
        }])
        payslips = self.create_and_validate_payslips(employees=trainee | director, year=2023, months=[3])
        trainee_payslip = payslips.filtered(lambda p: p.employee_id == trainee)
        gross = trainee_payslip._get_line_values(['GROSS'])['GROSS'][trainee_payslip.id]['total']
        self.assertGreater(gross, 3500)

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2023, 'month': '3'})
        sheet.training_employee_ids = trainee | director
        sheet._compute_line_ids()
        self.assertEqual(sheet.line_274_64_ids.employee_id, trainee)
        self.assertAlmostEqual(sheet.line_274_64_ids.taxable_amount, gross, places=2)
        self.assertAlmostEqual(sheet.line_274_64_ids.amount, 0.1175 * 3500, places=2)

    def test_rd_exemption_capped_at_withholding_left_by_training(self):
        # The training exemption (274.64) is imputed before the R&D one (274.33): a researcher at
        # 100% R&D selected for training gets the full 11.75% training exemption, and the R&D
        # exemption (80% of the withholding) only gets what is left, so amount_to_pay cannot go
        # below 0 for that employee. An isolated period (May, dedicated sheet) keeps the shared
        # June fixtures out of the totals.
        researcher = self.create_employee({
            "name": "Researcher / Trainee",
            "company_id": self.belgian_company.id,
            "contract_date_start": date(2022, 1, 1),
            "rd_percentage": 1.0,
            "certificate": "master",
        })
        self.create_and_validate_payslips(employees=researcher, year=2023, months=[5])

        sheet = (
            self
            .env["l10n_be.274_xx"]
            .with_company(self.belgian_company)
            .create({
                "year": 2023,
                "month": 5,
            })
        )
        sheet.training_employee_ids = researcher
        sheet._compute_line_ids()

        rd_line = sheet.line_274_33_ids
        training_line = sheet.line_274_64_ids
        self.assertEqual(len(rd_line), 1, "The researcher has a 274.33 R&D line")
        self.assertEqual(
            len(training_line),
            1,
            "The researcher has a 274.64 training line",
        )

        withholding = rd_line.withholding_amount
        self.assertAlmostEqual(
            training_line.amount,
            0.1175 * training_line.taxable_amount,
            2,
            "The training exemption is 11.75% of the taxable base",
        )
        self.assertLess(
            rd_line.amount,
            0.8 * withholding,
            "The R&D exemption is capped below its 80% value",
        )
        self.assertAlmostEqual(
            rd_line.amount,
            withholding - training_line.amount,
            2,
            "The R&D exemption is floored to the withholding left after the training exemption",
        )

        self.assertGreaterEqual(
            sheet.amount_to_pay,
            0,
            "The exemptions cannot exceed the withholding due",
        )
        self.assertAlmostEqual(
            sheet.amount_to_pay,
            0,
            2,
            "R&D + training consume the full withholding for this employee",
        )

    def test_exemptions_imputed_in_cascade_on_the_withholding_left(self):
        # The exemptions of a worker are imputed one after the other, each on the withholding tax the previous
        # ones leave. The aid zone exemption (274.81, 25 %) can't be cumulated with the research one (274.33, 80 % of
        # the withholding tax at the R&D percentage): the worker keeps the most advantageous one.
        for rd_percentage, month, rd_kept in ((1.0, 4, True), (0.1, 5, False)):
            with self.subTest(rd_percentage=rd_percentage):
                researcher = self.create_employee({
                    "name": f"Researcher In An Aid Zone {month}",
                    "company_id": self.belgian_company.id,
                    "contract_date_start": date(2022, 1, 1),
                    "rd_percentage": rd_percentage,
                    "certificate": "master",
                })
                researcher.version_id.l10n_be_is_aid_zone = True
                self.create_and_validate_payslips(employees=researcher, year=2023, months=[month])

                sheet = self.env["l10n_be.274_xx"].with_company(self.belgian_company).create({
                    "year": 2023, "month": str(month),
                })
                rd_line = sheet.line_274_33_ids
                aid_zone_line = sheet.line_274_81_ids
                withholding = sum(sheet.line_274_10_ids.filtered(
                    lambda l: l.employee_id == researcher).mapped("withholding_amount"))
                self.assertGreater(withholding, 0)
                if rd_kept:
                    self.assertFalse(aid_zone_line)
                    self.assertAlmostEqual(rd_line.amount, 0.8 * withholding, 2)
                else:
                    self.assertFalse(rd_line)
                    self.assertAlmostEqual(aid_zone_line.amount, 0.25 * withholding, 2)

    def test_only_selected_employees_get_training_lines(self):
        self.sheet.training_employee_ids = self.employee_a
        self.sheet._compute_line_ids()
        self.assertEqual(len(self.sheet.line_274_64_ids), 1)
        self.assertEqual(self.sheet.line_274_64_ids.employee_id, self.employee_a)

        # The employee selection is the single source of truth: clearing it drops the lines.
        self.sheet.training_employee_ids = False
        self.sheet._compute_line_ids()
        self.assertEqual(len(self.sheet.line_274_64_ids), 0)

    def test_seniority_warning_under_6_months(self):
        # self.create_and_validate_payslips(employees=recent | senior, year=2023, months=[6])

        self.sheet.training_employee_ids = self.employee_a | self.employee_b
        self.assertIn(
            "Employee B (Recent)",
            self.sheet.l10n_be_training_seniority_warning_message,
        )
        self.assertNotIn(
            "Employee A (Senior)",
            self.sheet.l10n_be_training_seniority_warning_message,
        )

        # Selecting only the senior employee clears the warning.
        self.sheet.training_employee_ids = self.employee_a
        self.assertFalse(self.sheet.l10n_be_training_seniority_warning_message)

    def _create_shift_premium_payslips(self, category_xmlid, wages, employee_vals=None, month=date(2023, 9, 1)):
        """
        Creates one payslip of the month (September 2023 by default) per given wage, each employee having 8 full
        weekdays (from the first Monday after the 3rd) tagged with the given premium category (PREMIUM_PAY_TEAM or
        PREMIUM_PAY_NIGHT) - comfortably above the 1/3-of-full-pay-hours eligibility
        threshold for the corresponding withholding tax exemption (274.74 / 274.75).
        All payslips are computed together in one batch so the "mutualized" exemption
        pooling (see ``hr.payslip._get_team_night_274_74_75_exemptions``) applies across
        them, exactly like a real monthly payroll run for the whole company.
        """
        first_monday = month + relativedelta(day=4, weekday=MO)
        work_entry_type = self.env['hr.work.entry.type'].create({
            'name': f'{category_xmlid} Test {month:%Y-%m}',
            'code': f'{category_xmlid}_TEST_{month:%Y%m}',
            'requires_allocation': False,
            'request_unit': 'day',
            'unit_of_measure': 'day',
            'category_ids': [Command.link(self.env.ref('l10n_be_hr_payroll.REMUNERATION_BASE').id)],
            'optional_category_ids': [Command.link(self.env.ref(f'l10n_be_hr_payroll.{category_xmlid}').id)],
        })

        employees = self.create_employee([
            {
                'name': f'{category_xmlid} Employee {i}',
                'company_id': self.belgian_company.id,
                'resource_calendar_id': self.belgian_company.resource_calendar_id.id,
                'contract_date_start': date(2022, 1, 1),
                'wage': wage,
                **(employee_vals or {}),
            }
            for i, wage in enumerate(wages)
        ])

        self.env['hr.leave'].create([
            {
                'employee_id': employee.id,
                'work_entry_type_id': work_entry_type.id,
                'request_date_from': first_monday,
                'request_date_to': first_monday + relativedelta(days=9),
                'category_options_ids': [Command.link(self.env.ref(f'l10n_be_hr_payroll.{category_xmlid}').id)],
            }
            for employee in employees
        ])

        payslips = self.env['hr.payslip'].create([
            {
                'name': f'{category_xmlid} Payslip {employee.name}',
                'employee_id': employee.id,
                'company_id': self.belgian_company.id,
                'date_from': month,
                'date_to': month + relativedelta(day=31),
                'version_id': employee.version_id.id,
            }
            for employee in employees
        ])
        payslips.compute_sheet()
        payslips.action_payslip_done()
        payslips.action_payslip_paid()
        return employees, payslips

    def test_274_74_exemption_pooling_matches_actual_payslip_grants(self):
        # The 274.74 report must reflect the same "mutualized" exemption pool the payroll
        # engine itself applies when computing WITHHOLDING_TAX_EX_274_74 on the real
        # payslips: unused theoretical exemption from a low-withholding employee is pooled
        # and can cover the shortfall of a higher-withholding employee processed after them.
        (employee_low, employee_high), payslips = self._create_shift_premium_payslips(
            'PREMIUM_PAY_TEAM', [1300.0, 9000.0],
        )
        payslip_low = payslips.filtered(lambda p: p.employee_id == employee_low)
        payslip_high = payslips.filtered(lambda p: p.employee_id == employee_high)

        line_values = payslips._get_line_values(['PPTOTAL', 'T_WITHHOLDING_TAX_EX_274_74', 'WITHHOLDING_TAX_EX_274_74'])
        theoretical_low = line_values['T_WITHHOLDING_TAX_EX_274_74'][payslip_low.id]['total']
        theoretical_high = line_values['T_WITHHOLDING_TAX_EX_274_74'][payslip_high.id]['total']
        withholding_low = line_values['PPTOTAL'][payslip_low.id]['total']
        withholding_high = line_values['PPTOTAL'][payslip_high.id]['total']
        granted_low = line_values['WITHHOLDING_TAX_EX_274_74'][payslip_low.id]['total']
        granted_high = line_values['WITHHOLDING_TAX_EX_274_74'][payslip_high.id]['total']

        self.assertGreater(theoretical_low, 0, "The low-wage employee should be team-shift eligible")
        self.assertGreater(theoretical_high, 0, "The high-wage employee should be team-shift eligible")
        self.assertGreater(
            theoretical_low, withholding_low,
            "This scenario needs a low enough wage that its withholding tax doesn't absorb "
            "the full theoretical exemption, leaving a surplus to pool",
        )
        self.assertGreater(
            withholding_high, theoretical_high,
            "This scenario needs a high enough wage that its own theoretical exemption falls "
            "short of its withholding tax, so it needs the pooled surplus",
        )
        self.assertGreater(
            granted_high, theoretical_high,
            "Sanity check: the payroll engine's own mutualization actually kicked in for the "
            "high-wage employee (it granted more than their own theoretical exemption)",
        )

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({
            'year': 2023,
            'month': 9,
        })
        sheet._compute_line_ids()

        report_line_low = sheet.line_274_74_ids.filtered(lambda l: l.employee_id == employee_low)
        report_line_high = sheet.line_274_74_ids.filtered(lambda l: l.employee_id == employee_high)

        self.assertAlmostEqual(
            report_line_low.amount, granted_low, 2,
            "The report's exemption for the low-wage employee matches what the payroll engine granted",
        )
        self.assertAlmostEqual(
            report_line_high.amount, granted_high, 2,
            "The report's exemption for the high-wage employee reflects the same pooled surplus "
            "the payroll engine granted, not just their own (smaller) theoretical exemption",
        )

    def test_274_75_night_premium_of_12_percent(self):
        # The night premium (1.5862 EUR an hour in 2023) must be at least 12% of the contractual hourly wage: met for a
        # wage of 1300 (7.89 EUR an hour), not for a wage of 9000 (54.66 EUR an hour)
        (employee_low, employee_high), payslips = self._create_shift_premium_payslips(
            'PREMIUM_PAY_NIGHT', [1300.0, 9000.0],
        )
        Declaration = self.env['l10n_be.274_xx']
        self.assertTrue(Declaration._is_night_exemption_eligible(payslips.filtered(lambda p: p.employee_id == employee_low)))
        self.assertFalse(Declaration._is_night_exemption_eligible(payslips.filtered(lambda p: p.employee_id == employee_high)))

    def test_274_75_night_premium_of_the_employer(self):
        # An employer paying its own night premium (by an input of its own, Odoo's PREMNIGHT archived): Odoo can't
        # measure the premium, the exemption is granted on the night hours
        self.env.ref('l10n_be_hr_payroll.l10n_be_hr_payroll_structure_cp200_employee_salary_premium_pay_night_rule').active = False
        (_employee_low, employee_high), payslips = self._create_shift_premium_payslips(
            'PREMIUM_PAY_NIGHT', [1300.0, 9000.0],
        )
        self.assertTrue(self.env['l10n_be.274_xx']._is_night_exemption_eligible(
            payslips.filtered(lambda p: p.employee_id == employee_high)))

    def test_274_75_exemption_pooling_matches_actual_payslip_grants(self):
        # Same pooling mechanism as 274.74, applied to the 274.75 (night shift) exemption.
        # A night premium of 7 EUR an hour: at least 12% of the hourly wage of both employees
        self.env['hr.rule.parameter.value'].create({
            'rule_parameter_id': self.env.ref('l10n_be_hr_payroll.rule_parameter_cp_200_premium_pay_night_hourly_rate').id,
            'date_from': date(2023, 1, 1),
            'parameter_value': '7',
        })
        (employee_low, employee_high), payslips = self._create_shift_premium_payslips(
            'PREMIUM_PAY_NIGHT', [1300.0, 9000.0],
        )
        payslip_low = payslips.filtered(lambda p: p.employee_id == employee_low)
        payslip_high = payslips.filtered(lambda p: p.employee_id == employee_high)

        line_values = payslips._get_line_values(['PPTOTAL', 'T_WITHHOLDING_TAX_EX_274_75', 'WITHHOLDING_TAX_EX_274_75'])
        theoretical_low = line_values['T_WITHHOLDING_TAX_EX_274_75'][payslip_low.id]['total']
        theoretical_high = line_values['T_WITHHOLDING_TAX_EX_274_75'][payslip_high.id]['total']
        withholding_low = line_values['PPTOTAL'][payslip_low.id]['total']
        withholding_high = line_values['PPTOTAL'][payslip_high.id]['total']
        granted_low = line_values['WITHHOLDING_TAX_EX_274_75'][payslip_low.id]['total']
        granted_high = line_values['WITHHOLDING_TAX_EX_274_75'][payslip_high.id]['total']

        self.assertGreater(theoretical_low, 0, "The low-wage employee should be night-shift eligible")
        self.assertGreater(theoretical_high, 0, "The high-wage employee should be night-shift eligible")
        self.assertGreater(
            theoretical_low, withholding_low,
            "This scenario needs a low enough wage that its withholding tax doesn't absorb "
            "the full theoretical exemption, leaving a surplus to pool",
        )
        self.assertGreater(
            withholding_high, theoretical_high,
            "This scenario needs a high enough wage that its own theoretical exemption falls "
            "short of its withholding tax, so it needs the pooled surplus",
        )
        self.assertGreater(
            granted_high, theoretical_high,
            "Sanity check: the payroll engine's own mutualization actually kicked in for the "
            "high-wage employee (it granted more than their own theoretical exemption)",
        )

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({
            'year': 2023,
            'month': 9,
        })
        sheet._compute_line_ids()

        report_line_low = sheet.line_274_75_ids.filtered(lambda l: l.employee_id == employee_low)
        report_line_high = sheet.line_274_75_ids.filtered(lambda l: l.employee_id == employee_high)

        self.assertAlmostEqual(
            report_line_low.amount, granted_low, 2,
            "The report's exemption for the low-wage employee matches what the payroll engine granted",
        )
        self.assertAlmostEqual(
            report_line_high.amount, granted_high, 2,
            "The report's exemption for the high-wage employee reflects the same pooled surplus "
            "the payroll engine granted, not just their own (smaller) theoretical exemption",
        )

    def test_274_75_exemption_pooled_whatever_the_order_of_the_employees(self):
        """ The night shifts exemption is pooled between all the eligible employees: the surplus of an employee whose
        theoretical exemption exceeds his withholding tax goes to the others, even to the ones computed before him.
        The total is min(sum of the theoretical exemptions, sum of the withholding taxes), on the payslips and in the
        declaration """
        # a night premium of 7 EUR an hour: at least 12 % of the hourly wage of both employees (54.66 EUR an hour for 9000)
        self.env['hr.rule.parameter.value'].create({
            'rule_parameter_id': self.env.ref('l10n_be_hr_payroll.rule_parameter_cp_200_premium_pay_night_hourly_rate').id,
            'date_from': date(2023, 1, 1),
            'parameter_value': '7',
        })
        (employee_high, employee_low), payslips = self._create_shift_premium_payslips(
            'PREMIUM_PAY_NIGHT', [9000.0, 1300.0],
        )
        line_values = payslips._get_line_values(['PPTOTAL', 'T_WITHHOLDING_TAX_EX_274_75', 'WITHHOLDING_TAX_EX_274_75'])
        theoretical = {p.employee_id: line_values['T_WITHHOLDING_TAX_EX_274_75'][p.id]['total'] for p in payslips}
        withholding = {p.employee_id: line_values['PPTOTAL'][p.id]['total'] for p in payslips}
        granted = {p.employee_id: line_values['WITHHOLDING_TAX_EX_274_75'][p.id]['total'] for p in payslips}
        self.assertGreater(theoretical[employee_low], withholding[employee_low])
        self.assertGreater(withholding[employee_high], theoretical[employee_high] + theoretical[employee_low])

        expected = min(sum(theoretical.values()), sum(withholding.values()))
        self.assertAlmostEqual(sum(granted.values()), expected, places=2)
        self.assertAlmostEqual(granted[employee_low], withholding[employee_low], places=2)

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2023, 'month': '9'})
        self.assertAlmostEqual(sheet.deducted_amount_75, expected, places=2)
        for employee in (employee_high, employee_low):
            line = sheet.line_274_75_ids.filtered(lambda l: l.employee_id == employee)
            self.assertAlmostEqual(line.amount, granted[employee], places=2)

    def test_274_75_exemption_pool_with_a_flexi_job(self):
        """ The taxable remuneration of an eligible flexi-job is in the pool of the night shifts exemption, as the one
        of the other eligible employees (the flexi-jobs have none of the other exemptions of the employees) """
        # a night premium of 7 EUR an hour: at least 12 % of the hourly wage of both employees (54.66 EUR an hour for 9000)
        self.env['hr.rule.parameter.value'].create({
            'rule_parameter_id': self.env.ref('l10n_be_hr_payroll.rule_parameter_cp_200_premium_pay_night_hourly_rate').id,
            'date_from': date(2023, 1, 1),
            'parameter_value': '7',
        })
        (employee, flexi), payslips = self._create_shift_premium_payslips(
            'PREMIUM_PAY_NIGHT', [9000.0, 1300.0],
            employee_vals={'contract_date_start': date(2023, 9, 1), 'contract_date_end': date(2023, 9, 30)})
        line_values = payslips._get_line_values(['PPTOTAL', 'GROSS', 'T_WITHHOLDING_TAX_EX_274_75'])
        theoretical = sum(line_values['T_WITHHOLDING_TAX_EX_274_75'][p.id]['total'] for p in payslips)
        withholding = sum(line_values['PPTOTAL'][p.id]['total'] for p in payslips)
        flexi_payslip = payslips.filtered(lambda p: p.employee_id == flexi)
        # the flexi wage of the version gives the hourly wage the 12 % night premium condition compares to
        flexi_payslip.version_id.write({'l10n_be_dimona_category': 'flx', 'l10n_be_flexi_monthly_wage': 1300.0})
        self.assertTrue(flexi_payslip.version_id.is_flexi())

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2023, 'month': '9'})
        flexi_line = sheet.line_274_75_ids.filtered(lambda l: l.employee_id == flexi)
        self.assertAlmostEqual(flexi_line.taxable_amount, line_values['GROSS'][flexi_payslip.id]['total'], places=2)
        self.assertEqual(sheet.line_274_75_ids.employee_id, employee + flexi)
        self.assertAlmostEqual(sheet.deducted_amount_75, min(theoretical, withholding), places=2)

    def test_normal_hourly_wage_of_an_hourly_flexi_job(self):
        """ The normal hourly wage of a flexi-job paid by the hour (the 12 % condition of the night premium, the base of
        the overtime) is its flexi hourly wage, not a monthly wage spread over the hours of its schedule """
        flexi = self.create_employee([{
            'name': 'Hourly Flexi',
            'company_id': self.belgian_company.id,
            'resource_calendar_id': self.belgian_company.resource_calendar_id.id,
            'contract_date_start': date(2023, 9, 1),
            'wage_type': 'hourly',
            'l10n_be_flexi_hourly_wage': 13.5,
            'l10n_be_dimona_category': 'flx',
        }])
        self.assertTrue(flexi.version_id.is_flexi())
        worked_days = self.env['hr.payslip.worked_days'].new({'version_id': flexi.version_id.id})
        self.assertAlmostEqual(worked_days._l10n_be_get_normal_hourly_wage(), 13.5, places=4)

    def test_274_74_exemption_capped_with_the_voluntary_withholding_tax(self):
        """ The voluntary withholding tax (fiscal voluntarism) is part of the cap of the team shifts exemption, on the
        payslip and in the declaration """
        _employees, payslip = self._create_shift_premium_payslips(
            'PREMIUM_PAY_TEAM', [2500.0],
            employee_vals={'fiscal_voluntarism_type': 'fixed', 'fiscal_voluntarism_amount': 100.0},
        )
        line_values = payslip._get_line_values(
            ['PPTOTAL', 'FISC_VOL', 'T_WITHHOLDING_TAX_EX_274_74', 'WITHHOLDING_TAX_EX_274_74'])
        withholding = line_values['PPTOTAL'][payslip.id]['total'] - line_values['FISC_VOL'][payslip.id]['total']
        self.assertAlmostEqual(line_values['FISC_VOL'][payslip.id]['total'], -100.0, places=2)
        self.assertGreater(line_values['T_WITHHOLDING_TAX_EX_274_74'][payslip.id]['total'], withholding)
        self.assertAlmostEqual(line_values['WITHHOLDING_TAX_EX_274_74'][payslip.id]['total'], withholding, places=2)

        sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({'year': 2023, 'month': '9'})
        self.assertAlmostEqual(sheet.line_274_74_ids.withholding_amount, withholding, places=2)
        self.assertAlmostEqual(sheet.line_274_74_ids.amount, withholding, places=2)

    def test_exemptions_capped_without_the_economic_unemployment_withholding_tax(self):
        """ The withholding tax the exemptions can reduce is the one of the remuneration: the flat-rate tax of the
        economic unemployment supplements (274.13) is not part of it, as the payslips cap the team shifts exemption """
        payslip = self.employee_a_payslip
        line_values = defaultdict(lambda: defaultdict(lambda: {'total': 0.0}))
        line_values['PPTOTAL'][payslip.id]['total'] = 40.84
        line_values['ECONOMIC_UNEMPLOYMENT.P.P'][payslip.id]['total'] = -13.62
        self.assertAlmostEqual(self.sheet._get_exemption_withholding_tax(payslip, line_values), 27.22, places=2)
        line_values['FISC_VOL'][payslip.id]['total'] = -10.0
        self.assertAlmostEqual(
            self.sheet._get_exemption_withholding_tax(payslip, line_values, voluntary=True), 37.22, places=2)

    def test_starting_company_exemption_of_each_worker_in_cascade(self):
        """ The exemption of the starting micro-enterprises (274.61) is one of each worker, capped to the withholding
        tax the exemptions imputed before it leave him: from 2026, it comes before the team shifts one (274.74),
        before 2026 after it """
        self.belgian_company.l10n_be_cbe_inscription = date(2022, 6, 1)
        for month, starting_company_first in ((date(2023, 9, 1), False), (date(2026, 5, 1), True)):
            with self.subTest(month=month):
                self.belgian_company._get_payroll_config(month).exemption_sme_status = 'micro'
                (employee,), payslip = self._create_shift_premium_payslips('PREMIUM_PAY_TEAM', [2500.0], month=month)
                line_values = payslip._get_line_values(['PPTOTAL', 'T_WITHHOLDING_TAX_EX_274_74'])
                withholding = line_values['PPTOTAL'][payslip.id]['total']
                self.assertGreater(
                    line_values['T_WITHHOLDING_TAX_EX_274_74'][payslip.id]['total'], withholding,
                    "This scenario needs a team exemption above the withholding tax")

                sheet = self.env['l10n_be.274_xx'].with_company(self.belgian_company).create({
                    'year': month.year,
                    'month': str(month.month),
                })
                starting_company_line = sheet.line_ids.filtered(
                    lambda l: l.nature_code == '274.61' and l.employee_id == employee)
                team_line = sheet.line_274_74_ids.filtered(lambda l: l.employee_id == employee)
                self.assertAlmostEqual(starting_company_line.withholding_amount, withholding, places=2)
                if starting_company_first:
                    self.assertAlmostEqual(starting_company_line.amount, round(0.2 * withholding, 2), places=2)
                    self.assertAlmostEqual(team_line.amount, withholding - starting_company_line.amount, places=2)
                else:
                    self.assertAlmostEqual(team_line.amount, withholding, places=2)
                    self.assertEqual(starting_company_line.amount, 0.0)
                self.assertAlmostEqual(
                    sheet.startup_exempted_amount,
                    sum(sheet.line_ids.filtered(lambda l: l.nature_code == '274.61').mapped('amount')), places=2)
                self.assertAlmostEqual(
                    sheet.startup_taxable_amount, sheet.taxable_amount_10 + sheet.taxable_amount_18, places=2)

    def test_training_page_usable_without_training_lines(self):
        """The Training (274.64) page holds the selection of the trained employees: it must stay
        visible when there is no training line yet."""
        self.assertFalse(self.sheet.line_274_64_ids)
        with Form(self.sheet) as sheet_form:
            sheet_form.training_employee_ids.add(self.employee_a)
        self.sheet._compute_line_ids()
        self.assertEqual(self.sheet.line_274_64_ids.employee_id, self.employee_a)

    def test_xml_only_declares_natures_with_data(self):
        self.sheet.training_employee_ids = self.employee_a
        self.sheet._compute_line_ids()
        natures = [d['revenue_nature'] for d in self.sheet._get_rendering_data()['declarations']]
        self.assertIn(10, natures)
        self.assertIn(64, natures)
        self.assertNotIn(32, natures, "No researcher: no 274.32 declaration")
        self.assertNotIn(81, natures, "No aid zone: no 274.81 declaration")

        # An exemption is declared even if its taxable revenue is 0
        sheet_class = self.registry['l10n_be.274_xx']
        compute_amounts = sheet_class._compute_amounts

        def _compute_amounts_without_taxable_64(sheets):
            compute_amounts(sheets)
            for sheet in sheets:
                sheet.taxable_amount_64 = 0

        with patch.object(sheet_class, '_compute_amounts', _compute_amounts_without_taxable_64):
            self.sheet.invalidate_recordset()
            self.assertFalse(self.sheet.taxable_amount_64)
            self.assertTrue(self.sheet.deducted_amount_64)
            declarations = self.sheet._get_rendering_data()['declarations']
        declaration_64 = next(d for d in declarations if d['revenue_nature'] == 64)
        self.assertNotEqual(declaration_64['prepayment'], '0')

    def test_pdf_only_prints_sections_with_data(self):
        self.sheet.training_employee_ids = self.employee_a
        self.sheet._compute_line_ids()
        self.assertEqual(self.sheet._get_pdf_sections(), ['274.10'])

        report_data = {
            'date_start': self.sheet.date_start.strftime("%d/%m/%Y"),
            'date_end': self.sheet.date_end.strftime("%d/%m/%Y"),
        }
        # The first printed page must not start with a page break, even when it is not the 274.10 one
        sheet_class = self.registry['l10n_be.274_xx']
        for sections in (['274.10'], ['274.18'], ['274.18', '274.32']):
            with patch.object(sheet_class, '_get_pdf_sections', lambda sheet, sections=sections: sections):
                html = self.env['ir.actions.report']._render_qweb_html(
                    'l10n_be_hr_payroll.report_274_10', self.sheet.ids, data=report_data)[0].decode()
            self.assertEqual(html.count('class="page"'), len(sections))
            self.assertEqual(html.count('page-break-before: always'), len(sections) - 1)

    def test_xlsx_only_contains_sheets_with_data(self):
        if load_workbook is None:
            self.skipTest("openpyxl not available")
        self.sheet.training_employee_ids = self.employee_a
        self.sheet._compute_line_ids()
        self.sheet.action_generate_xls()
        workbook = load_workbook(io.BytesIO(self.sheet.xls_file.content))
        self.assertEqual(workbook.sheetnames, ['Exemption Summary', 'Training (274.64)'])

    def _set_274_lines(self, *lines):
        """Replace the lines of the declaration by the given values, all for employee A."""
        # A draft would compute its lines again when it is generated
        self.sheet.state = 'ready'
        self.sheet.line_ids = [Command.clear()] + [
            Command.create({'employee_id': self.employee_a.id, **line}) for line in lines
        ]
        self.sheet._compute_amounts()

    def test_274_negative_amounts_block_only_the_xml(self):
        """
        Test that a negative withholding tax nature blocks the Finprof XML only: the PDF and the XLSX
        are generated, and the declaration shows the anomaly in its warning.
        """
        # Simulate a refund payslip leading to negative nature 274.10 amounts
        self._set_274_lines({'nature_code': '274.10', 'taxable_amount': -2500.0, 'withholding_amount': -500.0})

        with self.assertRaises(UserError) as err:
            self.sheet.action_generate_xml()
        self.assertIn("Nature 274.10", str(err.exception))
        self.assertIn("modification declaration", str(err.exception))
        self.assertNotIn("exceed the withholding tax", str(err.exception))

        self.sheet.action_generate_pdf()
        self.sheet.action_generate_xls()
        self.assertTrue(self.sheet.xls_file, "The XLSX helps to find the anomaly, it is not blocked")
        self.assertIn("Nature 274.10", self.sheet.l10n_be_negative_amounts_warning)
        self.assertIn("modification declaration", self.sheet.l10n_be_negative_amounts_warning)

    def test_274_negative_net_withholding_raises_user_error(self):
        """
        Test that exemptions exceeding total withholding taxes (net negative) trigger a UserError.
        """
        # Case where exemptions (274.32) exceed the available withholding tax (274.10)
        self._set_274_lines(
            {'nature_code': '274.10', 'taxable_amount': 2000.0, 'withholding_amount': 400.0},
            {'nature_code': '274.32', 'taxable_amount': 2000.0, 'withholding_amount': 400.0, 'amount': 1000.0},
        )

        with self.assertRaises(UserError) as err:
            self.sheet.action_generate_xml()
        self.assertIn("exceed the withholding tax", str(err.exception))

    def test_274_exact_zero_net_withholding_succeeds(self):
        """
        Test that a declaration where exemptions exactly offset withholding taxes (net zero) is valid.
        """
        # Total withholding is exactly equal to the exemption
        self._set_274_lines(
            {'nature_code': '274.10', 'taxable_amount': 2000.0, 'withholding_amount': 500.0},
            {'nature_code': '274.32', 'taxable_amount': 2000.0, 'withholding_amount': 500.0, 'amount': 500.0},
        )
        self.assertEqual(self.sheet.total_pp_amount, self.sheet.deducted_amount)

        self.sheet.action_generate_xml()
        self.assertTrue(self.sheet.xml_file, "XML file should be generated when net amount is exactly zero.")
        self.assertFalse(self.sheet.l10n_be_negative_amounts_warning)

    def test_274_negative_exemption_is_only_a_warning(self):
        """
        Test that a negative exemption (a regularisation) does not block the XML, it is shown in the warning.
        """
        # An adjustment causes the taxable base of an R&D exemption to be negative
        self._set_274_lines(
            {'nature_code': '274.10', 'taxable_amount': 4000.0, 'withholding_amount': 1000.0},
            {'nature_code': '274.33', 'taxable_amount': -1500.0},
        )

        self.sheet.action_generate_xml()
        self.assertTrue(self.sheet.xml_file)
        self.assertIn("274.33", self.sheet.l10n_be_negative_amounts_warning)
        self.assertNotIn("cannot be generated", self.sheet.l10n_be_negative_amounts_warning)
