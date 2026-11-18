# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from unittest.mock import patch

from odoo.tests import tagged

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestPayrollConfigBranches(TestPayrollCommon):

    def test_root_changes_reach_the_branches(self):
        """ The branches follow the changes of the payroll settings of the root company, except for the fields
        they set themselves """
        root, branch = self.multibranch_company[:2]
        root_config, branch_config = root.current_payroll_config_id, branch.current_payroll_config_id
        self.assertEqual(branch_config.parent_id, root_config)
        root_config.write({
            'onss_importance_code': '4',
            'l10n_be_in_difficulty': True,
            'group_insurance_name': 'Root Insurer',
            'worker_accident_insurance_name': 'Root Accident Insurer',
        })
        branch_config.worker_accident_insurance_name = 'Branch Accident Insurer'
        self.assertEqual(branch_config.onss_importance_code, '4')
        self.assertEqual(branch_config.group_insurance_name, 'Root Insurer')

        # The company has now 50 workers, and is not in difficulty anymore
        root_config.write({
            'onss_importance_code': '5',
            'l10n_be_in_difficulty': False,
            'group_insurance_name': 'New Root Insurer',
            'worker_accident_insurance_name': 'New Root Accident Insurer',
        })
        self.assertEqual(branch_config.onss_importance_code, '5')
        self.assertFalse(branch_config.l10n_be_in_difficulty)
        self.assertEqual(branch_config.group_insurance_name, 'New Root Insurer')
        self.assertEqual(branch_config.worker_accident_insurance_name, 'Branch Accident Insurer')

        # Nothing is written on the branches when nothing changes for them: their payslips would be flagged as
        # computed with an outdated configuration
        config_class = self.registry['payroll.config.settings']
        with patch.object(config_class, 'write', autospec=True, side_effect=config_class.write) as write:
            root_config.write({'onss_importance_code': '5'})
        self.assertNotIn(branch_config, [call.args[0] for call in write.call_args_list])

    def test_new_branch_follows_the_latest_settings(self):
        """ A branch created after a change of the payroll settings of the root company gets them """
        root = self.multibranch_company[0]
        # the branch is paid since then, as its root company
        root.first_payrun_date = date(2020, 1, 1)
        root.current_payroll_config_id.onss_importance_code = '4'
        root.create_payroll_config(date_version=date(2025, 1, 1)).onss_importance_code = '6'
        branch = self.env['res.company'].create({'name': 'New Branch', 'parent_id': root.id})
        branch_config = branch._get_payroll_config(date(2026, 1, 1))
        self.assertEqual(branch_config.parent_id, root._get_payroll_config(date(2026, 1, 1)))
        self.assertEqual(branch_config.onss_importance_code, '6')

    def test_version_change_recomputes_branch_payslips(self):
        """ Changing the wage of an employee of a branch from its root company recomputes the draft payslips """
        root, branch = self.multibranch_company[:2]
        self.env.user.company_ids |= root | branch
        employee = self.create_employee([{
            'name': 'Branch Worker',
            'company_id': branch.id,
            'contract_date_start': date(2025, 1, 1),
            'wage': 3000,
        }])
        payslip = self.env['hr.payslip'].create({
            'name': 'Branch payslip',
            'employee_id': employee.id,
            'company_id': branch.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'version_id': employee.version_id.id,
        })
        payslip.compute_sheet()
        self.assertEqual(payslip._get_line_values(['BASIC'])['BASIC'][payslip.id]['total'], 3000)
        employee.version_id.with_company(root).wage = 3500
        self.assertEqual(payslip._get_line_values(['BASIC'])['BASIC'][payslip.id]['total'], 3500)
