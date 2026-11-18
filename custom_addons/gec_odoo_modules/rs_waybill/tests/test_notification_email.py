"""Waybill emails: Georgian activation time, full links in the sync digest."""

from datetime import datetime
from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestNotificationEmail(RsWaybillCommon):

    def test_activation_time_is_georgian(self):
        waybill = self.make_waybill(rs_internal_id=980001, activation_date=datetime(2026, 8, 12, 6, 0))

        body = waybill._get_waybill_email_body()

        self.assertIn('10:00:00', body, "06:00 UTC is 10:00 in Tbilisi")
        self.assertNotIn('06:00:00', body)

    def test_digest_links_carry_the_full_address(self):
        waybill = self.make_waybill(rs_internal_id=980002, rs_waybill_number='WB-1')
        self.env.company.rs_notification_user_ids = self.env['res.users'].create({
            'name': 'Waybill Watcher', 'login': 'watcher@example.com', 'email': 'watcher@example.com'})
        self.env['ir.config_parameter'].sudo().set_str('web.base.url', 'https://erp.example.ge')
        with patch.object(type(self.env['mail.mail']), 'send'):
            self.env['rs.waybill']._rs_send_notification_digest([(waybill.id, 'Confirmed')])

        mail = self.env['mail.mail'].search([('recipient_ids.email', '=', 'watcher@example.com')])
        self.assertEqual(len(mail), 1)
        self.assertIn('href="https://erp.example.ge/odoo/rs.waybill/%s"' % waybill.id, mail.body_html)

    def test_email_uses_the_company_colors_and_logo(self):
        self.env.company.write({'primary_color': '#153749', 'email_secondary_color': '#049978',
                                'logo': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='})
        self.env['ir.config_parameter'].sudo().set_str('web.base.url', 'https://erp.example.ge')
        body = self.make_waybill(rs_internal_id=980003)._get_waybill_email_body()

        self.assertIn('background:#153749', body)
        self.assertIn('color:#049978', body)
        self.assertIn('src="https://erp.example.ge/logo.png?company=%s"' % self.env.company.id, body)
        self.assertNotIn('#0b2545', body, "no hard-coded navy left")

    def test_no_logo_shows_the_company_name(self):
        self.env.company.logo = False
        body = self.make_waybill(rs_internal_id=980004)._get_waybill_email_body()

        self.assertNotIn('/logo.png', body)
        self.assertIn(self.env.company.name, body)

    def test_unreadable_or_invalid_colors_fall_back(self):
        Waybill = self.env['rs.waybill']
        self.env.company.write({'primary_color': 'red; display:none', 'email_secondary_color': '#0b2546'})
        brand = Waybill._rs_mail_brand(self.env.company)
        self.assertEqual(brand['header'], '#0b2545', "not a color: default header")
        self.assertEqual(brand['accent'], '#ffffff', "navy on navy is unreadable: white instead")

        self.env.company.primary_color = '#f5f5f0'
        self.assertEqual(Waybill._rs_mail_brand(self.env.company)['text'], '#0f172a', "dark text on a light header")

    def test_digest_has_the_company_frame(self):
        waybill = self.make_waybill(rs_internal_id=980005, rs_waybill_number='WB-5')
        self.env.company.write({'primary_color': '#153749',
                                'rs_notification_user_ids': self.env['res.users'].create({
                                    'name': 'Watcher', 'login': 'w5@example.com', 'email': 'w5@example.com'})})
        with patch.object(type(self.env['mail.mail']), 'send'):
            self.env['rs.waybill']._rs_send_notification_digest([(waybill.id, 'Confirmed')])

        mail = self.env['mail.mail'].search([('recipient_ids.email', '=', 'w5@example.com')])
        self.assertIn('background:#153749', mail.body_html)
        self.assertIn('WB-5', mail.body_html)
