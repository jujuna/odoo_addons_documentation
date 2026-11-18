"""The 30-day deadline (Order 996, art. 54) counts until the invoice is sent to the buyer, not until the buyer confirms."""

from odoo import fields
from odoo.tests import tagged

from .common import RsEinvoiceCommon


@tagged('post_install', '-at_install')
class TestDeadline(RsEinvoiceCommon):

    def _posted(self, status, rs_id):
        """A posted invoice dated 40 days ago, at rs.ge ``status``."""
        invoice = self._invoice(invoice_date=fields.Date.subtract(fields.Date.today(), days=40))
        invoice.action_post()
        invoice.write({'rs_einv_id': rs_id, 'rs_einv_status': status})
        return invoice

    def test_sent_invoice_is_not_overdue_until_the_buyer_answers(self):
        sent = self._posted('1', '700201')
        draft = self._posted('0', '700202')
        self.assertEqual((sent.rs_einv_overdue_state, draft.rs_einv_overdue_state), ('ok', 'overdue'))

    def test_cron_logs_only_the_invoice_not_sent_to_the_buyer(self):
        sent = self._posted('1', '700201')
        draft = self._posted('0', '700202')
        self.env['account.move']._cron_rs_einv_check_deadlines()
        self.assertFalse(sent.rs_einv_log_ids.filtered(lambda log: log.name.startswith('[DEADLINE')))
        self.assertTrue(draft.rs_einv_log_ids.filtered(lambda log: log.name.startswith('[DEADLINE')))
