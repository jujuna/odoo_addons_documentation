"""Saving Settings keeps the RS.GE sync jobs as they are unless their box was changed."""

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestSettingsSyncSwitches(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.sync = self.env.ref('rs_waybill.ir_cron_sync_updated_waybills')
        self.transporter = self.env.ref('rs_waybill.cron_sync_transporter_waybills')

    def test_saving_other_settings_keeps_the_jobs_running(self):
        (self.sync | self.transporter).active = True
        settings = self.env['res.config.settings'].create({'rs_stock_integration_date': '2026-09-09'})
        self.assertTrue(settings.rs_auto_sync_updated, "the box shows the running job")
        settings.execute()
        self.assertTrue(self.sync.active)
        self.assertTrue(self.transporter.active)

    def test_unticking_the_box_stops_the_job(self):
        self.sync.active = True
        self.env['res.config.settings'].create({'rs_auto_sync_updated': False}).execute()
        self.assertFalse(self.sync.active)
