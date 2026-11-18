import smtplib
from unittest.mock import patch

from odoo.addons.base.tests.common import MockSmtplibCase
from odoo.addons.employee_registry_rs.models.hr_employee import WEEKLY_DIGEST_PARAM
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestWeeklyDigest(TransactionCase, MockSmtplibCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a, cls.company_b = cls.env['res.company'].create([{'name': 'Digest Company A'}, {'name': 'Digest Company B'}])
        cls.user_a, cls.user_b = cls.env['res.users'].create([{
            'name': f'Digest User {company.name[-1]}',
            'login': f'digest_user_{company.name[-1].lower()}',
            'email': f'digest_{company.name[-1].lower()}@example.com',
            'company_id': company.id,
            'company_ids': [company.id],
        } for company in (cls.company_a, cls.company_b)])

    def _send_digest(self, user, company):
        self.env['hr.employee'].with_user(user).sudo().with_company(company)._cron_maybe_send_weekly_digest(1, 0, 1)

    def _marker(self, company):
        return self.env['ir.config_parameter'].sudo().get_str(f'{WEEKLY_DIGEST_PARAM}.{company.id}')

    def test_each_company_gets_its_own_report_and_marker(self):
        with self.mock_smtplib_connection():
            self._send_digest(self.user_a, self.company_a)
            self._send_digest(self.user_b, self.company_b)
        self.assertEqual([email['msg_to'] for email in self.emails], [self.user_a.email, self.user_b.email])
        self.assertTrue(self._marker(self.company_a))
        self.assertTrue(self._marker(self.company_b))

    def test_second_call_within_seven_days_sends_nothing(self):
        with self.mock_smtplib_connection():
            self._send_digest(self.user_a, self.company_a)
            self._send_digest(self.user_a, self.company_a)
        self.assertEqual(len(self.emails), 1)

    @mute_logger('odoo.addons.mail.models.mail_mail')
    def test_delivery_failure_leaves_no_marker_and_next_call_sends_again(self):
        with self.mock_smtplib_connection():
            with patch.object(self.testing_smtp_session, 'send_message', side_effect=smtplib.SMTPException('refused')) as send_message:
                self._send_digest(self.user_a, self.company_a)
            self.assertEqual(send_message.call_count, 1)
            self.assertFalse(self._marker(self.company_a))
            self._send_digest(self.user_a, self.company_a)
        self.assertEqual([email['msg_to'] for email in self.emails], [self.user_a.email])
        self.assertTrue(self._marker(self.company_a))
