from contextlib import nullcontext

from requests.exceptions import ReadTimeout

from odoo.tests import tagged

from odoo.addons.rs_einvoice.models.account_move_seller import RsNoAnswerError

from . import stub_responses
from .common import RsEinvoiceCommon

TODO = 'Check the rs.ge cancellation'


@tagged('post_install', '-at_install')
class TestCancel(RsEinvoiceCommon):

    def setUp(self):
        super().setUp()
        self.invoice = self._invoice(invoice_date='2026-09-20')
        self.invoice.action_post()
        self.invoice.write({'rs_einv_id': '700123', 'rs_einv_status': '2'})

    def _rsge(self, status=2, **responses):
        return self._patch_rsge(chek=stub_responses.chek(), get_invoice=stub_responses.get_invoice(status=status), **responses)

    def _raised(self, call):
        """The exception of ``call``; unlike assertRaises it does not roll back the work done before it."""
        try:
            call()
        except Exception as error:
            return error

    def test_unanswered_cancel_keeps_a_todo_after_the_rollback(self):
        with self._rsge(), self.registry_test_mode():
            cr = self.registry.cursor()
            move = self.invoice.with_env(self.env(cr=cr))
            with self._rsge_failing('change_invoice_status', ReadTimeout):
                error = self._raised(move.action_rs_cancel)
            cr.rollback()
            cr.close()
        self.assertIsInstance(error, RsNoAnswerError)
        self.env.invalidate_all()
        self.assertEqual(self.invoice.rs_einv_status, '2')
        self.assertEqual(len(self.invoice.activity_ids.filtered(lambda activity: activity.summary == TODO)), 1)

    def _reissue_in_own_cursor(self, failing=None, **responses):
        """Cancel and Reissue with the rs.ge service call ``failing`` raising a Timeout, then the rollback of the request."""
        with self._rsge(**responses), self.registry_test_mode():
            cr = self.registry.cursor()
            move = self.invoice.with_env(self.env(cr=cr))
            with self._rsge_failing(failing, ReadTimeout) if failing else nullcontext():
                error = self._raised(move._rs_do_cancel_reissue)
            cr.rollback()
            cr.close()
        self.env.invalidate_all()
        return error

    def test_unanswered_cancel_and_reissue_survives_the_rollback(self):
        error = self._reissue_in_own_cursor('change_invoice_status')
        replacement = self.invoice.rs_einv_replaced_by_id
        self.assertIsInstance(error, RsNoAnswerError)
        self.assertEqual(replacement.rs_einv_replaces_id, self.invoice)
        self.assertIn(replacement.display_name, str(error))
        self.assertEqual(self.invoice.rs_einv_status, '2')
        self.assertEqual(len(self.invoice.activity_ids.filtered(lambda activity: activity.summary == TODO)), 1)

    def test_cancel_and_reissue_stopped_before_the_cancel_call_leaves_no_replacement(self):
        error = self._reissue_in_own_cursor('_check_auth')
        self.assertIsInstance(error, ReadTimeout)
        self.assertFalse(self.invoice.rs_einv_replaced_by_id)
        self.assertFalse(self.env['account.move'].search([('rs_einv_replaces_id', '=', self.invoice.id)]))

    def test_refused_cancel_and_reissue_leaves_no_replacement(self):
        error = self._reissue_in_own_cursor(change_invoice_status=stub_responses.change_invoice_status(result=False))
        self.assertIn('refused the cancellation', str(error))
        self.assertFalse(self.invoice.rs_einv_replaced_by_id)
        self.assertFalse(self.env['account.move'].search([('rs_einv_replaces_id', '=', self.invoice.id)]))

    def test_status_update_to_cancelled_sent_sets_the_waiting_todo(self):
        with self._rsge(status=6):
            self.invoice.action_rs_refresh_status()
        self.assertEqual(self.invoice.rs_einv_status, '6')
        self.assertTrue(self.invoice.rs_einv_cancel_pending_at)
