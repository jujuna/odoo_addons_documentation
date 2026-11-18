# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

import odoo.tests
from odoo.addons.hr_contract_salary.tests.test_salary_package import TestSalaryPackageItems


@odoo.tests.tagged('post_install_l10n', '-at_install', 'post_install')
class TestContractCompanyCar(TestSalaryPackageItems):

    def test_review_contract_and_sign_with_company_car(self):
        """ Clicking 'Review Contract & Sign' on a CP200 offer with a company car must succeed. """
        # Switch the seeded employee to a Belgian CP200 contract so the ATN.CAR rule applies.
        cp200 = self.env.ref('hr.structure_type_employee_cp200')
        active_version = self.env['hr.version'].search(
            [('employee_id', '=', self.employee.id), ('active', '=', True)], limit=1,
        )
        # Activate the JC200
        jc_200 = self.env['l10n.be.joint.committee'].with_context(active_test=False).search([('egov3_code', '=', '200')], limit=1)
        jc_200.active = True

        # Create a minimal company car the candidate can select on the configurator page.
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'Test Brand'})
        model = self.env['fleet.vehicle.model'].create({'name': 'Test Model', 'brand_id': brand.id})
        car = self.env['fleet.vehicle'].create({'model_id': model.id, 'company_id': self.company_id.id})
        # Link the contract to the CP200 structure + sign template + the chosen company car.
        active_version.write({
            'structure_type_id': cp200.id,
            'wage': 3000,
            'contract_date_start': date.today(),
            'transport_mode_car': True,
            'car_id': car.id,
            'sign_template_id': self.template.id,
            'contract_update_template_id': self.template.id,
            'hr_responsible_id': self.env.ref('base.user_admin').id,
        })
        # Create a payslip and call compute_sheet in a simulation context.
        # Before the fix, this raised KeyError('origin_version_id') due to missing origin_version_id in the simulation context.
        payslip = self.env['hr.payslip'].with_context(salary_simulation=True).create({
            'name': 'Simulation Payslip',
            'employee_id': self.employee.id,
            'version_id': active_version.id,
            'struct_id': cp200.default_struct_id.id,
            'company_id': self.company_id.id,
        })
        payslip.with_context(salary_simulation=True).compute_sheet()
        self.assertTrue(payslip.line_ids, "The payslip should be successfully computed and have lines.")

    def test_payroll_car_assignment_sets_future_driver_only(self):
        """ Selecting a car on payroll, just sets future_driver_id. """
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'Test Brand'})
        model = self.env['fleet.vehicle.model'].create({'name': 'Test Model', 'brand_id': brand.id})
        car = self.env['fleet.vehicle'].create({'model_id': model.id, 'company_id': self.company_id.id})

        active_version = self.env['hr.version'].search(
            [('employee_id', '=', self.employee.id), ('active', '=', True)], limit=1,
        )

        active_version.write({
            'transport_mode_car': True,
            'car_id': car.id,
        })

        work_contact = self.employee.work_contact_id
        self.assertEqual(
            car.future_driver_id, work_contact,
            "Employee should become the car's future_driver_id when selected on the version."
        )
        self.assertFalse(
            car.driver_id,
            "Driver (driver_id) must NOT be auto-assigned upon payroll selection."
        )

    def test_sign_item_vehicle_auto_value(self):
        """ The car and bike sign items of a version are filled with the name of the vehicle. """
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'Test Brand'})
        car_model, new_car_model, bike_model, new_bike_model = self.env['fleet.vehicle.model'].create([{
            'name': name,
            'brand_id': brand.id,
            'vehicle_type': vehicle_type,
        } for name, vehicle_type in [
            ('Car Model', 'car'), ('New Car Model', 'car'), ('Bike Model', 'bike'), ('New Bike Model', 'bike'),
        ]])
        car, bike = self.env['fleet.vehicle'].create([
            {'model_id': car_model.id, 'company_id': self.company_id.id},
            {'model_id': bike_model.id, 'company_id': self.company_id.id},
        ])
        version = self.env['hr.version'].search(
            [('employee_id', '=', self.employee.id), ('active', '=', True)], limit=1,
        )
        sign_request_item = self.env['sign.request.item']

        def get_auto_value(vehicule):
            return sign_request_item._get_vehicule_auto_value(
                'Default', version, f'transport_mode_{vehicule}', vehicule=vehicule)

        version.write({
            'transport_mode_car': True,
            'car_id': car.id,
            'transport_mode_bike': True,
            'bike_id': bike.id,
        })
        self.assertEqual(get_auto_value('car'), car.name)
        self.assertEqual(get_auto_value('bike'), bike.name)

        version.write({
            'car_id': False,
            'has_new_car': True,
            'new_car_model_id': new_car_model.id,
            'bike_id': False,
            'new_bike': True,
            'new_bike_model_id': new_bike_model.id,
        })
        self.assertEqual(get_auto_value('car'), new_car_model.name)
        self.assertEqual(get_auto_value('bike'), new_bike_model.name)
