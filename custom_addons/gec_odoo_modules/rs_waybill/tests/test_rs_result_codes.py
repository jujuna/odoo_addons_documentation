"""RS.GE reply-code handling: a rejected operation must never be stored as success or as an id."""

from unittest.mock import Mock, patch

from lxml import etree
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestRsResultCodes(RsWaybillCommon):

    def test_success_code_returns_1(self):
        self.assertEqual(self.service._check_rs_result('send_waybill', 1), 1)

    def test_bad_credentials_raises(self):
        with self.assertRaises(UserError) as e:
            self.service._check_rs_result('send_waybill', -100)
        self.assertIn('RS Username', e.exception.args[0])

    def test_foreign_waybill_raises(self):
        with self.assertRaises(UserError) as e:
            self.service._check_rs_result('send_waybill', -101)
        self.assertIn('another taxpayer', e.exception.args[0])

    def test_generic_failure_raises(self):
        with self.assertRaises(UserError):
            self.service._check_rs_result('send_waybill', -1)

    def test_unknown_code_raises(self):
        """An unmapped code must still be an error, never a silent success."""
        with self.assertRaises(UserError):
            self.service._check_rs_result('send_waybill', -1004)

    def test_none_result_raises(self):
        with self.assertRaises(UserError):
            self.service._check_rs_result('send_waybill', None)

    def test_positive_id_passes_through(self):
        self.assertEqual(self.service._check_rs_id('save_invoice', '4711'), 4711)

    def test_error_code_is_not_stored_as_an_id(self):
        """A -100 reply must not be stored as a new record id."""
        with self.assertRaises(UserError):
            self.service._check_rs_id('save_invoice', -100)

    def test_zero_id_raises(self):
        with self.assertRaises(UserError):
            self.service._check_rs_id('save_waybill_template', 0)

    def test_unreadable_id_raises_user_error_not_valueerror(self):
        with self.assertRaises(UserError):
            self.service._check_rs_id('save_invoice', 'not-a-number')

    def test_missing_status_element_is_an_error(self):
        """A reply with no <STATUS> is an error, not a success with an empty RS id."""
        waybill = self.make_waybill()
        self.add_line(waybill)
        reply = etree.fromstring('<RESULT><ID>0</ID></RESULT>')
        double = Mock()
        double.save_waybill.return_value = reply
        with self.mocked_client(double), \
             patch.object(type(self.service), '_build_waybill_xml',
                          return_value=etree.Element('WAYBILL')):
            with self.assertRaises(UserError) as e:
                self.service.save_waybill(waybill)
        self.assertIn('NOT saved', e.exception.args[0])

    def test_negative_status_is_an_error(self):
        waybill = self.make_waybill()
        reply = etree.fromstring('<RESULT><STATUS>-1</STATUS></RESULT>')
        double = Mock()
        double.save_waybill.return_value = reply
        with self.mocked_client(double), \
             patch.object(type(self.service), '_build_waybill_xml',
                          return_value=etree.Element('WAYBILL')):
            with self.assertRaises(UserError):
                self.service.save_waybill(waybill)

    def test_successful_save_returns_parsed_payload(self):
        waybill = self.make_waybill()
        reply = etree.fromstring(
            '<RESULT><STATUS>0</STATUS><ID>987</ID>'
            '<WAYBILL_NUMBER>AB-123</WAYBILL_NUMBER>'
            '<GOODS_LIST><GOODS><ID>5</ID><W_NAME>Widget</W_NAME>'
            '<BAR_CODE>X1</BAR_CODE><ERROR>0</ERROR></GOODS></GOODS_LIST></RESULT>')
        double = Mock()
        double.save_waybill.return_value = reply
        with self.mocked_client(double), \
             patch.object(type(self.service), '_build_waybill_xml',
                          return_value=etree.Element('WAYBILL')):
            result = self.service.save_waybill(waybill)
        self.assertEqual(result['id'], '987')
        self.assertEqual(result['waybill_number'], 'AB-123')
        self.assertEqual(len(result['goods']), 1)
        self.assertEqual(result['goods'][0]['id'], '5')

    def test_send_waybill_raises_on_rejection(self):
        double = Mock()
        double.send_waybill.return_value = -1
        with self.mocked_client(double):
            with self.assertRaises(UserError):
                self.service.send_waybill(123)

    def test_confirm_waybill_raises_on_rejection(self):
        double = Mock()
        double.confirm_waybill.return_value = -101
        with self.mocked_client(double):
            with self.assertRaises(UserError):
                self.service.confirm_waybill(123)

    def test_reject_waybill_raises_on_rejection(self):
        double = Mock()
        double.reject_waybill.return_value = -100
        with self.mocked_client(double):
            with self.assertRaises(UserError):
                self.service.reject_waybill(123)

    def test_real_rs_success_replies_pass(self):
        """Replies RS.GE really sends on success: the waybill number (Activate) and True (Received)."""
        double = Mock()
        double.send_waybill.return_value = '1013911932'
        double.confirm_waybill.return_value = True
        with self.mocked_client(double):
            self.assertEqual(self.service.send_waybill(123), '1013911932')
            self.assertIs(self.service.confirm_waybill(123), True)

    def test_send_waybill_accepts_success(self):
        double = Mock()
        double.send_waybill.return_value = 1
        with self.mocked_client(double):
            self.assertEqual(self.service.send_waybill(123), 1)

    def _save_with_reply(self, xml):
        waybill = self.make_waybill()
        double = Mock()
        double.save_waybill.return_value = etree.fromstring(xml)
        with self.mocked_client(double), \
             patch.object(type(self.service), '_build_waybill_xml', return_value=etree.Element('WAYBILL')), \
             patch.object(type(self.service), '_rs_error_codes', return_value={-1004: "Buyer TIN is wrong"}):
            return self.service.save_waybill(waybill)

    def test_save_success_codes_are_never_refused(self):
        """Save answers STATUS 0 on success (not 1 like the actions): it must not go through the 1-is-success check."""
        for status in ('0', '1'):
            result = self._save_with_reply('<RESULT><STATUS>%s</STATUS><ID>987</ID>'
                                           '<WAYBILL_NUMBER></WAYBILL_NUMBER></RESULT>' % status)
            self.assertEqual(result['id'], '987', "STATUS %s is a successful save" % status)

    def test_save_refusal_shows_rs_reason(self):
        with self.assertRaises(UserError) as caught:
            self._save_with_reply('<RESULT><STATUS>-1004</STATUS></RESULT>')
        message = str(caught.exception)
        self.assertIn("Buyer TIN is wrong", message)
        self.assertIn("-1004", message)
        self.assertIn("Save", message)

    def test_save_bad_login_keeps_its_hint(self):
        with self.assertRaises(UserError) as caught:
            self._save_with_reply('<RESULT><STATUS>-100</STATUS></RESULT>')
        self.assertIn("RS Username", str(caught.exception))
