"""Buttons show only where they can work, and the re-confirm banner clears when the customer
confirms or rejects again.
"""

from unittest.mock import patch

from lxml import etree

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestButtonsAndReconfirm(RsWaybillCommon):

    def _edited_after_confirmation(self, direction='seller'):
        return self.make_waybill(waybill_direction=direction, state='active', waybill_status='1',
                                 rs_internal_id=950001, is_confirmed='0',
                                 is_buyer_reconfirm_needed=True)

    def test_customer_confirms_again_clears_the_banner(self):
        waybill = self._edited_after_confirmation()
        waybill.write({'is_confirmed': '1'})
        self.assertFalse(waybill.is_buyer_reconfirm_needed)

    def test_customer_rejects_clears_the_banner(self):
        waybill = self._edited_after_confirmation()
        waybill.write({'is_confirmed': '2'})
        self.assertFalse(waybill.is_buyer_reconfirm_needed)

    def test_status_unchanged_keeps_the_banner(self):
        waybill = self._edited_after_confirmation()
        waybill.write({'is_confirmed': '0'})
        self.assertTrue(waybill.is_buyer_reconfirm_needed)

    def test_vendor_waybill_keeps_its_own_flag(self):
        """On a vendor's waybill the flag means OUR Received is needed again."""
        waybill = self._edited_after_confirmation('buyer')
        waybill.write({'is_confirmed': '1'})
        self.assertTrue(waybill.is_buyer_reconfirm_needed)

    def _invisible(self, button, string=None):
        arch = etree.fromstring(self.env['rs.waybill'].get_view(view_type='form')['arch'])
        nodes = [n for n in arch.iter('button') if n.get('name') == button
                 and (string is None or string in etree.tostring(n, encoding='unicode'))]
        self.assertTrue(nodes, button)
        return ' '.join(n.get('invisible') or '' for n in nodes)

    def test_adjustment_hidden_while_an_rs_change_waits(self):
        self.assertIn('rs_goods_pending_snapshot', self._invisible('action_edit_waybill', 'Adjustment'))

    def test_received_hidden_until_the_purchase_order_is_picked(self):
        self.assertIn('rs_needs_purchase_pick', self._invisible('action_confirm_waybill', 'Received'))

    def test_reconfirm_banner_not_on_vendor_waybills(self):
        arch = self.env['rs.waybill'].get_view(view_type='form')['arch']
        self.assertIn("not is_buyer_reconfirm_needed or waybill_direction == 'buyer'", arch)

    def test_no_adjustment_history_is_a_note_not_an_error(self):
        waybill = self.make_waybill(state='active', waybill_status='1', rs_internal_id=950002)
        service = type(self.env['rs.waybill.soap.service'])
        with patch.object(service, 'get_adjusted_waybills', return_value=[]):
            action = waybill.action_view_adjustments()
        self.assertEqual(action.get('tag'), 'display_notification')
