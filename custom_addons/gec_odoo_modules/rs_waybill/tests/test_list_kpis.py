"""The waybill list cards get their eight numbers in one request."""

from datetime import timedelta

from odoo import fields
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestListKpis(RsWaybillCommon):

    def test_eight_numbers_in_one_call(self):
        now = fields.Datetime.now()
        yesterday = now - timedelta(days=1)
        self.make_waybill(state='active', activation_date=now)
        self.make_waybill(state='active', activation_date=yesterday)
        self.make_waybill(state='cancelled', cancel_date=now)
        self.make_waybill(state='completed', delivery_date=yesterday)
        mine = [('rs_internal_id', '=', False), ('is_template', '=', False),
                ('id', 'in', self.env['rs.waybill'].search([], order='id desc', limit=4).ids)]

        kpis = self.env['rs.waybill'].rs_list_kpis(
            mine, fields.Datetime.to_string(now.replace(hour=0, minute=0, second=0)))

        self.assertEqual(kpis, {
            'total': 4, 'active': 2, 'cancelled': 1, 'completed': 1,
            'totalToday': 4, 'activeToday': 1, 'cancelledToday': 1, 'completedToday': 0,
        })
