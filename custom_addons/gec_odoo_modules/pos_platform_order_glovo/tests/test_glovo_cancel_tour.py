from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.pos_restaurant.tests.test_frontend import TestFrontendCommon


@tagged('post_install', '-at_install')
class TestGlovoCancelTour(TestFrontendCommon):

    def test_glovo_cancel_blocked_in_pos(self):
        self.env['pos.printer'].search([]).unlink()
        self.pos_config.with_user(self.pos_user).open_ui()
        session = self.pos_config.current_session_id

        provider = self.env['platform.order.provider'].create({
            'name': 'Glovo Tour', 'code': 'glovo', 'state': 'test',
            'company_id': self.env.company.id, 'default_pricelist_id': self.pos_config.pricelist_id.id,
        })
        store = self.env['platform.order.entity'].create({
            'name': 'Glovo Tour Store', 'external_id': 'TOUR-STORE',
            'provider_id': provider.id, 'config_id': self.pos_config.id,
        })
        product = self.coca_cola_test.product_variant_id if 'product_variant_id' in self.coca_cola_test else self.coca_cola_test
        product.default_code = 'TOUR-P1'
        glovo_order = store.sudo()._create_order_from_data({
            'order_id': '5001', 'store_id': 'TOUR-STORE', 'order_code': 'GLV5001', 'pick_up_code': '1',
            'estimated_total_price': 100, 'partner_discounted_products_total': 100, 'is_picked_up_by_customer': False,
            'products': [{'id': 'TOUR-P1', 'quantity': 1, 'price': 100, 'attributes': []}],
        })
        normal_order = self.env['pos.order'].create({
            'session_id': session.id, 'floating_order_name': 'NormalDraft',
            'amount_tax': 0, 'amount_total': 1, 'amount_paid': 0, 'amount_return': 0,
            'lines': [Command.create({
                'product_id': product.id, 'qty': 1, 'price_unit': 1,
                'price_subtotal': 1, 'price_subtotal_incl': 1, 'full_product_name': product.name,
            })],
        })
        for order in glovo_order | normal_order:
            self.env['pos.prep.order'].update_last_order_change(order)
        self.assertEqual(glovo_order.platform_order_provider_code, 'glovo')
        self.assertTrue(glovo_order.prep_order_ids and normal_order.prep_order_ids)

        self.start_pos_tour('glovo_cancel_blocked_tour')

        self.env.invalidate_all()
        self.assertEqual((glovo_order.state, glovo_order.platform_order_status), ('draft', 'accepted'))
        self.assertFalse(sum(glovo_order.prep_order_ids.prep_line_ids.mapped('cancelled')))
        self.assertEqual(normal_order.state, 'cancel')
