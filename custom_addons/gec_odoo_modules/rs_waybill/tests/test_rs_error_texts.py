"""RS.GE refusals are explained in words, from its own error-code list (get_error_codes), and never
send the user to the RS.GE site.
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


ENVELOPE_A = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>
<get_error_codesResponse><get_error_codesResult><ERROR_CODES>
  <ERROR_CODE><ID>-1004</ID><TEXT>მყიდველის საიდენტიფიკაციო ნომერი არასწორია</TEXT><TYPE>1</TYPE></ERROR_CODE>
  <ERROR_CODE><ID>-1005</ID><TEXT>Start address is empty</TEXT><TYPE>1</TYPE></ERROR_CODE>
</ERROR_CODES></get_error_codesResult></get_error_codesResponse></soap:Body></soap:Envelope>"""

ENVELOPE_B = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>
<r><Table><CODE>-2001</CODE><NAME>Car number is wrong</NAME></Table></r>
</soap:Body></soap:Envelope>"""


@tagged('post_install', '-at_install')
class TestRsErrorTexts(TransactionCase):

    def setUp(self):
        super().setUp()
        self.service = self.env['rs.waybill.soap.service']

    def _message(self, codes, method, code):
        with patch.object(type(self.service), '_rs_error_codes', return_value=codes):
            with self.assertRaises(UserError) as caught:
                self.service._check_rs_result(method, code)
        return str(caught.exception)

    def test_rs_text_code_and_plain_action(self):
        message = self._message({-1004: "Buyer TIN is wrong"}, 'save_waybill', -1004)

        self.assertIn("Buyer TIN is wrong", message)
        self.assertIn("-1004", message)
        self.assertIn("Save", message)
        self.assertNotIn("save_waybill", message)

    def test_without_the_list_the_code_is_still_shown(self):
        message = self._message({}, 'close_waybill', -1004)

        self.assertIn("-1004", message)
        self.assertIn("Complete", message)

    def test_known_codes_keep_their_odoo_hint(self):
        message = self._message({-100: "RS text"}, 'save_waybill', -100)

        self.assertIn("RS Username", message, "the Preferences hint is kept for a wrong login")

    def test_the_rs_list_is_read_in_both_layouts(self):
        self.assertEqual(self.service._parse_error_codes(ENVELOPE_A),
                         {-1004: "მყიდველის საიდენტიფიკაციო ნომერი არასწორია",
                          -1005: "Start address is empty"})
        self.assertEqual(self.service._parse_error_codes(ENVELOPE_B), {-2001: "Car number is wrong"})

    def test_no_result_points_to_update_not_the_rs_site(self):
        with self.assertRaises(UserError) as caught:
            self.service._check_rs_action_result('confirm_waybill', None)
        message = str(caught.exception)
        self.assertIn("Update", message)
        self.assertNotIn("on RS.GE and try again", message)
