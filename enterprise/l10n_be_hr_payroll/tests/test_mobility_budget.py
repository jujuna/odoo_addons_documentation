# Part of Odoo. See LICENSE file for full copyright and licensing details.

from freezegun import freeze_time
from odoo.tests import tagged
from odoo.addons.l10n_be_hr_payroll.tests.common import TestPayrollCommon


@tagged('post_install', '-at_install', 'post_install_l10n')
class TestMobilityBudget(TestPayrollCommon):

    @freeze_time('2026-08-31')
    def test_refund_payslip_with_mobility_budget(self):
        self.employee_a.version_id.write({
            'l10n_be_mobility_budget': True,
            'l10n_be_mobility_budget_amount': 6000,
        })
        payslip = self.create_and_validate_payslips(self.employee_a, 2026, 8)
        remaining_budget = payslip._get_line_values(['MOBILITY_REMAINING'])['MOBILITY_REMAINING'][payslip.id]['total']
        self.assertGreater(remaining_budget, 0)

        # Refunding reverses the balance and must not block validation.
        refund = payslip._action_refund_payslips()
        self.assertTrue(refund.is_refund_payslip)
