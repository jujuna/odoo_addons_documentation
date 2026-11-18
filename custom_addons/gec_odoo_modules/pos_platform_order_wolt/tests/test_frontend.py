from unittest.mock import patch

from odoo.fields import Command

from odoo.addons.pos_platform_order_wolt.tests.common import REQUESTS, _response
from odoo.addons.pos_restaurant.tests.test_frontend import TestFrontendCommon


class TestWoltFrontend(TestFrontendCommon):

    def test_wolt_takeaway_flow(self):
        provider = self.env['platform.order.provider'].search(
            [('code', '=', 'wolt'), ('company_id', '=', self.env.company.id)], limit=1)
        provider._setup_payment_method(provider)
        provider._setup_pricelist(provider)
        provider.write({'state': 'test', 'wolt_client_id': 'cid', 'wolt_client_secret': 'cs'})
        store = self.env['platform.order.entity'].create({
            'name': 'Main', 'provider_id': provider.id, 'external_id': 'VENUE1', 'config_id': self.pos_config.id,
            'payment_method_id': provider.default_payment_method_id.id,
            'pricelist_line_ids': [Command.create({
                'name': 'Default', 'external_key': 'default', 'pricelist_id': provider.default_pricelist_id.id,
            })],
        })
        self.env['platform.order.wolt.token'].create({
            'store_id': store.id, 'access_token': 'AT', 'refresh_token': 'RT', 'expiry': '2099-01-01 00:00:00',
        })
        self.env['pos.printer'].search([]).unlink()
        self.pos_config.with_user(self.pos_user).open_ui()
        product = self.coca_cola_test.product_tmpl_id
        order = {
            'id': 'W9', 'order_number': '042', 'type': 'instant', 'order_status': 'received',
            'delivery': {'type': 'takeaway', 'self_delivery': False},
            'order_handling': {'acceptance_status': 'to_be_accepted_by_venue'},
            'items': [{'pos_id': f'product_template_{product.id}', 'count': 1, 'options': [],
                       'item_price': {'total': {'amount': 220, 'currency': 'USD'}}}],
        }
        with patch(f'{REQUESTS}.request', return_value=_response(status=202)) as request:
            store._create_order_from_data(order)
            self.start_pos_tour("test_wolt_takeaway_flow")
        paths = [call.args[1].split('woltapi.com')[1] for call in request.call_args_list]
        self.assertEqual(paths, ['/orders/W9/accept', '/orders/W9/ready', '/orders/W9/delivered'])
        wolt_order = self.env['pos.order'].search([('platform_order_ref', '=', 'W9')])
        self.assertEqual(wolt_order.platform_order_status, 'delivered')
