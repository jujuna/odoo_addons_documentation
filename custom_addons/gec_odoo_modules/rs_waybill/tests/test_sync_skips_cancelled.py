"""A cancelled waybill Odoo already has is not downloaded again; completed ones still are (an
Adjustment can change them).
"""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestSyncSkipsCancelled(RsWaybillCommon):

    def _sync(self, row):
        Waybill = type(self.env['rs.waybill'])
        Service = type(self.env['rs.waybill.soap.service'])
        with patch.object(Service, '_get_client', return_value=(None, 'su', 'sp', None)), \
                patch.object(Service, 'get_full_waybill_with_client',
                             return_value=({'ID': row['ID']}, [])) as download, \
                patch.object(Waybill, '_map_rs_waybill_vals', return_value={}), \
                patch.object(Waybill, '_goods_lines_changed', return_value=False), \
                patch.object(self.env.cr, 'commit', lambda: None):
            self.env['rs.waybill']._process_rs_rows([row], 'transporter', {})
        return download.call_count

    def test_cancelled_waybill_is_not_downloaded_again(self):
        self.make_waybill(waybill_direction='transporter', state='cancelled',
                          waybill_status='-2', rs_internal_id=993001)
        self.assertEqual(self._sync({'ID': '993001', 'STATUS': '-2'}), 0)

    def test_completed_waybill_is_still_downloaded(self):
        self.make_waybill(waybill_direction='transporter', state='completed',
                          waybill_status='2', rs_internal_id=993002)
        self.assertEqual(self._sync({'ID': '993002', 'STATUS': '2'}), 1)

    def test_a_cancel_still_to_follow_up_is_downloaded(self):
        self.make_waybill(state='cancelled', waybill_status='-2', rs_internal_id=993003,
                          rs_cancel_cascade='pending')
        self.assertEqual(self._sync({'ID': '993003', 'STATUS': '-2'}), 1)

    def test_a_new_cancelled_waybill_is_downloaded(self):
        self.assertEqual(self._sync({'ID': '993004', 'STATUS': '-2'}), 1)
