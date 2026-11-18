# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from freezegun import freeze_time

from odoo.tests import tagged
from odoo.addons.l10n_be_hr_payroll.tests.common import TestPayrollCommon


@tagged('post_install', '-at_install', 'post_install_l10n')
class TestPayrollFuelCardPrivateUse(TestPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'Company Car Brand'})
        cls.car_model = cls.env['fleet.vehicle.model'].create({
            'name': 'Company Car Model',
            'brand_id': brand.id,
            'default_car_value': 30000.0,
            'default_fuel_type': 'diesel',
            'default_co2': 120.0,
        })

    def _create_employee_with_car(self, name, driver=True):
        employee = self.create_employee({
            'name': name,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'contract_date_end': False,
        })
        car = self.env['fleet.vehicle'].create({
            'model_id': self.car_model.id,
            'company_id': self.belgian_company.id,
            'acquisition_date': date(2025, 1, 1),
            'car_value': 30000.0,
            'fuel_type': 'diesel',
            'co2': 120.0,
            'driver_employee_id': driver and employee.id,
        })
        return employee, car

    def _create_payslip(self, employee):
        return self.env['hr.payslip'].create({
            'name': f"Payslip {employee.name} 2026-01",
            'employee_id': employee.id,
            'company_id': employee.company_id.id,
            'version_id': employee.version_id.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
        })

    def test_fuel_card_personal_use_default_applied_to_payslip(self):
        with freeze_time('2026-01-20'):
            employee = self.create_employee({
                'name': 'Fuel Card Private Use employee',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'contract_date_end': False,
                'fuel_card': 150.0,
                'fuel_card_personal_use': 50.0,
            })
            version = employee.version_id
            self.assertFalse(version.car_id, "Expected no company car on this version")
            self.assertEqual(version.fuel_card, 150.0)
            self.assertEqual(version.fuel_card_personal_use, 50.0)

            slip = self.env['hr.payslip'].create({
                'name': f"Payslip {employee.name} 2026-01",
                'employee_id': employee.id,
                'company_id': employee.company_id.id,
                'version_id': version.id,
                'date_from': date(2026, 1, 1),
                'date_to': date(2026, 1, 31),
            })
            slip.compute_sheet()

            line = slip.line_ids.filtered(lambda l: l.code == 'FUEL_CARD_PRIV')
            self.assertTrue(
                line,
                "The FUEL_CARD_PRIV rule should fire on the payslip: the employee has a "
                "fuel_card_personal_use default value set on the payroll tab, no company car.")
            self.assertEqual(
                line.total, 50.0,
                "The FUEL_CARD_PRIV salary input should default to the employee's "
                "fuel_card_personal_use value, not stay at 0.")

    def test_fuel_card_personal_use_ignored_with_company_car(self):
        with freeze_time('2026-01-20'):
            employee = self.create_employee({
                'name': 'Fuel Card Private Use employee with car',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'contract_date_end': False,
                'fuel_card': 150.0,
                'fuel_card_personal_use': 50.0,
            })
            version = employee.version_id
            brand = self.env['fleet.vehicle.model.brand'].create({'name': 'Fuel Card Brand'})
            version.car_id = self.env['fleet.vehicle'].create({
                'model_id': self.env['fleet.vehicle.model'].create({'name': 'Fuel Card Model', 'brand_id': brand.id}).id,
                'company_id': employee.company_id.id,
            })

            slip = self.env['hr.payslip'].create({
                'name': f"Payslip {employee.name} 2026-01",
                'employee_id': employee.id,
                'company_id': employee.company_id.id,
                'version_id': version.id,
                'date_from': date(2026, 1, 1),
                'date_to': date(2026, 1, 31),
            })
            slip.compute_sheet()

            line = slip.line_ids.filtered(lambda l: l.code == 'FUEL_CARD_PRIV')
            self.assertFalse(
                line,
                "FUEL_CARD_PRIV must not fire when the employee has a company car: "
                "the car's own benefit-in-kind already covers the fuel card.")

    def test_fuel_card_personal_use_ignored_with_mobility_budget(self):
        with freeze_time('2026-01-20'):
            employee = self.create_employee({
                'name': 'Fuel Card Private Use employee mobility budget',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'contract_date_end': False,
                'fuel_card': 150.0,
                'fuel_card_personal_use': 50.0,
                'l10n_be_mobility_budget': True,
            })
            version = employee.version_id
            self.assertTrue(version.l10n_be_mobility_budget)

            slip = self.env['hr.payslip'].create({
                'name': f"Payslip {employee.name} 2026-01",
                'employee_id': employee.id,
                'company_id': employee.company_id.id,
                'version_id': version.id,
                'date_from': date(2026, 1, 1),
                'date_to': date(2026, 1, 31),
            })
            slip.compute_sheet()

            line = slip.line_ids.filtered(lambda l: l.code == 'FUEL_CARD_PRIV')
            self.assertFalse(
                line,
                "FUEL_CARD_PRIV must not fire when the employee is on a mobility budget: "
                "the fuel card fields are meaningless/hidden in that mode.")

    def test_fuel_card_personal_use_ignored_without_fuel_card(self):
        with freeze_time('2026-01-20'):
            employee = self.create_employee({
                'name': 'Fuel Card Private Use employee no fuel card',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'contract_date_end': False,
                'fuel_card': 0.0,
                'fuel_card_personal_use': 50.0,
            })
            version = employee.version_id

            slip = self.env['hr.payslip'].create({
                'name': f"Payslip {employee.name} 2026-01",
                'employee_id': employee.id,
                'company_id': employee.company_id.id,
                'version_id': version.id,
                'date_from': date(2026, 1, 1),
                'date_to': date(2026, 1, 31),
            })
            slip.compute_sheet()

            line = slip.line_ids.filtered(lambda l: l.code == 'FUEL_CARD_PRIV')
            self.assertFalse(
                line,
                "FUEL_CARD_PRIV must not fire when fuel_card is 0: a stale "
                "fuel_card_personal_use value shouldn't leak in once the fuel card itself is removed.")

    def test_fuel_card_personal_use_manual_override_survives_recompute(self):
        with freeze_time('2026-01-20'):
            employee = self.create_employee({
                'name': 'Fuel Card Private Use employee manual override',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'contract_date_end': False,
                'fuel_card': 150.0,
                'fuel_card_personal_use': 50.0,
            })
            version = employee.version_id

            slip = self.env['hr.payslip'].create({
                'name': f"Payslip {employee.name} 2026-01",
                'employee_id': employee.id,
                'company_id': employee.company_id.id,
                'version_id': version.id,
                'date_from': date(2026, 1, 1),
                'date_to': date(2026, 1, 31),
            })
            slip.compute_sheet()
            slip.input_line_ids.filtered(lambda l: l.code == 'FUEL_CARD_PRIV').amount = 80.0
            slip.compute_sheet()

            line = slip.line_ids.filtered(lambda l: l.code == 'FUEL_CARD_PRIV')
            self.assertEqual(
                line.total, 80.0,
                "A manually-overridden salary input value on the payslip should survive a "
                "compute_sheet() recompute rather than being reset to the employee's default.")

    def test_fuel_card_personal_use_applied_while_waiting_for_new_car(self):
        # "Uses company car" is ticked for a requested car, the employee has no company car yet
        with freeze_time('2026-01-20'):
            employee = self.create_employee({
                'name': 'Fuel Card Private Use employee waiting for a car',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'contract_date_end': False,
                'fuel_card': 150.0,
                'fuel_card_personal_use': 50.0,
                'has_new_car': True,
            })
            version = employee.version_id
            self.assertTrue(version.transport_mode_car)
            self.assertFalse(version.car_id)

            slip = self.env['hr.payslip'].create({
                'name': f"Payslip {employee.name} 2026-01",
                'employee_id': employee.id,
                'company_id': employee.company_id.id,
                'version_id': version.id,
                'date_from': date(2026, 1, 1),
                'date_to': date(2026, 1, 31),
            })
            slip.compute_sheet()

            line = slip.line_ids.filtered(lambda l: l.code == 'FUEL_CARD_PRIV')
            self.assertEqual(line.total, 50.0, "Without company car, the private use of the fuel card is a benefit")

    def test_payslip_vehicle_follows_version_car(self):
        with freeze_time('2026-01-20'):
            employee, car = self._create_employee_with_car('Payslip vehicle employee')
            version = employee.version_id
            version.car_id = car
            slip = self._create_payslip(employee)
            self.assertEqual(slip.vehicle_id, car)

            # The car is given back: the draft payslip has no company car anymore
            version.car_id = False
            self.assertFalse(slip.vehicle_id)

    def test_car_benefits_follow_version_car(self):
        # "Uses company car" is unticked (e.g. a version from before it followed the car), the
        # company car of the version still gives its benefits on the payslip
        with freeze_time('2026-01-20'):
            employee, car = self._create_employee_with_car('Company car employee')
            version = employee.version_id
            version.write({'car_id': car.id, 'transport_mode_car': False})
            self.assertEqual(version.car_id, car)
            self.assertFalse(version.transport_mode_car)

            slip = self._create_payslip(employee)
            slip.compute_sheet()
            self.assertEqual(slip.vehicle_id, car)
            atn_line = slip.line_ids.filtered(lambda l: l.code == 'ATN.CAR')
            self.assertAlmostEqual(atn_line.total, car._get_monthly_car_atn(date=slip.date_from), places=2)
            self.assertTrue(atn_line.total)
            co2_line = slip.line_ids.filtered(lambda l: l.code == 'CO2FEE')
            self.assertTrue(co2_line.total)
            self.assertEqual(
                slip._get_be_withholding_taxes_transport_deduction(None),
                min(version.car_atn, slip._rule_parameter('private_car_withholding_monthly_exemption') * 12))

    def test_car_benefits_without_worked_days(self):
        # A month without any work entry (a suspension the time does not register, a variable schedule without a
        # planned day): the company car stays at the employee's disposal, its benefit is due for every day (art. 36,
        # § 2 CIR 92) and its CO2 contribution for the month (art. 38, § 3quater of the law of 29 June 1981). The
        # regular payslip without worked days carries them, once: not when another payslip of the month already has
        # worked days on the version.
        with freeze_time('2026-01-20'):
            employee, car = self._create_employee_with_car('Suspended company car employee')
            version = employee.version_id
            version.car_id = car
            slip = self._create_payslip(employee)
            slip.worked_days_line_ids.unlink()
            slip.compute_sheet()
            self.assertFalse(slip.worked_days_line_ids)
            atn_line = slip.line_ids.filtered(lambda l: l.code == 'ATN.CAR')
            self.assertAlmostEqual(atn_line.total, car._get_monthly_car_atn(date=slip.date_from), places=2)
            self.assertTrue(atn_line.total)
            self.assertTrue(slip.line_ids.filtered(lambda l: l.code == 'CO2FEE').total)

            regular = self._create_payslip(employee)
            regular.compute_sheet()
            self.assertTrue(regular.worked_days_line_ids)
            slip.compute_sheet()
            self.assertFalse(slip.line_ids.filtered(lambda l: l.code in ('ATN.CAR', 'CO2FEE') and l.total))

    def test_no_car_benefits_without_car(self):
        # A new car is requested ("Uses company car" is ticked) but not delivered yet: no
        # company car, no car benefits on the payslip
        with freeze_time('2026-01-20'):
            employee = self.create_employee({
                'name': 'New car employee',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'contract_date_end': False,
                'has_new_car': True,
                'new_car_model_id': self.car_model.id,
            })
            version = employee.version_id
            self.assertTrue(version.transport_mode_car)
            self.assertFalse(version.car_id)

            slip = self._create_payslip(employee)
            slip.compute_sheet()
            self.assertFalse(slip.vehicle_id)
            self.assertFalse(slip.line_ids.filtered(lambda l: l.code in ('ATN.CAR', 'CO2FEE')))
            self.assertEqual(slip._get_be_withholding_taxes_transport_deduction(None), 0)

    def test_missing_transport_benefit_warning_follows_car(self):
        def has_transport_warning(version):
            version = version.with_context(hr_payroll_force_compute_issue=True)
            version.invalidate_recordset(['issues'])
            version._compute_issues()
            return any(
                'threshold transport benefit required' in issue['message']
                for issue in (version.issues or {}).values())

        with freeze_time('2026-01-20'):
            employee, car = self._create_employee_with_car('Low wage employee', driver=False)
            version = employee.version_id
            version.wage = 2000.0

            # A new car requested but not delivered yet is no transport benefit
            version.has_new_car = True
            self.assertTrue(version.transport_mode_car)
            self.assertFalse(version.car_id)
            self.assertTrue(has_transport_warning(version))

            # The company car is a transport benefit, whatever "Uses company car"
            version.write({'car_id': car.id, 'transport_mode_car': False})
            self.assertFalse(has_transport_warning(version))
