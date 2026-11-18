"""The drift job saves each waybill as it goes, so a run cut by the time limit keeps its progress."""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestDriftProgress(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.waybills = self.env['rs.waybill']
        for rs_id in (910001, 910002, 910003):
            self.waybills |= self.make_waybill(state='active', waybill_status='1', rs_internal_id=rs_id)
        self.env['rs.waybill'].search([('id', 'not in', self.waybills.ids)]).write(
            {'rs_drifted_checked': '2000-01-01 00:00:00'})
        service = type(self.env['rs.waybill.soap.service'])
        patcher = patch.object(service, 'get_full_waybill', return_value=(None, []))
        self.get_full = patcher.start()
        self.addCleanup(patcher.stop)

    def _drift(self, seconds_left):
        cron = type(self.env['ir.cron'])
        with patch.object(cron, '_commit_progress', return_value=seconds_left) as progress:
            self.env['rs.waybill']._cron_rs_drift_repair_one()
        return progress

    def test_each_waybill_is_saved_as_it_goes(self):
        progress = self._drift(float('inf'))

        self.assertEqual(progress.call_count, 3)
        self.assertTrue(all(call.args == (1,) for call in progress.call_args_list))
        self.assertTrue(all(self.waybills.mapped('rs_drifted_checked')),
                        "a waybill RS.GE returned nothing for is still marked checked")

    def test_stops_when_the_cron_time_is_up(self):
        self._drift(0.0)

        self.assertEqual(self.get_full.call_count, 1)
        self.assertEqual(len(self.waybills.filtered('rs_drifted_checked')), 1,
                         "the other two are left for the next run")
