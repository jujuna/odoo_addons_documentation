# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from unittest.mock import patch
from dateutil.relativedelta import relativedelta

from odoo import SUPERUSER_ID
from odoo.addons.l10n_be_hr_payroll.models.hr_version import HrVersion
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import MockHTTPClient, TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install', 'post_install_l10n', 'dimona')
@patch.object(HrVersion, '_dimona_authenticate', lambda version, company, declare=True: 'dummy-token')
@patch.object(HrVersion, '_cron_l10n_be_check_dimona', lambda version: True)
class TestDimona(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.belgium = cls.env.ref('base.be')

        cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').write({'active': True})
        cls.env.company.write({
            'country_id': cls.belgium.id,
            'onss_expeditor_number': '123456',
        })
        cls.env.company.payroll_config_ids[-1].write({
            'onss_registration_number': '125482497',
        })

        cls.employee = cls.env['hr.employee'].create({
            'name': 'Test Employee',
            'niss': '93051822361',
            'private_street': '23 Test Street',
            'private_city': 'Test City',
            'private_zip': '6800',
            'private_country_id': cls.belgium.id,
            'wage': 2000,
            'date_version': date.today() + relativedelta(day=1, months=1),
            'contract_date_start': date.today() + relativedelta(day=1, months=1),
            'sex': 'male',
        })

        cls.version = cls.employee.version_id

    def test_dimona_open_classic(self):
        wizard = self.env['l10n.be.dimona.wizard'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'declaration_type': 'in',
        })

        self.version.l10n_be_dimona_category = False  # as version default type is Employee, and it has default category we set it to False to test the error case of missing category
        with MockHTTPClient(return_headers={'Location': 'foo/bar/blork/2029409422'}, return_status=201):
            with self.assertRaises(UserError) as e:
                wizard.submit_declaration()
            self.assertIn('The DIMONA category is missing for employee', str(e.exception))

        self.version.l10n_be_dimona_category = 'oth'
        with MockHTTPClient(return_headers={'Location': 'foo/bar/blork/2029409422'}, return_status=201):
            wizard.submit_declaration()

        self.assertEqual(self.version.l10n_be_dimona_declaration_id.name, '2029409422')
        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.name, '2029409422')
        self.assertFalse(self.version.l10n_be_dimona_declaration_id.state)
        self.assertFalse(self.version.l10n_be_last_dimona_declaration_id.state)

    def test_dimona_open_foreigner(self):
        self.employee.write({
            'birthday': date(1991, 7, 28),
            'place_of_birth': 'Paris',
            'country_of_birth': self.env.ref('base.fr').id,
            'country_id': self.env.ref('base.fr').id,
            'sex': 'male',
        })

        wizard = self.env['l10n.be.dimona.wizard'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'declaration_type': 'in',
            'without_niss': True,
        })
        self.version.l10n_be_dimona_category = 'oth'

        with MockHTTPClient(return_headers={'Location': 'foo/bar/blork/2029409422'}, return_status=201):
            wizard.submit_declaration()

        self.assertEqual(self.version.l10n_be_dimona_declaration_id.name, '2029409422')
        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.name, '2029409422')
        self.assertFalse(self.version.l10n_be_dimona_declaration_id.state)
        self.assertFalse(self.version.l10n_be_last_dimona_declaration_id.state)

    def test_dimona_open_student(self):
        self.version.write({
            'l10n_be_dimona_category': 'stu',
            'l10n_be_dimona_planned_hours': 130,
            'contract_date_end': date.today() + relativedelta(months=1, day=31),
        })
        wizard = self.env['l10n.be.dimona.wizard'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'declaration_type': 'in',
        })

        with MockHTTPClient(return_headers={'Location': 'foo/bar/blork/2029409422'}, return_status=201):
            wizard.submit_declaration()

        self.assertEqual(self.version.l10n_be_dimona_declaration_id.name, '2029409422')
        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.name, '2029409422')
        self.assertFalse(self.version.l10n_be_dimona_declaration_id.state)
        self.assertFalse(self.version.l10n_be_last_dimona_declaration_id.state)

    def test_dimona_student_planned_hours_quota(self):
        """ The planned hours of a student can't exceed the yearly quota of the student hours (650 in 2026) """
        self.version.write({
            'l10n_be_dimona_category': 'stu',
            'contract_date_start': date(2026, 7, 1),
            'contract_date_end': date(2026, 9, 30),
            'l10n_be_dimona_planned_hours': 650,
        })
        with self.assertRaisesRegex(ValidationError, "can't exceed the yearly quota of 650 hours"):
            self.version.l10n_be_dimona_planned_hours = 700
        with self.assertRaisesRegex(ValidationError, "can't be negative"):
            self.version.l10n_be_dimona_planned_hours = -1
        # from the employee form too
        with self.assertRaisesRegex(ValidationError, "can't exceed the yearly quota of 650 hours"):
            self.employee.l10n_be_dimona_planned_hours = 651
        # the quota of the year of the start of the occupation (600 hours in 2024)
        with self.assertRaisesRegex(ValidationError, "can't exceed the yearly quota of 600 hours"):
            self.version.write({
                'contract_date_start': date(2024, 7, 1),
                'contract_date_end': date(2024, 9, 30),
            })
        # the hours of a worker who is not a student are not limited
        self.version.write({'l10n_be_dimona_category': 'oth', 'l10n_be_dimona_planned_hours': 700})

    def test_dimona_close(self):
        self.version.l10n_be_dimona_declaration_id = self.env['l10n.be.dimona.declaration'].create({
                'name': '2029409422',
                'version_id': self.version.id,
                'employee_id': self.version.employee_id.id,
                'company_id': self.version.company_id.id,
            })
        self.version.contract_date_end = date.today() + relativedelta(months=1, day=31)

        wizard = self.env['l10n.be.dimona.wizard'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'declaration_type': 'out',
        })

        with MockHTTPClient(return_headers={'Location': 'foo/bar/blork/309320239'}, return_status=201):
            wizard.submit_declaration()

        self.assertEqual(self.version.l10n_be_dimona_declaration_id.name, '2029409422')
        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.name, '309320239')
        self.assertFalse(self.version.l10n_be_dimona_declaration_id.state)
        self.assertFalse(self.version.l10n_be_last_dimona_declaration_id.state)

    def test_dimona_close_without_entrance(self):
        # The entrance of the contract was declared outside Odoo
        self.version.contract_date_end = date.today() + relativedelta(months=1, day=31)
        wizard = self.env['l10n.be.dimona.wizard'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'declaration_type': 'out',
        })
        with self.assertRaisesRegex(UserError, 'was not declared from Odoo'):
            wizard.submit_declaration()

    def test_dimona_update(self):
        self.version.l10n_be_dimona_declaration_id = self.env['l10n.be.dimona.declaration'].create({
                'name': '2029409422',
                'version_id': self.version.id,
                'employee_id': self.version.employee_id.id,
                'company_id': self.version.company_id.id,
            })
        self.version.contract_date_end = date.today() + relativedelta(months=1, day=31)
        self.version.l10n_be_dimona_category = 'oth'

        wizard = self.env['l10n.be.dimona.wizard'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'declaration_type': 'update',
        })

        with MockHTTPClient(return_headers={'Location': 'foo/bar/blork/309320239'}, return_status=201):
            wizard.submit_declaration()

        self.assertEqual(self.version.l10n_be_dimona_declaration_id.name, '2029409422')
        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.name, '309320239')
        self.assertFalse(self.version.l10n_be_dimona_declaration_id.state)
        self.assertFalse(self.version.l10n_be_last_dimona_declaration_id.state)

    def test_dimona_cancel(self):
        self.version.l10n_be_dimona_declaration_id = self.env['l10n.be.dimona.declaration'].create({
                'name': '2029409422',
                'version_id': self.version.id,
                'employee_id': self.version.employee_id.id,
                'company_id': self.version.company_id.id,
            })

        wizard = self.env['l10n.be.dimona.wizard'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'declaration_type': 'cancel',
        })

        with MockHTTPClient(return_headers={'Location': 'foo/bar/blork/309320239'}, return_status=201):
            wizard.submit_declaration()

        self.assertEqual(self.version.l10n_be_dimona_declaration_id.name, '2029409422')
        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.name, '309320239')
        self.assertFalse(self.version.l10n_be_dimona_declaration_id.state)
        self.assertFalse(self.version.l10n_be_last_dimona_declaration_id.state)

    def test_dimona_branch_employee(self):
        """ The Dimona of the employees of a branch are filed with the access of the employer, its root company """
        certificate = self.env['certificate.certificate'].create({'name': 'onss cert'})
        self.env.company.onss_certificate_id = certificate
        branch = self.env['res.company'].create({
            'name': 'Branch', 'parent_id': self.env.company.id, 'country_id': self.belgium.id})
        self.env.user.company_ids |= branch
        # The Dimona IN is filed when the contract is created
        with MockHTTPClient(return_headers={'Location': 'foo/bar/blork/2029409422'}, return_status=201):
            employee = self.env['hr.employee'].create({
                'name': 'Branch Employee',
                'company_id': branch.id,
                'niss': '91111111192',
                'private_street': '23 Test Street',
                'private_city': 'Test City',
                'private_zip': '6800',
                'private_country_id': self.belgium.id,
                'wage': 2000,
                'date_version': date(2025, 9, 26),
                'contract_date_start': date(2025, 9, 26),
                'sex': 'male',
                'l10n_be_dimona_category': 'oth',
            })
        self.assertTrue(employee.version_id._l10n_be_dimona_can_declare())
        self.assertEqual(employee.version_id.l10n_be_dimona_declaration_id.name, '2029409422')

    def test_fetched_dimona_of_branch_employee(self):
        """ The Dimona fetched by the employer, the root company, are linked to the employees of its branches """
        branch = self.env['res.company'].create({
            'name': 'Branch', 'parent_id': self.env.company.id, 'country_id': self.belgium.id})
        self.employee.company_id = branch
        relation = self.env['l10n.be.dimona.relation'].create({
            'name': self.employee.niss,
            'company_id': self.env.company.id,
            'content': {'startDate': '2025-09-26'},
        })
        period = self.env['l10n.be.dimona.period'].create({
            'name': '2029409422',
            'company_id': self.env.company.id,
            'content': {'startDate': '2025-09-26', 'worker': {'ssin': self.employee.niss}},
        })
        self.assertEqual(relation.employee_id, self.employee)
        self.assertEqual(period.employee_id, self.employee)
        self.assertEqual(period.relation_id, relation)

    def test_fetch_all_dimona_from_cron(self):
        """ The cron fetches the Dimona of all the companies, without version """
        self.env.company.onss_certificate_id = self.env['certificate.certificate'].create({'name': 'onss cert'})
        cron_env = self.env(user=SUPERUSER_ID, su=True)
        with MockHTTPClient(return_json={'items': [], 'next': False}, return_status=200) as mock:
            cron_env['hr.version'].action_fetch_all_dimona()
        self.assertTrue(mock.calls)

    def test_dimona_flow_classic(self):
        # pylint: disable=function-redefined
        certificate = self.env['certificate.certificate'].create({'name': 'onss cert'})
        self.version.date_version = date(2025, 9, 26)
        self.version.contract_date_start = date(2025, 9, 26)

        self.env.company.write({
            'onss_certificate_id': certificate,
        })

        # No dimona yet
        self.assertFalse(self.employee.l10n_be_dimona_declaration_id)
        self.assertFalse(self.employee.l10n_be_last_dimona_declaration_id)

        # Needs Dimona IN is true
        self.assertTrue(self.employee.l10n_be_needs_dimona_in)
        self.assertFalse(self.employee.l10n_be_needs_dimona_update)
        self.assertFalse(self.employee.l10n_be_needs_dimona_out)
        self.assertFalse(self.employee.l10n_be_needs_dimona_cancel)
        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'in')

        self.version.l10n_be_dimona_category = False  # as version default type is Employee, and it has default category we set it to False to test the error case of missing category
        with MockHTTPClient(return_headers={'Location': 'foo/bar/blork/2029409422'}, return_status=201):
            with self.assertRaises(UserError) as e:
                self.employee.action_send_dimona()
            self.assertIn('The DIMONA category is missing for employee', str(e.exception))

        self.version.l10n_be_dimona_category = 'oth'
        with MockHTTPClient(return_headers={'Location': 'foo/bar/blork/2029409422'}, return_status=201):
            self.employee.action_send_dimona()

        # Dimona IN created
        self.assertEqual(self.version.l10n_be_dimona_declaration_id.name, '2029409422')
        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.name, '2029409422')
        self.assertFalse(self.version.l10n_be_dimona_declaration_id.state)
        self.assertFalse(self.version.l10n_be_last_dimona_declaration_id.state)

        # No displayed button, nothing to do
        self.assertFalse(self.employee.l10n_be_needs_dimona_in)
        self.assertFalse(self.employee.l10n_be_needs_dimona_update)
        self.assertFalse(self.employee.l10n_be_needs_dimona_out)
        self.assertFalse(self.employee.l10n_be_needs_dimona_cancel)
        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'progress')

        with MockHTTPClient(return_json={
            "href": "https://services-sim.socialsecurity.be/REST/dimona/v2/declarations/2029409422", "worker": {"ssin": "93051822361", "gender": "1", "birthDate": "1991-11-11", "givenName": "TEST", "familyName": "EMPLOYEE", "givenNames": "TEST EMPLOYEE", "nationality": 150}, "dimonaIn": {"features": {"workerType": "OTH", "jointCommissionNumber": "XXX"}, "startDate": "2025-09-26"}, "employer": {"employerId": 12548245, "enterpriseNumber": "477472701"}, "declarationStatus": {"period": {"id": 2029409422, "href": "https://services-sim.socialsecurity.be/REST/dimona/v2/periods/2029409422"}, "result": "B", "declarationId": 2029409422}
        }, return_status=200):
            self.employee.action_check_dimona()

        self.assertEqual(self.version.l10n_be_dimona_declaration_id.state, 'B')
        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.state, 'B')

        # Dimona issue, send dimona button is displayed to resubmit dimona in
        self.assertTrue(self.employee.l10n_be_needs_dimona_in)
        self.assertFalse(self.employee.l10n_be_needs_dimona_update)
        self.assertFalse(self.employee.l10n_be_needs_dimona_out)
        self.assertFalse(self.employee.l10n_be_needs_dimona_cancel)
        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'issue')

        with MockHTTPClient(return_json={
            "href": "https://services-sim.socialsecurity.be/REST/dimona/v2/declarations/2029409411", "worker": {"ssin": "93051822361", "gender": "1", "birthDate": "1991-11-11", "givenName": "TEST", "familyName": "EMPLOYEE", "givenNames": "TEST EMPLOYEE", "nationality": 150}, "dimonaIn": {"features": {"workerType": "OTH", "jointCommissionNumber": "XXX"}, "startDate": "2025-09-26"}, "employer": {"employerId": 125482497, "enterpriseNumber": "477472701"}, "declarationStatus": {"period": {"id": 2029409422, "href": "https://services-sim.socialsecurity.be/REST/dimona/v2/periods/2029409422"}, "result": "A", "declarationId": 2029409411}
        }, return_status=200):
            self.employee.action_check_dimona()

        self.assertEqual(self.version.l10n_be_dimona_declaration_id.state, 'A')
        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.state, 'A')

        # No displayed button, nothing to do
        self.assertFalse(self.employee.l10n_be_needs_dimona_in)
        self.assertFalse(self.employee.l10n_be_needs_dimona_update)
        self.assertFalse(self.employee.l10n_be_needs_dimona_out)
        self.assertFalse(self.employee.l10n_be_needs_dimona_cancel)
        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'done')

        # unset the certificate to avoid automatic declaration on write
        self.env.company.write({
            'onss_certificate_id': False,
        })

        # Now, update contract start date
        self.version.date_version = date(2025, 7, 3)
        self.version.contract_date_start = date(2025, 7, 3)

        self.env.company.write({
            'onss_certificate_id': certificate,
        })

        # send dimona button is displayed for dimona update
        self.assertFalse(self.employee.l10n_be_needs_dimona_in)
        self.assertTrue(self.employee.l10n_be_needs_dimona_update)
        self.assertFalse(self.employee.l10n_be_needs_dimona_out)
        self.assertFalse(self.employee.l10n_be_needs_dimona_cancel)
        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'update')

        with MockHTTPClient(return_headers={'Location': 'foo/bar/blork/656309296521'}, return_status=201):
            self.employee.action_send_dimona()

        # No displayed button, waiting for status
        self.assertFalse(self.employee.l10n_be_needs_dimona_in)
        self.assertTrue(self.employee.l10n_be_needs_dimona_update)
        self.assertFalse(self.employee.l10n_be_needs_dimona_out)
        self.assertFalse(self.employee.l10n_be_needs_dimona_cancel)
        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'progress')

        self.assertEqual(self.version.l10n_be_dimona_declaration_id.name, '2029409422')
        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.name, '656309296521')
        self.assertFalse(self.version.l10n_be_last_dimona_declaration_id.state)

        with MockHTTPClient(return_json={
            "href": "https://services-sim.socialsecurity.be/REST/dimona/v2/declarations/656309296521", "worker": {"ssin": "93051822361", "gender": "1", "birthDate": "1991-11-11", "givenName": "TEST", "familyName": "EMPLOYEE", "givenNames": "TEST EMPLOYEE", "nationality": 150}, "employer": {"employerId": 125482497, "enterpriseNumber": "477472701"}, "dimonaUpdate": {"periodId": 656309292174, "startDate": "2025-07-03"}, "declarationStatus": {"period": {"id": 656309292174, "href": "https://services-sim.socialsecurity.be/REST/dimona/v2/periods/656309292174"}, "result": "B", "declarationId": 656309296521}
        }, return_status=200):
            self.employee.action_check_dimona()

        self.assertEqual(self.version.l10n_be_dimona_declaration_id.state, 'A')
        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.state, 'B')

        # No displayed button, nothing to do
        self.assertFalse(self.employee.l10n_be_needs_dimona_in)
        self.assertTrue(self.employee.l10n_be_needs_dimona_update)
        self.assertFalse(self.employee.l10n_be_needs_dimona_out)
        self.assertFalse(self.employee.l10n_be_needs_dimona_cancel)
        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'issue')

        with MockHTTPClient(
            return_json={
                "href": "https://services-sim.socialsecurity.be/REST/dimona/v2/declarations/656309296531", "worker": {"ssin": "93051822361", "gender": "1", "birthDate": "1991-11-11", "givenName": "TEST", "familyName": "EMPLOYEE", "givenNames": "TEST EMPLOYEE", "nationality": 150}, "employer": {"employerId": 125482497, "enterpriseNumber": "477472701"}, "dimonaUpdate": {"periodId": 656309292174, "startDate": "2025-07-03"}, "declarationStatus": {"period": {"id": 656309292174, "href": "https://services-sim.socialsecurity.be/REST/dimona/v2/periods/656309292174"}, "result": "A", "declarationId": 656309296531}
            },
            return_status=200,
        ):
            self.employee.action_check_dimona()

        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.state, 'A')

        # No displayed button, nothing to do
        self.assertFalse(self.employee.l10n_be_needs_dimona_in)
        self.assertFalse(self.employee.l10n_be_needs_dimona_update)
        self.assertFalse(self.employee.l10n_be_needs_dimona_out)
        self.assertFalse(self.employee.l10n_be_needs_dimona_cancel)
        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'done')

        # unset the certificate to avoid automatic declaration on write
        self.env.company.write({
            'onss_certificate_id': False,
        })

        departure_reason = self.env['hr.departure.reason'].create({
            'name': 'End of Contract',
        })
        # Without departure reason, a new contract end date is not a departure yet
        self.version.contract_date_end = date(2025, 9, 30)
        self.assertFalse(self.employee.l10n_be_needs_dimona_out)

        # Blue-collar worker: an open-ended period must be closed too
        self.version.l10n_be_worker_code_id = self.env.ref('l10n_be_hr_payroll.l10n_be_worker_code_00015')
        self.employee.departure_reason_id = departure_reason.id

        # Now, set contract end date
        self.version.contract_date_end = date(2025, 9, 24)

        self.env.company.write({
            'onss_certificate_id': certificate,
        })

        # send dimona button is displayed for dimona out
        self.assertFalse(self.employee.l10n_be_needs_dimona_in)
        self.assertFalse(self.employee.l10n_be_needs_dimona_update)
        self.assertTrue(self.employee.l10n_be_needs_dimona_out)
        self.assertFalse(self.employee.l10n_be_needs_dimona_cancel)
        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'out')

        with MockHTTPClient(return_headers={'Location': 'foo/bar/blork/656309314911'}, return_status=201):
            self.employee.action_send_dimona()

        # No displayed button, waiting for status
        self.assertFalse(self.employee.l10n_be_needs_dimona_in)
        self.assertFalse(self.employee.l10n_be_needs_dimona_update)
        self.assertTrue(self.employee.l10n_be_needs_dimona_out)
        self.assertFalse(self.employee.l10n_be_needs_dimona_cancel)
        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'progress')

        self.assertEqual(self.version.l10n_be_dimona_declaration_id.name, '2029409422')
        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.name, '656309314911')
        self.assertFalse(self.version.l10n_be_last_dimona_declaration_id.state)

        with MockHTTPClient(
            return_json={
                "href": "https://services-sim.socialsecurity.be/REST/dimona/v2/declarations/656309314911", "worker": {"ssin": "93051822361", "gender": "1", "birthDate": "1991-11-11", "givenName": "TEST", "familyName": "EMPLOYEE", "givenNames": "TEST EMPLOYEE", "nationality": 150}, "employer": {"employerId": 125482497, "enterpriseNumber": "477472701"}, "dimonaOut": {"endDate": "2025-09-24", "periodId": 656309292174}, "declarationStatus": {"period": {"id": 656309292174, "href": "https://services-sim.socialsecurity.be/REST/dimona/v2/periods/656309292174"}, "result": "A", "declarationId": 656309314911}
            },
            return_status=200,
        ):
            self.employee.action_check_dimona()

        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.state, 'A')

        # No displayed button, nothing to do
        self.assertFalse(self.employee.l10n_be_needs_dimona_in)
        self.assertFalse(self.employee.l10n_be_needs_dimona_update)
        self.assertFalse(self.employee.l10n_be_needs_dimona_out)
        self.assertFalse(self.employee.l10n_be_needs_dimona_cancel)
        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'done')

        # unset the certificate to avoid automatic declaration on write
        self.env.company.write({
            'onss_certificate_id': False,
        })

        # Last, archive employee because contract was cancelled
        self.employee.active = False

        self.env.company.write({
            'onss_certificate_id': certificate,
        })

        # send dimona button is displayed for dimona cancel
        self.assertFalse(self.employee.l10n_be_needs_dimona_in)
        self.assertFalse(self.employee.l10n_be_needs_dimona_update)
        self.assertFalse(self.employee.l10n_be_needs_dimona_out)
        self.assertTrue(self.employee.l10n_be_needs_dimona_cancel)
        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'cancel')

        with MockHTTPClient(return_headers={'Location': 'foo/bar/blork/656309322385'}, return_status=201):
            self.employee.action_send_dimona()

        # No displayed button, waiting for status
        self.assertFalse(self.employee.l10n_be_needs_dimona_in)
        self.assertFalse(self.employee.l10n_be_needs_dimona_update)
        self.assertFalse(self.employee.l10n_be_needs_dimona_out)
        self.assertTrue(self.employee.l10n_be_needs_dimona_cancel)
        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'progress')

        self.assertEqual(self.version.l10n_be_dimona_declaration_id.name, '2029409422')
        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.name, '656309322385')
        self.assertFalse(self.version.l10n_be_last_dimona_declaration_id.state)

        with MockHTTPClient(
            return_json={
                "worker": {"ssin": "93051822361", "gender": "1", "birthDate": "1991-11-11", "givenName": "TEST", "familyName": "EMPLOYEE", "givenNames": "TEST EMPLOYEE", "nationality": 150}, "employer": {"employerId": 125482497, "enterpriseNumber": "477472701"}, "dimonaCancel": {"periodId": 656309292174}, "declarationStatus": {"period": {"id": 656309292174, "href": "https://services-sim.socialsecurity.be/REST/dimona/v2/periods/656309292174"}, "result": "A", "declarationId": 656309322385}
            },
            return_status=200,
        ):
            self.employee.action_check_dimona()

        self.assertEqual(self.version.l10n_be_last_dimona_declaration_id.state, 'A')

        # No displayed button, nothing to do
        self.assertFalse(self.employee.l10n_be_needs_dimona_in)
        self.assertFalse(self.employee.l10n_be_needs_dimona_update)
        self.assertFalse(self.employee.l10n_be_needs_dimona_out)
        self.assertFalse(self.employee.l10n_be_needs_dimona_cancel)
        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'done')

    def test_dimona_periods_alignment_mismatch_warning(self):
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        self.version = self.version.with_env(self.env)
        certificate = self.env["certificate.certificate"].create({"name": "onss cert"})
        self.version.date_version = date(2025, 9, 26)
        self.version.contract_date_start = date(2025, 9, 26)
        self.version.l10n_be_dimona_category = "oth"

        self.version.company_id.write({"onss_certificate_id": certificate})

        period_id = "2029409422"
        declaration_id = 2029409422
        with MockHTTPClient(
            return_json={
                "items": [
                    {
                        "worker": {
                            "ssin": self.employee.niss,
                            "gender": "1",
                            "birthDate": "1991-11-11",
                            "givenName": "TEST",
                            "familyName": "EMPLOYEE",
                            "givenNames": "TEST EMPLOYEE",
                            "nationality": 150,
                        },
                        "startDate": "2025-09-26",
                        "endDate": "2025-10-25",
                        "periodId": period_id,
                        "dimonaIn": {
                            "features": {
                                "workerType": "STU",
                                "jointCommissionNumber": "100",
                            },
                            "startDate": "2025-09-26",
                        },
                        "employer": {
                            "employerId": 12548245,
                            "enterpriseNumber": "477472701",
                        },
                        "declarationStatus": {
                            "period": {
                                "id": declaration_id,
                            },
                            "result": "A",
                            "declarationId": declaration_id,
                        },
                    }
                ],
                "next": False,
            },
            return_status=200,
        ):
            self.version.action_fetch_all_dimona()

        relation = self.env["l10n.be.dimona.relation"].search([("name", "=", self.employee.niss)])

        self.assertEqual(relation.employee_id, self.employee)
        issues = self.version.issues or {}
        self.assertIn("Dimona periods and contract versions are not aligned", " ".join(issue["message"] for issue in issues.values()))

    def test_dimona_periods_category_mismatch_warning(self):
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        self.version = self.version.with_env(self.env)
        certificate = self.env["certificate.certificate"].create({"name": "onss cert"})
        self.version.date_version = date(2025, 9, 26)
        self.version.contract_date_start = date(2025, 9, 26)
        self.version.contract_date_end = date(2025, 10, 25)
        self.version.l10n_be_dimona_category = "oth"
        self.version.l10n_be_joint_committee_id = self.env.ref("l10n_be_hr_payroll.l10n_be_joint_committee_302").id

        self.version.company_id.write({"onss_certificate_id": certificate})

        period_id = "2029409422"
        declaration_id = 2029409422
        with MockHTTPClient(
            return_json={
                "items": [
                    {
                        "worker": {
                            "ssin": self.employee.niss,
                            "gender": "1",
                            "birthDate": "1991-11-11",
                            "givenName": "TEST",
                            "familyName": "EMPLOYEE",
                            "givenNames": "TEST EMPLOYEE",
                            "nationality": 150,
                        },
                        "startDate": "2025-09-26",
                        "endDate": "2025-10-25",
                        "periodId": period_id,
                        "dimonaIn": {
                            "features": {
                                "workerType": "STU",
                                "jointCommissionNumber": "100",
                            },
                            "startDate": "2025-09-26",
                        },
                        "employer": {
                            "employerId": 12548245,
                            "enterpriseNumber": "477472701",
                        },
                        "declarationStatus": {
                            "period": {
                                "id": declaration_id,
                            },
                            "result": "A",
                            "declarationId": declaration_id,
                        },
                    }
                ],
                "next": False,
            },
            return_status=200,
        ):
            self.version.action_fetch_all_dimona()

        relation = self.env["l10n.be.dimona.relation"].search([("name", "=", self.employee.niss)])

        self.assertEqual(relation.employee_id, self.employee)
        issues = self.version.issues or {}
        self.assertIn("The Dimona category does not match the contract version one", " ".join(issue["message"] for issue in issues.values()))
        self.assertIn("The Dimona joint committee does not match the contract version one", " ".join(issue["message"] for issue in issues.values()))

    def test_dimona_periods_alignment_with_amendment(self):
        """ The versions of a same contract are compared as a single contract to the Dimona periods. """
        self.env = self.env(context=dict(self.env.context, hr_payroll_force_compute_issue=True))
        self.version = self.version.with_env(self.env)
        certificate = self.env["certificate.certificate"].create({"name": "onss cert"})
        self.version.date_version = date(2025, 9, 26)
        self.version.contract_date_start = date(2025, 9, 26)
        self.version.contract_date_end = date(2025, 10, 25)
        self.version.l10n_be_dimona_category = "oth"
        self.version.l10n_be_joint_committee_id = self.env.ref("l10n_be_hr_payroll.l10n_be_joint_committee_200").id
        amendment = self.employee.create_version({
            "date_version": date(2025, 10, 10),
            "wage": 3000,
        })
        self.assertEqual(amendment.contract_date_end, date(2025, 10, 25))

        self.version.company_id.write({"onss_certificate_id": certificate})

        with MockHTTPClient(
            return_json={
                "items": [
                    {
                        "worker": {
                            "ssin": self.employee.niss,
                            "gender": "1",
                            "birthDate": "1991-11-11",
                            "givenName": "TEST",
                            "familyName": "EMPLOYEE",
                            "givenNames": "TEST EMPLOYEE",
                            "nationality": 150,
                        },
                        "startDate": "2025-09-26",
                        "endDate": "2025-10-25",
                        "periodId": "2029409422",
                        "dimonaIn": {
                            "features": {
                                "workerType": "OTH",
                                # CP 200 is not one of the committees declared as such
                                "jointCommissionNumber": "XXX",
                            },
                            "startDate": "2025-09-26",
                        },
                        "employer": {
                            "employerId": 12548245,
                            "enterpriseNumber": "477472701",
                        },
                        "declarationStatus": {
                            "period": {
                                "id": 2029409422,
                            },
                            "result": "A",
                            "declarationId": 2029409422,
                        },
                    }
                ],
                "next": False,
            },
            return_status=200,
        ):
            self.version.action_fetch_all_dimona()

        self.assertFalse(self.employee._get_dimona_periods_version_mismatch_warning())

    def test_missing_dimona_in_warning(self):
        warning = self.env.ref('l10n_be_hr_payroll.hr_payroll_warning_missing_dimona_in')

        def get_dashboard_employees():
            return self.env['hr.employee'].union(
                warning_data['records'] for warning_data in warning._get_applicable_payroll_warnings(self.env.company)
            )

        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'in')
        self.assertIn(self.employee, get_dashboard_employees())

        # Submit Dimona
        action = self.version.action_send_dimona()
        self.assertEqual(action['res_model'], 'l10n.be.dimona.manual.wizard')
        wizard = self.env[action['res_model']].with_context(action['context']).create({})
        wizard.submit_dimona()

        self.assertEqual(self.employee.l10n_be_dimona_next_action, 'done')

        # No warning in dashboard
        self.assertNotIn(self.employee, get_dashboard_employees())

    def test_dimona_period_not_covered_by_payslip_warning(self):
        warning = self.env.ref('l10n_be_hr_payroll.hr_payroll_warning_dimona_period_not_covered_by_payslip')

        def get_dashboard_employees():
            return self.env['hr.employee'].union(
                warning_data['records'] for warning_data in warning._get_applicable_payroll_warnings(self.env.company)
            )

        date_start = self.version.contract_date_start
        colleague = self.env['hr.employee'].create({
            'name': 'Colleague',
            'wage': 2000,
            'date_version': date_start,
            'contract_date_start': date_start,
        })
        payrun = self.env['hr.payslip.run'].create({
            'name': 'Payrun',
            'date_start': date_start,
            'date_end': date_start + relativedelta(day=31),
            'structure_id': self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id,
        })
        payrun.version_ids -= self.version
        self.assertEqual(payrun.version_ids, colleague.version_id)

        # A declaration waiting for the ONSS answer and a cancellation carry no date
        self.env['l10n.be.dimona.declaration'].create([{
            'company_id': self.env.company.id,
            'employee_id': self.employee.id,
            'request_content': {'dimonaIn': {'startDate': date_start.isoformat()}},
        }, {
            'name': '2029409423',
            'company_id': self.env.company.id,
            'employee_id': self.employee.id,
            'content': {'dimonaCancel': {'periodId': 2029409422}, 'declarationStatus': {'result': 'A'}},
        }])
        self.assertNotIn(self.employee, get_dashboard_employees())

        self.env['l10n.be.dimona.declaration'].create({
            'name': '2029409422',
            'company_id': self.env.company.id,
            'employee_id': self.employee.id,
            'content': {'dimonaIn': {'startDate': date_start.isoformat()}, 'declarationStatus': {'result': 'A'}},
        })
        self.assertIn(self.employee, get_dashboard_employees())

    def test_dimona_needs_in_survives_stale_explicit_create_vals(self):
        # l10n_be_needs_dimona_in must stay purely server-computed.
        # The web client treats it as editable because of readonly=False, even though no view renders it as a widget, only button invisible= domains reference it.
        # An early onchange can compute it False before contract_date_start is filled in, and autosave then submits that stale value explicitly.
        # The ORM must not let an explicit vals value suppress the recompute here.
        employee = self.env['hr.employee'].create({
            'name': 'Test Employee Stale Vals',
            'niss': '93051822460',
            'private_country_id': self.belgium.id,
            'wage': 2000,
            'date_version': date.today() + relativedelta(day=1, months=1),
            'contract_date_start': date.today() + relativedelta(day=1, months=1),
            'sex': 'male',
            'l10n_be_needs_dimona_in': False,
        })

        self.assertTrue(employee.l10n_be_needs_dimona_in)
        self.assertEqual(employee.l10n_be_dimona_next_action, 'in')

    def _create_dimona_periods(self, period_dates):
        relation = self.env['l10n.be.dimona.relation'].create({
            'name': self.employee.niss,
            'company_id': self.env.company.id,
            'content': {'startDate': period_dates[0][0].isoformat(), 'worker': {'ssin': self.employee.niss}},
        })
        self.assertEqual(relation.employee_id, self.employee)
        periods = self.env['l10n.be.dimona.period'].create([{
            'name': str(9000000 + index),
            'company_id': self.env.company.id,
            'content': {
                'startDate': date_start.isoformat(),
                **({'endDate': date_end.isoformat()} if date_end else {}),
                'worker': {'ssin': self.employee.niss},
            },
        } for index, (date_start, date_end) in enumerate(period_dates)])
        self.assertEqual(relation.period_ids, periods)
        self.assertEqual(self.employee.l10n_be_dimona_relation_id, relation)
        return periods

    def _set_contracts(self, contract_dates):
        (first_start, first_end), *other_contracts = contract_dates
        self.version.write({
            'date_version': first_start,
            'contract_date_start': first_start,
            'contract_date_end': first_end,
        })
        for date_start, date_end in other_contracts:
            self.employee.create_version({
                'date_version': date_start,
                'contract_date_start': date_start,
                'contract_date_end': date_end,
            })

    def test_dimona_periods_mismatch_history_not_encoded(self):
        """ The company fetched the whole Dimona history but only encoded the current contract. """
        self.env.company.first_payrun_date = False
        self._set_contracts([(date(2024, 1, 1), False)])
        self._create_dimona_periods([(date(2020, 1, 1), date(2022, 12, 31)), (date(2024, 1, 1), False)])
        self.assertEqual(
            self.employee._get_dimona_periods_version_mismatch_warning(),
            "Dimona periods and contract versions are not aligned.",
            "Without first payrun date, the whole history is compared")

        self.env.company.first_payrun_date = date(2025, 1, 1)
        self.assertFalse(self.employee._get_dimona_periods_version_mismatch_warning())

    def test_dimona_periods_mismatch_history_encoded(self):
        """ The company encoded the past contracts too: they are ignored like the periods. """
        self.env.company.first_payrun_date = date(2025, 1, 1)
        self._set_contracts([(date(2020, 1, 1), date(2022, 12, 31)), (date(2024, 1, 1), False)])
        self._create_dimona_periods([(date(2020, 1, 1), date(2022, 12, 31)), (date(2024, 1, 1), False)])
        self.assertFalse(self.employee._get_dimona_periods_version_mismatch_warning())

        # A start date difference before the first payrun date is not compared anymore
        current_contract = self.employee.version_ids.filtered(lambda v: v.contract_date_start == date(2024, 1, 1))
        current_contract.contract_date_start = date(2024, 2, 1)
        self.assertFalse(self.employee._get_dimona_periods_version_mismatch_warning())

        # A real mismatch after the first payrun date is still reported
        current_contract.contract_date_end = date(2025, 6, 30)
        self.assertEqual(
            self.employee._get_dimona_periods_version_mismatch_warning(),
            "Dimona periods and contract versions are not aligned.")

    def test_dimona_periods_mismatch_no_first_payrun_date(self):
        self.env.company.first_payrun_date = False
        self._set_contracts([(date(2020, 1, 1), date(2022, 12, 31)), (date(2024, 1, 1), False)])
        self._create_dimona_periods([(date(2020, 1, 1), date(2022, 12, 31)), (date(2024, 1, 1), False)])
        self.assertFalse(self.employee._get_dimona_periods_version_mismatch_warning())

        self.employee.version_ids.filtered(lambda v: v.contract_date_start == date(2020, 1, 1)).contract_date_end = date(2022, 11, 30)
        self.assertEqual(
            self.employee._get_dimona_periods_version_mismatch_warning(),
            "Dimona periods and contract versions are not aligned.")

    def test_dimona_periods_mismatch_straddling_first_payrun_date(self):
        """ The Dimona period started long before the first payrun date while the contract
            was encoded from the first payrun date: compared from the first payrun date only. """
        self.env.company.first_payrun_date = date(2025, 1, 1)
        self._set_contracts([(date(2025, 1, 1), False)])
        self._create_dimona_periods([(date(2020, 1, 1), False)])
        self.assertFalse(self.employee._get_dimona_periods_version_mismatch_warning())

        # Same with the contract encoded with the real hiring date
        self.version.write({'date_version': date(2020, 1, 1), 'contract_date_start': date(2020, 1, 1)})
        self.assertFalse(self.employee._get_dimona_periods_version_mismatch_warning())

        # A contract starting after the first payrun date does not cover the period
        self.version.write({'date_version': date(2025, 2, 1), 'contract_date_start': date(2025, 2, 1)})
        self.assertEqual(
            self.employee._get_dimona_periods_version_mismatch_warning(),
            "Dimona periods and contract versions are not aligned.")

        self.env.company.first_payrun_date = False
        self.version.write({'date_version': date(2025, 1, 1), 'contract_date_start': date(2025, 1, 1)})
        self.assertEqual(
            self.employee._get_dimona_periods_version_mismatch_warning(),
            "Dimona periods and contract versions are not aligned.")

    def test_dimona_joint_committee_declaration(self):
        """ The joint committee is always declared in a Dimona IN: the committee number (3 digits)
            for the committees listed by the ONSS, "XXX" for the other ones. """
        cases = [
            ('l10n_be_joint_committee_302', 'oth', 'XXX'),
            ('l10n_be_joint_committee_302', 'stu', 'XXX'),
            ('l10n_be_joint_committee_302', 'ext', '302'),
            ('l10n_be_joint_committee_124', 'oth', '124'),
            ('l10n_be_joint_committee_140_03', 'oth', '140'),
            ('l10n_be_joint_committee_145_04', 'ext', '145'),
            ('l10n_be_joint_committee_149_01', 'oth', '149'),
            ('l10n_be_joint_committee_322', 'oth', '322'),
            ('l10n_be_joint_committee_322_01', 'oth', 'XXX'),
            ('l10n_be_joint_committee_200', 'oth', 'XXX'),
            ('l10n_be_joint_committee_200', 'stu', 'XXX'),
            ('l10n_be_joint_committee_118_03', 'oth', 'XXX'),
            (False, 'oth', 'XXX'),
        ]
        for committee_xmlid, category, expected in cases:
            with self.subTest(committee=committee_xmlid, category=category):
                self.version.write({
                    'l10n_be_joint_committee_id': committee_xmlid and self.env.ref(f'l10n_be_hr_payroll.{committee_xmlid}').id,
                    'l10n_be_dimona_category': category,
                })
                features = self.version._l10n_be_dimona_payload('in')['dimonaIn']['features']
                self.assertEqual(features, {'workerType': category, 'jointCommissionNumber': expected})

        # The submitted declaration carries it
        self.version.write({
            'l10n_be_joint_committee_id': self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
            'l10n_be_dimona_category': 'oth',
        })
        wizard = self.env['l10n.be.dimona.wizard'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'declaration_type': 'in',
        })
        with MockHTTPClient(return_headers={'Location': 'foo/bar/blork/2029409498'}, return_status=201):
            wizard.submit_declaration()
        declaration = self.version.l10n_be_dimona_declaration_id
        self.assertEqual(declaration.request_content['dimonaIn']['features']['jointCommissionNumber'], 'XXX')

    def test_dimona_joint_committee_mismatch_warning(self):
        """ The joint committee answered by the ONSS is compared with the declared value. """
        self.env.company.first_payrun_date = False
        self._set_contracts([(date(2024, 1, 1), False)])
        self.version.l10n_be_dimona_category = 'oth'
        period = self._create_dimona_periods([(date(2024, 1, 1), False)])

        def set_onss_committee(committee):
            period.declaration_ids.unlink()
            self.env['l10n.be.dimona.declaration'].create({
                'name': '2029409422',
                'company_id': self.env.company.id,
                'employee_id': self.employee.id,
                'content': {
                    'dimonaIn': {
                        'startDate': '2024-01-01',
                        'features': {'workerType': 'OTH', 'jointCommissionNumber': committee},
                    },
                    'declarationStatus': {'result': 'A', 'period': {'id': int(period.name)}},
                },
            })
            self.assertEqual(period.declaration_ids.declaration_type, 'dimona_in')

        for committee_xmlid, onss_committee, mismatch in [
            ('l10n_be_joint_committee_200', 'XXX', False),
            # declared before: the committee code was sent as is
            ('l10n_be_joint_committee_200', '200', False),
            ('l10n_be_joint_committee_200', '302', True),
            ('l10n_be_joint_committee_302', '302', False),
            ('l10n_be_joint_committee_302', 'XXX', False),
            ('l10n_be_joint_committee_302', '100', True),
            ('l10n_be_joint_committee_140_03', '140', False),
            ('l10n_be_joint_committee_140_03', '140.03', False),
        ]:
            with self.subTest(committee=committee_xmlid, onss_committee=onss_committee):
                self.version.l10n_be_joint_committee_id = self.env.ref(f'l10n_be_hr_payroll.{committee_xmlid}')
                set_onss_committee(onss_committee)
                self.assertEqual(
                    "The Dimona joint committee does not match the contract version one." in self.employee._get_dimona_periods_version_mismatch_warning(),
                    mismatch)
