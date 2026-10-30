
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from freezegun import freeze_time

from odoo.tests import Form, tagged
from odoo.exceptions import UserError, ValidationError
from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'payroll_dmfa')
class TestPayrollDmfa(TestPayrollCommon):

    """
    Other dmfa tests there :
        test_l10n_be_hr_payroll_account/tests/test_dmfa.py
    """

    """
    Prerequisites for a dmfa report:
       Companies need following properties to be set:
            - employer_category_id.dmfa_code
            - onss_registration_number
            - l10n_be_company_number
       Employees need:
            - niss
            - address_id (that matches a l10n_be.dmfa.local.unit)
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_report_can_only_be_generated_from_root_company(self):
        companies = self.multibranch_company
        with self.assertRaises(UserError):
            self.env['l10n_be.dmfa'].with_company(companies[1]).create({})

    def test_include_child_branches_in_report(self):
        companies = self.belgian_company | self.multibranch_company
        # company 0 -> root / no child
        # company 1 (is parent of) company 2 (is parent of) company 3
        target_company = companies[1]

        self.env['hr.work.location'].search([('company_id', 'in', companies.ids), ('location_type', '=', 'dmfa_unit')]).bce_code = '8888888374'

        employees = self.create_employee(
            [{
                'name': f'Employee {company.name}',
                'company_id': company.id,
                'contract_date_start': date(2026, 1, 1),
                'niss': self.generate_fake_niss(),
                'address_id': company.partner_id.id,
            }
            for company in companies])

        self.create_and_validate_payslips(employees=employees, year=2026, months=[1])

        dmfa = self.env['l10n_be.dmfa'].with_company(target_company).create({
            'year': 2026,
            'quarter': '1',
        })
        rendered_data = dmfa._get_rendering_data()

        reported_companies = rendered_data['data']['branch_ids']
        expected_branches = companies[1:]
        self.assertEqual(reported_companies, expected_branches, "DMFA report should include 3 companies 1-2-3")

        reported_employees = rendered_data['natural_persons']
        self.assertEqual(len(reported_employees), 3, "Expected 3 natural persons, one per company")

    @freeze_time('2026-07-01')
    def test_dmfa_warnings(self):
        """
        We have 12 warnings, the conditions for 3 of which are already
        satisfied for Employee Test. These are the following:

        - Missing NISS for employee
        - Missing DIMONA for period
        - Quarter not ended (the report is of the current quarter)

        The rest need to be activated:
        - Invalid DMFA work address
        - Missing company employer class
        - Missing ONSS company ID
        - Invalid work entry type dmfa code
        - Invalid vehicle license plate
        - Quarter working days incompatibility
        - Quarter working schedule incompatibility
        - Missing termination dates
        - Missing employee worker code
        """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        # Change the employee address to a work address that is not linked to a location unit
        self.employee_test.address_id = self.env['res.partner'].create({'name': 'Invalid Work Address'})
        # Remove employer category from company
        self.env.company.current_payroll_config_id.l10n_be_employer_category_id = False
        # Remove ONSS company Id
        self.env.company.current_payroll_config_id.l10n_be_company_number = False
        # For some reason there is no record of res.config.settings for the company
        self.env['res.config.settings'].create({'company_id': self.env.company.id})
        # Pick a random employee, i.e. Employee Test and make a paid payslip for it to be eligible for DMFA.
        # The payslip needs to be paid because cars are only considered in that case, not validated
        emp_id = self.employee_test.id
        payslip = self.env['hr.payslip'].create({'employee_id': emp_id, 'name': 'test payslip 1'})
        payslip.state = 'paid'
        # Remove the DMFA code on the Attendance work entry type
        payslip.worked_days_line_ids.work_entry_type_id.dmfa_code = False
        # Take a car, assign it to our company, make the license plate too long and assign it to the employee
        brand = self.env["fleet.vehicle.model.brand"].create({
            "name": "Ferrari",
        })
        model = self.env["fleet.vehicle.model"].create({
            "brand_id": brand.id,
            "name": "A good one",
        })
        car = self.env["fleet.vehicle"].create({'model_id': model.id, 'license_plate': '2-ASD-345'})
        car.company_id = self.env.company.id
        car.license_plate += '0000000000'
        self.employee_test.car_id = car
        # Make 4 more payslips for the quarter (1 has already been created) to make the amount of worked days
        # higher than the amount of days present in the quarter
        payslips = self.env['hr.payslip'].create([
            {
                'employee_id': emp_id,
                'name': 'test payslip 2',
                'date_from': datetime.now() + relativedelta(months=1),
            },
            {
                'employee_id': emp_id,
                'name': 'test payslip 3',
                'date_from': datetime.now() + relativedelta(months=2),
            },
            {
                'employee_id': emp_id,
                'name': 'test payslip 4',
                'date_from': datetime.now() + relativedelta(months=1),
            },
            {
                'employee_id': emp_id,
                'name': 'test payslip 5',
                'date_from': datetime.now() + relativedelta(months=2),
            },
        ])
        payslips.state = 'paid'
        # Make a payslip with Termination Fees pay structure
        termination_fees_struct_id = self.env['hr.payroll.structure'].search([('name', '=', 'Termination Fees (BE)')]).id
        term_payslip = self.env['hr.payslip'].create(
            {
                'employee_id': emp_id,
                'name': 'termination test payslip',
                'date_from': datetime.now(),
                'struct_id': termination_fees_struct_id,
            }
        )
        term_payslip.state = 'paid'
        # Remove the worker code from the employee
        self.employee_test.l10n_be_worker_code_id = False

        # Create DMFA and compute issues
        dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id})
        dmfa._compute_issues()
        messages = [issue['message'] for issue in dmfa.issues.values()]
        self.assertEqual(len(messages), 11)
        expected_messages = [
            'Employees with work address missing ONSS code',
            'Missing NISS for employees',
            'Employees missing DMFA worker code',
            'Missing employer class for company',
            'Missing ONSS company ID for company',
            'Termination payslips missing notice period dates',
            'Employees exceeding quarterly occupation days',
            'Occupation days mismatch working schedule',
            'Time types missing DMFA code',
            'DMFA employees missing DIMONA',
            "The quarter isn't ended yet",
        ]
        for expected_message in expected_messages:
            self.assertTrue(any(msg.startswith(expected_message) for msg in messages), f"Expected warning starting with '{expected_message}' not found in messages.")

    def test_dmfa_blocking_issues(self):
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        dmfa = self.env['l10n_be.dmfa'].create({
            'company_id': self.belgian_company.id,
            'year': 2026,
            'quarter': '1',
        })
        self.assertFalse(dmfa.is_invalid)

        # Missing ONSS company ID is a danger issue, only raised when the company has settings records
        self.belgian_company.current_payroll_config_id.l10n_be_company_number = False
        self.env['res.config.settings'].create({'company_id': self.belgian_company.id})
        dmfa.invalidate_recordset(['issues', 'is_invalid'])
        self.assertTrue(dmfa.is_invalid)
        with self.assertRaises(UserError):
            dmfa._get_rendering_data()

    @freeze_time('2026-05-15')
    def test_dmfa_quarter_not_ended(self):
        """ The ONSS only accepts the declarations of the ended quarters """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))

        def messages(quarter):
            dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': quarter})
            dmfa._compute_issues()
            return [issue['message'] for issue in (dmfa.issues or {}).values()]

        self.assertIn("The quarter isn't ended yet: it can only be declared from 01/07/2026.", messages('2'))
        self.assertFalse(any(message.startswith("The quarter isn't ended yet") for message in messages('1')))

    @freeze_time('2026-05-15')
    def test_dmfa_draft_payslips(self):
        """ The payslips of the quarter that aren't validated aren't declared """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee_test.id,
            'name': 'Draft payslip',
            'date_from': date(2026, 2, 1),
            'date_to': date(2026, 2, 28),
        })

        dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '1'})

        def messages():
            dmfa._compute_issues()
            return [issue['message'] for issue in (dmfa.issues or {}).values()]

        self.assertIn("1 payslips of the quarter aren't validated, they won't be declared: %s" % self.employee_test.name, messages())
        payslip.state = 'validated'
        self.assertFalse(any("aren't validated" in message for message in messages()))

    @freeze_time('2026-05-15')
    def test_dmfa_invalid_niss(self):
        """ A NISS with a wrong check number is refused by the ONSS """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        self.env['hr.payslip'].create({
            'employee_id': self.employee_test.id,
            'name': 'Payslip',
            'date_from': date(2026, 2, 1),
            'date_to': date(2026, 2, 28),
        }).state = 'validated'
        dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '1'})

        def messages():
            dmfa._compute_issues()
            return [issue['message'] for issue in (dmfa.issues or {}).values()]

        # The NISS are checked when saved, but not the ones saved before that check
        self.env.cr.execute("UPDATE hr_employee SET niss = '85010100116' WHERE id = %s", [self.employee_test.id])
        self.employee_test.invalidate_recordset(['niss'])
        self.assertIn("Invalid NISS for employees %s" % self.employee_test.name, messages())
        self.employee_test.niss = '85010100115'
        self.assertFalse(any(message.startswith("Invalid NISS") for message in messages()))

    @freeze_time('2026-05-15')
    def test_dmfa_unit_without_code(self):
        """ The establishment unit code of the work address is declared on each occupation """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        self.env['hr.payslip'].create({
            'employee_id': self.employee_test.id,
            'name': 'Payslip',
            'date_from': date(2026, 2, 1),
            'date_to': date(2026, 2, 28),
        }).state = 'validated'
        unit = self.env['hr.work.location'].search([
            ('address_id', '=', self.employee_test.address_id.id), ('location_type', '=', 'dmfa_unit')])
        self.assertTrue(unit)
        dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '1'})

        def messages():
            dmfa._compute_issues()
            return [issue['message'] for issue in (dmfa.issues or {}).values()]

        unit.bce_code = False
        self.assertIn("DMFA units without establishment unit code %s" % unit.name, messages())
        unit.bce_code = '8888888374'
        self.assertFalse(any(message.startswith("DMFA units without") for message in messages()))

    @freeze_time('2026-05-15')
    def test_dmfa_refused_flexi_worker_code(self):
        """ A flexi-job whose Dimona flexi was refused is declared as an ordinary worker """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        self.env['hr.payslip'].create({
            'employee_id': self.employee_test.id,
            'name': 'Payslip',
            'date_from': date(2026, 2, 1),
            'date_to': date(2026, 2, 28),
        }).state = 'validated'
        version = self.employee_test.version_id
        worker_codes = self.env['l10n.be.worker.code'].search([('dmfa_code', 'in', ('450', '495'))]).grouped('dmfa_code')
        self.env.cr.execute("""
            UPDATE hr_version SET l10n_be_dimona_category = 'flx', l10n_be_refused_flexijob = TRUE, l10n_be_worker_code_id = %s
            WHERE id = %s""", [worker_codes['450'].id, version.id])
        version.invalidate_recordset()
        dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '1'})

        def messages():
            dmfa._compute_issues()
            return [issue['message'] for issue in (dmfa.issues or {}).values()]

        self.assertTrue(any(message.startswith("Refused flexi-jobs are declared as ordinary workers") for message in messages()))
        self.env.cr.execute("UPDATE hr_version SET l10n_be_worker_code_id = %s WHERE id = %s", [worker_codes['495'].id, version.id])
        version.invalidate_recordset()
        self.assertFalse(any(message.startswith("Refused flexi-jobs") for message in messages()))

    @freeze_time('2026-05-15')
    def test_dmfa_work_exemption_date(self):
        """ The start date of an exemption from work is mandatory in the block of the activation contribution """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        self.env['hr.payslip'].create({
            'employee_id': self.employee_test.id,
            'name': 'Payslip',
            'date_from': date(2026, 2, 1),
            'date_to': date(2026, 2, 28),
        }).state = 'validated'
        version = self.employee_test.version_id
        version.l10n_be_work_exemption = '2'
        dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '1'})

        def messages():
            dmfa._compute_issues()
            return [issue['message'] for issue in (dmfa.issues or {}).values()]

        self.assertTrue(any(message.startswith("The exemption from work of these employees has no start date") for message in messages()))
        version.l10n_be_work_exemption_date = date(2025, 12, 1)
        self.assertFalse(any(message.startswith("The exemption from work") for message in messages()))

    @freeze_time('2026-05-15')
    def test_dmfa_complementary_indemnity_worker_code(self):
        """ The complementary indemnities (RCC/RCIC) can't be declared by Odoo """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        self.env['hr.payslip'].create({
            'employee_id': self.employee_test.id,
            'name': 'Payslip',
            'date_from': date(2026, 2, 1),
            'date_to': date(2026, 2, 28),
        }).state = 'validated'
        rcc_code = self.env['l10n.be.worker.code'].search([('dmfa_code', '=', '879')])
        self.assertTrue(rcc_code)
        self.env.cr.execute("UPDATE hr_version SET l10n_be_worker_code_id = %s WHERE id = %s", [rcc_code.id, self.employee_test.version_id.id])
        self.employee_test.version_id.invalidate_recordset()
        dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '1'})
        dmfa._compute_issues()
        messages = [issue['message'] for issue in (dmfa.issues or {}).values()]
        self.assertTrue(any(message.startswith("The complementary indemnities (RCC, RCIC") for message in messages))

    @freeze_time('2026-05-15')
    def test_dmfa_unit_invalid_code(self):
        """ The last 2 digits of the establishment unit code are its check number (97 - the first 8 digits modulo 97) """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        self.env['hr.payslip'].create({
            'employee_id': self.employee_test.id,
            'name': 'Payslip',
            'date_from': date(2026, 2, 1),
            'date_to': date(2026, 2, 28),
        }).state = 'validated'
        unit = self.env['hr.work.location'].search([
            ('address_id', '=', self.employee_test.address_id.id), ('location_type', '=', 'dmfa_unit')])
        dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '1'})

        def messages():
            dmfa._compute_issues()
            return [issue['message'] for issue in (dmfa.issues or {}).values()]

        unit.bce_code = '8888888375'
        self.assertIn("DMFA units with an invalid establishment unit code %s" % unit.name, messages())
        unit.bce_code = '8999999104'  # an official fictitious code
        self.assertFalse(any(message.startswith("DMFA units with an invalid") for message in messages()))

    @freeze_time('2026-05-15')
    def test_dmfa_student_hours(self):
        """ The student hours of a quarter can't exceed 650 """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        version = self.employee_test.version_id
        self.env.cr.execute("UPDATE hr_version SET l10n_be_dimona_category = 'stu' WHERE id = %s", [version.id])
        version.invalidate_recordset()
        attendance = self.env.ref('hr_work_entry.be_work_entry_type_attendance')
        self.assertEqual(attendance.code, '002.00')
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee_test.id,
            'name': 'Payslip',
            'date_from': date(2026, 2, 1),
            'date_to': date(2026, 2, 28),
            'worked_days_line_ids': [(0, 0, {
                'work_entry_type_id': attendance.id,
                'version_id': version.id,
                'number_of_days': 92,
                'number_of_hours': 700,
            })],
        })
        payslip.state = 'validated'
        dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '1'})

        def messages():
            dmfa._compute_issues()
            return [issue['message'] for issue in (dmfa.issues or {}).values()]

        self.assertTrue(any(message.startswith("Students with more than 650 hours") for message in messages()))
        payslip.worked_days_line_ids.number_of_hours = 600
        self.assertFalse(any(message.startswith("Students with more than 650 hours") for message in messages()))

    @freeze_time('2026-05-15')
    def test_dmfa_student_worker_code(self):
        """ The students are declared with the worker codes 840 and 841 """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        version = self.employee_test.version_id
        self.env.cr.execute("UPDATE hr_version SET l10n_be_dimona_category = 'stu' WHERE id = %s", [version.id])
        version.invalidate_recordset()
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee_test.id,
            'name': 'Payslip',
            'date_from': date(2026, 2, 1),
            'date_to': date(2026, 2, 28),
        })
        payslip.state = 'validated'
        dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '1'})

        def messages():
            dmfa._compute_issues()
            return [issue['message'] for issue in (dmfa.issues or {}).values()]

        self.assertNotIn(version.l10n_be_worker_code_id.dmfa_code, ['840', '841'])
        self.assertTrue(any(message.startswith("The students (Dimona STU) must have the worker code 840 or 841") for message in messages()))
        self.env.cr.execute("UPDATE hr_version SET l10n_be_worker_code_id = %s WHERE id = %s", [
            self.env['l10n.be.worker.code'].search([('dmfa_code', '=', '841')]).id, version.id])
        version.invalidate_recordset()
        self.assertFalse(any(message.startswith("The students (Dimona STU) must have the worker code 840 or 841") for message in messages()))

    def test_too_old_pupil_worker_code(self):
        """ The worker codes of the pupils and trainees (027, 022) are used until the end of the year they turn 18 """
        employee = self.employee_test
        employee.birthday = date(2000, 1, 1)
        WorkerCode = self.env['l10n.be.worker.code']
        for young_code, adult_code in (('027', '015'), ('022', '011')):
            employee.l10n_be_worker_code_id = WorkerCode.search([('dmfa_code', '=', young_code)])
            self.assertIn(employee, self.env['hr.employee']._get_l10n_be_too_old_worker_code_employees(employees=employee))
            employee.l10n_be_action_update_worker_codes()
            self.assertEqual(employee.l10n_be_worker_code_id.dmfa_code, adult_code)

    @freeze_time('2026-05-15')
    def test_dmfa_flexi_already_employed(self):
        """ A flexi-job can't be held at the employer already employing the worker in the quarter """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        ordinary_version = self.employee_test.version_id
        flexi_version = self.employee_test.create_version({'date_version': date(2026, 2, 1)})
        self.env.cr.execute("UPDATE hr_version SET l10n_be_dimona_category = 'flx' WHERE id = %s", [flexi_version.id])
        flexi_version.invalidate_recordset()
        self.assertTrue(flexi_version.is_flexi())
        payslips = self.env['hr.payslip'].create([{
            'employee_id': self.employee_test.id,
            'version_id': version.id,
            'name': 'Payslip',
            'date_from': date_from,
            'date_to': date_from + relativedelta(day=31),
        } for version, date_from in ((ordinary_version, date(2026, 1, 1)), (flexi_version, date(2026, 2, 1)))])
        payslips.write({'state': 'validated'})
        dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '1'})

        def messages():
            dmfa._compute_issues()
            return [issue['message'] for issue in (dmfa.issues or {}).values()]

        self.assertTrue(any(message.startswith("Flexi-jobs at the employer already employing the worker") for message in messages()))
        # a flexi-job can become an ordinary employment
        payslips[0].write({'version_id': flexi_version.id})
        payslips[1].write({'version_id': ordinary_version.id})
        self.assertFalse(any(message.startswith("Flexi-jobs at the employer already employing the worker") for message in messages()))

    @freeze_time('2026-05-15')
    def test_dmfa_excludes_not_subject_workers(self):
        """ The workers not subject to the ONSS (article 17, internships...) aren't declared """
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee_test.id,
            'name': 'Payslip',
            'date_from': date(2026, 2, 1),
            'date_to': date(2026, 2, 28),
        })
        payslip.state = 'validated'
        dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '1'})
        self.assertIn(payslip, dmfa.payslip_ids)
        self.employee_test.version_id.l10n_be_dimona_category = 'o17'
        self.assertTrue(self.employee_test.version_id.no_onss)
        dmfa._compute_eligible_payslip_ids()
        self.assertNotIn(payslip, dmfa.payslip_ids)

    @freeze_time('2027-01-15')
    def test_dmfa_holiday_starting_date(self):
        """ The date of the start of the holidays is mandatory in the fourth quarter with manual workers """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee_test.id,
            'name': 'Payslip',
            'date_from': date(2026, 11, 1),
            'date_to': date(2026, 11, 30),
        })
        payslip.state = 'validated'
        dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '4'})

        def messages():
            dmfa._compute_issues()
            return [issue['message'] for issue in (dmfa.issues or {}).values()]

        self.assertFalse(self.employee_test.version_id.is_worker())
        self.assertFalse(any(message.startswith("The date of the start of the holidays") for message in messages()))
        self.employee_test.version_id.l10n_be_worker_code_id = self.env['l10n.be.worker.code'].search([('dmfa_code', '=', '015')])
        self.assertTrue(any(message.startswith("The date of the start of the holidays") for message in messages()))

    @freeze_time('2026-05-15')
    def test_dmfa_percentage_paid(self):
        """ The reductions of the working time with an unpaid compensatory rest (service code 20) need the
        percentage of the increased pay """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        reduction = self.env['hr.work.entry.type'].search([('code', '=', '181.00')])
        self.assertEqual(reduction.dmfa_code, '20')
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee_test.id,
            'name': 'Payslip',
            'date_from': date(2026, 2, 1),
            'date_to': date(2026, 2, 28),
            'worked_days_line_ids': [(0, 0, {
                'work_entry_type_id': reduction.id,
                'version_id': self.employee_test.version_id.id,
                'number_of_days': 1,
                'number_of_hours': 7.6,
            })],
        })
        payslip.state = 'validated'
        dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '1'})
        dmfa._compute_issues()
        self.assertTrue(any(issue['message'].startswith("The percentage of the increased hourly pay") for issue in dmfa.issues.values()))

    @freeze_time('2026-05-15')
    def test_dmfa_correction_needed(self):
        """ A declared DMFA needs a correction for a new or a cancelled payslip of its company in its quarter """
        dmfa = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '1'})
        other_company = self.env['res.company'].create({
            'name': 'Other Belgian Company',
            'country_id': self.env.ref('base.be').id,
            'onss_expeditor_number': self.env.company.onss_expeditor_number or '123456',
        })
        other_dmfa = self.env['l10n_be.dmfa'].with_company(other_company).create({'company_id': other_company.id, 'year': '2026', 'quarter': '1'})
        (dmfa | other_dmfa).write({'state': 'done'})

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee_test.id,
            'name': 'Payslip',
            'date_from': date(2026, 2, 1),
            'date_to': date(2026, 2, 28),
        })
        payslip.compute_sheet()
        payslip.action_payslip_done()
        self.assertTrue(dmfa.is_correction_needed)
        self.assertFalse(other_dmfa.is_correction_needed)

        dmfa.is_correction_needed = False
        payslip.l10n_be_dmfa_id = dmfa
        payslip.action_payslip_cancel()
        self.assertTrue(dmfa.is_correction_needed)

    def test_dmfa_quarter_dates(self):
        # the dates of both are computed together
        dmfa_q1 = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '1'})
        dmfa_q2 = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '2'})
        self.assertEqual((dmfa_q1.quarter_start, dmfa_q1.quarter_end), (date(2026, 1, 1), date(2026, 3, 31)))
        self.assertEqual((dmfa_q2.quarter_start, dmfa_q2.quarter_end), (date(2026, 4, 1), date(2026, 6, 30)))

    @freeze_time('2026-07-15')
    def test_dmfa_termination_quarter(self):
        """ A termination indemnity is declared in the quarter of the end of the contract, the notice
        period starting after it """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        version = self.employee_test.version_id
        version.contract_date_end = date(2026, 3, 30)
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee_test.id,
            'name': 'Termination Fees',
            'version_id': version.id,
            'date_from': date(2026, 4, 6),
            'date_to': date(2026, 4, 6),
            'struct_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_termination_fees').id,
        })
        payslip.state = 'validated'
        dmfa_q1 = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '1'})
        dmfa_q2 = self.env['l10n_be.dmfa'].create({'company_id': self.env.company.id, 'year': '2026', 'quarter': '2'})
        self.assertIn(payslip, dmfa_q1.payslip_ids)
        self.assertNotIn(payslip, dmfa_q2.payslip_ids)

        # The DMFA of the quarter of the end of the contract is already declared
        dmfa_q2._compute_issues()
        self.assertTrue(any(issue['message'].startswith("Termination indemnities to declare with a modification")
                            for issue in (dmfa_q2.issues or {}).values()))
        payslip.l10n_be_is_dmfa_reported = True
        dmfa_q2._compute_issues()
        self.assertFalse(any(issue['message'].startswith("Termination indemnities to declare with a modification")
                             for issue in (dmfa_q2.issues or {}).values()))

    def test_dmfa_service_codes(self):
        """ The service codes of the ONSS working time codification """
        for xmlid, dmfa_code in [
            ('l10n_be_work_entry_type_temporary_unemployment_strike', '70'),  # temporary unemployment, not economic
            ('l10n_be_work_entry_type_adoption_company', '1'),  # paid by the employer, not by the INAMI
            ('l10n_be_work_entry_type_training_social_promotion', '13'),
            ('l10n_be_work_entry_type_public_holiday_temporary_unemployment_no_onss', '10'),
            ('l10n_be_work_entry_type_overtime_no_onss', '80'),  # Horeca overtime without ONSS
        ]:
            self.assertEqual(self.env.ref(f'hr_work_entry.{xmlid}').dmfa_code, dmfa_code, xmlid)

    def test_dmfa_establishment_unit_code_format(self):
        """
        Test that checks if a validation error is raised when trying to write an invalid code on an establishment unit.
        """
        with self.assertRaises(ValidationError) as error:
            self.env['hr.work.location'].create({
                "company_id": self.belgian_company.id,
                "bce_code": 1234567890,
                "address_id": self.belgian_company.partner_id.id,
            })
        self.assertIn('The DMFA establishment unit code must be 10 digits long. The first digit must be between 2 and 8.', str(error.exception))

        with self.assertRaises(ValidationError) as error:
            self.env['hr.work.location'].create({
                "company_id": self.belgian_company.id,
                "bce_code": 888888888,
                "address_id": self.belgian_company.partner_id.id,
            })
        self.assertIn('The DMFA establishment unit code must be 10 digits long. The first digit must be between 2 and 8.', str(error.exception))

        establishment_unit = self.env['hr.work.location'].create({
            "company_id": self.belgian_company.id,
            "bce_code": 8888888888,
            "address_id": self.belgian_company.partner_id.id,
        })
        with self.assertRaises(ValidationError) as error:
            establishment_unit.write({'bce_code': 123})
        self.assertIn('The DMFA establishment unit code must be 10 digits long. The first digit must be between 2 and 8.', str(error.exception))

    def test_dmfa_establishment_unit_valid_location_dates(self):
        """
        Checks that a validation error is raised when:
        1. Trying to change the location date after the contract start date of an employee working in the related EU.
        2. Trying to change the contract start date of an employee working in an EU before its location date.
        """
        self.employee_a.write({'work_location_id': self.env['hr.work.location'].search([
            ('company_id', '=', self.belgian_company.id),
        ], limit=1).id})
        establishment_unit = self.env['hr.work.location'].create({
            "company_id": self.belgian_company.id,
            "bce_code": 8234567890,
            "address_id": self.belgian_company.partner_id.id,
            "date_start": "2016-12-05"
        })
        establishment_unit.write({"date_start": datetime.now()})
        with self.assertRaises(ValidationError):
            self.employee_a.write({'work_location_id': establishment_unit.id})
        self.employee_a.version_id.work_location_id.write({'date_start': self.employee_a.version_id.date_start})
        with self.assertRaises(ValidationError):
            self.employee_a.version_id.write({'contract_date_start': "2019-12-05"})

    def test_dmfa_establishment_unit_competence_computation(self):
        """
        Checks that the correct competence and payslip language are set on an establishment unit when setting its
        address.
        """
        nl_partner = self.env['res.partner'].create({
            'name': 'NL partner',
            'city': 'Machelen',
            'zip': 1830
        })
        de_partner = self.env['res.partner'].create({
            'name': 'DE partner',
            'city': 'Eupen',
            'zip': 4700
        })
        with Form(self.env['hr.work.location']) as eu:
            eu.bce_code = 8234567890
            eu.address_id = self.belgian_company.partner_id
        self.assertEqual(eu.competence, 'wa')
        with Form(self.env['hr.work.location']) as eu:
            eu.bce_code = 8234567890
            eu.address_id = nl_partner
        self.assertEqual(eu.competence, 'fl')
        with Form(self.env['hr.work.location']) as eu:
            eu.bce_code = 8234567890
            eu.address_id = de_partner
        self.assertEqual(eu.competence, 'cg')
