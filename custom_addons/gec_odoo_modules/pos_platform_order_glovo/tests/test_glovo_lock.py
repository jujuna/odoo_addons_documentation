from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.glovo_base.utils.glovo_client import GlovoClient
from odoo.addons.pos_platform_order_glovo.tests.common import TestGlovoCommon

LOCK_MSG = "Glovo orders can't be changed or paid in the POS"


@tagged('post_install', '-at_install')
class TestGlovoLock(TestGlovoCommon):

    def _sync(self, order, **vals):
        data = {
            'uuid': order.uuid, 'session_id': order.session_id.id, 'state': 'draft', 'lines': [], 'payment_ids': [],
            'amount_total': order.amount_total, 'amount_tax': order.amount_tax, 'amount_paid': 0, 'amount_return': 0,
            **vals,
        }
        return self.env['pos.order'].with_user(self.pos_user).sync_from_ui([data])

    def _try(self, label, call, message=LOCK_MSG):
        """Run call in a savepoint; return 'refused' (expected message), 'allowed' or the other error."""
        try:
            with self.env.cr.savepoint():
                call()
            return 'allowed'
        except UserError as error:
            return 'refused' if message in str(error) else f'{label}: other error: {error}'

    def test_glovo_sync_batch_tour(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self._webhook('dispatched', '7101')
        self._webhook('dispatched', '7102')
        self._webhook('picked_up', '7102')
        glovo = self._glovo_order('7101')
        before = glovo.lines.read(['product_id', 'qty', 'price_unit', 'discount'])
        logger = 'odoo.addons.pos_platform_order_glovo.models.pos_order'
        with self.assertLogs(logger, 'WARNING') as logs:
            self.start_pos_tour('glovo_sync_batch_tour', login='pos_user')
        self.env.invalidate_all()
        after = glovo.lines.read(['product_id', 'qty', 'price_unit', 'discount'])
        normal = self.env['pos.order'].search([
            ('session_id', '=', glovo.session_id.id), ('platform_order_store_id', '=', False), ('state', '=', 'paid'),
        ])
        warnings = [line for line in logs.output if '7101' in line]
        self.assertEqual((glovo.state, len(glovo.payment_ids)), ('draft', 0))
        self.assertEqual(after, before)
        self.assertEqual(len(normal), 1)
        self.assertIn(len(warnings), (1, 2))

    def test_glovo_refund_and_payment_delete(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        session = self.main_pos_config.current_session_id
        self._webhook('dispatched', '7201')
        self._webhook('picked_up', '7201')
        paid = self._glovo_order('7201')
        line = paid.lines[:1]
        refund_msg = "Only a POS manager can refund a Glovo order or delete its payments."
        self.assertEqual((paid.state, len(paid.payment_ids)), ('paid', 1))
        refund_order = {
            'uuid': '00000000-0000-4000-8000-000000007201', 'session_id': session.id, 'state': 'draft', 'is_refund': True,
            'lines': [Command.create({
                'product_id': line.product_id.id, 'qty': -line.qty, 'price_unit': line.price_unit,
                'price_subtotal': -line.price_subtotal, 'price_subtotal_incl': -line.price_subtotal_incl,
                'full_product_name': line.full_product_name, 'refunded_orderline_id': line.id,
            })],
            'payment_ids': [], 'amount_total': -paid.amount_total, 'amount_tax': -paid.amount_tax,
            'amount_paid': 0, 'amount_return': 0,
        }
        results = {
            'cashier refund (backend Return Products)': self._try(
                'cashier refund (backend Return Products)', lambda: paid.with_user(self.pos_user).refund(), refund_msg),
            'cashier refund (POS sync_from_ui)': self._try(
                'cashier refund (POS sync_from_ui)', lambda: self.env['pos.order'].with_user(self.pos_user).sync_from_ui([dict(refund_order)]), refund_msg),
            'cashier payment delete': self._try(
                'cashier payment delete', lambda: paid.payment_ids.with_user(self.pos_user).unlink(), refund_msg),
        }
        manager_refund = self._try('manager refund (backend Return Products)', lambda: paid.with_user(self.pos_admin).refund(), refund_msg)
        refunds = self.env['pos.order'].search([('lines.refunded_orderline_id', 'in', paid.lines.ids)])
        manager_delete = self._try('manager payment delete', lambda: paid.payment_ids.with_user(self.pos_admin).unlink(), refund_msg)
        self.assertTrue(all(result == 'refused' for result in results.values()), results)
        self.assertEqual((manager_refund, manager_delete), ('allowed', 'allowed'))
        self.assertEqual(len(refunds), 1)
        self.assertEqual(refunds.lines.mapped('qty'), [-2.0])
        self.assertFalse(paid.payment_ids)

    def test_glovo_pos_hr_manager_check(self):
        """pos_hr: on a manager-user device, the logged-in employee's role decides (context current_cashier_id)."""
        if 'manager_employee_ids' not in self.env['pos.config']._fields:
            self.skipTest("pos_hr not installed")
        basic = self.env['hr.employee'].sudo().create({'name': 'Glovo Basic Employee', 'company_id': self.env.company.id})
        manager = self.env['hr.employee'].sudo().create({'name': 'Glovo Manager Employee', 'company_id': self.env.company.id})
        self.main_pos_config.sudo().write({
            'module_pos_hr': True, 'cashier_employee_ids': [Command.set(basic.ids)],
            'manager_employee_ids': [Command.set(manager.ids)],
        })
        self.main_pos_config.with_user(self.pos_admin).open_ui()
        session = self.main_pos_config.current_session_id
        self._webhook('dispatched', '7401')
        self._webhook('picked_up', '7401')
        paid = self._glovo_order('7401')
        line = paid.lines[:1]
        refund_msg = "Only a POS manager can refund a Glovo order or delete its payments."
        self.assertEqual(len(paid.payment_ids), 1)
        self.assertTrue(self.pos_admin.has_group('point_of_sale.group_pos_manager'))

        def refund(uuid, employee):
            data = {
                'uuid': uuid, 'session_id': session.id, 'state': 'draft', 'is_refund': True, 'employee_id': employee.id,
                'lines': [Command.create({
                    'product_id': line.product_id.id, 'qty': -1, 'price_unit': line.price_unit,
                    'price_subtotal': -line.price_unit, 'price_subtotal_incl': -line.price_unit,
                    'full_product_name': line.full_product_name, 'refunded_orderline_id': line.id,
                })],
                'payment_ids': [], 'amount_total': -line.price_unit, 'amount_tax': 0, 'amount_paid': 0, 'amount_return': 0,
            }
            return lambda: self.env['pos.order'].with_user(self.pos_admin).with_context(current_cashier_id=employee.id).sync_from_ui([data])

        def delete_payments(employee):
            return lambda: paid.payment_ids.with_user(self.pos_admin).with_context(current_cashier_id=employee.id).unlink()

        class RolledBack(Exception):
            pass

        def without_pos_hr_login():
            """Config without employee login: current_cashier_id is ignored, the manager user passes. Rolled back."""
            try:
                with self.env.cr.savepoint():
                    self.main_pos_config.module_pos_hr = False
                    delete_payments(basic)()
                    self.assertFalse(paid.payment_ids)
                    raise RolledBack
            except RolledBack:
                return 'allowed'
            except UserError as error:
                return 'refused' if refund_msg in str(error) else f'other error: {error}'
            finally:
                self.env.invalidate_all()

        results = {
            'basic employee refund (manager-user device)': self._try('POSHR basic employee refund', refund('00000000-0000-4000-8000-000000007401', basic), refund_msg),
            'basic employee payment delete (manager-user device)': self._try('POSHR basic employee payment delete', delete_payments(basic), refund_msg),
            'manager employee refund': self._try('POSHR manager employee refund', refund('00000000-0000-4000-8000-000000007402', manager), refund_msg),
        }
        user_check = without_pos_hr_login()
        self.assertEqual((len(paid.payment_ids), self.main_pos_config.module_pos_hr), (1, True))
        results['manager employee payment delete'] = self._try('POSHR manager employee payment delete', delete_payments(manager), refund_msg)
        refunds = self.env['pos.order'].search([('lines.refunded_orderline_id', 'in', paid.lines.ids)])
        self.assertEqual(list(results.values()), ['refused', 'refused', 'allowed', 'allowed'], results)
        self.assertEqual(refunds.employee_id, manager)
        self.assertEqual(user_check, 'allowed')
        self.assertFalse(paid.payment_ids)

    def test_glovo_sync_batch_server(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        session = self.main_pos_config.current_session_id
        self._webhook('dispatched', '7301')
        glovo = self._glovo_order('7301')
        line = glovo.lines[:1]
        before = glovo.lines.read(['product_id', 'qty', 'price_unit', 'discount'])
        pen = self.whiteboard_pen.product_variant_id
        glovo_changed = {
            'uuid': glovo.uuid, 'session_id': session.id, 'state': 'paid', 'partner_id': self.partner_a.id,
            'lines': [Command.update(line.id, {'qty': 5}), Command.create({
                'product_id': pen.id, 'qty': 1, 'price_unit': 5, 'price_subtotal': 5, 'price_subtotal_incl': 5,
                'full_product_name': pen.name})],
            'payment_ids': [Command.create({'payment_method_id': self.cash.id, 'amount': 55})],
            'amount_total': 55, 'amount_tax': 0, 'amount_paid': 55, 'amount_return': 0,
        }
        normal_new = {
            'uuid': '00000000-0000-4000-8000-000000007301', 'session_id': session.id, 'state': 'paid',
            'lines': [Command.create({
                'product_id': pen.id, 'qty': 1, 'price_unit': 5, 'price_subtotal': 5, 'price_subtotal_incl': 5,
                'full_product_name': pen.name})],
            'payment_ids': [Command.create({'payment_method_id': self.cash.id, 'amount': 5})],
            'amount_total': 5, 'amount_tax': 0, 'amount_paid': 5, 'amount_return': 0,
        }
        logger = 'odoo.addons.pos_platform_order_glovo.models.pos_order'
        with self.assertLogs(logger, 'WARNING') as logs:
            result = self.env['pos.order'].with_user(self.pos_user).sync_from_ui([glovo_changed, normal_new])
        normal = self.env['pos.order'].search([('uuid', '=', normal_new['uuid'])])
        returned = {o['uuid']: o['state'] for o in result['pos.order']}
        self.assertEqual(returned, {glovo.uuid: 'draft', normal_new['uuid']: 'paid'})
        self.assertEqual(len([line for line in logs.output if '7301' in line]), 1)
        self.assertEqual((glovo.state, len(glovo.payment_ids), glovo.partner_id.id), ('draft', 0, False))
        self.assertEqual(glovo.lines.read(['product_id', 'qty', 'price_unit', 'discount']), before)
        self.assertEqual(normal.state, 'paid')

    def test_glovo_lock_tour(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self._webhook('dispatched', '7001')
        glovo = self._glovo_order('7001')
        before = glovo.lines.read(['product_id', 'qty', 'price_unit', 'discount'])

        with patch.object(GlovoClient, 'ready_for_pickup', return_value=None) as ready:
            self.start_pos_tour('glovo_lock_tour', login='pos_user')

        self.env.invalidate_all()
        normal = self.env['pos.order'].search([
            ('session_id', '=', glovo.session_id.id), ('platform_order_store_id', '=', False), ('state', '=', 'paid'),
        ])
        after = glovo.lines.read(['product_id', 'qty', 'price_unit', 'discount'])
        self.assertEqual((glovo.state, glovo.platform_order_status), ('draft', 'accepted'))
        self.assertTrue(glovo.platform_order_food_ready)
        self.assertEqual(ready.call_count, 1)
        self.assertFalse(glovo.payment_ids)
        self.assertEqual(after, before)
        self.assertEqual(len(normal), 1)
        self.assertEqual(normal.payment_ids.payment_method_id.mapped('type'), ['cash'])

    def test_glovo_lock_server(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        session = self.main_pos_config.current_session_id
        self._webhook('dispatched', '7002')
        glovo = self._glovo_order('7002')
        line = glovo.lines[:1]
        other = self.whiteboard_pen.product_variant_id
        new_line = {'product_id': other.id, 'qty': 1, 'price_unit': 5, 'price_subtotal': 5, 'price_subtotal_incl': 5,
                    'full_product_name': other.name}

        def as_cashier(records):
            return records.with_user(self.pos_user)

        before = glovo.lines.read(['product_id', 'qty', 'price_unit', 'discount'])
        fiscal_before = glovo.fiscal_position_id.id
        fiscal_position = self.env['account.fiscal.position'].create({'name': 'Glovo Sync Position'})
        kept = {
            'sync_from_ui change fiscal position': lambda: self._sync(glovo, fiscal_position_id=fiscal_position.id),
            'sync_from_ui add line': lambda: self._sync(glovo, lines=[Command.create(new_line)]),
            'sync_from_ui change qty': lambda: self._sync(glovo, lines=[Command.update(line.id, {'qty': 5})]),
            'sync_from_ui remove line': lambda: self._sync(glovo, lines=[Command.delete(line.id)]),
            'sync_from_ui change customer': lambda: self._sync(glovo, partner_id=self.partner_a.id),
            'sync_from_ui pay cash': lambda: self._sync(glovo, state='paid', amount_paid=glovo.amount_total, payment_ids=[
                Command.create({'payment_method_id': self.cash.id, 'amount': glovo.amount_total})]),
            'sync_from_ui cancel': lambda: self._sync(glovo, state='cancel'),
        }
        kept_results = {}
        for label, call in kept.items():
            kept_results[label] = self._try(label, call)
            self.env.invalidate_all()
            state = (glovo.state, glovo.partner_id.id, len(glovo.payment_ids), glovo.fiscal_position_id.id)
            lines = glovo.lines.read(['product_id', 'qty', 'price_unit', 'discount'])
            kept_results[label] = (kept_results[label], state == ('draft', False, 0, fiscal_before) and lines == before)
        refused = {
            'line create': lambda: as_cashier(self.env['pos.order.line']).create({**new_line, 'order_id': glovo.id}),
            'line write qty': lambda: as_cashier(line).write({'qty': 5}),
            'line write price_unit': lambda: as_cashier(line).write({'price_unit': 1}),
            'line write discount': lambda: as_cashier(line).write({'discount': 50}),
            'line unlink': lambda: as_cashier(line).unlink(),
            'payment create': lambda: as_cashier(self.env['pos.payment']).create({
                'pos_order_id': glovo.id, 'payment_method_id': self.cash.id, 'amount': 1}),
            'order write customer': lambda: as_cashier(glovo).write({'partner_id': self.partner_a.id}),
        }
        results = {label: self._try(label, call) for label, call in refused.items()}
        unchanged = self._try('sync_from_ui resend unchanged values', lambda: self._sync(glovo, partner_id=False, lines=[
            Command.update(line.id, {'product_id': line.product_id.id, 'qty': line.qty, 'price_unit': line.price_unit,
                                     'discount': line.discount})]))

        normal = as_cashier(self.env['pos.order']).create({
            'session_id': session.id, 'amount_tax': 0, 'amount_total': 0, 'amount_paid': 0, 'amount_return': 0})
        normal_results = {
            'normal line create': self._try('normal line create', lambda: as_cashier(self.env['pos.order.line']).create({**new_line, 'order_id': normal.id})),
            'normal line write qty': self._try('normal line write qty', lambda: as_cashier(normal.lines).write({'qty': 3})),
            'normal payment create': self._try('normal payment create', lambda: as_cashier(self.env['pos.payment']).create({
                'pos_order_id': normal.id, 'payment_method_id': self.cash.id, 'amount': 1})),
            'normal write customer': self._try('normal write customer', lambda: as_cashier(normal).write({'partner_id': self.partner_a.id})),
        }

        close_message = "Ask a POS manager to resolve Glovo order 7002."
        self.assertIn(close_message, session.with_user(self.pos_user).close_session_from_ui().get('message'))

        wizard = self.env['pos.glovo.order.resolve'].with_user(self.pos_admin).with_context(
            active_model='pos.order', active_ids=glovo.ids, default_resolution='delivered',
        ).create({'reason': 'Courier collected, no webhook'})
        wizard.action_confirm()
        already_paid = (200, 'failed', "Order already paid in Odoo; check it manually")
        self.assertEqual(self._webhook('picked_up', '7002'), already_paid)

        self._webhook('dispatched', '7003')
        paid = self._glovo_order('7003')
        paid.sudo().add_payment({'pos_order_id': paid.id, 'payment_method_id': self.cash.id, 'amount': paid.amount_total})
        paid.sudo().action_pos_order_paid()
        self.assertEqual(self._webhook('picked_up', '7003'), already_paid)

        self._webhook('dispatched', '7004')
        unpaid = self._glovo_order('7004')
        self.assertEqual(self._webhook('picked_up', '7004'), (200, 'processed', False))
        self.assertEqual(unpaid.payment_ids.payment_method_id, self.store.payment_method_id)

        self.assertTrue(all(result == 'refused' for result in results.values()), results)
        self.assertTrue(all(result == ('allowed', True) for result in kept_results.values()), kept_results)
        self.assertEqual(unchanged, 'allowed')
        self.assertTrue(all(result == 'allowed' for result in normal_results.values()), normal_results)
        self.assertEqual((glovo.state, len(glovo.payment_ids)), ('paid', 1))
        self.assertEqual((paid.state, len(paid.payment_ids)), ('paid', 1))
        self.assertEqual((unpaid.state, unpaid.platform_order_status, len(unpaid.payment_ids)), ('paid', 'delivered', 1))
