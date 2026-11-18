# Part of Odoo. See LICENSE file for full copyright and licensing details

import json

from odoo import Command
from odoo.addons.mail.tests.common import MailCase
from odoo.tests.common import HttpCase

from .common import TestPlanningFieldServiceSaleTimesheetCommon


class TestPlanningFieldServiceSaleTimesheetRating(TestPlanningFieldServiceSaleTimesheetCommon, HttpCase, MailCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Enable rating feature
        cls.env['res.config.settings'].create({'group_field_service_allow_customer_ratings': True}).execute()

        cls.partner_user = cls.env['res.users'].create({
            'partner_id': cls.partner.id,
            'login': 'partner',
            'group_ids': [Command.set(cls.env.ref('base.group_portal').ids)],
        })

    def test_rating_email_sent_once_when_timesheets_generated_on_complete(self):
        """ The timesheets generated when completing the intervention make the report available,
            so the rating request must wait for the customer signature instead of being sent twice.
        """
        self.intervention.state = '3_in_progress'
        self.set_field_service_project(self.field_service_project, self.intervention)
        self.assertFalse(self.intervention.sudo().intervention_timesheet_ids, 'The intervention should not have any timesheet yet')

        with self.mock_mail_gateway():
            self.intervention.with_user(self.george_user).action_complete()

        self.assertTrue(self.intervention.sudo().intervention_timesheet_ids, 'Completing the intervention should generate its timesheets')
        self.assertTrue(self.intervention._can_sign_report(), 'The intervention report should be available for signature')
        mail = self.env['mail.mail'].search([('recipient_ids', 'in', self.partner.id)])
        self.assertFalse(mail, 'No rating request email should be sent while the report awaits the customer signature')

        # Sign the report
        self.authenticate("partner", "partner")
        self.url_open(
            url=f'/my/field-service/{self.intervention.id}/sign',
            data=json.dumps({
                "params": {
                    'name': "Customer Name",
                    'access_token': self.intervention.access_token,
                    'signature': "R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                },
            }),
            headers={"Content-Type": "application/json"},
        )

        mails = self.env['mail.mail'].search([('recipient_ids', 'in', self.partner.id)])
        self.assertEqual(len(mails), 2, 'The customer request and intervention report emails should have been sent to the partner')
        self.assertEqual(len(mails.filtered(lambda m: "Service Rating Request" in m.subject)), 1, 'Exactly one rating request email should be sent, upon signature')
        self.assertEqual(len(mails.filtered(lambda m: "Field Service Report" in m.subject)), 1, 'The intervention report email should be sent upon signature')
