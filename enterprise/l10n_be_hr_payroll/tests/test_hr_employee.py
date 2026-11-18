from freezegun import freeze_time

from odoo.tests import TransactionCase, Form, tagged
from odoo.exceptions import ValidationError
from datetime import date, datetime


@tagged('post_install', '-at_install', 'post_install_l10n')
class TestHrEmployeeBelgiumForm(TransactionCase):

    @classmethod
    def setUpClass(self):
        super().setUpClass()
        self.be_company = self.env['res.company'].create({
            'name': 'My Belgian Company - TEST',
            'country_id': self.env.ref('base.be').id,
        })
        self.env.user.write({
            'company_ids': [(4, self.be_company.id)],
            'company_id': self.be_company.id,
        })

    @freeze_time('2026-10-26 10:00:00')
    def test_dmfa_unit_presence(self):
        location = self.env['hr.work.location'].create({
            'name': 'DMFA Unit',
            'location_type': 'dmfa_unit',
            'address_id': self.env['res.partner'].create({'name': 'DMFA Unit Address'}).id,
        })
        for exceptional in (False, True):
            with self.subTest(exceptional=exceptional):
                employee = self.env['hr.employee'].create({
                    'name': 'Employee at DMFA Unit',
                    'monday_location_id': False if exceptional else location.id,
                })
                if exceptional:
                    self.env['hr.employee.location'].create({
                        'employee_id': employee.id,
                        'work_location_id': location.id,
                        'date': '2026-10-26',
                    })
                public_employee = self.env['hr.employee.public'].browse(employee.id)
                for record in (employee, public_employee):
                    self.assertEqual(record.hr_icon_display, 'presence_other')
                    self.assertEqual(record.work_location_type, 'other')
                    self.assertTrue(record.show_hr_icon_display)
                    self.assertEqual(record.work_location_name, location.name)
        self.assertEqual(location.location_type, 'dmfa_unit')

    def test_belgian_employee_creation_via_form(self):
        with Form(self.env['hr.employee'].with_company(self.be_company)) as employee_form:
            employee_form.name = 'Tony Stark'
            employee_form.contract_date_start = '2025-01-01'
            employee_form.version_id.contract_date_start = '2025-01-01'
            employee_form.wage = 2500.0
            employee_form.employee_type_id = self.env.ref('hr.contract_type_employee')

        new_employee = employee_form.save()

        self.assertTrue(new_employee.id, "The employee did not save to the database!")
        self.assertEqual(new_employee.name, 'Tony Stark')
        self.assertEqual(str(new_employee.contract_date_start), '2025-01-01')

    @freeze_time('2026-09-01')
    def test_joint_committee_preserved_on_contract_start(self):
        committee = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200')
        for default in (self.env['l10n.be.joint.committee'], self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302')):
            self.be_company.current_payroll_config_id.l10n_be_main_joint_committee = default
            for start in (False, '2026-08-01'):
                with self.subTest(default=default, start=start):
                    with Form(self.env['hr.employee'].with_company(self.be_company)) as employee_form:
                        employee_form.name = 'Student'
                        employee_form.employee_type_id = self.env.ref('hr.contract_type_student')
                        employee_form.contract_date_start = start
                        employee_form.l10n_be_joint_committee_id = committee
                        employee_form.l10n_be_salary_scale_id = self.env.ref('l10n_be_hr_payroll.cp200_b')
                    employee = employee_form.record
                    self.assertEqual(employee.l10n_be_joint_committee_id, committee)
                    with Form(employee) as employee_form:
                        employee_form.contract_date_start = '2026-09-01'
                    self.assertEqual(employee.l10n_be_joint_committee_id, committee)

    def test_joint_committee_activated_when_used(self):
        committee = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_207')
        committee.active = False
        employee = self.env['hr.employee'].with_company(self.be_company).create({'name': 'Chemist'})
        employee.l10n_be_joint_committee_id = committee
        self.assertTrue(committee.active)

    def test_joint_committee_activates_its_benefits(self):
        committee = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_207')
        committee.active = False
        benefit = self.env.ref('l10n_be_hr_payroll.l10n_be_withholding_tax_benefit')
        benefit.write({'l10n_be_joint_committee_ids': committee.ids, 'active': False})
        committee.active = True
        self.assertTrue(benefit.active)
        committee.active = False
        self.assertFalse(benefit.active)

    def test_correct_niss_parsing(self):
        self.employee_nana = self.env['hr.employee'].create({
            'name': 'Nana',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
        })

        # Try a NISS with a valid date, it should save the value and update the birthday
        self.employee_nana.write({
            'niss': 88010119776,
        })

        self.assertEqual(self.employee_nana.niss, '88010119776')
        self.assertEqual(self.employee_nana.birthday, date(1988, 1, 1))

        # Reset birthday
        self.employee_nana.write({
            'birthday': False,
        })

        # Try NISS with no valid date, it should save the value but not update the birthday
        self.employee_nana.write({
            'niss': 88000119769,
        })

        self.assertEqual(self.employee_nana.niss, '88000119769')
        self.assertFalse(self.employee_nana.birthday)

        # Try invalid NISS, it should raise a ValidationError saying the NISS is invalid
        with self.assertRaises(ValidationError):
            self.employee_nana.write({
                'niss': 88000119760,
            })

    def test_default_payslip_language(self):
        """
        We verify that new employees have their payslip's language set by default to the environment's language if that language is part
        of the Belgian national languages i.e. French, Dutch or German.
        """
        # Also works with the 'fr_FR' and 'nl_NL' codes
        self.env['res.lang']._activate_lang('fr_BE')
        self.env['res.lang']._activate_lang('nl_BE')
        self.env['res.lang']._activate_lang('de_DE')

        employee_1 = self.env['hr.employee'].with_context(lang='en_US').create({
            'name': 'Emp 1',
        })
        employee_2 = self.env['hr.employee'].with_context(lang='fr_BE').create({
            'name': 'Emp 2',
        })
        employee_3 = self.env['hr.employee'].with_context(lang='nl_BE').create({
            'name': 'Emp 3',
        })
        employee_4 = self.env['hr.employee'].with_context(lang='de_DE').create({
            'name': 'Emp 4',
        })

        self.assertFalse(employee_1.lang, "The employee's payslip's language should not have any default value.")
        self.assertEqual(employee_2.lang, 'fr_BE', "The employee's payslip's language should be 'fr_BE' by default.")
        self.assertEqual(employee_3.lang, 'nl_BE', "The employee's payslip's language should be 'nl_BE' by default.")
        self.assertEqual(employee_4.lang, 'de_DE', "The employee's payslip's language should be 'de_DE' by default.")

    def test_payslip_language_installed_on_employee_creation(self):
        lang_fr_be = self.env.ref('base.lang_fr_BE')
        lang_fr_be.active = False

        employee = self.env['hr.employee'].create({
            'name': 'Faruk',
            'lang': 'fr_BE',
        })
        # In the creation of the employee, if the payslip language is missing, install it.
        self.assertTrue(lang_fr_be.active, "The employee's payslip's language should be installed.")
        self.assertEqual(employee.with_context(lang=employee.lang).env.lang, 'fr_BE')

    @freeze_time('2026-08-01')
    def test_create_public_holiday_allocation(self):
        self.env['resource.calendar.leaves'].create({
            'name': 'Public Holiday',
            'date_from': datetime(2026, 7, 31, 22, 0, 0),
            'date_to': datetime(2026, 8, 1, 21, 59, 59),
        })
        self.env['resource.calendar.leaves'].create({
            'name': 'Next Year Public Holiday',
            'date_from': datetime(2027, 4, 30, 22, 0, 0),
            'date_to': datetime(2027, 5, 1, 21, 59, 59),
        })

        emp_flora, emp_stella, emp_musa = self.env['hr.employee'].create([
            {
                'name': 'Flora',
                'company_id': self.be_company.id,
                'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00495').id,
                'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
                'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_b').id,
            }, {
                'name': 'Stella',
                'company_id': self.be_company.id,
                'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00495').id,
                'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
                'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_b').id,
                'contract_date_start': date(2026, 1, 1),
            }, {
                'name': 'Musa',
                'company_id': self.be_company.id,
                'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00495').id,
                'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
                'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_b').id,
                'contract_date_start': date(2026, 1, 1),
                'contract_date_end': date(2026, 10, 1),
            }
        ])
        allocations_by_employee = dict(self.env['hr.leave.allocation']._read_group(
            domain=[
                ('employee_id', 'in', (emp_flora + emp_musa + emp_stella).ids),
                ('work_entry_type_id', 'any', [
                    ('code', '=', '006.15'),
                    ('country_id.code', '=', 'BE')
                ])
            ],
            groupby=['employee_id'],
            aggregates=['id:recordset']
        ))
        self.assertFalse(allocations_by_employee.get(emp_flora))
        self.assertEqual(sum(allocations_by_employee.get(emp_stella).mapped('number_of_days')), 1)
        self.assertEqual(sum(allocations_by_employee.get(emp_musa).mapped('number_of_days')), 1)

    @freeze_time('2026-08-01')
    def test_create_public_holiday_allocation_next_year(self):
        """ The public holidays of the year the contract starts in are compensated at the hiring, the ones of
        the following years only once the generate allocations wizard compensated them for the others. """
        next_year_holiday, later_holiday = self.env['resource.calendar.leaves'].create([{
            'name': 'Next Year Public Holiday',
            'date_from': datetime(2027, 4, 30, 22, 0, 0),
            'date_to': datetime(2027, 5, 1, 21, 59, 59),
        }, {
            'name': 'Later Public Holiday',
            'date_from': datetime(2027, 8, 14, 22, 0, 0),
            'date_to': datetime(2027, 8, 15, 21, 59, 59),
        }])
        employee_values = {
            'company_id': self.be_company.id,
            'l10n_be_worker_code_id': self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00495').id,
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'l10n_be_salary_scale_id': self.env.ref('l10n_be_hr_payroll.cp200_b').id,
        }

        def get_compensated_holidays(employee):
            return self.env['hr.leave.allocation'].search([('employee_id', '=', employee.id)]).public_holiday_id

        # Hired this year: the holidays of next year aren't compensated yet
        this_year_hire = self.env['hr.employee'].create({
            **employee_values, 'name': 'This Year Hire', 'contract_date_start': date(2026, 9, 1)})
        self.assertFalse(get_compensated_holidays(this_year_hire))

        # Hired from next January, encoded this year: the holidays of next year are compensated
        next_year_hire = self.env['hr.employee'].create({
            **employee_values, 'name': 'Next Year Hire', 'contract_date_start': date(2027, 1, 1)})
        self.assertEqual(get_compensated_holidays(next_year_hire), next_year_holiday + later_holiday)

        # Hired this year once the holidays of next year are compensated for the others: compensated too
        other_hire = self.env['hr.employee'].create({
            **employee_values, 'name': 'Other Hire', 'contract_date_start': date(2026, 9, 1)})
        self.assertEqual(get_compensated_holidays(other_hire), next_year_holiday + later_holiday)

    def test_export_work_entries_employee_without_niss(self):
        # A foreign worker or a student waiting for a BIS number has no NISS yet
        employee = self.env['hr.employee'].with_company(self.be_company).create({
            'name': 'Jean Sans Niss',
            'company_id': self.be_company.id,
        })
        self.assertFalse(employee.niss)
        export = self.env['hr.export.work.entries'].with_company(self.be_company).new({})
        line = export._generate_line(employee, date(2026, 10, 1), self.be_company, {
            'work_entries': [{'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance')}],
            'duration': 8 * 3600,
        })
        self.assertEqual(line.split(';')[8], '')

    def test_export_work_entries_duration_in_hours(self):
        # A day of 7.6 hours (full time 38 hours a week) must not be exported as 7
        employee = self.env['hr.employee'].with_company(self.be_company).create({
            'name': 'Jean Trente-Huit',
            'company_id': self.be_company.id,
        })
        export = self.env['hr.export.work.entries'].with_company(self.be_company).new({})
        for duration, expected in [(7.6, '7.60'), (3.8, '3.80'), (0.5, '0.50'), (8, '8.00')]:
            with self.subTest(duration=duration):
                line = export._generate_line(employee, date(2026, 10, 1), self.be_company, {
                    'work_entries': [{'work_entry_type_id': self.env.ref('hr_work_entry.be_work_entry_type_attendance')}],
                    'duration': duration * 3600,
                })
                self.assertEqual(line.strip().split(';')[9], expected)
