# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo.addons.hr_payroll.tests.common import TestPayslipBase
from odoo.tests import tagged, HttpCase
from odoo.fields import Date


@tagged('post_install', '-at_install')
class TestPayrunFlow(TestPayslipBase, HttpCase):

    def test_payrun_flow(self):
        self._sealand_fake_country_setup()
        self.start_tour("/odoo", 'payroll_payrun_tour', login="admin")

    def _setup_for_branch_company_selection(self, country_id):
        self.parent_company = self.env['res.company'].create({
            'name': 'Parent Company',
            'country_id': country_id,
        })
        self.branch_company = self.env['res.company'].create({
            'name': 'Branch Company',
            'country_id': country_id,
            'parent_id': self.parent_company.id,
        })
        self.env = self.env(context=dict(
            self.env.context,
            company_id=self.parent_company.id,
            allowed_company_ids=[self.parent_company.id, self.branch_company.id]
        ))
        self.structure_type = self.env['hr.payroll.structure.type'].create({
            'name': 'Test Structure Type',
        })
        self.developer_pay_structure = self.env['hr.payroll.structure'].create({
            'name': 'Test Salary Structure',
            'type_id': self.structure_type.id,
            'sequence': 1,
        })
        self.employee_faruk = self.env['hr.employee'].create({
            'name': 'test Faruk',
            'employee_type_id': self.env.ref('hr.contract_type_employee').id,
            'country_id': country_id,
            'company_id': self.branch_company.id,
            'date_version': Date.to_date('2026-01-01'),
            'contract_date_start': Date.to_date('2026-01-01'),
            'wage': 5000,
            'structure_type_id': self.structure_type.id,
        })
        self.user_admin = self.env.ref('base.user_admin')
        self.user_admin.company_ids |= self.parent_company | self.branch_company
        self.user_admin.write({
            'company_id': self.parent_company.id,
            'email': 'mitchell.admin@example.com',
        })

    def test_branch_company_selection_payrun(self):
        self._setup_for_branch_company_selection(self.env.ref('base.us').id)
        self.start_tour("/odoo", 'branch_company_selection_payrun_tour', login="admin")
