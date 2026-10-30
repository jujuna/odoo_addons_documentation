# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime, date
from odoo.addons.l10n_ch_hr_payroll.tests.swissdec_5_0 import TestSwissdec5Common
from odoo.tests.common import tagged, TransactionCase
from freezegun import freeze_time

from odoo.tools import file_open
import json


@tagged('post_install_l10n', 'post_install', '-at_install', 'swissdec_payroll')
class TestSwissdecTestCases(TestSwissdec5Common):
    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2021_11(self):
        identifier = "yearly_retrospective_2021_11"
        generated_dict = self.yearly_retrospective_2021_11._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2021_12(self):
        identifier = "yearly_retrospective_2021_12"
        generated_dict = self.yearly_retrospective_2021_12._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2022_01(self):
        identifier = "yearly_retrospective_2022_01"
        generated_dict = self.yearly_retrospective_2022_01._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2022_02(self):
        identifier = "yearly_retrospective_2022_02"
        generated_dict = self.yearly_retrospective_2022_02._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2022_03(self):
        identifier = "yearly_retrospective_2022_03"
        generated_dict = self.yearly_retrospective_2022_03._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2022_04(self):
        identifier = "yearly_retrospective_2022_04"
        generated_dict = self.yearly_retrospective_2022_04._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2022_05(self):
        identifier = "yearly_retrospective_2022_05"
        generated_dict = self.yearly_retrospective_2022_05._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2022_06(self):
        identifier = "yearly_retrospective_2022_06"
        generated_dict = self.yearly_retrospective_2022_06._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2022_07(self):
        identifier = "yearly_retrospective_2022_07"
        generated_dict = self.yearly_retrospective_2022_07._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2022_08(self):
        identifier = "yearly_retrospective_2022_08"
        generated_dict = self.yearly_retrospective_2022_08._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2022_09(self):
        identifier = "yearly_retrospective_2022_09"
        generated_dict = self.yearly_retrospective_2022_09._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2022_10(self):
        identifier = "yearly_retrospective_2022_10"
        generated_dict = self.yearly_retrospective_2022_10._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2022_11(self):
        identifier = "yearly_retrospective_2022_11"
        generated_dict = self.yearly_retrospective_2022_11._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2022_12(self):
        identifier = "yearly_retrospective_2022_12"
        generated_dict = self.yearly_retrospective_2022_12._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2023_01(self):
        identifier = "yearly_retrospective_2023_01"
        generated_dict = self.yearly_retrospective_2023_01._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_retrospective_2023_02(self):
        identifier = "yearly_retrospective_2023_02"
        generated_dict = self.yearly_retrospective_2023_02._get_declaration()
        self._compare_with_truth_base("yearly_retrospective", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2021_11(self):
        identifier = "ema_declaration_2021_11"
        generated_dict = self.ema_declaration_2021_11._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2021_12(self):
        identifier = "ema_declaration_2021_12"
        generated_dict = self.ema_declaration_2021_12._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2022_01(self):
        identifier = "ema_declaration_2022_01"
        generated_dict = self.ema_declaration_2022_01._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2022_02(self):
        identifier = "ema_declaration_2022_02"
        generated_dict = self.ema_declaration_2022_02._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2022_03(self):
        identifier = "ema_declaration_2022_03"
        generated_dict = self.ema_declaration_2022_03._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2022_04(self):
        identifier = "ema_declaration_2022_04"
        generated_dict = self.ema_declaration_2022_04._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2022_05(self):
        identifier = "ema_declaration_2022_05"
        generated_dict = self.ema_declaration_2022_05._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2022_06(self):
        identifier = "ema_declaration_2022_06"
        generated_dict = self.ema_declaration_2022_06._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2022_07(self):
        identifier = "ema_declaration_2022_07"
        generated_dict = self.ema_declaration_2022_07._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2022_08(self):
        identifier = "ema_declaration_2022_08"
        generated_dict = self.ema_declaration_2022_08._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2022_09(self):
        identifier = "ema_declaration_2022_09"
        generated_dict = self.ema_declaration_2022_09._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2022_10(self):
        identifier = "ema_declaration_2022_10"
        generated_dict = self.ema_declaration_2022_10._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2022_11(self):
        identifier = "ema_declaration_2022_11"
        generated_dict = self.ema_declaration_2022_11._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2022_12(self):
        identifier = "ema_declaration_2022_12"
        generated_dict = self.ema_declaration_2022_12._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2023_01(self):
        identifier = "ema_declaration_2023_01"
        generated_dict = self.ema_declaration_2023_01._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_ema_declaration_2023_02(self):
        identifier = "ema_declaration_2023_02"
        generated_dict = self.ema_declaration_2023_02._get_declaration()
        self._compare_with_truth_base("ema_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2021_11(self):
        identifier = "statistic_declaration_2021_11"
        generated_dict = self.statistic_declaration_2021_11._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2021_12(self):
        identifier = "statistic_declaration_2021_12"
        generated_dict = self.statistic_declaration_2021_12._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2022_01(self):
        identifier = "statistic_declaration_2022_01"
        generated_dict = self.statistic_declaration_2022_01._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2022_02(self):
        identifier = "statistic_declaration_2022_02"
        generated_dict = self.statistic_declaration_2022_02._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2022_03(self):
        identifier = "statistic_declaration_2022_03"
        generated_dict = self.statistic_declaration_2022_03._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2022_04(self):
        identifier = "statistic_declaration_2022_04"
        generated_dict = self.statistic_declaration_2022_04._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2022_05(self):
        identifier = "statistic_declaration_2022_05"
        generated_dict = self.statistic_declaration_2022_05._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2022_06(self):
        identifier = "statistic_declaration_2022_06"
        generated_dict = self.statistic_declaration_2022_06._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2022_07(self):
        identifier = "statistic_declaration_2022_07"
        generated_dict = self.statistic_declaration_2022_07._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2022_08(self):
        identifier = "statistic_declaration_2022_08"
        generated_dict = self.statistic_declaration_2022_08._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2022_09(self):
        identifier = "statistic_declaration_2022_09"
        generated_dict = self.statistic_declaration_2022_09._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2022_10(self):
        identifier = "statistic_declaration_2022_10"
        generated_dict = self.statistic_declaration_2022_10._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2022_11(self):
        identifier = "statistic_declaration_2022_11"
        generated_dict = self.statistic_declaration_2022_11._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2022_12(self):
        identifier = "statistic_declaration_2022_12"
        generated_dict = self.statistic_declaration_2022_12._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2023_01(self):
        identifier = "statistic_declaration_2023_01"
        generated_dict = self.statistic_declaration_2023_01._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_statistic_declaration_2023_02(self):
        identifier = "statistic_declaration_2023_02"
        generated_dict = self.statistic_declaration_2023_02._get_declaration()
        self._compare_with_truth_base("statistic_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2021_11(self):
        identifier = "is_declaration_2021_11"
        generated_dict = self.is_declaration_2021_11._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2021_12(self):
        identifier = "is_declaration_2021_12"
        generated_dict = self.is_declaration_2021_12._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2022_01(self):
        identifier = "is_declaration_2022_01"
        generated_dict = self.is_declaration_2022_01._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2022_02(self):
        identifier = "is_declaration_2022_02"
        generated_dict = self.is_declaration_2022_02._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2022_03(self):
        identifier = "is_declaration_2022_03"
        generated_dict = self.is_declaration_2022_03._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2022_04(self):
        identifier = "is_declaration_2022_04"
        generated_dict = self.is_declaration_2022_04._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2022_05(self):
        identifier = "is_declaration_2022_05"
        generated_dict = self.is_declaration_2022_05._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2022_06(self):
        identifier = "is_declaration_2022_06"
        generated_dict = self.is_declaration_2022_06._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2022_07(self):
        identifier = "is_declaration_2022_07"
        generated_dict = self.is_declaration_2022_07._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2022_08(self):
        identifier = "is_declaration_2022_08"
        generated_dict = self.is_declaration_2022_08._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2022_09(self):
        identifier = "is_declaration_2022_09"
        generated_dict = self.is_declaration_2022_09._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2022_10(self):
        identifier = "is_declaration_2022_10"
        generated_dict = self.is_declaration_2022_10._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2022_11(self):
        identifier = "is_declaration_2022_11"
        generated_dict = self.is_declaration_2022_11._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2022_12(self):
        identifier = "is_declaration_2022_12"
        generated_dict = self.is_declaration_2022_12._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2023_01(self):
        identifier = "is_declaration_2023_01"
        generated_dict = self.is_declaration_2023_01._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_is_declaration_2023_02(self):
        identifier = "is_declaration_2023_02"
        generated_dict = self.is_declaration_2023_02._get_declaration()
        self._compare_with_truth_base("is_declaration", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_rectificate_2022_01(self):
        identifier = "rectificate_2022_01"
        generated_dict = self.rectificate_2022_01._get_declaration()
        self._compare_with_truth_base("rectificate", identifier, generated_dict)

    @freeze_time("2024-01-01")
    def test_yearly_prospective_2023_01(self):
        identifier = "yearly_prospective_2023_01"
        generated_dict = self.yearly_prospective_2023_01._get_declaration()
        self._compare_with_truth_base("yearly_prospective", identifier, generated_dict)

    @freeze_time("2025-12-16")
    def test_lpp_basis_report_with_employee_creation(self):
        """
        Test employee creation for Swiss company while having duplicate LPP reports.
        """
        swiss_company = self.env.company
        lpp_report_1 = self.env['l10n.ch.lpp.basis.report'].create({
            'year': datetime.now().year,
            'month': str(datetime.now().month),
            'company_id': swiss_company.id,
        })
        lpp_report_2 = lpp_report_1.copy()
        employee = self.env['hr.employee'].create({
            'name': 'Test Employee',
            'company_id': swiss_company.id,
        })
        self.assertTrue(employee.exists())
        self.assertEqual(employee.company_id, swiss_company)
        self.assertEqual(lpp_report_1.year, 2025)
        self.assertEqual(lpp_report_1.month, '12')
        self.assertEqual(lpp_report_2.year, 2025)
        self.assertEqual(lpp_report_2.month, '12')

    @freeze_time("2023-01-01")
    def test_is_declaration_perception_2022_06(self):
        # Load perception commission IS Rates
        rates_to_load = [
            ('BE_PEL', 'BE_PEL.json'),
            ('TI_PEL', 'TI_PEL.json'),
            ('VD_PEL', 'VD_PEL.json'),
        ]
        for xml_id, file_name in rates_to_load:
            rule_parameter = self.env['hr.rule.parameter'].create({
                'name': f'CH Withholding Tax: {xml_id}',
                'code': f'l10n_ch_withholding_tax_rates_{xml_id}',
                'country_id': self.env.ref('base.ch').id,
            })
            self.env['hr.rule.parameter.value'].create({
                'parameter_value': json.load(file_open(f'l10n_ch_hr_payroll/tests/data/is_rates/{file_name}')),
                'rule_parameter_id': rule_parameter.id,
                'date_from': date(2021, 1, 1),
            })

        identifier = "is_declaration_perception_2022_06"
        self.is_declaration_2022_06.action_prepare_data()
        generated_dict = self.is_declaration_2022_06._get_declaration()
        self._compare_with_truth_base("is_declaration_perception", identifier, generated_dict)

    @freeze_time("2023-01-01")
    def test_salary_certificate_remarks(self):
        rule = self.env.ref('l10n_ch_hr_payroll.l10n_ch_elm_rule_7010')
        rule.l10n_ch_salary_certificate = '15'
        employee = self.env['hr.employee'].search([('registration_number', '=', '1'), ('company_id', '=', self.muster_ag_company.id)])
        payslips = self.env['hr.payslip'].search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ['validated', 'paid']),
            ('date_from', '>=', date(2022, 1, 1)),
            ('date_to', '<=', date(2022, 12, 31)),
        ])
        lines = payslips.line_ids.filtered(lambda line: line.salary_rule_id == rule)
        # as named by an input
        lines.name = "Cotisation AVS employeur"
        lines[0].name = "Cotisation AVS employeur (correction)"
        total = sum(lines.mapped('total'))

        self.yearly_retrospective_2022_12.action_prepare_data()
        person = next(
            person for person in self.yearly_retrospective_2022_12.l10n_ch_declare_salary_data['Staff']['Person']
            if person['Particulars']['EmployeeNumber'] == employee.registration_number
        )
        self.assertEqual(
            person['TaxSalaries']['TaxSalary'][0]['Remark'],
            f"Cotisation AVS employeur, Cotisation AVS employeur (correction): {total:.2f} CHF",
            "The total of the rule should be declared in the remarks, named after its payslip lines",
        )


@tagged('post_install_l10n', 'post_install', '-at_install', 'swissdec_payroll')
class TestSourceTaxRounding(TransactionCase):
    """Rule 5060 (Source-Tax), yearly IS model.

    Under the yearly model the rule loops over every tax code the employee had
    during the year, logs one IS line per code through `_log_is_line`, and sums
    the amounts into `total_is`. `_log_is_line` rounds each line to 5 cents, so
    `total_is` has to round each contribution too: rounding only the total makes
    the payslip line disagree with the declaration built from the log lines.
    """

    @classmethod
    @freeze_time("2022-06-30")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Rounding Test AG',
            'country_id': cls.env.ref('base.ch').id,
            'l10n_ch_uid': 'CHE-999.999.996',
        })
        cls.env.user.company_ids |= cls.company
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=cls.company.ids))

        # Flat 10% on any determinant salary, no minimum, for both tax codes:
        # the rate is not what is under test, the rounding of the result is.
        for xml_id in ('VD_N_A_0', 'VD_N_B_0'):
            code = f'l10n_ch_withholding_tax_rates_{xml_id}'
            cls.env['hr.rule.parameter'].search([('code', '=', code)]).unlink()
            rule_parameter = cls.env['hr.rule.parameter'].create({
                'name': f'CH Withholding Tax: {xml_id}',
                'code': code,
                'country_id': cls.env.ref('base.ch').id,
            })
            cls.env['hr.rule.parameter.value'].create({
                'parameter_value': repr([[0, 9999999, 0, 10.0]]),
                'rule_parameter_id': rule_parameter.id,
                'date_from': date(2021, 1, 1),
            })

        # Vaud is one of the cantons settling the source tax yearly.
        cls.employee = cls.env['hr.employee'].create({
            'name': 'IS Rounding Employee',
            'company_id': cls.company.id,
            'country_id': cls.env.ref('base.it').id,
            'birthday': date(1992, 6, 6),
            'marital': 'single',
            'l10n_ch_marital_from': date(1992, 6, 6),
            'l10n_ch_sv_as_number': '756.6508.6893.67',
            'private_street': 'Route de chavannes 11',
            'private_zip': '1007',
            'private_city': 'Lausanne',
            'private_country_id': cls.env.ref('base.ch').id,
            'l10n_ch_canton': 'VD',
            'l10n_ch_municipality': '5586',
            'l10n_ch_residence_category': 'annual-B',
            'l10n_ch_tax_scale': 'A',
            'l10n_ch_tax_scale_type': 'TaxAtSourceCode',
            'l10n_ch_has_withholding_tax': True,
            'date_version': date(2022, 1, 1),
            'contract_date_start': date(2022, 1, 1),
            'wage': 5000.0,
            'structure_type_id': cls.env.ref('l10n_ch_hr_payroll.structure_type_employee_ch').id,
            'l10n_ch_social_insurance_id': cls.env['l10n.ch.social.insurance'].create({
                'name': 'Test Social Insurance',
                'insurance_code': '048.000',
            }).id,
            'l10n_ch_has_monthly': True,
        })
        cls.struct = cls.env.ref('l10n_ch_hr_payroll.hr_payroll_structure_ch_elm')

    def _create_payslip(self, date_from, date_to):
        return self.env['hr.payslip'].create({
            'name': f'Payslip {date_from}',
            'employee_id': self.employee.id,
            'version_id': self.employee.version_id.id,
            'company_id': self.company.id,
            'struct_id': self.struct.id,
            'date_from': date_from,
            'date_to': date_to,
        })

    @freeze_time("2022-06-30")
    def test_yearly_is_model_rounds_every_tax_code(self):
        previous_payslip = self._create_payslip(date(2022, 1, 1), date(2022, 1, 31))
        previous_payslip.action_payslip_done()

        # Year to date salary per tax code, nothing withheld yet. At 10% this
        # gives the two amounts that used to round the wrong way together:
        # 10.01 (-> 10.00) and 0.02 (-> 0.00), but 10.03 as a total (-> 10.05).
        for is_code, is_salary in (('A0N', 100.10), ('B0N', 0.20)):
            self.env['hr.payslip.is.log.line'].create({
                'payslip_id': previous_payslip.id,
                'source_tax_canton': 'VD',
                'source_tax_municipality': '5586',
                'is_code': is_code,
                'code': 'ISSALARY',
                'amount': is_salary,
            })
        self.env.flush_all()

        payslip = self._create_payslip(date(2022, 2, 1), date(2022, 2, 28))
        self.assertEqual(payslip.l10n_ch_is_code, 'VD-A0N-5586')
        self.assertEqual(payslip.l10n_ch_is_model, 'yearly')

        localdict = payslip._get_localdict()
        localdict['result_rules']['ISDTSALARY'] = {
            'total': 5000.0, 'amount': 5000.0, 'quantity': 1, 'rate': 100,
        }
        rule = self.env.ref('l10n_ch_hr_payroll.l10n_ch_elm_rule_5060')
        self.assertTrue(rule._satisfy_condition(localdict))
        amount = rule._compute_rule(localdict)[0]

        logged = payslip.l10n_ch_is_log_line_ids.filtered(lambda line: line.code == 'IS')
        self.assertEqual(
            {line.is_code: line.amount for line in logged},
            {'A0N': 10.00, 'B0N': 0.00},
            "Every tax code is logged rounded to 5 cents",
        )
        # What the employee is deducted has to be what the declaration reports:
        # rounding 10.01 + 0.02 as a whole deducts 10.05 for 10.00 declared.
        self.assertAlmostEqual(
            amount, -sum(logged.mapped('amount')), places=2,
            msg="The IS amount must match the sum of the IS lines it logged",
        )
        self.assertAlmostEqual(amount, -10.00, places=2)
