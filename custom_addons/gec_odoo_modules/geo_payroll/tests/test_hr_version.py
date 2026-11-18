from datetime import date

from odoo import Command
from odoo.tests import tagged

from .common import GeoPayrollCase


@tagged('post_install', '-at_install', 'geo_payroll')
class TestGeoPayrollVersion(GeoPayrollCase):
    def test_shipped_structures_have_expected_wage_types_defaults_and_rules(self):
        required_codes = {
            'BASIC', 'DAILY_BASIC', 'TIMESHEET_BASIC', 'UNIT_BASIC', 'WORKLOG_OT',
            'WORKLOG_DAILY', 'TIMESHEET_EXTRA', 'UNIT_EXTRA', 'GROSS',
            'PENSION_EE', 'PIT', 'PENSION_ER', 'NET',
        }
        basic_category = self.env.ref('hr_payroll.BASIC')
        alw_category = self.env.ref('hr_payroll.ALW')
        for wage_type in ('monthly', 'hourly', 'daily', 'unit'):
            structure_type = self.structure_types[wage_type]
            structure = self.structures[wage_type]
            self.assertEqual(structure_type.wage_type, wage_type)
            self.assertEqual(structure_type.default_struct_id, structure)
            self.assertLessEqual(required_codes, set(structure.rule_ids.mapped('code')))
            timesheet_basic = structure.rule_ids.filtered(lambda r: r.code == 'TIMESHEET_BASIC')
            self.assertEqual(timesheet_basic.category_ids, basic_category)
            unit_basic = structure.rule_ids.filtered(lambda r: r.code == 'UNIT_BASIC')
            self.assertEqual(unit_basic.category_ids, basic_category)
            unit_extra = structure.rule_ids.filtered(lambda r: r.code == 'UNIT_EXTRA')
            self.assertEqual(unit_extra.category_ids, alw_category)

    def test_create_forces_supported_sources_even_when_explicitly_unsupported(self):
        version = self._make_template(hourly_source='timesheet')
        self.assertEqual(version.hourly_source, 'work_entry')

    def test_multi_create_normalizes_every_version(self):
        values = []
        for index in range(2):
            values.append({
                'name': f'Batch Template {index}',
                'company_id': self.company.id,
                'date_version': self.contract_start,
                'structure_type_id': self.structure_types['monthly'].id,
                'pay_scheme': 'fixed',
                'hourly_source': 'timesheet',
            })
        versions = self.env['hr.version'].create(values)
        self.assertEqual(set(versions.mapped('hourly_source')), {'work_entry'})

    def test_write_of_configuration_repairs_legacy_sources(self):
        version = self._seed_legacy_sources(self._make_template())
        version.write({'pay_scheme': 'fixed'})
        self.assertEqual(version.hourly_source, 'work_entry')

    def test_any_write_repairs_an_already_legacy_row(self):
        version = self._seed_legacy_sources(self._make_template())
        version.write({'name': 'Legacy repaired'})
        self.assertEqual(version.hourly_source, 'work_entry')

    def test_unrelated_write_preserves_supported_sources(self):
        version = self._make_template()
        version.write({'name': 'Still supported'})
        self.assertEqual(version.hourly_source, 'work_entry')

    def test_all_scheme_mappings_and_component_flags(self):
        expected = {
            'fixed': ('monthly', False, False),
            'hourly': ('hourly', False, False),
            'daily': ('daily', False, False),
            'unit': ('unit', False, False),
            'fixed_daily': ('monthly', True, False),
            'fixed_hourly': ('monthly', False, True),
            'daily_hourly': ('daily', False, True),
            'daily_unit': ('daily', False, False),
        }
        for scheme, result in expected.items():
            with self.subTest(scheme=scheme):
                version = self._make_template(scheme)
                self.assertEqual(
                    (version.wage_type, version.worklog_daily_enabled, version.timesheet_extra_enabled),
                    result,
                )

    def test_switching_scheme_preserves_all_rates_and_optional_settings(self):
        employee = self._make_employee(
            'fixed_hourly',
            wage=1733.25,
            hourly_wage=12.75,
            daily_wage=91.5,
            worklog_ot_enabled=True,
            timesheet_pay_start_date=date(2025, 6, 1),
            timesheet_pay_project_ids=[Command.set((self.project | self.other_project).ids)],
        )
        version = employee.version_id
        version.write({'pay_scheme': 'daily_hourly', 'structure_type_id': self.structure_types['daily'].id})
        self.assertRecordValues(version, [{
            'pay_scheme': 'daily_hourly',
            'wage_type': 'daily',
            'wage': 1733.25,
            'hourly_wage': 12.75,
            'daily_wage': 91.5,
            'worklog_ot_enabled': True,
            'timesheet_pay_start_date': date(2025, 6, 1),
            'hourly_source': 'work_entry',
        }])
        self.assertEqual(version.timesheet_pay_project_ids, self.project | self.other_project)

    def test_employee_related_fields_write_the_current_version(self):
        employee = self._make_employee('fixed')
        employee.write({
            'daily_wage': 95.0,
            'worklog_ot_enabled': True,
            'timesheet_pay_start_date': date(2025, 7, 1),
            'timesheet_pay_project_ids': [Command.set([self.other_project.id])],
        })
        version = employee.version_id
        self.assertEqual(version.daily_wage, 95.0)
        self.assertTrue(version.worklog_ot_enabled)
        self.assertEqual(version.timesheet_pay_start_date, date(2025, 7, 1))
        self.assertEqual(version.timesheet_pay_project_ids, self.other_project)

    def test_new_version_copies_payroll_values_but_remains_independent(self):
        employee = self._make_employee(
            'fixed_hourly',
            worklog_ot_enabled=True,
            timesheet_pay_project_ids=[Command.set((self.project | self.other_project).ids)],
        )
        old_version = employee.version_id
        new_version = employee.create_version({'date_version': date(2026, 6, 1), 'hourly_wage': 25.0})
        self.assertEqual(new_version.pay_scheme, 'fixed_hourly')
        self.assertEqual(new_version.daily_wage, old_version.daily_wage)
        self.assertEqual(new_version.timesheet_pay_project_ids, old_version.timesheet_pay_project_ids)
        self.assertTrue(new_version.worklog_ot_enabled)
        self.assertEqual(new_version.hourly_wage, 25.0)
        self.assertEqual(old_version.hourly_wage, 10.0)

        new_version.timesheet_pay_project_ids = [Command.set([self.other_project.id])]
        self.assertEqual(old_version.timesheet_pay_project_ids, self.project | self.other_project)
        self.assertEqual(new_version.timesheet_pay_project_ids, self.other_project)

    def test_new_version_can_change_scheme_structure_and_wage_type_together(self):
        employee = self._make_employee('fixed')

        new_version = employee.create_version({
            'date_version': date(2026, 6, 1),
            'pay_scheme': 'daily',
            'structure_type_id': self.structure_types['daily'].id,
            'daily_wage': 90.0,
        })

        self.assertEqual(new_version.pay_scheme, 'daily')
        self.assertEqual(new_version.structure_type_id, self.structure_types['daily'])
        self.assertEqual(new_version.wage_type, 'daily')

    def test_effective_version_selection_uses_work_date_boundaries(self):
        employee = self._make_employee('fixed', wage=1600.0)
        old_version = employee.version_id
        new_version = employee.create_version({'date_version': date(2026, 2, 1), 'wage': 2200.0})
        self.assertEqual(employee._get_version(date(2026, 1, 31)), old_version)
        self.assertEqual(employee._get_version(date(2026, 2, 1)), new_version)
        self.assertEqual(employee._get_version(date(2027, 1, 1)), new_version)

    def test_current_employee_mirror_follows_current_effective_version(self):
        employee = self._make_employee('fixed', daily_wage=80.0)
        historical = employee.version_id
        current = employee.create_version({'date_version': date(2026, 6, 1), 'daily_wage': 120.0})
        employee._compute_current_version_id()
        self.assertEqual(employee.current_version_id, current)
        self.assertEqual(employee.daily_wage, 120.0)
        self.assertEqual(historical.daily_wage, 80.0)

    def test_future_version_does_not_replace_current_employee_mirror(self):
        employee = self._make_employee('fixed', daily_wage=80.0)
        current = employee.version_id
        employee.create_version({'date_version': date(2027, 1, 1), 'daily_wage': 120.0})
        employee._compute_current_version_id()
        self.assertEqual(employee.current_version_id, current)
        self.assertEqual(employee.daily_wage, 80.0)

    def test_daily_contract_wage_and_normalized_wage(self):
        employee = self._make_employee('daily', daily_wage=96.0)
        version = employee.version_id
        self.assertEqual(version._get_contract_wage_field(), 'daily_wage')
        self.assertEqual(version._get_contract_wage(), 96.0)
        self.assertAlmostEqual(version._get_normalized_wage(), 96.0 / version.resource_calendar_id.hours_per_day)

    def test_daily_normalized_wage_is_zero_without_hours_per_day(self):
        calendar = self.env['resource.calendar'].create({
            'name': 'GEO Zero-Hour Calendar',
            'company_id': self.company.id,
            'hours_per_day': 0.0,
        })
        employee = self._make_employee('daily', daily_wage=96.0, resource_calendar_id=calendar.id)
        self.assertEqual(employee.version_id._get_normalized_wage(), 0.0)

    def test_payroll_fields_are_in_template_and_recompute_whitelists(self):
        version = self._make_template()
        template_fields = set(version._get_whitelist_fields_from_template())
        recompute_fields = set(version._get_fields_that_recompute_payslip())
        self.assertTrue({
            'pay_scheme', 'hourly_wage', 'daily_wage', 'worklog_ot_enabled',
            'worklog_daily_enabled', 'timesheet_extra_enabled', 'hourly_source',
            'timesheet_pay_project_ids', 'timesheet_pay_start_date',
        } <= template_fields)
        self.assertTrue({
            'pay_scheme', 'structure_type_id', 'wage_type', 'wage', 'hourly_wage',
            'daily_wage', 'worklog_ot_enabled', 'hourly_source',
            'timesheet_pay_project_ids', 'timesheet_pay_start_date',
        } <= recompute_fields)
