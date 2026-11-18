# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import Command
from odoo.tests import new_test_user, tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestSalaryBenefit(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.payroll_manager = new_test_user(
            cls.env, login='payroll_manager', groups='base.group_user,hr_payroll.group_hr_payroll_manager')
        cls.structure_type = cls.env['hr.payroll.structure.type'].create({'name': 'Benefit Test Structure Type'})
        cls.view = cls.env['ir.ui.view'].create({
            'name': 'Benefit Test View',
            'type': 'qweb',
            'arch': '<t t-name="hr_payroll.benefit_test_view"><div/></t>',
        })

    def test_payroll_manager_toggles_benefit_views(self):
        """ A payroll manager without ir.ui.view access can create and (un)archive
        a benefit, and its related views follow the benefit's active state. """
        self.assertFalse(self.payroll_manager.has_group('base.group_system'))

        benefit = self.env['hr.contract.salary.benefit'].with_user(self.payroll_manager).create({
            'name': 'Archived Benefit',
            'active': False,
            'structure_type_id': self.structure_type.id,
            'view_ids': [Command.link(self.view.id)],
        })
        self.assertFalse(self.view.active)

        benefit.write({'active': True})
        self.assertTrue(self.view.active)

        benefit.write({'active': False})
        self.assertFalse(self.view.active)
