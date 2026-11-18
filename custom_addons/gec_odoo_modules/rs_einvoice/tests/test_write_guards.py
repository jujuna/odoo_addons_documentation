"""The write() guards of a document that is on rs.ge, and the audit trail of the rs.ge ID bypass."""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import RsEinvoiceCommon


@tagged('post_install', '-at_install')
class TestWriteGuards(RsEinvoiceCommon):

    def setUp(self):
        super().setUp()
        self.invoice = self._invoice(invoice_date=date(2026, 9, 20))
        self.invoice.action_post()
        self.invoice.write({'rs_einv_id': '700123', 'rs_einv_status': '0'})

    def _audit_logs(self):
        return self.env['rs.einvoice.log'].search([
            ('move_id', '=', self.invoice.id), ('level', '=', 'warning')])

    def test_rs_id_cannot_be_cleared_or_changed(self):
        with self.assertRaises(UserError):
            self.invoice.write({'rs_einv_id': False})
        with self.assertRaises(UserError):
            self.invoice.write({'rs_einv_id': '1'})
        self.assertEqual(self.invoice.rs_einv_id, '700123')

    def test_rs_id_overwrite_with_context_is_audited(self):
        self.invoice.with_context(rs_allow_id_overwrite=True).write({'rs_einv_id': '700999'})
        self.assertEqual(self.invoice.rs_einv_id, '700999')
        self.assertTrue(any('context bypass' in log.name for log in self._audit_logs()))
        self.assertTrue(self.invoice.message_ids.filtered(lambda m: 'context bypass' in (m.body or '')))

    def test_settlement_mode_locked_once_sent(self):
        self.invoice.write({'rs_einv_advance_settlement_mode': 'native_attach'})
        self.invoice.write({'rs_einv_status': '1'})
        with self.assertRaises(UserError):
            self.invoice.write({'rs_einv_advance_settlement_mode': 'net'})

    def test_immutable_fields_locked_once_on_rsge(self):
        # reversed_entry_id is the immutable field core itself does not lock on a posted move
        other = self._invoice(invoice_date=date(2026, 9, 19))
        other.action_post()
        with self.assertRaises(UserError):
            self.invoice.write({'reversed_entry_id': other.id})
        self.assertFalse(self.invoice.reversed_entry_id)

    def test_skip_toggle_locked_on_posted(self):
        invoice = self._invoice(invoice_date=date(2026, 9, 20))
        invoice.action_post()
        with self.assertRaises(UserError):
            invoice.write({'rs_einv_skip': True, 'rs_einv_skip_reason': 'other'})
        self.assertFalse(invoice.rs_einv_skip)

    def test_unticking_skip_clears_its_reason(self):
        invoice = self._invoice(invoice_date=date(2026, 9, 20))
        invoice.write({'rs_einv_skip': True, 'rs_einv_skip_reason': 'other'})
        invoice.write({'rs_einv_skip': False})
        self.assertFalse(invoice.rs_einv_skip_reason)
