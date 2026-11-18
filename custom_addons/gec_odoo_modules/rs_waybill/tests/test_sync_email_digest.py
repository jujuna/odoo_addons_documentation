"""One email per sync run, not one per waybill: a summary per notification user, one email per
customer, and each waybill keeps its chatter note.
"""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestSyncEmailDigest(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.user = self.env['res.users'].create({
            'name': 'Waybill Watcher', 'login': 'watcher@example.com', 'email': 'watcher@example.com'})
        self.env.company.rs_notification_user_ids = self.user
        customer_a = self.env['res.partner'].create({'name': 'A LLC', 'email': 'a@example.com'})
        customer_b = self.env['res.partner'].create({'name': 'B LLC', 'email': 'b@example.com'})
        self.waybills = self.env['rs.waybill']
        for rs_id, contact in ((995001, customer_a), (995002, customer_a), (995003, customer_b)):
            self.waybills |= self.make_waybill(state='active', waybill_status='1', rs_internal_id=rs_id,
                                               rs_waybill_number='0%s' % rs_id,
                                               buyer_contact_email=contact.id, comment='old')

    def _sync_changes(self):
        Waybill = type(self.env['rs.waybill'])
        Service = type(self.env['rs.waybill.soap.service'])
        with patch.object(Service, '_get_client', return_value=(None, 'su', 'sp', None)), \
                patch.object(Service, 'get_full_waybill_with_client', return_value=({'ID': 1}, [])), \
                patch.object(Waybill, '_map_rs_waybill_vals', return_value={'comment': 'changed on RS.GE'}), \
                patch.object(Waybill, '_goods_lines_changed', return_value=False), \
                patch.object(type(self.env['mail.mail']), 'send'), \
                patch.object(self.env.cr, 'commit', lambda: None):
            self.env['rs.waybill']._process_rs_rows(
                [{'ID': str(w.rs_internal_id)} for w in self.waybills], 'seller', {})

    def _mails_to(self, address):
        return self.env['mail.mail'].search([]).filtered(
            lambda m: address in (m.email_to or '') or address in m.recipient_ids.mapped('email'))

    def test_users_get_one_summary_with_every_waybill_linked(self):
        self._sync_changes()

        mails = self._mails_to('watcher@example.com')
        self.assertEqual(len(mails), 1)
        for waybill in self.waybills:
            self.assertIn(waybill.rs_waybill_number, mails.body_html)
            self.assertIn('/odoo/rs.waybill/%s' % waybill.id, mails.body_html)

    def test_each_customer_gets_one_email_with_their_waybills(self):
        self._sync_changes()

        mail_a, mail_b = self._mails_to('a@example.com'), self._mails_to('b@example.com')
        self.assertEqual((len(mail_a), len(mail_b)), (1, 1))
        self.assertIn('0995001', mail_a.body_html)
        self.assertIn('0995002', mail_a.body_html)
        self.assertNotIn('0995003', mail_a.body_html)

    def test_each_waybill_keeps_its_chatter_note(self):
        self._sync_changes()
        for waybill in self.waybills:
            self.assertTrue(waybill.message_ids.filtered(lambda m: m.subject and 'Waybill' in m.subject))
