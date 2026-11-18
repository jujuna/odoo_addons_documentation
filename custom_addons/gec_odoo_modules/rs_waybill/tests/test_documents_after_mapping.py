"""Documents built after Resolve Now leave nothing half-built when they fail: the mapping stays, a banner says why,
and the drift job builds them once the cause is fixed."""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestDocumentsAfterMapping(RsWaybillCommon):

    def test_a_failed_order_leaves_nothing_behind_and_is_built_later(self):
        self.env.company.write({'rs_enable_stock': True, 'rs_stock_integration_date': '2000-01-01'})
        goods = self.env['product.product'].create({'name': 'Juice', 'is_storable': True})
        waybill = self.make_waybill(state='active', waybill_status='1', rs_internal_id=999001)
        self.add_line(waybill, quantity=5, product_id=goods.id, name='Juice')
        orders = lambda: self.env['sale.order'].search([('partner_id', '=', self.buyer.id)])

        with patch.object(type(self.env['sale.order']), 'action_confirm',
                          side_effect=UserError("No route for Juice")):
            waybill._rs_documents_after_mapping()

        self.assertFalse(waybill.sales_order_id)
        self.assertFalse(orders(), "no draft order left behind")
        self.assertIn('No route for Juice', waybill.rs_post_commit_error)

        waybill._rs_repair_local_state()  # the drift job, once the route is fixed

        self.assertTrue(waybill.sales_order_id)
        self.assertTrue(waybill.picking_id)
        self.assertFalse(waybill.rs_post_commit_error, "banner gone")
