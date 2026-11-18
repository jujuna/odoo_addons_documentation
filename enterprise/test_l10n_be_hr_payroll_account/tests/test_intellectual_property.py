# Part of Odoo. See LICENSE file for full copyright and licensing details.

import datetime

from odoo.tests.common import tagged

from odoo.addons.l10n_be_hr_payroll.tests.common import TestBelgiumCommon
from odoo.addons.test_l10n_be_hr_payroll_account.tests.common import TestPayslipNoAccountingCommon


@tagged('post_install', '-at_install', 'payslips_validation')
class TestIntellectualProperty(TestPayslipNoAccountingCommon, TestBelgiumCommon):
    """ Intellectual property (IP) rules applicable since 2026:
    - the IP is exempt from ONSS up to 30 % of the total remuneration, unless forced (DmfA code 47)
    - the IP withholding tax (15 %) only applies within that share and while the average IP of the
      4 previous years doesn't exceed the yearly limit, otherwise the IP is a regular remuneration
    - the lump-sum professional costs only remain for the owners of a certificate of artistic work
    - the IP is capped on the yearly limit, the exceeding part being paid as a regular remuneration

    The expected payslip lines are stored in the JSON snapshots of
    tests/test_files/payslips/test_intellectual_property/.
    """

    _test_user_groups = None  # FIXME list needed groups

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.current_payroll_config_id.write({
            'l10n_be_employer_category_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00010').id,
            'l10n_be_main_joint_committee': cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
        })
        cls.env.user.group_ids |= cls.quick_ref('hr_payroll.group_hr_payroll_officer') | cls.quick_ref('hr.group_hr_manager')
        cls._setup_common(
            country=cls.env.ref('base.be'),
            structure=cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary'),
            structure_type=cls.env.ref('hr.structure_type_employee_cp200'),
            tz='Europe/Brussels',
            version_fields={
                'contract_date_start': datetime.date(2018, 12, 31),
                'date_version': datetime.date(2018, 12, 31),
                'wage': 2650.0,
                'ip_wage_rate': 0.25,  # IP = 662.5
                'ip_onss': False,  # ONSS contributions are forced by default: test the exemption
                'l10n_be_joint_committee_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
                'l10n_be_salary_scale_id': cls.env.ref('l10n_be_hr_payroll.cp200_b').id,
            },
            employee_fields={
                'lang': 'fr_BE',  # payslips can only be validated in a Belgian language
            },
        )
        cls.date_from = datetime.date(2026, 3, 1)
        cls.date_to = datetime.date(2026, 3, 31)

    def test_ip_within_limits(self):
        # IP (662.5) below 30 % of the total remuneration (2650): exempt from ONSS (IP.EXEMPT),
        # carved out of the withholding base (IP.PART) and taxed at 15 % (IP.DED)
        payslip = self._generate_payslip(self.date_from, self.date_to)
        self._validate_payslip(payslip)
        self._validate_rule_computed(payslip, 'IP.EXEMPT')
        self._validate_rule_computed(payslip, 'IP.ONSS', expected=False)
        self._validate_rule_computed(payslip, 'ONSS.NO.WT', expected=False)
        payslip.with_context(hr_payroll_force_compute_issue=True)._compute_issues()
        self.assertFalse(payslip.error_count)

    def test_ip_onss_forced(self):
        # the ONSS contributions are forced on the whole IP (IP.ONSS, ONSS.NO.WT), which stays
        # taxed at 15 % net of its ONSS (default behaviour of the contracts)
        self.version.ip_onss = True
        payslip = self._generate_payslip(self.date_from, self.date_to)
        self._validate_payslip(payslip)
        self._validate_rule_computed(payslip, 'IP.EXEMPT', expected=False)
        self._validate_rule_computed(payslip, 'IP.ONSS')
        self._validate_rule_computed(payslip, 'ONSS.NO.WT')

    def test_ip_above_max_share(self):
        # IP (1060) above 30 % of the total remuneration (2650): only the 30 % share is exempt
        # from ONSS and the whole IP is taxed as a regular remuneration
        self.version.ip_wage_rate = 0.4
        payslip = self._generate_payslip(self.date_from, self.date_to)
        self._validate_payslip(payslip)
        self._validate_rule_computed(payslip, 'IP.EXEMPT')
        for code in ['IP.PART', 'IP.ONSS', 'ONSS.NO.WT', 'GROSSIP', 'IP', 'IP.DED']:
            self._validate_rule_computed(payslip, code, expected=False)

    def test_ip_artist_flat_rate_costs(self):
        # 50 % lump-sum costs within the first bracket (20590 in 2026)
        self.version.ip_artist = True
        payslip = self._generate_payslip(self.date_from, self.date_to)
        self._validate_payslip(payslip)

    def test_ip_artist_flat_rate_costs_brackets(self):
        # the brackets are yearly amounts: 50 % up to 500, 25 % up to 1000, nothing above
        self.version.ip_artist = True
        self._add_rule_parameter_value('ip_deduction_bracket_1', 500, datetime.date(2026, 2, 1))
        self._add_rule_parameter_value('ip_deduction_bracket_2', 1000, datetime.date(2026, 2, 1))
        payslip = self._generate_payslip(self.date_from, self.date_to)
        self._validate_payslip(payslip)

    def test_ip_previous_years_average_above_limit(self):
        # the average IP of the 4 previous years (5000 / 4) exceeds the yearly limit (1000): the IP
        # is a regular remuneration for the withholding tax but remains exempt from ONSS
        self.employee.write({'review_state': '1_reviewed'})
        self.version.wage = 20000.0  # IP = 5000
        payslip_2025 = self._generate_payslip(datetime.date(2025, 12, 1), datetime.date(2025, 12, 31))
        self._validate_payslip(payslip_2025)
        payslip_2025.action_payslip_done()
        self.assertEqual(payslip_2025.state, 'validated')
        self.version.wage = 2650.0
        self._add_rule_parameter_value('ip_limit', 1000, datetime.date(2026, 2, 1))

        payslip = self._generate_payslip(self.date_from, self.date_to)
        self._validate_payslip(payslip)
        self._validate_rule_computed(payslip, 'IP.EXEMPT')
        for code in ['IP.PART', 'IP.ONSS', 'ONSS.NO.WT', 'GROSSIP', 'IP', 'IP.DED']:
            self._validate_rule_computed(payslip, code, expected=False)

    def test_ip_yearly_limit_reached(self):
        # the yearly limit caps the IP: 500 out of the 662.5 are paid as IP, the rest as a regular
        # remuneration, with a non-blocking warning
        self.employee.write({'review_state': '1_reviewed'})
        self._add_rule_parameter_value('ip_limit', 500, datetime.date(2026, 2, 1))
        payslip = self._generate_payslip(self.date_from, self.date_to)
        self._validate_payslip(payslip)
        self.assertAlmostEqual(payslip.line_ids.filtered(lambda l: l.code == 'IP').total, 500, 2)
        payslip.with_context(hr_payroll_force_compute_issue=True)._compute_issues()
        self.assertFalse(payslip.error_count)
        messages = [issue['message'] for issue in payslip.issues.values()]
        self.assertTrue(any('intellectual property limit' in message for message in messages), messages)
        payslip.action_payslip_done()
        self.assertEqual(payslip.state, 'validated')

        # the limit is reached: the whole IP of the next payslip is a regular remuneration
        payslip = self._generate_payslip(datetime.date(2026, 4, 1), datetime.date(2026, 4, 30))
        self._validate_payslip(payslip)
        for code in ['IP.EXEMPT', 'IP.PART', 'IP.ONSS', 'ONSS.NO.WT', 'GROSSIP', 'IP', 'IP.DED']:
            self._validate_rule_computed(payslip, code, expected=False)
        payslip.with_context(hr_payroll_force_compute_issue=True)._compute_issues()
        self.assertFalse(payslip.error_count)
        messages = [issue['message'] for issue in payslip.issues.values()]
        self.assertTrue(any('intellectual property limit' in message for message in messages), messages)

    def test_ip_previous_years_average_without_start_year(self):
        # The average of the 4 previous years leaves out the year the activity started in: started in 2025, the
        # employee has no complete previous year in 2026 and the IP of 2025 (5000) doesn't make it exceed the
        # yearly limit (1000)
        self.employee.write({'review_state': '1_reviewed'})
        self.version.write({'contract_date_start': datetime.date(2025, 6, 1), 'date_version': datetime.date(2025, 6, 1)})
        self.assertEqual(self.employee.first_contract_date, datetime.date(2025, 6, 1))
        self.version.wage = 20000.0  # IP = 5000
        payslip_2025 = self._generate_payslip(datetime.date(2025, 12, 1), datetime.date(2025, 12, 31))
        payslip_2025.action_payslip_done()
        self.version.wage = 2650.0
        self._add_rule_parameter_value('ip_limit', 1000, datetime.date(2026, 2, 1))

        payslip = self._generate_payslip(self.date_from, self.date_to)
        for code in ['IP.EXEMPT', 'IP.PART', 'IP', 'IP.DED']:
            self._validate_rule_computed(payslip, code)

    def test_ip_max_share_of_the_year(self):
        # The 30 % share is assessed on the year: 848 of IP (32 % of 2650) on the April payslip, but 662.5 + 848 =
        # 1510.5 of IP for 5300 of remuneration since January (28.5 %): the IP withholding tax applies
        self.employee.write({'review_state': '1_reviewed'})
        payslip_march = self._generate_payslip(self.date_from, self.date_to)
        payslip_march.action_payslip_done()
        self.assertEqual(payslip_march.state, 'validated')
        self.version.ip_wage_rate = 0.32
        payslip = self._generate_payslip(datetime.date(2026, 4, 1), datetime.date(2026, 4, 30))
        self.assertAlmostEqual(payslip.line_ids.filtered(lambda l: l.code == 'IP').total, 848, 2)
        for code in ['IP.EXEMPT', 'IP.PART', 'IP', 'IP.DED']:
            self._validate_rule_computed(payslip, code)

        # Above 30 % of the remuneration of the year, the IP is a regular remuneration
        self.version.ip_wage_rate = 0.4
        payslip.compute_sheet()
        for code in ['IP.PART', 'IP', 'IP.DED']:
            self._validate_rule_computed(payslip, code, expected=False)

    def test_ip_indexed_amounts(self):
        # Indexed amounts of the income years (SPF Finances, explications IPP, cadre VII D): the lump-sum cost
        # brackets and the yearly limit (since 2023)
        expected = {
            2018: (15990, 31990, None),
            2019: (16320, 32640, None),
            2020: (16560, 33110, None),
            2021: (16680, 33360, None),
            2022: (17090, 34170, None),
            2023: (18720, 37450, 70220),
            2024: (19480, 38970, 73070),
            2025: (20100, 40190, 75360),
            2026: (20590, 41180, 77220),
        }
        parameter = self.env['hr.rule.parameter']
        for year, (bracket_1, bracket_2, limit) in expected.items():
            day = datetime.date(year, 6, 1)
            self.assertEqual(parameter._get_parameter_from_code('ip_deduction_bracket_1', day), bracket_1, year)
            self.assertEqual(parameter._get_parameter_from_code('ip_deduction_bracket_2', day), bracket_2, year)
            self.assertEqual(
                parameter._get_parameter_from_code('ip_limit', day, raise_if_not_found=False) or None, limit, year)

    def test_ip_above_max_share_2024(self):
        # The 30 % share of the withholding tax applies since the income year 2024: IP (1060) above 30 % of the
        # remuneration (2650) in 2024 is a regular remuneration. The ONSS exemption only exists since 2026.
        self.version.ip_wage_rate = 0.4
        payslip = self._generate_payslip(datetime.date(2024, 3, 1), datetime.date(2024, 3, 31))
        for code in ['IP.EXEMPT', 'IP.PART', 'GROSSIP', 'IP', 'IP.DED']:
            self._validate_rule_computed(payslip, code, expected=False)
        # The share doesn't exist in 2023
        payslip = self._generate_payslip(datetime.date(2023, 3, 1), datetime.date(2023, 3, 31))
        for code in ['IP.PART', 'IP', 'IP.DED']:
            self._validate_rule_computed(payslip, code)
