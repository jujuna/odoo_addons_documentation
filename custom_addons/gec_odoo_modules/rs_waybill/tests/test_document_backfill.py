"""Documents built from a synced waybill are all-or-nothing, shown when they fail, and retried."""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestDocumentBackfill(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.env.company.rs_enable_stock = True
        self.env.company.rs_stock_integration_date = '2000-01-01'
        self.waybill = self.make_waybill(state='active', waybill_status='1', rs_internal_id=990001)
        self.add_line(self.waybill)
        self.sale_count = self.env['sale.order'].search_count([])

    def _build(self):
        """What sync, Update and drift do for a waybill without documents."""
        self.waybill._rs_build_documents()

    def test_a_failing_confirm_leaves_nothing_half_made(self):
        with patch.object(type(self.env['sale.order']), 'action_confirm',
                          side_effect=ValueError("no route for this product")):
            self._build()

        self.assertFalse(self.waybill.sales_order_id)
        self.assertEqual(self.env['sale.order'].search_count([]), self.sale_count)
        self.assertIn('no route', self.waybill.rs_post_commit_error)
        self.assertTrue(self.waybill._rs_has_outstanding_step())

    def test_it_is_retried_once_the_cause_is_fixed(self):
        with patch.object(type(self.env['sale.order']), 'action_confirm',
                          side_effect=ValueError("no route for this product")):
            self._build()

        self.waybill._rs_repair_local_state()

        self.assertTrue(self.waybill.sales_order_id)
        self.assertTrue(self.waybill.picking_id)
        self.assertFalse(self.waybill.rs_post_commit_error)
