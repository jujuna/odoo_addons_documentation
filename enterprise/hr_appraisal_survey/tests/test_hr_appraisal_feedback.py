# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from dateutil.relativedelta import relativedelta
from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests.common import tagged, TransactionCase

@tagged('-at_install', 'post_install')
class TestHrAppraisalFeedback(TransactionCase):

    def setUp(self):
        super(TestHrAppraisalFeedback, self).setUp()

        group = self.env.ref('hr_appraisal.group_hr_appraisal_user').id
        self.user = self.env['res.users'].create({
            'name': 'Test',
            'login': 'test',
            'group_ids': [(6, 0, [group])],
            'notification_type': 'email',
        })

        self.user_work_contact = self.env['res.partner'].create({
            'name': 'Me Myself and I',
            'email': 'mymyselfandi@example.com',
        })

        self.user_employee = self.env['hr.employee'].create({
            'name': 'Me Myself and I',
            'user_id': self.user.id,
            'work_contact_id': self.user_work_contact.id
        })
        self.test_employee = self.env['hr.employee'].create({
            'name': 'John Smith'
        })
        self.manager = self.env['hr.employee'].create({
            'name': 'Mr. Manager'
        })

        self.appraisal = self.env['hr.appraisal'].create({
            'employee_id': self.test_employee.id,
            'manager_ids': [self.manager.id],
            'state': '2_pending',
        })

        self.appraisal_survey = self.env['survey.survey'].create({
            'title': 'appraisal feedback',
            'questions_layout': 'one_page',
            'questions_selection': 'all',
            'access_mode': 'public',
            'survey_type': 'appraisal',
            'question_and_page_ids': [Command.create({
                'title': 'How was your collaboration?',
                'question_type': 'text_box',
            })],
        })

    def test_appraisal_feedback_deadline(self):
        today = fields.Date.context_today(self.appraisal)
        feedback = self.env['appraisal.ask.feedback'].create({
            'appraisal_id': self.appraisal.id,
            'partner_ids': [self.user_employee.work_contact_id.id],
            'deadline': today,
            'survey_template_id': self.appraisal_survey.id,
        })
        feedback.action_send()
        feedback['deadline'] = today + relativedelta(months=1)
        feedback.action_send()

        survey_input = self.env['survey.user_input'].search([('appraisal_id', '=', self.appraisal.id)])
        self.assertEqual(feedback['deadline'], survey_input['deadline'].date())

        # by the way, check that completed_survey_count is computed correctly
        survey_input._mark_done()
        self.assertEqual(self.appraisal.completed_survey_count, 1)

    def test_appraisal_feedback_empty_survey(self):
        self.appraisal_survey.question_and_page_ids.unlink()
        feedback = self.env['appraisal.ask.feedback'].create({
            'appraisal_id': self.appraisal.id,
            'partner_ids': [self.user_employee.work_contact_id.id],
            'deadline': fields.Date.context_today(self.appraisal),
            'survey_template_id': self.appraisal_survey.id,
        })
        with self.assertRaises(UserError):
            feedback.action_send()
        self.assertFalse(self.env['survey.user_input'].search([('appraisal_id', '=', self.appraisal.id)]))
