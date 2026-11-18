"""Drift checks what can still change: draft and active waybills, completed ones for 15 days after
delivery, and any with an Odoo step left.
"""

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestDriftScope(RsWaybillCommon):

    def test_only_what_can_still_change_is_checked(self):
        now = fields.Datetime.now()
        make = lambda rs_id, **vals: self.make_waybill(rs_internal_id=rs_id, **vals)
        active = make(994001, state='active', waybill_status='1')
        recent = make(994002, state='completed', waybill_status='2', delivery_date=now - timedelta(days=5))
        old = make(994003, state='completed', waybill_status='2', delivery_date=now - timedelta(days=20))
        old_no_date = make(994004, state='completed', waybill_status='2',
                           activation_date=now - timedelta(days=40))
        old_but_unfinished = make(994005, state='completed', waybill_status='2',
                                  delivery_date=now - timedelta(days=20),
                                  rs_post_commit_error='Validate the linked transfer: no stock')
        cancelled = make(994006, state='cancelled', waybill_status='-2')
        mine = active | recent | old | old_no_date | old_but_unfinished | cancelled
        self.env['rs.waybill'].search([('id', 'not in', mine.ids)]).write(
            {'rs_drifted_checked': '2000-01-01 00:00:00'})

        service = type(self.env['rs.waybill.soap.service'])
        with patch.object(service, 'get_full_waybill', return_value=(None, [])), \
                patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=float('inf')):
            self.env['rs.waybill']._cron_rs_drift_repair_one()

        checked = mine.filtered('rs_drifted_checked')
        self.assertEqual(checked, active | recent | old_but_unfinished)
