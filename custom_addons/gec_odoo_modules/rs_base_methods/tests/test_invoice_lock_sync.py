"""An RS.GE goods change is held while an invoice locks the waybill."""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestInvoiceLockSync(TransactionCase):

    def setUp(self):
        super().setUp()
        self.waybill = self.env['rs.waybill'].with_context(rs_skip_resolve=True).create({
            'waybill_direction': 'seller', 'waybill_type': '2', 'transport_type': '1',
            'start_address': 'Tbilisi', 'end_address': 'Batumi',
            'state': 'completed', 'waybill_status': '2', 'rs_internal_id': 870001,
        })

    def _lock(self, locked):
        move = self.env['account.move'].search([], limit=1)
        self.env.flush_all()   # else the pending recompute overwrites the lock below
        self.env.cr.execute("UPDATE rs_waybill SET is_locked_by_invoice = %s, locked_by_move_id = %s "
                            "WHERE id = %s", (locked, (move.id or None) if locked else None, self.waybill.id))
        self.waybill.invalidate_recordset(['is_locked_by_invoice', 'locked_by_move_id'])

    def test_locked_by_invoice_blocks_the_rs_change(self):
        self._lock(True)
        self.assertTrue(self.waybill._rs_auto_apply_blocked())

    def test_not_locked_lets_it_through(self):
        self._lock(False)
        self.assertFalse(self.waybill._rs_auto_apply_blocked())
