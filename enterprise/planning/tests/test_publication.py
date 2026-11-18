# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details
from datetime import datetime

from .common import TestCommonPlanning
from odoo import Command
from odoo.tests import tagged

from odoo.addons.mail.tests.common import MailCase


@tagged('at_install', '-post_install')  # LEGACY at_install
class TestPlanningPublishing(TestCommonPlanning, MailCase):

    @classmethod
    def setUpClass(cls):
        super(TestPlanningPublishing, cls).setUpClass()

        cls.setUpEmployees()

        # employee without work email
        cls.employee_dirk_no_mail = cls.env['hr.employee'].create({
            'user_id': False,
            'name': 'Dirk',
            'work_email': False,
            'tz': 'UTC'
        })
        cls.resource_dirk = cls.employee_dirk_no_mail.resource_id

        values = {
            'resource_ids': cls.resource_joseph.ids,
            'allocated_hours': 8,
            'start_datetime': datetime(2019, 6, 6, 8, 0, 0),
            'end_datetime': datetime(2019, 6, 6, 17, 0, 0)
        }
        cls.shift = cls.env['planning.slot'].create(values)

    def test_planning_publication(self):
        self.shift.write({
            'allocated_hours': 10
        })

        Mails = self.env['mail.mail'].sudo()
        before_mails = Mails.search([])

        with self.mock_mail_gateway():
            self.shift.action_send()
        self.assertEqual(self.shift.state, '2_published', 'planning is published when we call its action_send')

        shift_mails = set(Mails.search([])) ^ set(before_mails)
        self.assertEqual(len(shift_mails), 1, 'only one mail is created when publishing planning')

    def test_sending_planning_do_not_create_mail_if_employee_has_no_email(self):
        self.shift.write({'resource_ids': self.resource_dirk.ids})

        self.assertFalse(self.employee_dirk_no_mail.work_email)  # if no work_email

        Mails = self.env['mail.mail'].sudo()
        before_mails = Mails.search([])

        self.shift.action_send()
        shift_mails = set(Mails.search([])) ^ set(before_mails)
        self.assertEqual(len(shift_mails), 0, 'no mail should be sent when the employee has no work email')

    def test_send_shift_without_hr_rights(self):
        self.assertFalse(self.planning_manager_user.has_group("hr.group_hr_user"))
        with self.mock_mail_gateway():
            self.shift.with_user(self.planning_manager_user).action_send()
        self.assertEqual(self._new_mails.mapped("email_to"), ["joseph@a.be"])

    def test_reassign_published_shift_without_hr_rights(self):
        self.shift.resource_ids |= self.resource_bert
        self.shift.action_send()
        self.assertFalse(self.planning_manager_user.has_group('hr.group_hr_user'))
        with self.mock_mail_gateway():
            self.shift.with_user(self.planning_manager_user).write({
                'resource_ids': [Command.set((self.resource_bert | self.resource_janice).ids)],
            })
        self.assertEqual(self._new_mails.mapped('email_to'), ['joseph@a.be'])
        self.assertIn('joseph', self._new_mails.body_html)
        self.assertIn('janice', self._new_mails.body_html)

    def test_reassign_published_shift_mail_subject(self):
        self.shift.action_send()
        with self.mock_mail_gateway():
            self.shift.resource_ids = self.resource_bert
        self.assertEqual(len(self._new_mails), 1)
        self.assertEqual(
            self._new_mails.subject,
            "Your shift on 06/06/2019 08:00 AM was re-assigned to bert",
        )
