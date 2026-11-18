"""A vendor document the buyer rejected is cancelled; when the supplier re-sends the same rs.ge record, the
buyer resets it to draft, gets the supplier's new lines, and accepts it."""

from types import SimpleNamespace

from odoo import Command
from odoo.tests import tagged

from . import stub_responses
from .common import RsEinvoiceCommon


@tagged('post_install', '-at_install')
class TestBuyerRejectResend(RsEinvoiceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({'name': 'Supplier LLC', 'vat': '404404404'})

    def _pulled_bill(self, status, rs_id='555100'):
        """A pulled vendor bill of one line, 2 x 50 GEL, at rs.ge ``status``."""
        return self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor.id,
            'company_id': self.company.id,
            'invoice_date': '2026-09-20',
            'rs_einv_id': rs_id,
            'rs_einv_status': status,
            'invoice_line_ids': [Command.create({'name': 'Cement', 'quantity': 2, 'price_unit': 50})],
        })

    def _rsge(self, statuses):
        """rs.ge answering get_invoice with ``statuses`` in call order; its line is 2 x 50 until the reject,
        then 2 x 45 as the supplier re-sent it."""
        def lines(price):
            return stub_responses.datatable('get_invoice_desc', [{
                'ID': 800101, 'INV_ID': 555100, 'GOODS': 'Cement', 'G_UNIT': 'ერთეული',
                'G_NUMBER': 2, 'FULL_AMOUNT': 2 * price, 'DRG_AMOUNT': 0.0, 'VAT_TYPE': -1,
            }])
        return self._patch_rsge(
            chek=stub_responses.chek(),
            get_invoice=[stub_responses.get_invoice(status=s, seller_un_id=1149251, buyer_un_id=731937)
                         for s in statuses],
            get_makoreqtirebeli=stub_responses.envelope(
                'get_makoreqtirebeli', get_makoreqtirebeliResult=True, k_id=-1),
            get_invoice_desc=[lines(50), lines(45)],
            ref_invoice_status=stub_responses.envelope('ref_invoice_status', ref_invoice_statusResult=True),
            acsept_invoice_status=stub_responses.envelope(
                'acsept_invoice_status', acsept_invoice_statusResult=True),
        )

    def _reject(self, bill):
        self.env['rs.einvoice.reject.wizard'].create({'move_id': bill.id, 'reason': 'Wrong price'}).action_confirm()

    def test_rejected_bill_comes_back_with_the_resent_lines(self):
        bill = self._pulled_bill('1')
        with self._rsge([1, 0, 1, 1, 1, 2]) as rsge:
            self._reject(bill)
            self.assertEqual((bill.state, bill.rs_einv_status), ('cancel', '0'))
            self.assertTrue(bill.rs_einv_rejection_note)
            self.assertFalse(bill.show_reset_to_draft_button)

            bill.action_rs_refresh_status()
            self.assertEqual(bill.rs_einv_status, '1')
            self.assertFalse(bill.rs_einv_rejection_note)
            self.assertTrue(bill.show_reset_to_draft_button)

            bill.button_draft()
            self.assertEqual(bill.state, 'draft')
            self.assertEqual(bill.invoice_line_ids.price_unit, 45)
            bill.action_rs_buyer_accept()
        self.assertEqual(rsge.calls.count('get_invoice'), 6)
        self.assertEqual((bill.state, bill.rs_einv_status), ('posted', '2'))
        self.assertEqual(bill.amount_untaxed, 90)

    def test_rejected_correction_comes_back_when_resent(self):
        bill = self._pulled_bill('5')
        with self._rsge([5, 4, 5, 5, 5, 8]) as rsge:
            self._reject(bill)
            self.assertEqual((bill.state, bill.rs_einv_status), ('cancel', '4'))
            bill.action_rs_refresh_status()
            bill.button_draft()
            bill.action_rs_buyer_accept()
        self.assertEqual(rsge.calls.count('get_invoice'), 6)
        self.assertEqual((bill.state, bill.rs_einv_status), ('posted', '8'))

    def test_reset_stays_hidden_unless_resent(self):
        posted = self._pulled_bill('2')
        posted.with_context(rs_skip_lock_check=True).action_post()
        self.assertFalse(posted.show_reset_to_draft_button)
        for status in ('0', '7'):
            with self.subTest(status=status):
                bill = self._pulled_bill(status, rs_id='5551%s' % status)
                bill.with_context(rs_skip_lock_check=True).button_cancel()
                self.assertFalse(bill.show_reset_to_draft_button)

    def test_resend_read_keeps_the_seller_rejection_notice(self):
        invoice = self._invoice(rs_einv_id='555200', rs_einv_status='0', rs_einv_rejection_note='Rejected by buyer')
        invoice._rs_refresh_rejection(SimpleNamespace(was_ref=False), '1', '0')
        self.assertEqual(invoice.rs_einv_rejection_note, 'Rejected by buyer')
