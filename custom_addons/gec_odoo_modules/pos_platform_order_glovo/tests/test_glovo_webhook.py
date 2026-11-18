from odoo.tests import tagged

from odoo.addons.pos_platform_order_glovo.tests.common import TestGlovoCommon

CONTROLLER_LOGGER = 'odoo.addons.pos_platform_order_glovo.controllers.main'


@tagged('post_install', '-at_install')
class TestGlovoWebhook(TestGlovoCommon):

    def setUp(self):
        super().setUp()
        self.main_pos_config.with_user(self.pos_user).open_ui()

    def _post(self, order_id, store_id, token):
        return self.url_open(
            '/glovo/order/dispatched', data=f'{{"order_id": "{order_id}", "store_id": "{store_id}"}}',
            headers={'Content-Type': 'application/json', 'Authorization': token},
        )

    def test_unknown_store_answers_like_a_wrong_token(self):
        with self.assertLogs(CONTROLLER_LOGGER, 'WARNING') as logs:
            unknown_store = self._post('7951', 'NO-SUCH-STORE', 'lock-token')
            wrong_token = self._post('7952', 'LOCK-STORE', 'wrong')
        self.assertEqual((unknown_store.status_code, unknown_store.text), (401, "Unauthorized"))
        self.assertEqual((wrong_token.status_code, wrong_token.text), (401, "Unauthorized"))
        self.assertIn("no store found matching ID NO-SUCH-STORE", logs.output[0])
        self.assertIn("invalid token", logs.output[1])
        self.assertFalse(self.env['glovo.event'].search([('glovo_order_id', 'in', ['7951', '7952'])]))

    def test_disabled_provider_records_failed_event(self):
        self.provider.state = 'disabled'
        self.assertEqual(self._webhook('dispatched', '7955'), (200, 'failed', "Glovo provider is disabled"))
        self.assertFalse(self._glovo_order('7955'))
