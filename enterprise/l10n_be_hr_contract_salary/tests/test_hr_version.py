from freezegun import freeze_time

from odoo.tests import tagged, Form

from odoo.addons.http_routing.tests.common import MockRequest
from odoo.addons.l10n_be_hr_contract_salary.controllers.main import HrContractSalary
from odoo.addons.l10n_be_hr_payroll.tests.test_hr_version import TestPayrollHrVersion


@tagged('-at_install', 'post_install', 'post_install_l10n', 'salary')
class TestHrVersion(TestPayrollHrVersion):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employment_sign_template = cls.env['sign.template'].create({
            'name': 'Test Employment Contract',
            'tag_ids': [cls.env.ref('sign.sign_template_tag_1').id]
        })

    @freeze_time('2025-12-01')
    def test_no_dimona_version_write_salary_simulation(self):
        """ Assert no dimona action is triggered when writing on a version while we are in a `hr_version_context` """
        self.test_company.l10n_be_dimona_environment = 'sandbox'
        self.student_emp.niss = '19082624244'

        # Assert no dimona has been created for that employee
        self.assertFalse(self.student_emp.l10n_be_last_dimona_declaration_id)
        self.assertEqual(len(self.student_emp.version_ids), 1)
        student_version = self.student_emp.version_ids[0].with_company(self.test_company)

        # Simulate a `hr_version_context` by setting 'salary_simulation' in the context
        # Assert writing on the employee with 'salary_simulation' set doesn't trigger a dimona action
        student_version.with_context(salary_simulation=True).write({
            'private_zip': 1367,
            'l10n_be_dimona_next_action': 'in',
            'l10n_be_dimona_planned_hours': 1,
            'contract_date_start': "2026-01-01",
            'contract_date_end': "2026-01-02",
        })
        self.assertFalse(self.student_emp.l10n_be_last_dimona_declaration_id, 'No dimona action should be triggered here!')

        # Assert creating a new offer doesn't trigger a dimona action
        with freeze_time('2026-01-02'):
            action_generate_offer = self.student_emp.action_generate_offer()
            with Form.from_action(self.student_emp.env, action_generate_offer) as offer_form:
                offer_form.sign_template_id = self.employment_sign_template
                offer_form.contract_end_date = '2026-01-03'
                offer_form.contract_end_date = '2026-01-03'

        self.assertFalse(self.student_emp.l10n_be_last_dimona_declaration_id, 'No dimona action should be triggered here!')

        # Assert writing on the version without 'salary_simulation' triggers a dimona action
        student_version.write({
            'contract_date_start': "2026-01-02",
        })
        self.assertTrue(self.student_emp.l10n_be_last_dimona_declaration_id, 'A dimona action should\'ve been triggered!')

    def test_salary_configurator_new_bike(self):
        version = self.employee.version_id
        bike_model = self._create_bike_model()
        version.write(version._get_benefit_values_company_bike_depreciated_cost({}, {
            'fold_company_bike_depreciated_cost': True,
            'select_company_bike_depreciated_cost': f'new-{bike_model.id}',
        }))
        self.assertTrue(version.transport_mode_bike)
        self.assertTrue(version.new_bike)
        self.assertEqual(version.company_bike_depreciated_cost, 50.0)
        # Still requested (and costing the employer) after a recompute of "Uses company bike"
        version.new_bike = True
        self.assertEqual(version.new_bike_model_id, bike_model)
        self.assertEqual(version.company_bike_depreciated_cost, 50.0)

    def test_salary_configurator_student_eco_checks(self):
        offer = self.env['hr.contract.salary.offer'].create({
            'employee_id': self.student_emp.id,
            'company_id': self.test_company.id,
        })
        with MockRequest(self.env):
            initial_values = HrContractSalary()._get_benefits_values(self.student_emp.version_id, offer)[-1]
        self.assertEqual(initial_values['eco_checks'], 0)

    def test_private_bicycle_cost(self):
        version = self.employee.version_id
        self.employee.km_home_work = 50
        self.assertEqual(version.l10n_be_bicyle_cost, 0)
        bike = self.env['fleet.vehicle'].create({
            'model_id': self._create_bike_model().id,
            'company_id': self.employee.company_id.id,
        })
        # The bicycle allowance is also due to the employees riding a company bike
        self.employee.bike_id = bike
        version.invalidate_recordset(['l10n_be_bicyle_cost'])
        with freeze_time('2026-05-01'):
            # 4 x min(10.80 € daily cap, 0.27 € x 50 km x 2)
            self.assertAlmostEqual(version.l10n_be_bicyle_cost, 43.2, places=2)
            self.assertAlmostEqual(self.env['hr.version']._get_private_bicycle_cost(50), 43.2, places=2)
