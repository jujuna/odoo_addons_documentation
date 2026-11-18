from unittest.mock import patch

import psycopg2

from odoo.exceptions import AccessError, UserError
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.glovo_base.utils.glovo_client import GlovoClient
from odoo.addons.pos_platform_order_glovo.tests.common import TestGlovoCommon
from odoo.addons.pos_platform_order_glovo.tests.test_glovo_retry_payment import MISSING_PRODUCT

LOCK_MSG = "Glovo orders can't be changed or paid in the POS"


@tagged('post_install', '-at_install')
class TestGlovoFixes(TestGlovoCommon):

    def setUp(self):
        super().setUp()
        self.main_pos_config.with_user(self.pos_user).open_ui()

    def test_resolve_wizard_is_manager_only(self):
        self._webhook('dispatched', '8001')
        order = self._glovo_order('8001')
        resolve = self.env['pos.glovo.order.resolve'].with_context(
            active_model='pos.order', active_ids=order.ids, default_resolution='delivered', default_reason='x')
        with self.assertRaises(AccessError):
            resolve.with_user(self.pos_user).create({})
        resolve.with_user(self.pos_admin).create({}).action_confirm()
        self.assertEqual((order.state, order.platform_order_status), ('paid', 'delivered'))

    def test_cancel_cannot_be_bypassed(self):
        self._webhook('dispatched', '8002')
        order = self._glovo_order('8002')
        with self.assertRaises(UserError):
            order.with_user(self.pos_user).write({'platform_order_status': 'cancelled'})
        with self.assertRaises(UserError):
            order.with_user(self.pos_user).write({'state': 'cancel'})
        with self.assertRaises(UserError):
            order.with_user(self.pos_user).write({'state': 'paid'})
        self.assertEqual((order.state, order.platform_order_status), ('draft', 'accepted'))

    def test_cancelled_webhook_cancels_order(self):
        self._webhook('dispatched', '8003')
        self.assertEqual(self._webhook('cancelled', '8003', cancel_reason='USER_ERROR')[:2], (200, 'processed'))
        order = self._glovo_order('8003')
        self.assertEqual(
            (order.state, order.platform_order_status, order.platform_order_cancel_reason),
            ('cancel', 'cancelled', 'USER_ERROR'),
        )

    def test_total_mismatch_is_noted(self):
        status, state, error = self._webhook('dispatched', '8004', partner_discounted_products_total=1500)
        self.assertEqual((status, state), (200, 'processed'))
        self.assertIn("differs from Glovo total after product discounts", error)
        self.assertIn("15.00", error)

    def test_pickup_order_food_ready_calls_glovo(self):
        self._webhook('dispatched', '8005', is_picked_up_by_customer=True)
        order = self._glovo_order('8005')
        self.assertEqual(order.platform_order_type, 'pickup')
        with patch.object(GlovoClient, 'ready_for_pickup', return_value=None) as ready:
            self.assertTrue(order.platform_order_status_update_from_ui('food_ready')['success'])
        ready.assert_called_once_with('8005', 'LOCK-STORE')
        self.assertTrue(order.platform_order_food_ready)

    def test_cash_order_books_the_cash_method(self):
        cash = self.main_pos_config._get_cash_payment_method()
        if not cash:
            journal = self.env['account.journal'].create({
                'name': 'Glovo Cash', 'type': 'cash', 'code': 'GLVC', 'company_id': self.env.company.id,
            })
            cash = self.env['pos.payment.method'].create(
                {'name': 'Glovo Cash', 'type': 'cash', 'journal_id': journal.id})
            self.main_pos_config.payment_method_ids = [Command.link(cash.id)]
        self._webhook('dispatched', '8006', payment_method='CASH')
        self.assertEqual(self._webhook('picked_up', '8006')[1], 'processed')
        order = self._glovo_order('8006')
        self.assertEqual((order.state, len(order.payment_ids)), ('paid', 1))
        self.assertEqual(order.payment_ids.payment_method_id, cash)
        self.assertNotEqual(order.payment_ids.payment_method_id, self.store.payment_method_id)

    def test_cash_order_without_cash_method_fails_with_a_clear_error(self):
        self._webhook('dispatched', '8008', payment_method='CASH')
        no_cash = patch.object(type(self.main_pos_config), '_get_cash_payment_method', return_value=self.cash.browse())
        with no_cash:
            status, state, error = self._webhook('picked_up', '8008')
        self.assertEqual((status, state), (200, 'failed'))
        self.assertIn("Add a cash payment method to", error)
        self.assertFalse(self._glovo_order('8008').payment_ids)

    def test_late_picked_up_is_replayed_by_dispatched(self):
        self.assertEqual(self._webhook('picked_up', '8007')[1], 'failed')
        self.assertFalse(self._glovo_order('8007'))
        self._webhook('dispatched', '8007')
        order = self._glovo_order('8007')
        picked_up = self.env['glovo.event'].search([('glovo_order_id', '=', '8007'), ('event_type', '=', 'picked_up')])
        self.assertEqual(
            (order.state, order.platform_order_status, picked_up.state), ('paid', 'delivered', 'processed'))

    def _events(self, order_id):
        return self.env['glovo.event'].search([('glovo_order_id', '=', order_id)], order='id')

    def test_retry_of_events_that_arrived_out_of_order(self):
        self.assertEqual(self._webhook('picked_up', '9101')[1], 'failed')
        self.assertEqual(self._webhook('dispatched', '9101', **MISSING_PRODUCT)[1], 'failed')
        self.whiteboard_pen.product_variant_id.default_code = 'LOCK-P9'
        events = self._events('9101')
        events.with_user(self.pos_admin).action_retry()
        order = self._glovo_order('9101')
        self.assertEqual((order.state, len(order.payment_ids)), ('paid', 1))
        self.assertEqual(events.mapped('state'), ['processed', 'processed'])

    def test_retry_skips_event_the_dispatched_replay_processed(self):
        self.assertEqual(self._webhook('dispatched', '9102', **MISSING_PRODUCT)[1], 'failed')
        self.assertEqual(self._webhook('picked_up', '9102')[1], 'failed')
        self.whiteboard_pen.product_variant_id.default_code = 'LOCK-P9'
        events = self._events('9102')
        events.with_user(self.pos_admin).action_retry()
        order = self._glovo_order('9102')
        self.assertEqual((order.state, len(order.payment_ids)), ('paid', 1))
        self.assertEqual(events.mapped('state'), ['processed', 'processed'])

    def test_replay_applies_pending_events_in_arrival_order(self):
        self.assertEqual(self._webhook('picked_up', '9103')[1], 'failed')
        self.assertEqual(self._webhook('cancelled', '9103', cancel_reason='USER_ERROR')[1], 'failed')
        self.assertEqual(self._webhook('dispatched', '9103')[1], 'processed')
        order = self._glovo_order('9103')
        states = {event.event_type: event.state for event in self._events('9103')}
        self.assertEqual((order.state, order.platform_order_status), ('paid', 'delivered'))
        self.assertEqual(states, {'picked_up': 'processed', 'cancelled': 'failed', 'dispatched': 'processed'})

    def test_payment_uses_the_total_of_the_locked_lines(self):
        self._webhook('dispatched', '9104')
        order = self._glovo_order('9104')
        order.sudo().write({'amount_total': 1.0})
        self.assertEqual(self._webhook('picked_up', '9104')[1], 'processed')
        self.assertAlmostEqual(order.payment_ids.amount, sum(order.lines.mapped('price_subtotal_incl')), places=2)
        self.assertNotEqual(order.payment_ids.amount, 1.0)
        self.assertEqual(order.payment_ids.amount, order.amount_total)

    def test_tax_and_fiscal_position_are_locked(self):
        self._webhook('dispatched', '9105')
        order = self._glovo_order('9105')
        tax = self.env['account.tax'].create({'name': 'Glovo Lock Tax', 'amount': 5})
        fiscal_position = self.env['account.fiscal.position'].create({'name': 'Glovo Lock Position'})
        with self.assertRaisesRegex(UserError, LOCK_MSG):
            order.lines.with_user(self.pos_user).write({'tax_ids': [Command.set(tax.ids)]})
        with self.assertRaisesRegex(UserError, LOCK_MSG):
            order.with_user(self.pos_user).write({'fiscal_position_id': fiscal_position.id})
        with self.assertRaisesRegex(UserError, LOCK_MSG):
            order.lines.with_user(self.pos_user).write({'extra_tax_data': {'manual_tax_amounts': {}}})

    def test_concurrency_error_is_raised_for_a_request_retry(self):
        self._webhook('dispatched', '9106')
        event = self._events('9106').sudo()
        event.state = 'failed'
        failure = patch.object(type(event), '_apply_notification', side_effect=psycopg2.errors.SerializationFailure)
        # without the re-raise the broad except stores it on the event and nothing reaches Odoo's request retry
        with failure, self.assertRaises(psycopg2.errors.SerializationFailure):
            event._process_notification(self.store.sudo(), {})


