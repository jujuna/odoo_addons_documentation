"""An error of a failed rs.ge call is re-written in a new cursor after the rollback, and written once on a commit."""

from contextlib import contextmanager

from odoo.tests import tagged

from odoo.addons.rs_einvoice.models.account_move import _rs_replay_after_rollback

from .common import RsEinvoiceCommon

KEEP_KEY = 'rs_einvoice_keep'
STOPPED = 'Line sync to rs.ge stopped'


@tagged('post_install', '-at_install')
class TestKeepAfterRollback(RsEinvoiceCommon):

    def setUp(self):
        super().setUp()
        self.move = self._invoice()

    @contextmanager
    def _own_cursor(self):
        """Yield a test cursor with its own transaction and the invoice browsed on it."""
        with self.registry_test_mode():
            cr = self.registry.cursor()
            try:
                yield cr, self.move.with_env(self.env(cr=cr))
            finally:
                if not cr.closed:
                    cr.close()

    def _logs(self, message, operator='='):
        self.env.invalidate_all()
        return self.env['rs.einvoice.log'].search([
            ('move_id', '=', self.move.id), ('name', operator, message)])

    def test_only_an_error_is_queued(self):
        with self._own_cursor() as (cr, move):
            move._rs_log('i', 'info')
            move._rs_log('w', 'warning')
            self.assertNotIn(KEEP_KEY, cr.postrollback.data)
            move._rs_log('e', 'error')
            self.assertEqual(cr.postrollback.data[KEEP_KEY], [
                (self.move.id, '_rs_log', ('e', 'error')),
            ])
            cr.commit()

    def test_rollback_keeps_the_error(self):
        with self._own_cursor() as (cr, move):
            move._rs_log('e', 'error')
            cr.rollback()
            cr.close()
        self.assertEqual(len(self._logs('e')), 1)

    def test_commit_writes_the_error_once(self):
        with self._own_cursor() as (cr, move):
            move._rs_log('e', 'error')
            cr.commit()
            cr.close()
        self.assertEqual(len(self._logs('e')), 1)

    def test_rollback_does_not_keep_a_warning(self):
        with self._own_cursor() as (cr, move):
            move._rs_log('w', 'warning')
            cr.rollback()
            cr.close()
        self.assertFalse(self._logs('w'))

    def test_rollback_keeps_the_partial_flag_and_the_todo(self):
        with self._own_cursor() as (cr, move):
            move._rs_mark_lines_partial()
            move._rs_schedule_line_sync_activity(123, 'Line B', 1, 2)
            cr.rollback()
            cr.close()
        self.env.invalidate_all()
        self.assertEqual(self.move.rs_einv_lines_sync_state, 'partial')
        self.assertEqual(len(self.env['mail.activity'].search([
            ('res_model', '=', 'account.move'), ('res_id', '=', self.move.id)])), 1)
        self.assertEqual(len(self.env['mail.message'].search([
            ('model', '=', 'account.move'), ('res_id', '=', self.move.id),
            ('body', 'ilike', STOPPED)])), 1)
        self.assertEqual(len(self._logs(STOPPED, 'ilike')), 1)

    def test_replay_skips_a_missing_move(self):
        missing_id = self.env['account.move'].search([], order='id desc', limit=1).id + 1
        queue = [
            (missing_id, '_rs_log', ('lost', 'error')),
            (self.move.id, '_rs_log', ('kept', 'error')),
        ]
        with self.registry_test_mode():
            _rs_replay_after_rollback(self.env.registry, self.env.uid, self.env.context, queue)
        self.assertEqual(len(self._logs('kept')), 1)
        self.assertFalse(self.env['rs.einvoice.log'].search([('name', '=', 'lost')]))
