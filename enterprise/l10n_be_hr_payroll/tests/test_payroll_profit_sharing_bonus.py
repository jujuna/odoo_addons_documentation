# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from freezegun import freeze_time

from odoo.tests import tagged

from odoo.addons.hr_payroll.tests.common import TestPayrollBase
from odoo.addons.l10n_be_hr_payroll.tests.common import TestBelgiumCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'profit_sharing_bonus')
class TestPayrollProfitSharingBonus(TestPayrollBase, TestBelgiumCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        resource_calendar = cls.env['resource.calendar'].create({
                'name': 'Test Calendar',
                'attendance_ids': [(5, 0, 0),
                    (0, 0, {'dayofweek': '0', 'duration_hours': 7.6, 'hour_from': 0, 'hour_to': 0}),
                    (0, 0, {'dayofweek': '1', 'duration_hours': 7.6, 'hour_from': 0, 'hour_to': 0}),
                    (0, 0, {'dayofweek': '2', 'duration_hours': 7.6, 'hour_from': 0, 'hour_to': 0}),
                    (0, 0, {'dayofweek': '3', 'duration_hours': 7.6, 'hour_from': 0, 'hour_to': 0}),
                    (0, 0, {'dayofweek': '4', 'duration_hours': 7.6, 'hour_from': 0, 'hour_to': 0}),
                ]
            })
        cls._setup_common(
            country=cls.env.ref('base.be'),
            structure=cls.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_profit_sharing_bonus'),
            structure_type=cls.env.ref('hr.structure_type_employee_cp200'),
            resource_calendar=resource_calendar,
            version_fields={
                'name': 'A',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'contract_date_end': False,
                'wage': 2500.0,
                'l10n_be_worker_code_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00495').id,
            }
        )

    @freeze_time('2025-01-25')
    def test_profit_sharing_bonus_low(self):
        payslip = self._generate_payslip(date(2025, 1, 1), date(2025, 1, 31), input_values={'PROFITSHARINGLOW': 2452.87})
        payslip_results = {'PROFITSHARINGLOW': 2452.87, 'BEPROFITSHARING_BASIC': 2452.87, 'PROFITSHARING_SALARY': 2452.87, 'ONSS_PROFITSHARING': -320.59, 'ONSSTOTAL': 320.59, 'PROFITSHARINGLOW.PP': -149.26, 'PPTOTAL': 149.26, 'NET': 1983.02}
        self._validate_payslip(payslip, payslip_results)

    @freeze_time('2025-01-25')
    def test_profit_sharing_bonus_high(self):
        payslip = self._generate_payslip(date(2025, 1, 1), date(2025, 1, 31), input_values={'PROFITSHARINGHIGH': 2452.87})
        payslip_results = {'PROFITSHARINGHIGH': 2452.87, 'BEPROFITSHARING_BASIC': 2452.87, 'PROFITSHARING_SALARY': 2452.87, 'ONSS_PROFITSHARING': -320.59, 'ONSSTOTAL': 320.59, 'PROFITSHARINGHIGH.PP': -319.84, 'PPTOTAL': 319.84, 'NET': 1812.44}
        self._validate_payslip(payslip, payslip_results)

    @freeze_time('2025-01-25')
    def test_profit_sharing_bonus_no_withholding_tax(self):
        payslip = self._generate_payslip(date(2025, 1, 1), date(2025, 1, 31))
        payslip.version_id.no_withholding_taxes = True
        payslip._set_input_values({
            'PROFITSHARINGLOW': 2452.87,
            'PROFITSHARINGHIGH': 2452.87,
        })
        payslip.compute_sheet()
        payslip_results = {'PROFITSHARINGLOW': 2452.87, 'BEPROFITSHARING_BASIC': 4905.74, 'PROFITSHARINGHIGH': 2452.87, 'PROFITSHARING_SALARY': 4905.74, 'ONSS_PROFITSHARING': -641.18, 'ONSSTOTAL': 641.18, 'PPTOTAL': 0.0, 'NET': 4264.56}
        self._validate_payslip(payslip, payslip_results)

    @freeze_time('2025-01-25')
    def test_profit_sharing_bonus_low_and_high(self):
        # The solidarity contribution is computed on both bonuses: each withholding
        # tax base must only be reduced by the contribution on its own bonus.
        payslip = self._generate_payslip(date(2025, 1, 1), date(2025, 1, 31))
        payslip._set_input_values({
            'PROFITSHARINGLOW': 1000.0,
            'PROFITSHARINGHIGH': 1000.0,
        })
        payslip.compute_sheet()
        payslip_results = {'PROFITSHARINGLOW': 1000.0, 'BEPROFITSHARING_BASIC': 2000.0, 'PROFITSHARINGHIGH': 1000.0, 'PROFITSHARING_SALARY': 2000.0, 'ONSS_PROFITSHARING': -261.4, 'ONSSTOTAL': 261.4, 'PROFITSHARINGLOW.PP': -60.85, 'PROFITSHARINGHIGH.PP': -130.4, 'PPTOTAL': 191.25, 'NET': 1547.35}
        self._validate_payslip(payslip, payslip_results)

    @freeze_time('2025-01-25')
    def test_profit_sharing_bonus_student(self):
        # The solidarity contribution is 13.07% of the bonus, students included.
        payslip = self._generate_payslip(date(2025, 1, 1), date(2025, 1, 31))
        payslip.version_id.l10n_be_dimona_category = 'stu'
        payslip._set_input_value('PROFITSHARINGLOW', 1000.0)
        payslip.compute_sheet()
        payslip_results = {'PROFITSHARINGLOW': 1000.0, 'BEPROFITSHARING_BASIC': 1000.0, 'PROFITSHARING_SALARY': 1000.0, 'ONSS_PROFITSHARING': -130.7, 'ONSSTOTAL': 130.7, 'PROFITSHARINGLOW.PP': -60.85, 'PPTOTAL': 60.85, 'NET': 808.45}
        self._validate_payslip(payslip, payslip_results)
