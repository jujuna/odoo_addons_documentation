# Part of Odoo. See LICENSE file for full copyright and licensing details

from .common import TestPlanningFieldServiceSaleTimesheetCommon
from odoo.tests import new_test_user, HttpCase


class TestFsmProductCatalog(TestPlanningFieldServiceSaleTimesheetCommon, HttpCase):

    def test_catalog_routes_with_restricted_sales_user(self):
        """
        Checks that a "Sales: Own Documents Only" user can open the catalog of a task whose SO
        belongs to another salesperson.
        """
        self.intervention.write({
            'state': '3_in_progress',
            'partner_id': self.partner_1.id,
        })
        restricted_user = new_test_user(
            self.env, 'restricted_salesman',
            groups='planning.group_planning_user,sales_team.group_sale_salesman',
        )
        resource = self.env['resource.resource'].create({
            "name": "James",
            "user_id": restricted_user.id,
            "resource_type": "user",
        })
        sale_order = self.env['sale.order'].create({
            "partner_id": self.partner_1.id,
        })
        self.intervention.sale_order_id = sale_order
        sale_order.action_confirm()

        slot = self.intervention
        slot.resource_ids = resource
        self.consu_product_ordered.with_context(intervention_id=slot.id).set_fsm_quantity(2)
        self.assertFalse(sale_order.with_user(restricted_user).has_access('read'))

        self.authenticate(restricted_user.login, restricted_user.login)
        params = {
            'res_model': 'sale.order',
            'order_id': sale_order.id,
            'child_field': 'order_line',
            'intervention_id': slot.id,
        }
        order_lines_info = self.make_jsonrpc_request('/product/catalog/order_lines_info', {
            **params,
            'product_ids': self.consu_product_ordered.ids,
            'section_id': False,
        })
        self.assertEqual(order_lines_info[str(self.consu_product_ordered.id)]['quantity'], 2)
