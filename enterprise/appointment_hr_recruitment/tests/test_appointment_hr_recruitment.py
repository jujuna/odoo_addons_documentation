# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json

from freezegun import freeze_time
from datetime import datetime
from unittest.mock import patch

from odoo.tests import HttpCase, tagged, users


@tagged('post_install', '-at_install')
class AppointmentHrRecruitmentTest(HttpCase):

    @users('admin')
    def test_tour_applicant_propagation(self):
        """ Test that the applicant is correctly propagated to the appointment invitation created """
        with freeze_time(datetime(year=2025, month=2, day=12, hour=17)):
            self.env.user.tz = "Europe/Brussels"
            dep_rd = self.env['hr.department'].create({
                'name': 'Research & Development',
            })
            job_developer = self.env['hr.job'].create({
                'name': 'Test Job',
                'department_id': dep_rd.id,
                'no_of_recruitment': 5,
            })
            applicant = self.env['hr.applicant'].sudo().create({
                'partner_name': 'Test Applicant',
                'job_id': job_developer.id,
            })
            self.start_tour('/odoo', 'appointment_hr_recruitment_tour', login='admin')
            calendar_event = self.env['calendar.event'].search([('applicant_id', '=', applicant.id)])
            self.assertIn('Ana Tourelle', calendar_event.name)

    @users('admin')
    def test_interview_invite_url_from_job(self):
        """ Test interview invite url is generated from the related job base url """
        job = self.env['hr.job'].create({
            'name': 'Test Job',
        })
        applicant = self.env['hr.applicant'].create({
            'partner_name': 'Test Applicant',
            'job_id': job.id,
        })
        # Needs to be parsed properly by urlsplit
        expected_host = 'http://custom_domain'

        def get_mock_url(records, *args, **kwargs):
            return expected_host

        self.authenticate(self.env.user.login, self.env.user.login)
        with patch.object(self.env.registry['hr.job'], 'get_base_url', get_mock_url):
            res = self.url_open(
                '/appointment/appointment_type/search_create_anytime',
                data=json.dumps({
                    'params': {
                        'applicant_code': applicant.interview_invite_code,
                    },
                }),
                headers={'Content-Type': 'application/json'},
            )
            self.assertEqual(res.status_code, 200, 'Response should be OK')
            res_data = res.json()
            self.assertIn(expected_host, res_data['result']['invite_url'])
