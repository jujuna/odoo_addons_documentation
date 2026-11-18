# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo.tests import tagged

from odoo.addons.l10n_be_hr_payroll.tests.common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestHrContractNoONSS(TestPayrollCommon):

    _minimal_payroll_setup = True

    def test_employer_cost_no_onss(self):
        """
        Test that the employer cost computation is correct when we have a posted employee with no ONSS
        """
        contract = self.georges_contracts[0]
        self.assertAlmostEqual(contract.l10n_be_group_insurance_rate, 0) # To ensure correct computation of yearly cost
        prev_yearly_cost = contract.final_yearly_costs
        employer_onss_rate = contract._l10n_be_get_employer_onss_rate()
        contract.write({
            'l10n_be_dimona_category': 'dwd',  # DWD is a dimona category with no ONSS
        })
        new_yearly_cost = contract.final_yearly_costs
        correct_yearly_cost = prev_yearly_cost - (contract.wage * 13 * employer_onss_rate)
        self.assertAlmostEqual(new_yearly_cost, correct_yearly_cost)
