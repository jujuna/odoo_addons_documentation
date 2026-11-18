"""Received shows why RS.GE refused; several waybills at once go on past a refused one and end with
a summary.
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestReceiveErrors(RsWaybillCommon):

    def _vendor_waybill(self, rs_id):
        return self.make_waybill(waybill_direction='buyer', waybill_type='5', state='active',
                                 waybill_status='1', rs_internal_id=rs_id)

    def _confirm(self, waybills, refused_ids):
        def confirm(waybill_id):
            if waybill_id in refused_ids:
                raise UserError("RS.GE refused: wrong RS username or password")
            return True
        service = type(self.env['rs.waybill.soap.service'])
        # The action commits after RS.GE accepts; tests forbid commits on the instance.
        with patch.object(service, 'confirm_waybill', side_effect=confirm), \
                patch.object(self.env.cr, 'commit'):
            return waybills.action_confirm_waybill()

    def test_single_receive_shows_the_refusal(self):
        waybill = self._vendor_waybill(920001)

        with self.assertRaisesRegex(UserError, 'wrong RS username'):
            self._confirm(waybill, {920001})

        self.assertNotEqual(waybill.is_confirmed, '1')

    def test_bulk_receive_goes_on_past_a_refusal(self):
        refused, accepted = self._vendor_waybill(920002), self._vendor_waybill(920003)

        result = self._confirm(refused | accepted, {920002})

        self.assertEqual(accepted.is_confirmed, '1')
        self.assertNotEqual(refused.is_confirmed, '1')
        self.assertIn('1 confirmed, 1 skipped', result['params']['message'])
