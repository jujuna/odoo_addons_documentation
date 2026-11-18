"""The Reconcile Delivery banner is cleared even when there is nothing to reconcile."""

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestReconcileStuck(RsWaybillCommon):

    def _click(self, mark):
        waybill = self.make_waybill(state='completed', waybill_status='2', rs_internal_id=940001,
                                    pending_return_json=mark)
        return waybill, waybill.action_reconcile_pending_return()

    def test_empty_mark_is_cleared_with_a_note(self):
        waybill, action = self._click('[]')
        self.assertFalse(waybill.pending_return_json)
        self.assertEqual(action.get('tag'), 'display_notification')

    def test_damaged_mark_is_cleared_with_a_note(self):
        waybill, action = self._click('not json')
        self.assertFalse(waybill.pending_return_json)
        self.assertEqual(action.get('tag'), 'display_notification')
