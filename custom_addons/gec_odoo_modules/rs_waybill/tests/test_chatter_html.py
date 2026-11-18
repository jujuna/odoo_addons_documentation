"""Chatter messages are marked as HTML, so bold text shows; values from RS.GE or users stay escaped."""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestChatterHtml(RsWaybillCommon):

    def _last_body(self, record):
        return str(record.message_ids[:1].body)

    def _fail_step(self, waybill, label):
        def boom():
            raise ValueError("RS.GE down")
        waybill._rs_post_commit(label, boom)

    def test_bold_is_shown_as_bold(self):
        waybill = self.make_waybill(state='active', waybill_status='1', rs_internal_id=940001)

        self._fail_step(waybill, "Validate the linked transfer")

        body = self._last_body(waybill)
        self.assertIn('<b>Validate the linked transfer</b>', body)
        self.assertNotIn('&lt;b&gt;', body)

    def test_values_inside_stay_escaped(self):
        waybill = self.make_waybill(state='active', waybill_status='1', rs_internal_id=940002)

        self._fail_step(waybill, "<script>x</script>")

        body = self._last_body(waybill)
        self.assertNotIn('<script>', body)
        self.assertIn('&lt;script&gt;', body)

    def test_notification_email_is_html(self):
        waybill = self.make_waybill(state='active', waybill_status='1', rs_internal_id=940003)
        self.env.user.partner_id.email = 'me@example.com'

        with patch.object(type(waybill), '_get_notification_users', return_value=self.env.user):
            waybill._send_notification_email(action='Edited')

        body = self._last_body(waybill)
        self.assertIn('<table', body)
        self.assertNotIn('&lt;table', body)
