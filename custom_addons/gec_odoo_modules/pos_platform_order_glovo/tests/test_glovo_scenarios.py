from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.pos_platform_order_glovo.tests.common import TestGlovoScenarioCommon, glovo_attribute, glovo_product, glovo_sub_product

EVENT_LOGGER = 'odoo.addons.pos_platform_order_glovo.models.glovo_event'
CONTROLLER_LOGGER = 'odoo.addons.pos_platform_order_glovo.controllers.main'
NOT_ALLOWED = "Cannot update state for orders that are not in the allowed states: new, accepted, driver_allocated, driver_arrived, collected."
NO_SESSION = "No open POS session."
ANOTHER_STORE = "Glovo: order %s belongs to another store."
NO_ORDER = "Glovo: no order found matching order ID %s."
DRAFT = ('draft', 'accepted', 0)
PROCESSED = ('processed', False)


@tagged('post_install', '-at_install')
class TestGlovoScenarios(TestGlovoScenarioCommon):

    def _age(self, events, days):
        self.env.cr.execute("UPDATE glovo_event SET write_date = now() - interval '%s days' WHERE id IN %s", [days, tuple(events.ids)])
        events.invalidate_recordset(['write_date'])

    def _resolve(self, order, resolution, reason, user=None):
        return self.env['pos.glovo.order.resolve'].with_user(user or self.pos_admin).with_context(
            active_model='pos.order', active_ids=order.ids, default_resolution=resolution).create({'reason': reason})

    def _chatter(self, order):
        return " ".join(str(body) for body in order.message_ids.mapped('body'))

    def test_delayed_order_is_paid_on_the_store_method_after_pickup(self):
        self._open_pos()
        self.assertEqual(self._notify('dispatched', '8101').status_code, 200)
        order = self._glovo_order('8101')
        self.assertEqual(self._order_status(order), DRAFT)
        self.assertEqual(self._result(self._events('8101', 'dispatched')), (*PROCESSED, order))

        result, ready = self._food_ready(order)
        self.assertTrue(result['success'])
        ready.assert_called_once_with('8101', 'LOCK-STORE')
        self.assertTrue(order.platform_order_food_ready)

        self.assertEqual(self._notify('picked_up', '8101').status_code, 200)
        payment = order.payment_ids
        self.assertEqual(self._order_status(order), ('paid', 'delivered', 1))
        self.assertEqual((payment.payment_method_id, payment.amount, order.amount_total), (self.store.payment_method_id, 20.0, 20.0))
        self.assertEqual(self._result(self._events('8101', 'picked_up')), (*PROCESSED, order))

    def test_cash_order_is_paid_on_the_cash_method_after_pickup(self):
        self._open_pos()
        self.assertTrue(self.cash)
        self._notify('dispatched', '8102', payment_method='CASH')
        order = self._glovo_order('8102')
        self.assertTrue(self._food_ready(order)[0]['success'])
        self._notify('picked_up', '8102', payment_method='CASH')
        payment = order.payment_ids
        self.assertEqual(self._order_status(order), ('paid', 'delivered', 1))
        self.assertEqual((payment.payment_method_id, payment.amount), (self.cash, 20.0))
        self.assertNotEqual(payment.payment_method_id, self.store.payment_method_id)

    def test_cancel_before_pickup_cancels_the_order_without_payment(self):
        self._open_pos()
        self._notify('dispatched', '8103')
        order = self._glovo_order('8103')
        self.assertEqual(self._notify('cancelled', '8103', cancel_reason='STORE_CAN_NOT_DELIVER').status_code, 200)
        self.assertEqual(self._order_status(order), ('cancel', 'cancelled', 0))
        self.assertEqual(order.platform_order_cancel_reason, 'STORE_CAN_NOT_DELIVER')
        self.assertEqual(self._result(self._events('8103', 'cancelled')), (*PROCESSED, order))

    def test_cancel_after_pickup_leaves_the_paid_order_and_fails_the_event(self):
        """Known limitation: Glovo's late cancellation is refused by Odoo's state rule; the store handles it in the Glovo Partner Webapp."""
        self._open_pos()
        self._notify('dispatched', '8104')
        self._notify('picked_up', '8104')
        order = self._glovo_order('8104')
        with mute_logger(EVENT_LOGGER):
            self.assertEqual(self._notify('cancelled', '8104').status_code, 200)
        self.assertEqual(self._order_status(order), ('paid', 'delivered', 1))
        self.assertEqual(self._result(self._events('8104', 'cancelled')), ('failed', NOT_ALLOWED, order))
        self.assertNotIn("cancelled with reason", self._chatter(order))

    def test_notifications_arriving_out_of_order_are_replayed_by_the_dispatched(self):
        self._open_pos()
        with mute_logger(EVENT_LOGGER):
            self._notify('picked_up', '8105')
            self._notify('cancelled', '8105')
        picked_up, cancelled = self._events('8105')
        self.assertEqual(self._result(picked_up), ('failed', NO_ORDER % '8105', self.no_order))
        self.assertEqual(self._result(cancelled), ('failed', NO_ORDER % '8105', self.no_order))

        with mute_logger(EVENT_LOGGER):
            self.assertEqual(self._notify('dispatched', '8105').status_code, 200)
        order = self._glovo_order('8105')
        dispatched = self._events('8105', 'dispatched')
        self.assertEqual(self._order_status(order), ('paid', 'delivered', 1))
        self.assertEqual(self._result(picked_up), (*PROCESSED, order))
        self.assertEqual(self._result(cancelled), ('failed', NOT_ALLOWED, order))
        self.assertEqual(self._result(dispatched), (*PROCESSED, order))

    def test_the_same_notification_twice_makes_one_order_and_one_event(self):
        self._open_pos()
        self.assertEqual([self._notify('dispatched', '8106').status_code for _ in range(2)], [200, 200])
        order = self._glovo_order('8106')
        events = self._events('8106')
        self.assertEqual((len(order), len(events)), (1, 1))
        self.assertEqual(self._order_status(order), DRAFT)
        self.assertEqual(self._result(events), (*PROCESSED, order))

    def test_order_received_while_the_pos_was_closed_is_created_by_the_cron(self):
        self.assertEqual(self._notify('dispatched', '8107').status_code, 200)
        event = self._events('8107', 'dispatched')
        self.assertEqual(self._result(event), ('failed', NO_SESSION, self.no_order))
        self.assertFalse(self._glovo_order('8107'))

        self._open_pos()
        self.env['glovo.event']._cron_retry_failed_events()
        order = self._glovo_order('8107')
        self.assertEqual(self._order_status(order), DRAFT)
        self.assertEqual(self._result(event), (*PROCESSED, order))

    def test_manager_retry_creates_the_order_once_the_product_is_mapped(self):
        self._open_pos()
        self._notify('dispatched', '8108', products=[glovo_product('SC-NEW', 1000)])
        event = self._events('8108', 'dispatched')
        self.assertEqual(self._result(event), ('failed', "Glovo: no product with Internal Reference SC-NEW.", self.no_order))
        self.assertFalse(self._glovo_order('8108'))

        self.unmapped_product.default_code = 'SC-NEW'
        self._retry_as_manager(event)
        order = self._glovo_order('8108')
        self.assertEqual(order.lines.product_id, self.unmapped_product)
        self.assertEqual(self._result(event), (*PROCESSED, order))

    def test_partner_discount_that_reconciles_leaves_no_error_and_one_that_differs_names_both_totals(self):
        self._open_pos()
        discounted = [glovo_product('SC-PLAIN', 1000, quantity=2, discount=300)]
        self._notify('dispatched', '8109', products=discounted, partner_discounts_products=300, partner_discounted_products_total=1700)
        order = self._glovo_order('8109')
        self.assertEqual(order.amount_total, 17.0)
        self.assertEqual(self._result(self._events('8109')), (*PROCESSED, order))

        self._notify('dispatched', '8110', products=discounted, partner_discounts_products=300, partner_discounted_products_total=1500)
        event = self._events('8110')
        self.assertEqual((self._glovo_order('8110').amount_total, event.state), (17.0, 'processed'))
        self.assertIn("POS order total 17.00 differs from Glovo total after product discounts 15.00", event.error)

    def test_combo_attribute_and_taxes_give_glovo_total(self):
        self._open_pos()
        combo = glovo_product(
            'SC-COMBO', 1000, attributes=[glovo_attribute('A1', 'Large', 100)],
            sub_products=[
                glovo_sub_product('S1', 'Burger', 300, discount=50, attributes=[glovo_attribute('SA1', 'No onion', 0)]),
                glovo_sub_product('S2', 'Fries', 100, quantity=2),
            ])
        products = [
            combo,
            glovo_product('SC-ATTR', 500, quantity=2, attributes=[glovo_attribute('A2', 'Extra cheese', 50)]),
            glovo_product('SC-INCL', 1000),
            glovo_product('SC-EXCL', 1100),
        ]
        self._notify('dispatched', '8111', products=products, partner_discounted_products_total=4750)
        order = self._glovo_order('8111')
        lines = {line.product_id.default_code: line for line in order.lines}
        self.assertEqual(order.amount_total, 47.5)
        self.assertEqual(self._result(self._events('8111')), (*PROCESSED, order))
        incl = {code: line.price_subtotal_incl for code, line in lines.items()}
        self.assertEqual(incl, {'SC-COMBO': 15.5, 'SC-ATTR': 11.0, 'SC-INCL': 10.0, 'SC-EXCL': 11.0})
        self.assertEqual((lines['SC-ATTR'].price_subtotal, lines['SC-EXCL'].price_subtotal), (10.0, 10.0))
        included, excluded = self.tax_included, self.tax_excluded
        taxes = {code: line.tax_ids for code, line in lines.items()}
        self.assertEqual(taxes, {'SC-COMBO': included, 'SC-ATTR': excluded, 'SC-INCL': included, 'SC-EXCL': excluded})
        self.assertEqual(lines['SC-COMBO'].customer_note, "1 x Large, 1 x Burger (1 x No onion), 2 x Fries")
        self.assertEqual(lines['SC-ATTR'].customer_note, "1 x Extra cheese")

    def test_branch_pos_takes_the_taxes_of_its_own_company_before_the_parents(self):
        branch = self.env['res.company'].create({'name': 'Glovo Branch', 'parent_id': self.company_a.id, 'country_id': self.company_a.country_id.id})
        branch_tax = self.env['account.tax'].create({
            'name': 'Branch 5%',
            'amount': 5,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
            'company_id': branch.id,
            'tax_group_id': self.env['account.tax.group'].create({'name': 'Branch group', 'company_id': branch.id}).id,
        })
        both = self.products['SC-INCL'].copy({'name': 'Scenario both', 'default_code': 'SC-BOTH', 'company_id': False})
        self.env.cr.execute("INSERT INTO product_taxes_rel (prod_id, tax_id) VALUES (%s, %s)", [both.product_tmpl_id.id, branch_tax.id])
        both.invalidate_recordset(['taxes_id'])
        self.assertEqual(both.taxes_id, self.tax_included | branch_tax)
        data = {'products': [glovo_product('SC-BOTH', 1000), glovo_product('SC-EXCL', 1100)]}

        def line_taxes():
            return [line['tax_ids'] for line in self.store._prepare_order_lines_values_from_data(data)]

        self.assertEqual(line_taxes(), [[Command.set(self.tax_included.ids)], [Command.set(self.tax_excluded.ids)]])
        branch_config = self.main_pos_config.copy({'name': 'Branch POS'})
        # SQL: only the config's company matters here; a real branch POS needs its own journals, payment methods and pricelists
        self.env.cr.execute("UPDATE pos_config SET company_id = %s WHERE id = %s", [branch.id, branch_config.id])
        branch_config.invalidate_recordset(['company_id'])
        self.store.config_id = branch_config
        self.assertEqual(line_taxes(), [[Command.set(branch_tax.ids)], [Command.set(self.tax_excluded.ids)]])

    def test_other_company_token_cannot_pay_or_cancel_the_order_of_another_store(self):
        self._open_pos()
        self._notify('dispatched', '8201')
        order = self._glovo_order('8201')
        with mute_logger(EVENT_LOGGER):
            statuses = [self._notify(event_type, '8201', token='token-b').status_code for event_type in ('picked_up', 'cancelled')]
        self.assertEqual(statuses, [200, 200])
        for event in self._events('8201', 'picked_up') | self._events('8201', 'cancelled'):
            self.assertEqual(event.company_id, self.company_b)
            self.assertEqual(self._result(event), ('failed', ANOTHER_STORE % '8201', self.no_order))
        self.assertEqual(self._order_status(order), DRAFT)

        with mute_logger(EVENT_LOGGER):
            self.assertEqual(self._notify('picked_up', '8202', token='token-b').status_code, 200)
        nowhere = self._events('8202')
        self.assertEqual(nowhere.company_id, self.company_b)
        self.assertEqual(self._result(nowhere), ('failed', NO_ORDER % '8202', self.no_order))

    def test_other_company_cannot_reuse_the_event_of_an_existing_order(self):
        self._open_pos()
        self._notify('dispatched', '8211')
        order = self._glovo_order('8211')
        event = self._events('8211')
        with self.assertLogs(CONTROLLER_LOGGER, 'WARNING') as logs:
            self.assertEqual(self._notify('dispatched', '8211', token='token-b').status_code, 200)
        self.assertIn("belongs to another store", logs.output[0])
        self.assertEqual(self._events('8211'), event)
        self.assertEqual((event.company_id, self._result(event)), (self.company_a, (*PROCESSED, order)))
        self.assertFalse(self.env['pos.order'].search([('platform_order_store_id', '=', self.store_b.id)]))

    def test_retry_of_an_event_uses_the_store_of_the_events_own_company(self):
        self._open_pos()
        self._open_pos_b()
        self._notify('dispatched', '8221')
        order = self._glovo_order('8221')
        with mute_logger(EVENT_LOGGER):
            self._notify('picked_up', '8221', token='token-b')
        event_b = self._events('8221', 'picked_up')
        refused = ('failed', ANOTHER_STORE % '8221', self.no_order)
        self.assertEqual((event_b.company_id, self._result(event_b)), (self.company_b, refused))

        with mute_logger(EVENT_LOGGER):
            self.env['glovo.event']._cron_retry_failed_events()
            self.assertEqual(self._result(event_b), refused)
            self._retry_as_manager(event_b)
        self.assertEqual(self._result(event_b), refused)
        self.assertEqual(self._order_status(order), DRAFT)

    def test_manager_retry_of_a_failed_event_binds_to_the_store_of_the_event(self):
        self._open_pos()
        self._notify('dispatched', '8222', products=[glovo_product('SC-NEW', 1000)])
        event = self._events('8222')
        self.assertEqual((event.company_id, event.state), (self.company_a, 'failed'))
        self.unmapped_product.default_code = 'SC-NEW'
        self._retry_as_manager(event)
        order = self._glovo_order('8222')
        self.assertEqual((order.platform_order_store_id, event.order_id, event.state), (self.store, order, 'processed'))

    def test_pending_event_of_another_company_is_not_replayed_onto_the_new_order(self):
        self._open_pos()
        with mute_logger(EVENT_LOGGER):
            self._notify('picked_up', '8231', token='token-b')
        pending = self._events('8231', 'picked_up')
        self.assertEqual((pending.company_id, pending.state), (self.company_b, 'failed'))

        self.assertEqual(self._notify('dispatched', '8231').status_code, 200)
        order = self._glovo_order('8231')
        self.assertEqual(self._order_status(order), DRAFT)
        self.assertEqual(self._result(self._events('8231', 'dispatched')), (*PROCESSED, order))
        self.assertEqual(self._result(pending), ('failed', NO_ORDER % '8231', self.no_order))

    def test_notification_of_another_store_of_the_same_company_cannot_pay_or_cancel(self):
        self._open_pos()
        self._notify('dispatched', '8241')
        order = self._glovo_order('8241')
        with mute_logger(EVENT_LOGGER):
            statuses = [self._notify(event_type, '8241', store_id='LOCK-STORE-2').status_code for event_type in ('picked_up', 'cancelled')]
        self.assertEqual(statuses, [200, 200])
        for event in self._events('8241', 'picked_up') | self._events('8241', 'cancelled'):
            self.assertEqual(event.store_external_id, 'LOCK-STORE-2')
            self.assertEqual(self._result(event), ('failed', ANOTHER_STORE % '8241', self.no_order))
        self.assertEqual(self._order_status(order), DRAFT)

        with self.assertLogs(CONTROLLER_LOGGER, 'WARNING'):
            self.assertEqual(self._notify('dispatched', '8241', store_id='LOCK-STORE-2').status_code, 200)
        self.assertEqual(self._events('8241', 'dispatched').store_external_id, 'LOCK-STORE')
        self.assertEqual(len(self._events('8241', 'dispatched')), 1)

    def test_same_token_in_two_companies_uses_the_store_of_the_enabled_provider(self):
        self._open_pos()
        self.provider_b.write({'glovo_token': 'lock-token', 'state': 'disabled'})
        with self.assertLogs(CONTROLLER_LOGGER, 'ERROR') as logs:
            self.assertEqual(self._notify('dispatched', '8251').status_code, 200)
        self.assertIn("LOCK-STORE", logs.output[0])
        event = self._events('8251')
        self.assertEqual(event.company_id, self.company_a)
        self.assertEqual(self._result(event), (*PROCESSED, self._glovo_order('8251')))

        self.provider_b.state = 'test'
        self.provider.state = 'disabled'
        with self.assertLogs(CONTROLLER_LOGGER, 'ERROR'):
            self.assertEqual(self._notify('dispatched', '8252').status_code, 200)
        event = self._events('8252')
        self.assertEqual((event.company_id, event.state), (self.company_b, 'failed'))
        self.assertFalse(self._glovo_order('8252'))

    def test_closing_the_session_names_the_glovo_order_to_resolve(self):
        self._open_pos()
        self._notify('dispatched', '8301')
        message = self.main_pos_config.current_session_id.with_user(self.pos_user).close_session_from_ui().get('message')
        self.assertIn("Ask a POS manager to resolve Glovo order 8301.", message)
        self.assertEqual(self._glovo_order('8301').state, 'draft')

    def test_manager_resolves_an_order_without_glovo_and_a_cashier_cannot(self):
        self._open_pos()
        self._notify('dispatched', '8311')
        self._notify('dispatched', '8312')
        picked_up, cancelled = self._glovo_order('8311'), self._glovo_order('8312')
        with self.assertRaises(AccessError):
            self._resolve(picked_up, 'delivered', 'Cashier tries', user=self.pos_user)

        self._resolve(picked_up, 'delivered', 'Courier collected it').action_confirm()
        self.assertEqual(self._order_status(picked_up), ('paid', 'delivered', 1))
        self.assertIn("Marked picked up by a manager. Reason: Courier collected it", self._chatter(picked_up))

        self._resolve(cancelled, 'cancelled', 'Glovo phoned').action_confirm()
        self.assertEqual(self._order_status(cancelled), ('cancel', 'cancelled', 0))
        self.assertEqual(cancelled.platform_order_cancel_reason, 'Glovo phoned')

    def test_cleanup_deletes_old_events_of_every_state_and_keeps_the_pos_order(self):
        self._open_pos()
        self._notify('dispatched', '8401')
        self._notify('picked_up', '8401')
        with mute_logger(EVENT_LOGGER):
            self._notify('cancelled', '8401')
        order = self._glovo_order('8401')
        dispatched, picked_up, cancelled = (self._events('8401', event_type) for event_type in ('dispatched', 'picked_up', 'cancelled'))
        self.assertEqual([event.state for event in dispatched | picked_up | cancelled], ['processed', 'processed', 'failed'])

        self._age(dispatched | cancelled, 100)
        self.env['glovo.event']._gc_processed_events()
        self.assertFalse((dispatched | cancelled).exists())
        self.assertEqual(picked_up.exists().order_id, order)
        self.assertEqual(order.exists().state, 'paid')

        self._age(picked_up, 400)
        self.env['ir.config_parameter'].set_int('glovo_base.event_retention_days', 0)
        self.env['glovo.event']._gc_processed_events()
        self.assertTrue(picked_up.exists())
