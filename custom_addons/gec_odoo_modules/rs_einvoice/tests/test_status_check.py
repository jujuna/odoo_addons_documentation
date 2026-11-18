"""A status check that cannot reach rs.ge (connection, timeout or HTTP failure) stops the button; any other failure reaches the traceback."""

from requests.exceptions import ReadTimeout
from zeep.exceptions import TransportError

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import RsEinvoiceCommon


@tagged('post_install', '-at_install')
class TestStatusCheck(RsEinvoiceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({'name': 'Supplier LLC', 'vat': '404404404'})

    def _bill(self):
        """A draft vendor bill at Sent (Pending)."""
        return self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor.id,
            'company_id': self.company.id,
            'invoice_date': '2026-09-20',
            'rs_einv_id': '555300',
            'rs_einv_status': '1',
            'invoice_line_ids': [Command.create({'name': 'Cement', 'quantity': 1, 'price_unit': 70})],
        })

    def test_unreachable_rsge_stops_the_button(self):
        bill = self._bill()
        with self._rsge_failing('get_invoice', ReadTimeout), self.assertRaisesRegex(UserError, 'cannot be reached'):
            bill.action_rs_buyer_accept()

    def test_http_failure_stops_the_button(self):
        bill = self._bill()
        with self._rsge_failing('get_invoice', TransportError(status_code=503)), self.assertRaisesRegex(UserError, 'cannot be reached'):
            bill.action_rs_buyer_accept()

    def test_other_failures_are_not_reported_as_unreachable(self):
        bill = self._bill()
        with self._rsge_failing('get_invoice', AttributeError), self.assertRaises(AttributeError):
            bill.action_rs_buyer_accept()

    def test_replacement_of_a_cancelled_original_is_posted_without_rsge(self):
        original = self._invoice()
        original.action_post()
        original.write({'rs_einv_id': '700123', 'rs_einv_status': '7'})
        replacement = self._invoice(rs_einv_replaces_id=original.id, rs_einv_replacement_mode='fresh')
        with self._rsge_failing('get_invoice', ReadTimeout):
            replacement.action_post()
        self.assertEqual(replacement.state, 'posted')