@tagged('post_install', '-at_install')
class TestGlovoRetryCron(TestGlovoCommon):

    def setUp(self):
        super().setUp()
        # the cron commits after each event; a test cursor refuses commits
        self.startPatcher(patch.object(self.env.registry['ir.cron'], '_commit_progress', return_value=1.0))

    def _failed_event(self, order_id):
        """A dispatched event that failed because no POS session was open."""
        self.assertEqual(self._webhook('dispatched', order_id)[1], 'failed')
        return self.env['glovo.event'].search([('glovo_order_id', '=', order_id), ('event_type', '=', 'dispatched')])

    def test_cron_retries_once_a_session_is_open(self):
        event = self._failed_event('9201')
        self.env['glovo.event']._cron_retry_failed_events()
        self.assertEqual(event.state, 'failed')
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self.env['glovo.event']._cron_retry_failed_events()
        self.assertEqual(event.state, 'processed')
        self.assertTrue(self._glovo_order('9201'))

    def test_cron_skips_events_older_than_the_window(self):
        event = self._failed_event('9202')
        self.env.cr.execute("UPDATE glovo_event SET create_date = now() - interval '2 days' WHERE id = %s", [event.id])
        event.invalidate_recordset(['create_date'])
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self.env['glovo.event']._cron_retry_failed_events()
        self.assertEqual(event.state, 'failed')
        self.assertFalse(self._glovo_order('9202'))

    def test_cron_skips_stores_of_a_disabled_provider(self):
        event = self._failed_event('9203')
        self.provider.state = 'disabled'
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self.env['glovo.event']._cron_retry_failed_events()
        self.assertEqual((event.state, event.error), ('failed', "No open POS session."))
        self.assertFalse(self._glovo_order('9203'))
