"""'Enable Stock Integration' in Settings really switches it: off means waybills only, no sales
orders, purchase orders or deliveries.
"""

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestStockIntegrationSwitch(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.env.company.rs_stock_integration_date = '2026-01-01'
        self.waybill = self.make_waybill(state='active', waybill_status='1', rs_internal_id=950001,
                                         activation_date='2026-06-01 10:00:00')

    def _switch(self, on):
        self.env.company.rs_enable_stock = on

    def test_switch_off_keeps_waybills_only(self):
        self._switch(False)
        self.assertFalse(self.waybill._in_integration_scope())

    def test_switch_on_uses_the_start_date(self):
        self._switch(True)
        self.assertTrue(self.waybill._in_integration_scope())
        self.waybill.activation_date = '2025-06-01 10:00:00'
        self.assertFalse(self.waybill._in_integration_scope(), "before the start date")

    def test_each_company_has_its_own_switch(self):
        self._switch(True)
        company_b = self.env['res.company'].create({'name': 'Switch Second Co',
                                                    'rs_stock_integration_date': '2026-01-01'})
        waybill_b = self.make_waybill(state='active', waybill_status='1', rs_internal_id=950002,
                                      activation_date='2026-06-01 10:00:00', company_id=company_b.id)

        self.assertTrue(self.waybill._in_integration_scope())
        self.assertFalse(waybill_b._in_integration_scope(), "company B never switched it on")
