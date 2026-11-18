from odoo.tests import tagged

from odoo.addons.geo_payroll.models.res_company import CORE_GE_PAYROLL, ResCompany

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestCoreGePayroll(GeoPayrollCase):
    def test_new_georgian_company_never_gets_odoos_georgian_payroll(self):
        Module = self.env['ir.module.module']
        payroll = Module.search([('name', '=', CORE_GE_PAYROLL)])
        payroll_account = Module.search([('name', '=', 'l10n_ge_hr_payroll_account')])
        self.assertTrue(payroll and payroll_account)
        company = self.env['res.company'].create({'name': self._next_name('GEO Core Company'), 'country_id': self.env.ref('base.ge').id})
        # Odoo lists a Georgian module only while it is uninstalled and its automatic dependencies are installed.
        payroll.state = payroll_account.state = 'uninstalled'
        self.env.flush_all()
        super(ResCompany, company)._compute_uninstalled_l10n_module_ids()
        self.assertEqual(company.uninstalled_l10n_module_ids & (payroll | payroll_account), payroll)
        company.invalidate_recordset(['uninstalled_l10n_module_ids'])
        self.assertFalse(company.uninstalled_l10n_module_ids & (payroll | payroll_account))

    def test_retire_moves_free_contracts_and_archives_when_none_is_left(self):
        core_type = self.env.ref('l10n_ge_hr_payroll.structure_type_employee_ge', raise_if_not_found=False)
        if not core_type:
            self.skipTest("Odoo's Georgian payroll is not installed")
        core_structure = self.env.ref('l10n_ge_hr_payroll.hr_payroll_structure_ge_employee_salary')
        Version = self.env['hr.version'].with_context(active_test=False)
        Version.search([('structure_type_id', '=', core_type.id)]).structure_type_id = self.structure_types['monthly']
        free = self._make_employee('fixed', structure_type=core_type).version_id
        opted_out = self._make_employee('fixed', structure_type=core_type, l10n_ge_pension_status='opted_out').version_id
        net_salary = self._make_employee('fixed', structure_type=core_type, l10n_ge_net_salary=True).version_id
        privileged = self._make_employee('fixed', structure_type=core_type, l10n_ge_tax_privilege='a').version_id
        used_employee = self._make_employee('fixed', structure_type=core_type)
        payslip = self._make_payslip(used_employee, structure=core_structure)
        Type = self.env['hr.payroll.structure.type']
        Type._gec_retire_core_ge_structure()
        self.assertEqual((free | opted_out).structure_type_id, self.structure_types['monthly'])
        self.assertTrue(free.employee_id.pension_fund_member)
        self.assertFalse(opted_out.employee_id.pension_fund_member)
        self.assertEqual((net_salary | privileged | used_employee.version_id).structure_type_id, core_type)
        self.assertFalse(((net_salary | privileged).employee_id | used_employee).pension_fund_member)
        self.assertTrue(core_type.active and core_structure.active)
        self.assertEqual(Type.search([('country_id', '=', core_type.country_id.id)], limit=1), self.structure_types['monthly'])
        payslip.unlink()
        Type._gec_retire_core_ge_structure()
        self.assertEqual(used_employee.version_id.structure_type_id, self.structure_types['monthly'])
        self.assertEqual((net_salary | privileged).structure_type_id, core_type)
        self.assertTrue(core_type.active and core_structure.active)
        (net_salary | privileged).structure_type_id = self.structure_types['monthly']
        Type._gec_retire_core_ge_structure()
        self.assertFalse(core_type.active or core_structure.active)
