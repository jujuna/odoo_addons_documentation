# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import AccessError
from odoo.tests.common import tagged, TransactionCase
from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.tests import users

from markupsafe import Markup


@tagged('at_install', '-post_install')  # LEGACY at_install
class TestAppraisalPublicAccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = cls.env['res.company'].create({'name': 'mami rock'})
        cls.user_without_hr_right = mail_new_test_user(
            cls.env,
            name='user_without_hr_right',
            login='user_without_hr_right',
            email='user_without_hr_right@example.com',
            groups='base.group_user',
            notification_type='email',
            company_id=cls.company.id,
        )

        cls.manager = cls.env['hr.employee'].create({
            'name': 'Johnny',
            'user_id': cls.user_without_hr_right.id,
            'company_id': cls.company.id,
        })

        cls.employee_a, cls.employee_b = cls.env['hr.employee'].create([{
            'name': 'David',
            'parent_id': cls.manager.id,
            'company_id': cls.company.id,
            'wage': 1,
            'contract_date_start': '2017-12-05',
            'next_appraisal_date': '2057-12-05',
        }, {
            'name': 'Laura',
            'company_id': cls.company.id,
            'wage': 1,
            'contract_date_start': '2018-12-05',
            'next_appraisal_date': '2058-12-05',
        }])
        cls.employee_c = cls.env['hr.employee'].create({
            'name': 'Jade',
            'parent_id': cls.employee_a.id,
            'company_id': cls.company.id,
            'wage': 1,
            'contract_date_start': '2019-12-05',
            'next_appraisal_date': '2059-12-05',
        })
        cls.assessment_note = cls.env["hr.appraisal.note"].create({"name": "Meets expectations"})

    def test_manager(self):
        with self.with_user(self.user_without_hr_right.login):
            david, laura, jade = self.env['hr.employee.public'].browse((self.employee_a | self.employee_b | self.employee_c).ids)

            self.assertTrue(david.is_manager)
            self.assertFalse(laura.is_manager)
            self.assertTrue(jade.is_manager)

    def test_manager_access_read(self):
        with self.with_user(self.user_without_hr_right.login):
            david, laura, jade = self.env['hr.employee.public'].browse((self.employee_a | self.employee_b | self.employee_c).ids)

            # Should be able to read direct reports and indirect reports birthday_public_display_string
            self.assertEqual(str(david.next_appraisal_date), '2057-12-05')
            self.assertEqual(str(jade.next_appraisal_date), '2059-12-05')
            # Cannot read values of "manager only field" on an employee the user is not manager of
            self.assertFalse(laura.next_appraisal_date)

    def test_manager_access_search(self):
        with self.with_user(self.user_without_hr_right.login):
            employees = self.env['hr.employee.public'].search([('next_appraisal_date', '>=', '2057-12-05')])

            # Should not find Laura as the user is not her manager
            self.assertEqual(len(employees), 2)
            self.assertTrue('Laura' not in employees.mapped('name'))

    @users('user_without_hr_right')
    def test_appraisal_flow_without_hr_right(self):
        appraisal = self.env['hr.appraisal'].create({'employee_id': self.employee_a.id, 'manager_ids': self.env.user.employee_ids.ids})
        # A manager without hr right should be able to confirm an appraisal of one of his subordinate
        appraisal.action_confirm()
        appraisal.assessment_note = self.assessment_note
        # A manager without hr right should be able to mark as done an appraisal of one of his subordinate
        appraisal.action_done()

    def test_prevent_officer_access_to_own_appraisal_feedback(self):
        """
        Checks that an officer who has high access rights doesn't have access to the manager feedbacj of his own
        appraisal before it's published.
        """
        user_manager = mail_new_test_user(
            self.env,
            name='user_manager',
            login='user_manager',
            email='user_manager@example.com',
            groups='base.group_user,hr_appraisal.group_hr_appraisal_manager,base.group_allow_export',
            notification_type='email',
            company_id=self.company.id,
        )
        manager = self.env['hr.employee'].create({
            'name': 'Silver hand',
            'user_id': user_manager.id,
            'company_id': self.company.id,
        })
        appraisal = self.env['hr.appraisal'].create({
            'employee_id': manager.id,
            'manager_ids': [self.employee_a.id],
            'manager_feedback': Markup("<span>This is a manager feedback!!</span>")
        })
        self.env = self.env(user=user_manager)
        with self.assertRaises(AccessError):
            appraisal.with_user(user_manager).export_data(['id', 'manager_feedback'])

    def test_officer_own_appraisal_feedback_among_others(self):
        """
        An officer sees the manager feedback of the other appraisals, but not the one of their own appraisal before it
        is published, also when read or exported together: the feedback is only accessible through
        accessible_manager_feedback.
        """
        user_officer = mail_new_test_user(
            self.env,
            name='user_officer',
            login='user_officer',
            email='user_officer@example.com',
            groups='base.group_user,hr_appraisal.group_hr_appraisal_manager,base.group_allow_export',
            notification_type='email',
            company_id=self.company.id,
        )
        officer = self.env['hr.employee'].create({
            'name': 'Silver hand',
            'user_id': user_officer.id,
            'company_id': self.company.id,
        })
        own_appraisal, other_appraisal = self.env['hr.appraisal'].create([{
            'employee_id': officer.id,
            'manager_ids': [self.employee_a.id],
            'state': '2_pending',
            'manager_feedback': Markup("<span>Own feedback</span>"),
        }, {
            'employee_id': self.employee_b.id,
            'manager_ids': [self.employee_a.id],
            'state': '2_pending',
            'manager_feedback': Markup("<span>Other feedback</span>"),
        }])
        appraisals = (other_appraisal | own_appraisal).with_user(user_officer)

        # several appraisals are fetched at once
        self.env.invalidate_all()
        self.assertEqual(appraisals.mapped('state'), ['2_pending', '2_pending'])

        self.assertEqual(appraisals.mapped('accessible_manager_feedback'), [
            Markup("<span>Other feedback</span>"),
            Markup("<p>Unpublished</p>"),
        ])
        self.assertEqual(appraisals.export_data(['accessible_manager_feedback'])['datas'], [
            [Markup("<span>Other feedback</span>")],
            [Markup("<p>Unpublished</p>")],
        ])

        # the raw feedback is not accessible, whatever the appraisal
        with self.assertRaises(AccessError):
            appraisals.read(['manager_feedback'])
        with self.assertRaises(AccessError):
            other_appraisal.with_user(user_officer).export_data(['manager_feedback'])
        with self.assertRaises(AccessError):
            own_appraisal.with_user(user_officer).accessible_manager_feedback = Markup("<span>Changed</span>")
