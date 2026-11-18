import json

from odoo import sql_db
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command
from odoo.tests import tagged
from odoo.tests.common import get_db_name

from odoo.addons.pos_platform_order_glovo.tests.common import TestGlovoCommon

MISSING_PRODUCT = {
    'products': [{'id': 'LOCK-P9', 'purchased_product_id': 'A9', 'quantity': 1, 'price': 500, 'attributes': []}],
    'estimated_total_price': 500, 'partner_discounted_products_total': 500,
}


@tagged('post_install', '-at_install')
class TestGlovoRetryAndPayment(TestGlovoCommon):

    def _event(self, order_id):
        return self.env['glovo.event'].search([('glovo_order_id', '=', order_id), ('event_type', '=', 'dispatched')])

    def test_retry_failed_no_product_event(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        _status, state, error = self._webhook('dispatched', '7601', **MISSING_PRODUCT)
        self.assertEqual(state, 'failed')
        self.assertIn("no product with Internal Reference LOCK-P9", error)
        self.assertFalse(self._glovo_order('7601'))

        pen = self.whiteboard_pen.product_variant_id
        pen.default_code = 'LOCK-P9'
        event = self._event('7601')
        event.with_user(self.pos_admin).action_retry()

        order = self._glovo_order('7601')
        self.assertEqual(event.state, 'processed')
        self.assertNotIn("no product", event.error or '')
        self.assertEqual((order.lines.product_id, order.state, order.platform_order_status), (pen, 'draft', 'accepted'))

    def test_retry_processed_event_refused(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self.assertEqual(self._webhook('dispatched', '7602')[1], 'processed')
        with self.assertRaisesRegex(UserError, "Processed Glovo events can't be retried."):
            self._event('7602').with_user(self.pos_admin).action_retry()

    def test_cashier_cannot_see_or_retry(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self._webhook('dispatched', '7603', **MISSING_PRODUCT)
        event = self._event('7603')
        self.assertFalse(self.pos_user.has_group('point_of_sale.group_pos_manager'))

        with self.assertRaises(AccessError):
            self.env['glovo.event'].with_user(self.pos_user).search([])
        with self.assertRaises(AccessError):
            event.with_user(self.pos_user).action_retry()
        menu = self.env.ref('pos_platform_order_glovo.menu_glovo_event')
        self.assertNotIn(menu.id, self.env['ir.ui.menu'].with_user(self.pos_user)._visible_menu_ids())
        self.assertIn(menu.id, self.env['ir.ui.menu'].with_user(self.pos_admin)._visible_menu_ids())
        self.assertEqual(event.state, 'failed')

        views = self.env['glovo.event'].with_user(self.pos_admin).get_views([(False, 'list'), (False, 'form')])['views']
        self.assertIn('action_retry', views['list']['arch'])
        self.assertIn('action_retry', views['form']['arch'])

    def test_payment_method_shown_to_cashier(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self._webhook('dispatched', '7701', payment_method='CASH')
        self._webhook('dispatched', '7702', payment_method='DELAYED')
        self.assertEqual(self._glovo_order('7701').glovo_payment_method, 'CASH')
        self.assertEqual(self._glovo_order('7702').glovo_payment_method, 'DELAYED')
        self.start_pos_tour('glovo_payment_method_tour', login='pos_user')


@tagged('post_install', '-at_install')
class TestGlovoEventLock(TestGlovoCommon):
    """A second transaction holds the event's row lock: Retry refuses, the webhook answers 200 without processing.

    The event is committed before the test transaction starts, so a second, real connection can see and lock it.
    """

    @classmethod
    def setUpClass(cls):
        payload = {
            'order_id': '7801', 'store_id': 'LOCK-STORE', 'order_code': 'LOCK7801', 'pick_up_code': '433',
            'payment_method': 'DELAYED', 'currency': 'USD', 'estimated_total_price': 2000,
            'partner_discounted_products_total': 2000, 'is_picked_up_by_customer': False,
            'products': [{'id': 'LOCK-P1', 'purchased_product_id': 'A1', 'quantity': 2, 'price': 1000, 'attributes': []}],
        }
        with sql_db.db_connect(get_db_name()).cursor() as cr:
            cr.execute("""
                INSERT INTO glovo_event (event_type, glovo_order_id, store_external_id, payload, state, error, company_id, create_date, write_date)
                SELECT 'dispatched', '7801', 'LOCK-STORE', %s, 'failed', 'Earlier failure', res_id,
                       now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC'
                  FROM ir_model_data WHERE module = 'base' AND name = 'main_company'
             RETURNING id
            """, [json.dumps(payload)])
            cls.locked_event_id = cr.fetchone()[0]
        # registered before the test transaction's own cleanups, so it runs after its rollback
        cls.addClassCleanup(cls._delete_locked_event)
        super().setUpClass()
        cls.provider.default_pricelist_id.company_id = False
        cls.provider.company_id = cls.env.ref('base.main_company')

    @classmethod
    def _delete_locked_event(cls):
        with sql_db.db_connect(get_db_name()).cursor() as cr:
            cr.execute("DELETE FROM glovo_event WHERE id = %s", [cls.locked_event_id])

    def test_locked_event_skipped_by_retry_and_webhook(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        event = self.env['glovo.event'].sudo().browse(self.locked_event_id)
        self.pos_admin.sudo().company_ids = [Command.link(event.company_id.id)]
        manager_event = event.with_user(self.pos_admin).with_context(
            allowed_company_ids=(self.pos_admin.company_id | event.company_id).ids)

        holder = sql_db.db_connect(get_db_name()).cursor()
        try:
            holder.execute("SELECT id FROM glovo_event WHERE id = %s FOR UPDATE", [self.locked_event_id])
            with self.assertRaisesRegex(UserError, "This event is being processed right now. Try again in a moment."):
                manager_event.action_retry()
            with self.assertLogs('odoo.addons.pos_platform_order_glovo.models.glovo_event', 'INFO') as logs:
                self.assertEqual(self._webhook('dispatched', '7801')[0], 200)
            self.assertIn("is locked; skipped", logs.output[0])
            event.invalidate_recordset()
            self.assertEqual((event.state, event.error), ('failed', 'Earlier failure'))
            self.assertFalse(self._glovo_order('7801'))
        finally:
            holder.rollback()
            holder.close()

        manager_event.action_retry()
        event.invalidate_recordset()
        self.assertEqual(event.state, 'processed')
        self.assertTrue(self._glovo_order('7801'))
