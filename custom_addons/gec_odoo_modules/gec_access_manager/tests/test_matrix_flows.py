# Business flows of the core apps run twice, by a user with the needed Odoo groups and no profile and by the same kind
# of user carrying the profile under test: a profile that allows a flow must leave its numbers untouched, one that
# refuses a step must refuse it with an access error and leave nothing half done.
from contextlib import contextmanager, nullcontext
from unittest import SkipTest

from lxml import etree

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, HttpCase, TransactionCase, new_test_user, tagged

# the Accounting app: enterprise moves the menus of account under its own root
ACCOUNTING = ('accountant.menu_accounting', 'account.menu_finance')


class Undone(Exception):
    """ Raised at the end of FlowCase._undone to roll the savepoint back. """


class FlowRefused(Exception):
    """ A step of a flow was refused: which one, and the error the user got. """

    def __init__(self, step, error):
        super().__init__(f"refused at step {step!r}: {type(error).__name__}: {error}")
        self.step = step
        self.error = error


class Flow:
    """ A business flow done step by step as ``user``. Each step runs in a savepoint, like the transaction of one
    client call: a refused step leaves nothing behind. ``trace`` lists (step, numbers) of the steps done. """

    steps = ()

    def __init__(self, case, user):
        self.case = case
        self.user = user
        self.env = case.env(user=user)
        self.trace = []

    def run(self, until=None):
        for name in self.steps:
            try:
                with self.atomic():
                    getattr(self, f'step_{name}')()
            except (AccessError, UserError) as error:
                raise FlowRefused(name, error) from error
            self.trace.append((name, self.numbers()))
            if name == until:
                break
        return self

    def atomic(self):
        return self.case.env.cr.savepoint()

    def numbers(self):
        raise NotImplementedError

    def counts(self):
        raise NotImplementedError

    def left_behind(self):
        """ What the flow added to the database since it was built. """
        now = self.counts()
        return {key: now[key] - self.start[key] for key in now}

    def validate(self, picking):
        for move in picking.move_ids:
            move.write({'quantity': move.product_uom_qty, 'picked': True})
        if picking.button_validate() is not True:
            raise AssertionError("the transfer asked for a wizard")

    def onhand(self, product, location):
        quants = self.case.env['stock.quant'].search([('product_id', '=', product.id), ('location_id', '=', location.id)])
        return sum(quants.mapped('quantity'))


@tagged('post_install', '-at_install', 'gec_matrix')
class FlowCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env['gec.access.profile']
        cls.company = cls.env.company

    @classmethod
    def _need(cls, *models):
        for model_name in models:
            if model_name not in cls.env:
                raise SkipTest(f"{model_name} is not installed")

    @classmethod
    def _need_field(cls, model_name, field_name):
        if field_name not in cls.env[model_name]._fields:
            raise SkipTest(f"{model_name}.{field_name} is not there: its module is not installed")

    @classmethod
    def _user(cls, login, *groups):
        """ A user with the groups that exist: the quality manager is only there when Quality is installed, and
        the receipts of this database carry quality points that only a quality manager may skip. """
        found = [xmlid for xmlid in groups if cls.env.ref(xmlid, raise_if_not_found=False)]
        return new_test_user(cls.env, f'mx_flows_{login}', groups=','.join(found), password=f'mx-flows-{login}')

    @classmethod
    def _employee_of(cls, user, **values):
        """ A free demo employee of the company, taken over by ``user``: hr.employee cannot be created on this
        database while geo_payroll's _recompute_payslips asks for dates that Odoo's own call does not give. """
        employee = cls.env['hr.employee'].search([
            ('company_id', '=', cls.company.id), ('user_id', '=', False)], limit=1)
        employee.write(dict(values, user_id=user.id, work_contact_id=user.partner_id.id))
        return employee

    def _profile(self, users, **values):
        return self.Profile.create({
            'name': values.pop('name', 'MX Flow Profile'), 'user_ids': [Command.set(users.ids)], **values})

    def _line(self, profile, model_name, **values):
        return self.env['gec.access.profile.model'].create({
            'profile_id': profile.id, 'model_id': self.env['ir.model']._get(model_name).id, **values})

    def _template(self, key, users, app=None, name=None):
        wizard = self.env['gec.access.template.wizard'].create({
            'template_key': key, 'name': name or f'MX {key}', 'user_ids': [Command.set(users.ids)],
            'app_id': app.id if app else False})
        return self.Profile.browse(wizard.action_create()['res_id'])

    @classmethod
    def _neutral_models(cls):
        """ The models of the registry holding records, bar the framework's own: the flow touches a subset. """
        names = [model.model for model in cls.env['ir.model'].search([('transient', '=', False)])
                 if model.model in cls.env and cls.env[model.model]._auto and not cls.env[model.model]._abstract
                 and not model.model.startswith(('ir.', 'gec.', 'bus.', 'base'))]
        return names + ['ir.attachment', 'ir.sequence']

    def _neutral(self, users):
        """ A profile with a filter that keeps every record, on every model the flows can touch. """
        profile = self._profile(users)
        self.env['gec.access.profile.model'].create([{
            'profile_id': profile.id, 'model_id': self.env['ir.model']._get(name).id,
            'domain': "[('id', '!=', False)]"} for name in self._neutral_models()])
        self.assertGreater(len(profile.model_ids), 300)
        return profile

    @classmethod
    def _products(cls):
        values = {'type': 'consu', 'list_price': 100.0, 'standard_price': 40.0}
        if 'sale.order' in cls.env:
            values['invoice_policy'] = 'delivery'
        cls.storable = cls.env['product.product'].create(
            dict(values, name='MX Flow Storable', default_code='MXFS', is_storable=True))
        cls.consumable = cls.env['product.product'].create(
            dict(values, name='MX Flow Consumable', default_code='MXFC', is_storable=False, list_price=50.0,
                 standard_price=20.0))

    def _menu(self, xmlid):
        xmlids = (xmlid,) if isinstance(xmlid, str) else xmlid
        return next(filter(None, (self.env.ref(xmlid, raise_if_not_found=False) for xmlid in xmlids)),
                    self.env['ir.ui.menu'])

    def _refused(self, user, records, operation):
        with self.assertRaises(AccessError):
            records.with_user(user).check_access(operation)

    @contextmanager
    def _undone(self):
        """ What is done inside is rolled back at the end: the next round starts from the same database. """
        try:
            with self.env.cr.savepoint():
                yield
                raise Undone()
        except Undone:
            pass

    def _nothing_left(self, flow):
        left = flow.left_behind()
        self.assertEqual(left, dict.fromkeys(left, 0))

    def _trace(self, flow):
        try:
            return flow.run().trace
        except FlowRefused as refused:
            return self.fail(f"{refused}; done before: {[name for name, _numbers in flow.trace]}")

    def _refusal(self, flow):
        try:
            flow.run()
        except FlowRefused as refused:
            return refused
        return self.fail(f"the flow was not refused: {flow.trace[-1]}")


class SaleFlow(Flow):
    """ Quotation of two lines (one storable product) -> confirm -> deliver -> invoice -> post -> pay. """

    steps = ('quote', 'confirm', 'deliver', 'invoice', 'post', 'pay')

    def __init__(self, case, user, partner):
        super().__init__(case, user)
        self.partner = partner
        self.order = self.invoice = self.payments = None
        self.warehouse = case.env['stock.warehouse'].search([('company_id', '=', case.company.id)], limit=1)
        case.env['stock.quant']._update_available_quantity(case.storable, self.warehouse.lot_stock_id, 50)
        self.onhand0 = self._onhand()
        self.start = self.counts()

    def _onhand(self):
        return self.onhand(self.case.storable, self.warehouse.lot_stock_id)

    def step_quote(self):
        case = self.case
        self.order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [
                Command.create({'product_id': case.storable.id, 'product_uom_qty': 3}),
                Command.create({'product_id': case.consumable.id, 'product_uom_qty': 2}),
            ],
        })

    def step_confirm(self):
        self.order.action_confirm()

    def step_deliver(self):
        self.validate(self.order.picking_ids)

    def step_invoice(self):
        self.env['sale.advance.payment.inv'].with_context(
            active_model='sale.order', active_ids=self.order.ids, active_id=self.order.id,
        ).create({'advance_payment_method': 'delivered'}).create_invoices()
        invoices = self.order.sudo().invoice_ids
        if not invoices:
            raise UserError("no invoice was created")
        self.invoice = invoices.with_env(self.env)

    def step_post(self):
        self.invoice.action_post()

    def step_pay(self):
        self.payments = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=self.invoice.ids,
        ).create({'journal_id': self.case.bank.id})._create_payments()

    def counts(self):
        env = self.case.env
        domain = [('partner_id', '=', self.partner.id)]
        return {
            'orders': env['sale.order'].search_count(domain),
            'pickings': env['stock.picking'].search_count(domain),
            'invoices': env['account.move'].search_count(domain + [('move_type', '=', 'out_invoice')]),
            'payments': env['account.payment'].search_count(domain),
            'onhand': self._onhand(),
        }

    def numbers(self):
        order = self.order.sudo()
        result = {
            'order': (order.state, order.invoice_status, order.amount_untaxed, order.amount_tax, order.amount_total),
            'lines': [(line.product_id.default_code, line.product_uom_qty, line.qty_delivered, line.qty_invoiced,
                       line.price_unit, line.price_subtotal) for line in order.order_line.sorted('id')],
            'pickings': [(picking.state, len(picking.move_ids), len(picking.move_line_ids))
                         for picking in order.picking_ids.sorted('id')],
            'onhand': self._onhand() - self.onhand0,
        }
        if self.invoice:
            invoice = self.invoice.sudo()
            result['invoice'] = (
                invoice.state, invoice.payment_state, invoice.journal_id.code, invoice.amount_untaxed,
                invoice.amount_tax, invoice.amount_total, invoice.amount_residual,
                len(invoice.invoice_line_ids), len(invoice.line_ids))
        if self.payments:
            payments = self.payments.sudo()
            result['payments'] = [(payment.state, payment.amount, payment.payment_type, payment.journal_id.code,
                                   len(payment.move_id.line_ids)) for payment in payments]
        return result


class PurchaseFlow(Flow):
    """ Request for quotation of two lines (one storable product) -> confirm -> receive -> bill -> post. """

    steps = ('rfq', 'confirm', 'receive', 'bill', 'post')

    def __init__(self, case, user, vendor):
        super().__init__(case, user)
        self.vendor = vendor
        self.order = self.bill = None
        self.warehouse = case.env['stock.warehouse'].search([('company_id', '=', case.company.id)], limit=1)
        self.onhand0 = self.onhand(case.storable, self.warehouse.lot_stock_id)
        self.start = self.counts()

    def step_rfq(self):
        case = self.case
        self.order = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'order_line': [
                Command.create({'product_id': case.storable.id, 'product_qty': 4, 'price_unit': 30.0}),
                Command.create({'product_id': case.consumable.id, 'product_qty': 2, 'price_unit': 10.0}),
            ],
        })

    def step_confirm(self):
        self.order.button_confirm()

    def step_receive(self):
        self.validate(self.order.picking_ids)

    def step_bill(self):
        self.order.action_create_invoice()
        bills = self.order.sudo().invoice_ids
        if not bills:
            raise UserError("no bill was created")
        self.bill = bills.with_env(self.env)

    def step_post(self):
        self.bill.write({'invoice_date': fields.Date.today()})
        self.bill.action_post()

    def counts(self):
        env = self.case.env
        domain = [('partner_id', '=', self.vendor.id)]
        return {
            'orders': env['purchase.order'].search_count(domain),
            'pickings': env['stock.picking'].search_count(domain),
            'bills': env['account.move'].search_count(domain + [('move_type', '=', 'in_invoice')]),
            'onhand': self.onhand(self.case.storable, self.warehouse.lot_stock_id),
        }

    def numbers(self):
        order = self.order.sudo()
        result = {
            'order': (order.state, order.invoice_status, order.amount_untaxed, order.amount_tax, order.amount_total),
            'lines': [(line.product_id.default_code, line.product_qty, line.qty_received, line.qty_invoiced,
                       line.price_unit, line.price_subtotal) for line in order.order_line.sorted('id')],
            'pickings': [(picking.state, len(picking.move_ids), len(picking.move_line_ids))
                         for picking in order.picking_ids.sorted('id')],
            'onhand': self.onhand(self.case.storable, self.warehouse.lot_stock_id) - self.onhand0,
        }
        if self.bill:
            bill = self.bill.sudo()
            result['bill'] = (
                bill.state, bill.payment_state, bill.journal_id.code, bill.amount_untaxed, bill.amount_tax,
                bill.amount_total, bill.amount_residual, len(bill.invoice_line_ids), len(bill.line_ids))
        return result


class ExpenseFlow(Flow):
    """ An employee creates and submits an expense, the manager approves it and posts its entry. """

    steps = ('create', 'submit', 'approve', 'post')

    def __init__(self, case, employee_user, manager_user, employee):
        super().__init__(case, employee_user)
        self.manager_env = case.env(user=manager_user)
        self.employee = employee
        self.expense = None
        self.start = self.counts()

    def step_create(self):
        self.expense = self.env['hr.expense'].create({
            'name': 'MX Flow Lunch', 'employee_id': self.employee.id, 'product_id': self.case.expense_product.id,
            'total_amount_currency': 120.0, 'payment_mode': 'own_account'})

    def step_submit(self):
        self.expense.action_submit()

    def step_approve(self):
        if self.expense.with_env(self.manager_env).action_approve() is not None:
            raise AssertionError("the approval asked for a wizard")

    def step_post(self):
        move = self.expense.sudo().account_move_id
        if not move:
            raise UserError("no entry was created")
        move.with_env(self.manager_env).action_post()

    def counts(self):
        env = self.case.env
        return {
            'expenses': env['hr.expense'].search_count([('employee_id', '=', self.employee.id)]),
            'entries': env['account.move'].search_count([('expense_ids.employee_id', '=', self.employee.id)]),
        }

    def numbers(self):
        expense = self.expense.sudo()
        result = {
            'expense': (expense.state, expense.approval_state, expense.payment_mode, expense.total_amount,
                        expense.total_amount_currency, expense.tax_amount),
        }
        move = expense.account_move_id
        if move:
            result['entry'] = (move.state, move.move_type, move.journal_id.code, move.amount_total, move.amount_residual,
                               move.payment_state, len(move.line_ids))
        return result


class ProjectFlow(Flow):
    """ A task is created, a timesheet line is logged on it, the task changes stage. """

    steps = ('task', 'timesheet', 'stage')

    def __init__(self, case, user, employee):
        super().__init__(case, user)
        self.employee = employee
        self.task = self.line = None
        self.start = self.counts()

    def step_task(self):
        self.task = self.env['project.task'].create({
            'name': 'MX Flow Task', 'project_id': self.case.project.id, 'user_ids': [Command.set(self.user.ids)]})

    def step_timesheet(self):
        self.line = self.env['account.analytic.line'].create({
            'name': 'MX Flow Work', 'project_id': self.case.project.id, 'task_id': self.task.id, 'unit_amount': 2.5})

    def step_stage(self):
        self.task.write({'stage_id': self.case.stage_done.id})

    def counts(self):
        env = self.case.env
        return {
            'tasks': env['project.task'].search_count([('user_ids', 'in', self.user.ids)]),
            'timesheets': env['account.analytic.line'].search_count([('employee_id', '=', self.employee.id)]),
        }

    def numbers(self):
        task = self.task.sudo()
        result = {'task': (task.stage_id.name, task.project_id.name, task.effective_hours, len(task.timesheet_ids))}
        if self.line:
            line = self.line.sudo()
            result['line'] = (line.unit_amount, line.employee_id == self.employee, line.task_id == task, line.name)
        return result


class HelpdeskFlow(Flow):
    """ A ticket is created, assigned to the user and closed. """

    steps = ('create', 'assign', 'close')

    def __init__(self, case, user, customer):
        super().__init__(case, user)
        self.customer = customer
        self.ticket = None
        self.start = self.counts()

    def step_create(self):
        self.ticket = self.env['helpdesk.ticket'].create({
            'name': 'MX Flow Ticket', 'team_id': self.case.team.id, 'partner_id': self.customer.id})

    def step_assign(self):
        self.ticket.write({'user_id': self.user.id})

    def step_close(self):
        self.ticket.write({'stage_id': self.case.stage_done.id})

    def counts(self):
        return {'tickets': self.case.env['helpdesk.ticket'].search_count([('partner_id', '=', self.customer.id)])}

    def numbers(self):
        ticket = self.ticket.sudo()
        return {
            'ticket': (ticket.stage_id.name, ticket.user_id == self.user, bool(ticket.close_date),
                       bool(ticket.assign_date), ticket.team_id.name, ticket.closed_by_partner),
            'sla': [(status.sla_id.name, bool(status.reached_datetime)) for status in ticket.sla_status_ids],
        }


class ProductionFlow(Flow):
    """ A manufacturing order of a simple bill of materials: confirm -> produce -> done. """

    steps = ('create', 'confirm', 'produce', 'done')

    def __init__(self, case, user):
        super().__init__(case, user)
        self.warehouse = case.env['stock.warehouse'].search([('company_id', '=', case.company.id)], limit=1)
        self.location = self.warehouse.lot_stock_id
        case.env['stock.quant']._update_available_quantity(case.component, self.location, 100)
        self.component0 = self.onhand(case.component, self.location)
        self.finished0 = self.onhand(case.finished, self.location)
        self.production = None
        self.start = self.counts()

    def step_create(self):
        self.production = self.env['mrp.production'].create({
            'product_id': self.case.finished.id, 'bom_id': self.case.bom.id, 'product_qty': 5.0})

    def step_confirm(self):
        self.production.action_confirm()

    def step_produce(self):
        self.production.write({'qty_producing': 5.0})

    def step_done(self):
        if self.production.button_mark_done() is not True:
            raise AssertionError("the production asked for a wizard")

    def counts(self):
        return {
            'productions': self.case.env['mrp.production'].search_count([('product_id', '=', self.case.finished.id)]),
            'components': self.onhand(self.case.component, self.location),
            'finished': self.onhand(self.case.finished, self.location),
        }

    def numbers(self):
        production = self.production.sudo()
        return {
            'production': (production.state, production.product_qty, production.qty_producing, production.qty_produced),
            'raw': [(move.product_id.default_code, move.state, move.product_uom_qty, move.quantity)
                    for move in production.move_raw_ids.sorted('id')],
            'finished': [(move.product_id.default_code, move.state, move.product_uom_qty, move.quantity)
                         for move in production.move_finished_ids.sorted('id')],
            'components': self.onhand(self.case.component, self.location) - self.component0,
            'produced': self.onhand(self.case.finished, self.location) - self.finished0,
        }


class RpcFlow:
    """ Mixin: the steps of a flow made with the calls the web client makes. Every step is one or two requests to
    /web/dataset, where the client switches of the profile are enforced, and a request that fails rolls back alone. """

    def atomic(self):
        return nullcontext()

    def run(self, until=None):
        self.case.authenticate(self.user.login, f'mx-flows-{self.user.login[len("mx_flows_"):]}')
        return super().run(until)

    def rpc(self, model, method, args, kwargs=None, route='call_kw'):
        response = self.case.url_open(f'/web/dataset/{route}/{model}/{method}', json={
            'jsonrpc': '2.0', 'method': 'call', 'id': 1,
            'params': {'model': model, 'method': method, 'args': args, 'kwargs': kwargs or {}},
        })
        body = response.json()
        if 'error' in body:
            name, message = body['error']['data']['name'], body['error']['data']['message']
            if name.endswith('AccessError'):
                raise AccessError(message)
            if name.endswith(('UserError', 'ValidationError', 'MissingError')):
                raise UserError(message)
            raise AssertionError(f"{name}: {message}")
        return body['result']

    def button(self, model, method, ids, context=None):
        result = self.rpc(model, method, [ids], {'context': context or {}}, route='call_button')
        if isinstance(result, dict) and result.get('type') == 'ir.actions.act_window' and result.get('target') == 'new':
            raise AssertionError(f"{method} asked for a wizard: {result.get('res_model')}")
        return result

    def save(self, model, values, names=('display_name',)):
        saved = self.rpc(model, 'web_save', [[], values], {'specification': dict.fromkeys(names, {})})
        return self.case.env[model].browse(saved[0]['id'])

    def numbers(self):
        self.case.env.invalidate_all()
        return super().numbers()


class RpcSaleFlow(RpcFlow, SaleFlow):
    """ The flow of the sale through the client door. """

    def step_quote(self):
        case = self.case
        saved = self.rpc('sale.order', 'web_save', [[], {
            'partner_id': self.partner.id,
            'order_line': [
                [0, 0, {'product_id': case.storable.id, 'product_uom_qty': 3}],
                [0, 0, {'product_id': case.consumable.id, 'product_uom_qty': 2}],
            ],
        }], {'specification': {'name': {}, 'state': {}, 'partner_id': {'fields': {'display_name': {}}}}})
        self.order = case.env['sale.order'].browse(saved[0]['id'])

    def step_confirm(self):
        self.button('sale.order', 'action_confirm', self.order.ids)

    def step_deliver(self):
        env = self.case.env
        env.invalidate_all()
        picking = self.order.picking_ids
        for move in picking.move_ids:
            self.rpc('stock.move', 'write', [[move.id], {'quantity': move.product_uom_qty, 'picked': True}])
        self.button('stock.picking', 'button_validate', picking.ids)

    def step_invoice(self):
        context = {'active_model': 'sale.order', 'active_ids': self.order.ids, 'active_id': self.order.id}
        wizard = self.rpc('sale.advance.payment.inv', 'create', [{'advance_payment_method': 'delivered'}],
                          {'context': context})
        self.rpc('sale.advance.payment.inv', 'create_invoices', [[wizard]], {'context': context}, route='call_button')
        self.case.env.invalidate_all()
        invoices = self.order.invoice_ids
        if not invoices:
            raise UserError("no invoice was created")
        self.invoice = invoices

    def step_post(self):
        self.button('account.move', 'action_post', self.invoice.ids)

    def step_pay(self):
        context = {'active_model': 'account.move', 'active_ids': self.invoice.ids}
        wizard = self.rpc('account.payment.register', 'create', [{'journal_id': self.case.bank.id}],
                          {'context': context})
        known = self.case.env['account.payment'].search([('partner_id', '=', self.partner.id)])
        self.rpc('account.payment.register', 'action_create_payments', [[wizard]], {'context': context},
                 route='call_button')
        self.case.env.invalidate_all()
        self.payments = self.case.env['account.payment'].search([('partner_id', '=', self.partner.id)]) - known


class RpcPurchaseFlow(RpcFlow, PurchaseFlow):
    """ The flow of the purchase through the client door. """

    def step_rfq(self):
        case = self.case
        self.order = self.save('purchase.order', {
            'partner_id': self.vendor.id,
            'order_line': [
                [0, 0, {'product_id': case.storable.id, 'product_qty': 4, 'price_unit': 30.0}],
                [0, 0, {'product_id': case.consumable.id, 'product_qty': 2, 'price_unit': 10.0}],
            ]})

    def step_confirm(self):
        self.button('purchase.order', 'button_confirm', self.order.ids)

    def step_receive(self):
        self.case.env.invalidate_all()
        picking = self.order.picking_ids
        for move in picking.move_ids:
            self.rpc('stock.move', 'write', [[move.id], {'quantity': move.product_uom_qty, 'picked': True}])
        self.button('stock.picking', 'button_validate', picking.ids)

    def step_bill(self):
        self.button('purchase.order', 'action_create_invoice', self.order.ids)
        self.case.env.invalidate_all()
        bills = self.order.invoice_ids
        if not bills:
            raise UserError("no bill was created")
        self.bill = bills

    def step_post(self):
        self.rpc('account.move', 'write', [self.bill.ids, {'invoice_date': str(fields.Date.today())}])
        self.button('account.move', 'action_post', self.bill.ids)


class RpcProjectFlow(RpcFlow, ProjectFlow):
    """ The flow of the project and its timesheets through the client door. """

    def step_task(self):
        self.task = self.save('project.task', {
            'name': 'MX Flow Task', 'project_id': self.case.project.id, 'user_ids': [[6, 0, self.user.ids]]})

    def step_timesheet(self):
        self.line = self.save('account.analytic.line', {
            'name': 'MX Flow Work', 'project_id': self.case.project.id, 'task_id': self.task.id, 'unit_amount': 2.5})

    def step_stage(self):
        self.rpc('project.task', 'write', [self.task.ids, {'stage_id': self.case.stage_done.id}])


class RpcHelpdeskFlow(RpcFlow, HelpdeskFlow):
    """ The flow of the helpdesk through the client door. """

    def step_create(self):
        self.ticket = self.save('helpdesk.ticket', {
            'name': 'MX Flow Ticket', 'team_id': self.case.team.id, 'partner_id': self.customer.id})

    def step_assign(self):
        self.rpc('helpdesk.ticket', 'write', [self.ticket.ids, {'user_id': self.user.id}])

    def step_close(self):
        self.rpc('helpdesk.ticket', 'write', [self.ticket.ids, {'stage_id': self.case.stage_done.id}])


class PosFlow(Flow):
    """ A cashier opens the register, rings up a sale paid in cash and closes the register. """

    steps = ('open', 'order', 'pay', 'close')

    def __init__(self, case, user):
        super().__init__(case, user)
        self.session = self.order = None
        self.start = self.counts()

    def step_open(self):
        config = self.case.config.with_env(self.env)
        config.open_ui()
        self.session = config.current_session_id
        self.session.set_opening_control(0, '')

    def step_order(self):
        self.order = self.env['pos.order'].create({
            'session_id': self.session.id, 'company_id': self.case.company.id, 'amount_total': 20.0,
            'amount_paid': 0, 'amount_tax': 0, 'amount_return': 0, 'date_order': fields.Datetime.now(),
            'lines': [Command.create({
                'product_id': self.case.pos_product.id, 'qty': 2, 'price_unit': 10.0, 'price_subtotal': 20.0,
                'price_subtotal_incl': 20.0})],
        })

    def step_pay(self):
        context = {'active_ids': self.order.ids, 'active_id': self.order.id}
        self.env['pos.make.payment'].with_context(**context).create({
            'payment_method_id': self.case.pos_method.id, 'amount': 20.0}).with_context(**context).check()

    def step_close(self):
        counted = self.session.sudo().opening_balance + 20.0
        result = self.session.close_session_from_ui({self.case.pos_method.id: counted})
        if not result.get('status'):
            raise UserError(str(result.get('message')))

    def counts(self):
        env = self.case.env
        return {
            'sessions': env['pos.session'].search_count([('config_id', '=', self.case.config.id)]),
            'orders': env['pos.order'].search_count([('config_id', '=', self.case.config.id)]),
            'payments': env['pos.payment'].search_count([('payment_method_id', '=', self.case.pos_method.id)]),
            'entries': env['account.move'].search_count([('journal_id', 'in', (
                self.case.config.journal_id | self.case.pos_method.journal_id).ids)]),
        }

    def numbers(self):
        session = self.session.sudo()
        result = {'session': (session.state, session.total_payments_amount)}
        if self.order:
            order = self.order.sudo()
            result['order'] = (order.state, order.amount_total, order.amount_paid, order.amount_tax,
                               len(order.lines), len(order.payment_ids))
        if session.state == 'closed':
            result['closing'] = (session.closing_balance - session.opening_balance, session.account_move_count,
                                 session.sale_move_count)
        return result


class SaleVariantFlow(SaleFlow):
    """ The sale in the ways it is lived: a form quotation, a partial delivery with its backorder, a quotation
    edited, an order resized or cancelled, a return and a credit note. """

    VARIANT_STEPS = {
        'form': SaleFlow.steps,
        'partial': ('quote', 'confirm', 'deliver', 'deliver_rest', 'invoice', 'post', 'pay'),
        'edit': ('quote', 'edit', 'confirm', 'deliver', 'invoice', 'post', 'pay'),
        'resize': ('quote', 'confirm', 'resize', 'deliver', 'invoice', 'post', 'pay'),
        'cancel': ('quote', 'confirm', 'cancel'),
        'refund': ('quote', 'confirm', 'deliver', 'invoice', 'post', 'pay', 'return', 'refund'),
        'unreserve': ('quote', 'confirm', 'unreserve', 'reassign', 'deliver', 'invoice', 'post', 'pay'),
        'edit_invoice': ('quote', 'confirm', 'deliver', 'invoice', 'edit_invoice', 'post', 'pay'),
    }

    def __init__(self, case, user, partner, variant):
        self.variant = variant
        self.steps = self.VARIANT_STEPS[variant]
        super().__init__(case, user, partner)

    def step_quote(self):
        case = self.case
        if self.variant == 'form':
            with Form(self.env['sale.order']) as form:
                form.partner_id = self.partner
                for product, quantity in ((case.storable, 3), (case.consumable, 2)):
                    with form.order_line.new() as line:
                        line.product_id = product
                        line.product_uom_qty = quantity
            self.order = form.record
            return
        lines = [Command.create({'product_id': case.storable.id, 'product_uom_qty': 3}),
                 Command.create({'product_id': case.consumable.id, 'product_uom_qty': 2})]
        if self.variant == 'edit':
            lines.append(Command.create({'product_id': case.consumable.id, 'product_uom_qty': 7}))
        self.order = self.env['sale.order'].create({'partner_id': self.partner.id, 'order_line': lines})

    def step_edit(self):
        lines = self.order.order_line.sorted('id')
        self.order.write({'order_line': [Command.update(lines[0].id, {'product_uom_qty': 4}), Command.delete(lines[2].id)]})

    def step_resize(self):
        self.order.order_line.sorted('id')[0].write({'product_uom_qty': 5})

    def step_deliver(self):
        if self.variant != 'partial':
            return super().step_deliver()
        picking = self.order.picking_ids
        for move in picking.move_ids:
            move.write({'quantity': 1 if move.product_id == self.case.storable else move.product_uom_qty, 'picked': True})
        action = picking.button_validate()
        if action is not True:
            Form.from_action(self.env, action).save().process()

    def step_deliver_rest(self):
        self.validate(self.order.picking_ids.filtered(lambda picking: picking.state not in ('done', 'cancel')))

    def step_cancel(self):
        self.order.action_cancel()

    def step_unreserve(self):
        self.order.picking_ids.do_unreserve()

    def step_reassign(self):
        self.order.picking_ids.action_assign()

    def step_edit_invoice(self):
        line = self.invoice.invoice_line_ids.sorted('id')[0]
        self.invoice.write({'invoice_line_ids': [Command.update(line.id, {'price_unit': 90.0, 'quantity': 2.0})]})

    def step_return(self):
        picking = self.order.picking_ids.filtered(lambda p: p.state == 'done')
        returned = picking._create_return()
        for move in returned.move_ids:
            move.product_uom_qty = move.product_uom_qty or picking.move_ids.filtered(
                lambda m: m.product_id == move.product_id).product_uom_qty
        returned.action_assign()
        self.validate(returned)

    def step_refund(self):
        invoice = self.invoice
        wizard = self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({
                'journal_id': invoice.journal_id.id, 'reason': 'MX Flow return'})
        wizard.refund_moves()
        credit = invoice.sudo().reversal_move_ids.with_env(self.env)
        if not credit:
            raise UserError("no credit note was created")
        credit.action_post()

    def numbers(self):
        result = super().numbers()
        order = self.order.sudo()
        result['moves'] = [(move.move_type, move.state, move.payment_state, move.amount_total, move.amount_residual)
                           for move in order.invoice_ids.sorted('id')]
        result['all_pickings'] = [(picking.state, bool(picking.backorder_id), picking.picking_type_code)
                                  for picking in order.picking_ids.sorted('id')]
        return result


class PurchaseVariantFlow(PurchaseFlow):
    """ The purchase in the ways it is lived: a partial receipt, a cancelled order, an edited order or bill, a
    return and a vendor credit note. """

    VARIANT_STEPS = {
        'partial': ('rfq', 'confirm', 'receive', 'receive_rest', 'bill', 'post'),
        'cancel': ('rfq', 'confirm', 'cancel'),
        'edit': ('rfq', 'edit', 'confirm', 'receive', 'bill', 'post'),
        'edit_bill': ('rfq', 'confirm', 'receive', 'bill', 'edit_bill', 'post'),
        'refund': ('rfq', 'confirm', 'receive', 'bill', 'post', 'return', 'refund'),
    }

    def __init__(self, case, user, vendor, variant):
        self.variant = variant
        self.steps = self.VARIANT_STEPS[variant]
        super().__init__(case, user, vendor)

    def step_edit(self):
        line = self.order.order_line.sorted('id')[0]
        self.order.write({'order_line': [Command.update(line.id, {'product_qty': 6, 'price_unit': 25.0})]})

    def step_receive(self):
        if self.variant != 'partial':
            return super().step_receive()
        picking = self.order.picking_ids
        for move in picking.move_ids:
            move.write({'quantity': 2 if move.product_id == self.case.storable else move.product_uom_qty,
                        'picked': True})
        action = picking.button_validate()
        if action is not True:
            Form.from_action(self.env, action).save().process()

    def step_receive_rest(self):
        self.validate(self.order.picking_ids.filtered(lambda picking: picking.state not in ('done', 'cancel')))

    def step_cancel(self):
        self.order.button_cancel()

    def step_edit_bill(self):
        line = self.bill.invoice_line_ids.sorted('id')[0]
        self.bill.write({'invoice_line_ids': [Command.update(line.id, {'price_unit': 28.0, 'quantity': 3.0})]})

    def step_return(self):
        picking = self.order.picking_ids.filtered(lambda p: p.state == 'done')
        returned = picking._create_return()
        for move in returned.move_ids:
            move.product_uom_qty = move.product_uom_qty or picking.move_ids.filtered(
                lambda m: m.product_id == move.product_id).product_uom_qty
        returned.action_assign()
        self.validate(returned)

    def step_refund(self):
        wizard = self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=self.bill.ids).create({
                'journal_id': self.bill.journal_id.id, 'reason': 'MX Flow return'})
        wizard.refund_moves()
        credit = self.bill.sudo().reversal_move_ids.with_env(self.env)
        if not credit:
            raise UserError("no credit note was created")
        credit.write({'invoice_date': fields.Date.today()})
        credit.action_post()

    def numbers(self):
        result = super().numbers()
        order = self.order.sudo()
        result['moves'] = [(move.move_type, move.state, move.payment_state, move.amount_total, move.amount_residual)
                           for move in order.invoice_ids.sorted('id')]
        result['all_pickings'] = [(picking.state, bool(picking.backorder_id), picking.picking_type_code)
                                  for picking in order.picking_ids.sorted('id')]
        return result


class ProductionVariantFlow(ProductionFlow):
    """ The manufacturing in the ways it is lived: a partial production with its backorder, an edited or a cancelled
    order, and an unbuild. """

    VARIANT_STEPS = {
        'partial': ('create', 'confirm', 'produce', 'done'),
        'edit': ('create', 'edit', 'confirm', 'produce', 'done'),
        'cancel': ('create', 'confirm', 'cancel'),
        'unbuild': ('create', 'confirm', 'produce', 'done', 'unbuild'),
    }

    def __init__(self, case, user, variant):
        self.variant = variant
        self.steps = self.VARIANT_STEPS[variant]
        super().__init__(case, user)
        self.last_id = max(case.env['mrp.production'].search([]).ids or [0])

    def step_edit(self):
        self.production.write({'product_qty': 8.0})

    def step_produce(self):
        if self.variant == 'partial':
            with Form(self.production) as form:
                form.qty_producing = 3.0
            return
        self.production.write({'qty_producing': self.production.product_qty})

    def step_done(self):
        action = self.production.button_mark_done()
        if action is True:
            return
        if self.variant != 'partial':
            raise AssertionError("the production asked for a wizard")
        result = Form(self.env['mrp.production.backorder'].with_context(**action['context'])).save().action_backorder()
        while isinstance(result, dict):
            result = Form.from_action(self.env, result).save().action_confirm()

    def step_cancel(self):
        self.production.action_cancel()

    def step_unbuild(self):
        with Form(self.env['mrp.unbuild']) as form:
            form.product_id = self.case.finished
            form.bom_id = self.case.bom
            form.product_qty = 2.0
        form.record.action_unbuild()

    def numbers(self):
        result = super().numbers()
        result['productions'] = [
            (production.state, production.product_qty, production.qty_produced)
            for production in self.case.env['mrp.production'].search([
                ('product_id', '=', self.case.finished.id), ('id', '>', self.last_id)], order='id')]
        return result


class ExpenseVariantFlow(ExpenseFlow):
    """ An expense refused by the manager, reset by the employee, then submitted again and carried to the end. """

    steps = ('create', 'submit', 'refuse', 'reset', 'resubmit', 'approve', 'post')

    def step_resubmit(self):
        self.expense.with_env(self.manager_env).action_submit()

    def step_refuse(self):
        self.manager_env['hr.expense.refuse.wizard'].create({
            'expense_ids': [Command.set(self.expense.ids)], 'reason': 'MX Flow refusal'}).action_refuse()

    def step_reset(self):
        self.expense.with_env(self.manager_env).action_reset()


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixSaleFlow(FlowCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('sale.order', 'stock.picking', 'account.move')
        cls._need_field('sale.order', 'picking_ids')
        env = cls.env
        groups = ('base.group_user', 'sales_team.group_sale_salesman', 'stock.group_stock_user',
                  'account.group_account_invoice')
        cls.plain = cls._user('sale_plain', *groups)
        cls.prof = cls._user('sale_prof', *groups)
        Partner = env['res.partner']
        cls.partner_plain = Partner.create({'name': 'MX Flow Customer Plain', 'user_id': cls.plain.id})
        cls.partner_prof = Partner.create({'name': 'MX Flow Customer Prof', 'user_id': cls.prof.id})
        cls._products()
        Journal = env['account.journal']
        cls.bank = Journal.search([('type', '=', 'bank'), ('company_id', '=', cls.company.id)], limit=1)
        cls.other_bank = Journal.create({'name': 'MX Flow Other Bank', 'code': 'MXFB', 'type': 'bank'})
        cls.other_sales = Journal.create({'name': 'MX Flow Other Sales', 'code': 'MXFO', 'type': 'sale'})
        cls.thin = cls._user('sale_thin', 'base.group_user', 'sales_team.group_sale_salesman', 'stock.group_stock_user')
        cls.partner_thin = Partner.create({'name': 'MX Flow Customer Thin', 'user_id': cls.thin.id})
        cls.baseline = SaleFlow(cls, cls.plain, cls.partner_plain).run().trace
        cls.baseline_journal = cls.baseline[-1][1]['invoice'][2]

    def _flow(self):
        return SaleFlow(self, self.prof, self.partner_prof)

    def _identical(self, flow=None, user=None):
        flow = flow or self._flow()
        self.assertTrue(self.Profile._resolve((user or flow.user).id).enabled, "the profile does not reach the user")
        self.assertEqual(self._trace(flow), self.baseline)
        return flow

    def _passes(self, **values):
        profile = self._profile(self.prof, **values)
        self._identical()
        return profile

    def test_the_flow_without_a_profile(self):
        steps = [name for name, _numbers in self.baseline]
        self.assertEqual(steps, list(SaleFlow.steps))
        numbers = self.baseline[-1][1]
        self.assertEqual(numbers['order'][:2], ('sale', 'invoiced'))
        self.assertEqual(numbers['order'][4], 460.0)
        self.assertEqual(numbers['onhand'], -3)
        self.assertEqual(numbers['pickings'], [('done', 2, 2)])
        self.assertEqual(numbers['invoice'][:2], ('posted', 'in_payment'))
        self.assertEqual(numbers['payments'][0][:2], ('paid', 460.0))

    def test_the_salesperson_template(self):
        self._template('salesperson', self.prof)
        flow = self._identical()
        self._refused(self.prof, flow.order, 'unlink')

    def test_the_accountant_template(self):
        self._template('accountant', self.prof)
        self._identical()
        self._refused(self.prof, self.bank, 'write')

    def test_the_warehouse_template(self):
        self._template('warehouse', self.prof)
        self._identical()
        self._refused(self.prof, self.env['stock.warehouse'].search([], limit=1), 'write')

    def test_the_templates_of_the_three_roles_together(self):
        for key in ('salesperson', 'accountant', 'warehouse'):
            self._template(key, self.prof)
        flow = self._identical()
        self._refused(self.prof, flow.order, 'unlink')
        self._refused(self.prof, self.bank, 'write')

    def test_the_app_user_template_of_the_three_apps(self):
        for xmlid in ('sale.sale_menu_root', 'stock.menu_stock_root', ACCOUNTING):
            app = self._menu(xmlid)
            if app:
                self._template('app_user', self.prof, app=app)
        flow = self._identical()
        self._refused(self.prof, flow.order, 'unlink')
        self._refused(self.prof, self.bank, 'write')

    def test_the_sales_read_only_template_refuses_the_quotation(self):
        self._template('sales_readonly', self.prof)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual(refused.step, 'quote')
        self.assertIsInstance(refused.error, AccessError)
        self._nothing_left(flow)

    def test_the_auditor_template_refuses_the_quotation(self):
        self._template('auditor', self.prof)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual(refused.step, 'quote')
        self.assertIsInstance(refused.error, AccessError)
        self._nothing_left(flow)

    def _on_the_fly(self, user):
        env = self.env(user=user)
        partner = env['res.partner'].create({'name': f'MX Flow New Customer {user.id}'})
        order = env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [Command.create({'product_id': self.consumable.id, 'product_uom_qty': 1})]})
        order.action_confirm()
        return order.sudo().amount_total, order.sudo().state

    def test_a_customer_made_on_the_fly(self):
        expected = self._on_the_fly(self.plain)
        self._template('salesperson', self.prof)
        self.assertEqual(self._on_the_fly(self.prof), expected)

    def test_the_documents_print_for_the_profile(self):
        for key in ('salesperson', 'accountant', 'warehouse'):
            self._template(key, self.prof)
        self._profile(self.prof, name='MX Flow Switches', hide_costs=True, hide_sale_prices=True, block_export=True)
        flow = self._flow().run()
        Report = self.env['ir.actions.report'].with_user(self.prof)
        for xmlid, records in (
                ('sale.action_report_saleorder', flow.order), ('account.account_invoices', flow.invoice),
                ('stock.action_report_delivery', flow.order.picking_ids)):
            html = Report._render_qweb_html(xmlid, records.ids)[0]
            self.assertIn(records[:1].name, html.decode() if isinstance(html, bytes) else html)

    def test_block_export(self):
        self._passes(block_export=True)

    def test_block_import(self):
        self._passes(block_import=True)

    def test_block_duplicate(self):
        self._passes(block_duplicate=True)

    def test_block_archive(self):
        self._passes(block_archive=True)

    def test_hide_costs(self):
        self._passes(hide_costs=True)

    def test_hide_sale_prices(self):
        self._passes(hide_sale_prices=True)

    def test_hide_settings_menu(self):
        self._passes(hide_settings_menu=True)

    def test_block_developer_mode(self):
        self._passes(block_developer_mode=True)

    def test_the_other_switches_of_the_screens(self):
        self._passes(
            hide_chatter_all=True, hide_activities=True, lock_statusbar=True, hide_print_all=True,
            hide_action_menu_all=True, hide_send_message_all=True, hide_followers_all=True,
            hide_attachments_all=True, block_custom_filter=True, block_custom_group=True, block_favorites=True,
            block_properties=True, block_apps=True, block_rpc=True)

    def test_hidden_menus_of_other_apps(self):
        menus = self.env['ir.ui.menu']
        for xmlid in ('hr.menu_hr_root', 'project.menu_main_pm', 'crm.crm_menu_root', 'purchase.menu_purchase_root',
                      'mrp.menu_mrp_root', 'point_of_sale.menu_point_root', 'helpdesk.menu_helpdesk_root'):
            menus |= self._menu(xmlid)
        self.assertTrue(menus)
        self._passes(hidden_menu_ids=[Command.set(menus.ids)])

    def test_hidden_menus_of_the_apps_of_the_flow(self):
        menus = self.env['ir.ui.menu']
        for xmlid in ('sale.sale_menu_root', 'stock.menu_stock_root', ACCOUNTING):
            menus |= self._menu(xmlid)
        self._passes(hidden_menu_ids=[Command.set(menus.ids)])

    def test_every_benign_switch_at_once(self):
        self._passes(
            block_export=True, block_import=True, block_duplicate=True, block_archive=True, hide_costs=True,
            hide_sale_prices=True, hide_settings_menu=True, block_developer_mode=True, hide_chatter_all=True,
            hide_activities=True, lock_statusbar=True, hide_print_all=True, hide_action_menu_all=True,
            hide_send_message_all=True, hide_followers_all=True, hide_attachments_all=True)

    def test_a_profile_of_another_company_changes_nothing(self):
        other = self.env['res.company'].search([('id', '!=', self.company.id)], limit=1)
        profile = self._profile(self.prof, global_readonly=True, company_id=other.id)
        self.assertFalse(self.Profile._resolve(self.prof.id).enabled)
        self.assertEqual(self._trace(self._flow()), self.baseline)
        profile.company_id = self.company
        self.assertEqual(self._refusal(self._flow()).step, 'quote')

    def test_an_archived_profile_changes_nothing(self):
        self._profile(self.prof, global_readonly=True, active=False)
        self.assertFalse(self.Profile._resolve(self.prof.id).enabled)
        self.assertEqual(self._trace(self._flow()), self.baseline)

    def test_the_read_only_profile_refuses_the_first_write(self):
        for strictness in ('additive', 'override'):
            with self._undone():
                self._profile(self.prof, global_readonly=True, strictness=strictness)
                flow = self._flow()
                refused = self._refusal(flow)
                self.assertEqual((refused.step, type(refused.error)), ('quote', AccessError), strictness)
                self._nothing_left(flow)

    def test_the_read_only_profile_of_a_group_refuses_the_first_write(self):
        group = self.env['res.groups'].create({'name': 'MX Flow Read Only Group'})
        self.prof.group_ids = [Command.link(group.id)]
        self._profile(self.env['res.users'], global_readonly=True, group_ids=[Command.set(group.ids)])
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('quote', AccessError))
        self._nothing_left(flow)

    def test_the_read_only_profile_of_a_temporary_assignment_refuses_the_first_write(self):
        profile = self._profile(self.env['res.users'], global_readonly=True)
        self.env['gec.access.profile.assignment'].create({'profile_id': profile.id, 'user_id': self.prof.id})
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('quote', AccessError))
        self._nothing_left(flow)

    def test_two_additive_profiles_one_read_only_and_one_full(self):
        models = ('sale.order', 'sale.order.line')
        readonly = self._profile(self.prof, name='MX Flow Read Only')
        full = self._profile(self.prof, name='MX Flow Full')
        for model_name in models:
            self._line(readonly, model_name, perm_write=False, perm_create=False, perm_unlink=False)
            self._line(full, model_name)
        self._identical()

    def test_two_additive_profiles_both_read_only_refuse(self):
        for name in ('MX Flow Read Only One', 'MX Flow Read Only Two'):
            profile = self._profile(self.prof, name=name)
            self._line(profile, 'sale.order', perm_write=False, perm_create=False, perm_unlink=False)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('quote', AccessError))
        self._nothing_left(flow)

    def test_an_override_read_only_picking_refuses_the_delivery(self):
        override = self._profile(self.prof, name='MX Flow Picking Read Only', strictness='override')
        self._line(override, 'stock.picking', perm_write=False, perm_create=False, perm_unlink=False)
        full = self._profile(self.prof, name='MX Flow Full')
        for model_name in ('stock.picking', 'sale.order'):
            self._line(full, model_name)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('deliver', AccessError))
        self.assertEqual(flow.trace, self.baseline[:2])
        self.assertEqual(flow.numbers(), self.baseline[1][1])
        self.assertEqual(flow.left_behind()['onhand'], 0)
        self.assertEqual(flow.left_behind()['invoices'], 0)

    def test_a_neutral_filter_on_every_model_changes_nothing(self):
        self._neutral(self.prof)
        self._identical()

    def test_a_profile_granting_the_invoicing_group(self):
        flow = SaleFlow(self, self.thin, self.partner_thin)
        self.assertEqual(self._refusal(flow).step, 'post')
        profile = self._profile(self.thin, granted_group_ids=[Command.set(self.env.ref('account.group_account_invoice').ids)])
        self.assertTrue(self.thin.has_group('account.group_account_invoice'))
        self.assertEqual(self._trace(SaleFlow(self, self.thin, self.partner_thin)), self.baseline)
        profile.unlink()
        self.assertFalse(self.thin.has_group('account.group_account_invoice'))

    def _own_records_with_allowed_journals_and_warehouse(self):
        profile = self._template('salesperson', self.prof)
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        sales = self.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', self.company.id), ('code', '=', self.baseline_journal)])
        profile.allowed_ids = [
            Command.create({'kind': 'journal', 'res_id': sales.id}),
            Command.create({'kind': 'journal', 'res_id': self.bank.id}),
            Command.create({'kind': 'warehouse', 'res_id': warehouse.id}),
        ]
        return profile

    def test_own_orders_in_the_allowed_journals_and_warehouse(self):
        self._own_records_with_allowed_journals_and_warehouse()
        self._identical()

    def test_own_records_hide_the_orders_of_others(self):
        self._own_records_with_allowed_journals_and_warehouse()
        mine = SaleFlow(self, self.prof, self.partner_prof).run(until='quote').order
        others = SaleFlow(self, self.plain, self.partner_plain).run(until='quote').order
        Order = self.env['sale.order'].with_user(self.prof)
        self.assertEqual(Order.search([('id', 'in', (mine | others).ids)]), mine)
        with self.assertRaises(AccessError):
            others.with_user(self.prof).action_confirm()

    def test_posting_into_a_journal_that_is_not_allowed_is_refused(self):
        self._own_records_with_allowed_journals_and_warehouse()
        flow = self._flow().run(until='invoice')
        invoice = flow.invoice.sudo()
        invoice.journal_id = self.other_sales
        with self.assertRaises(AccessError):
            invoice.with_user(self.prof).action_post()
        self.assertEqual(invoice.state, 'draft')

    def test_a_direct_invoice_in_a_journal_that_is_not_allowed_is_refused(self):
        self._own_records_with_allowed_journals_and_warehouse()
        Move = self.env['account.move']
        values = {'move_type': 'out_invoice', 'partner_id': self.partner_prof.id, 'journal_id': self.other_sales.id}
        before = Move.search_count([('journal_id', '=', self.other_sales.id)])
        with self.assertRaises(AccessError):
            Move.with_user(self.prof).create(values)
        self.assertEqual(Move.search_count([('journal_id', '=', self.other_sales.id)]), before)

    def test_a_payment_into_a_journal_that_is_not_allowed_is_refused(self):
        self._own_records_with_allowed_journals_and_warehouse()
        flow = self._flow().run(until='post')
        payments = self.env['account.payment'].search_count([('partner_id', '=', self.partner_prof.id)])
        with self.assertRaises(AccessError):
            self.env['account.payment.register'].with_user(self.prof).with_context(
                active_model='account.move', active_ids=flow.invoice.ids,
            ).create({'journal_id': self.other_bank.id})._create_payments()
        self.assertEqual(self.env['account.payment'].search_count([('partner_id', '=', self.partner_prof.id)]), payments)
        self.assertEqual(flow.invoice.sudo().payment_state, 'not_paid')

    def test_no_creation_of_entries_stops_a_direct_invoice(self):
        profile = self._profile(self.prof)
        self._line(profile, 'account.move', perm_create=False)
        Move = self.env['account.move']
        before = Move.search_count([])
        with self.assertRaises(AccessError):
            Move.with_user(self.prof).create({'move_type': 'out_invoice', 'partner_id': self.partner_prof.id})
        self.assertEqual(Move.search_count([]), before)

    def test_no_creation_of_entries_leaves_the_invoice_core_makes_for_an_order(self):
        """ Core makes the invoice of an order in sudo, so that a salesperson without accounting rights gets it:
        a profile that stops creating entries does not stop it either. """
        thin = SaleFlow(self, self.thin, self.partner_thin).run(until='invoice')
        self.assertEqual(thin.trace[-1][1]['invoice'][0], 'draft')
        profile = self._profile(self.prof)
        self._line(profile, 'account.move', perm_create=False)
        self.assertEqual(self._trace(self._flow()), self.baseline)


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixPurchaseFlow(FlowCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('purchase.order', 'stock.picking', 'account.move')
        cls._need_field('purchase.order', 'picking_ids')
        env = cls.env
        groups = ('base.group_user', 'purchase.group_purchase_user', 'stock.group_stock_user',
                  'account.group_account_invoice', 'quality.group_quality_manager')
        cls.plain = cls._user('purchase_plain', *groups)
        cls.prof = cls._user('purchase_prof', *groups)
        cls.vendor_plain = env['res.partner'].create({'name': 'MX Flow Vendor Plain'})
        cls.vendor_prof = env['res.partner'].create({'name': 'MX Flow Vendor Prof'})
        cls._products()
        cls.bank = env['account.journal'].search([('type', '=', 'bank'), ('company_id', '=', cls.company.id)], limit=1)
        cls.baseline = PurchaseFlow(cls, cls.plain, cls.vendor_plain).run().trace
        cls.baseline_journal = cls.baseline[-1][1]['bill'][2]

    def _flow(self):
        return PurchaseFlow(self, self.prof, self.vendor_prof)

    def _identical(self):
        self.assertTrue(self.Profile._resolve(self.prof.id).enabled, "the profile does not reach the user")
        self.assertEqual(self._trace(self._flow()), self.baseline)

    def _passes(self, **values):
        profile = self._profile(self.prof, **values)
        self._identical()
        return profile

    def test_the_flow_without_a_profile(self):
        self.assertEqual([name for name, _numbers in self.baseline], list(PurchaseFlow.steps))
        numbers = self.baseline[-1][1]
        self.assertEqual(numbers['order'][:2], ('purchase', 'invoiced'))
        self.assertEqual(numbers['onhand'], 4)
        self.assertEqual(numbers['pickings'], [('done', 2, 2)])
        self.assertEqual(numbers['bill'][:2], ('posted', 'not_paid'))
        self.assertEqual(numbers['bill'][5], numbers['bill'][6])

    def test_the_purchase_template(self):
        self._template('purchase', self.prof)
        self._identical()

    def test_the_accountant_template(self):
        self._template('accountant', self.prof)
        self._identical()

    def test_the_warehouse_template(self):
        self._template('warehouse', self.prof)
        self._identical()

    def test_the_templates_of_the_three_roles_together(self):
        for key in ('purchase', 'accountant', 'warehouse'):
            self._template(key, self.prof)
        self._identical()

    def test_the_app_user_template_of_the_three_apps(self):
        for xmlid in ('purchase.menu_purchase_root', 'stock.menu_stock_root', ACCOUNTING):
            app = self._menu(xmlid)
            if app:
                self._template('app_user', self.prof, app=app)
        self._identical()

    def test_the_auditor_template_refuses_the_rfq(self):
        self._template('auditor', self.prof)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('rfq', AccessError))
        self._nothing_left(flow)

    def test_the_switches_that_change_no_right(self):
        self._passes(
            block_export=True, block_import=True, block_duplicate=True, block_archive=True, hide_costs=True,
            hide_sale_prices=True, hide_settings_menu=True, block_developer_mode=True, hide_chatter_all=True,
            hide_activities=True, lock_statusbar=True, hide_print_all=True, hide_action_menu_all=True,
            hide_send_message_all=True, hide_followers_all=True, hide_attachments_all=True, block_rpc=True)

    def test_hidden_menus_of_other_apps(self):
        menus = self.env['ir.ui.menu']
        for xmlid in ('hr.menu_hr_root', 'project.menu_main_pm', 'crm.crm_menu_root', 'sale.sale_menu_root',
                      'mrp.menu_mrp_root', 'point_of_sale.menu_point_root', 'helpdesk.menu_helpdesk_root'):
            menus |= self._menu(xmlid)
        self.assertTrue(menus)
        self._passes(hidden_menu_ids=[Command.set(menus.ids)])

    def test_the_allowed_journals_and_warehouse(self):
        profile = self._template('purchase', self.prof)
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        purchases = self.env['account.journal'].search([
            ('type', '=', 'purchase'), ('company_id', '=', self.company.id), ('code', '=', self.baseline_journal)])
        profile.allowed_ids = [
            Command.create({'kind': 'journal', 'res_id': purchases.id}),
            Command.create({'kind': 'journal', 'res_id': self.bank.id}),
            Command.create({'kind': 'warehouse', 'res_id': warehouse.id}),
        ]
        self._identical()

    def test_the_read_only_profile_refuses_the_first_write(self):
        self._profile(self.prof, global_readonly=True)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('rfq', AccessError))
        self._nothing_left(flow)

    def test_no_creation_of_entries_stops_the_bill(self):
        profile = self._profile(self.prof)
        self._line(profile, 'account.move', perm_create=False)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('bill', AccessError))
        self.assertEqual(flow.trace, self.baseline[:3])
        self.assertEqual(flow.numbers(), self.baseline[2][1])
        self.assertEqual(flow.left_behind()['bills'], 0)
        self.assertEqual(flow.order.sudo().invoice_status, 'to invoice')

    def test_two_additive_profiles_one_read_only_and_one_full(self):
        readonly = self._profile(self.prof, name='MX Flow Read Only')
        full = self._profile(self.prof, name='MX Flow Full')
        for model_name in ('purchase.order', 'purchase.order.line'):
            self._line(readonly, model_name, perm_write=False, perm_create=False, perm_unlink=False)
            self._line(full, model_name)
        self._identical()

    def test_an_override_read_only_picking_refuses_the_receipt(self):
        override = self._profile(self.prof, name='MX Flow Picking Read Only', strictness='override')
        self._line(override, 'stock.picking', perm_write=False, perm_create=False, perm_unlink=False)
        full = self._profile(self.prof, name='MX Flow Full')
        for model_name in ('stock.picking', 'purchase.order'):
            self._line(full, model_name)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('receive', AccessError))
        self.assertEqual(flow.trace, self.baseline[:2])
        self.assertEqual(flow.numbers(), self.baseline[1][1])
        self.assertEqual(flow.left_behind()['onhand'], 0)
        self.assertEqual(flow.left_behind()['bills'], 0)

    def test_a_neutral_filter_on_every_model_changes_nothing(self):
        self._neutral(self.prof)
        self._identical()


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixExpenseFlow(FlowCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('hr.expense', 'account.move')
        manager_groups = ('base.group_user', 'hr_expense.group_hr_expense_manager', 'account.group_account_invoice')
        cls.employee_plain = cls._user('expense_employee_plain', 'base.group_user')
        cls.employee_prof = cls._user('expense_employee_prof', 'base.group_user')
        cls.manager_plain = cls._user('expense_manager_plain', *manager_groups)
        cls.manager_prof = cls._user('expense_manager_prof', *manager_groups)
        cls.record_plain = cls._employee_of(cls.employee_plain, expense_manager_id=cls.manager_plain.id)
        cls.record_prof = cls._employee_of(cls.employee_prof, expense_manager_id=cls.manager_prof.id)
        cls.expense_product = cls.env['product.product'].create({
            'name': 'MX Flow Expense', 'type': 'service', 'standard_price': 0.0, 'list_price': 0.0,
            'can_be_expensed': True})
        cls.baseline = ExpenseFlow(cls, cls.employee_plain, cls.manager_plain, cls.record_plain).run().trace
        cls.baseline_journal = cls.baseline[-1][1]['entry'][2]
        cls.both = cls.employee_prof | cls.manager_prof

    def _flow(self):
        return ExpenseFlow(self, self.employee_prof, self.manager_prof, self.record_prof)

    def _identical(self, users=None):
        for user in users or self.both:
            self.assertTrue(self.Profile._resolve(user.id).enabled, "the profile does not reach the user")
        self.assertEqual(self._trace(self._flow()), self.baseline)

    def _passes(self, **values):
        profile = self._profile(self.both, **values)
        self._identical()
        return profile

    def test_the_flow_without_a_profile(self):
        self.assertEqual([name for name, _numbers in self.baseline], list(ExpenseFlow.steps))
        numbers = self.baseline[-1][1]
        self.assertEqual(numbers['expense'][:4], ('posted', 'approved', 'own_account', 120.0))
        self.assertEqual(numbers['entry'][:2], ('posted', 'in_receipt'))
        self.assertEqual(numbers['entry'][3], 120.0)

    def test_the_hr_officer_template(self):
        self._template('hr_officer', self.both)
        self._identical()

    def test_the_accountant_template_of_the_manager(self):
        self._template('accountant', self.manager_prof)
        self._identical(self.manager_prof)

    def test_the_app_user_template_of_the_apps(self):
        for xmlid in ('hr_expense.menu_hr_expense_root', 'hr.menu_hr_root', ACCOUNTING):
            app = self._menu(xmlid)
            if app:
                self._template('app_user', self.both, app=app)
        self._identical()

    def test_the_switches_that_change_no_right(self):
        self._passes(
            block_export=True, block_import=True, block_duplicate=True, block_archive=True, hide_costs=True,
            hide_sale_prices=True, hide_settings_menu=True, block_developer_mode=True, hide_chatter_all=True,
            hide_activities=True, lock_statusbar=True, hide_print_all=True, hide_action_menu_all=True,
            hide_send_message_all=True, hide_followers_all=True, hide_attachments_all=True, block_rpc=True)

    def test_hidden_menus_of_other_apps(self):
        menus = self.env['ir.ui.menu']
        for xmlid in ('sale.sale_menu_root', 'project.menu_main_pm', 'crm.crm_menu_root', 'purchase.menu_purchase_root',
                      'mrp.menu_mrp_root', 'point_of_sale.menu_point_root', 'helpdesk.menu_helpdesk_root'):
            menus |= self._menu(xmlid)
        self.assertTrue(menus)
        self._passes(hidden_menu_ids=[Command.set(menus.ids)])

    def test_the_allowed_journals(self):
        journals = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('code', 'in', (self.baseline_journal, 'BILL', 'EXP'))])
        self.assertIn(self.baseline_journal, journals.mapped('code'))
        self._passes(allowed_ids=[Command.create({'kind': 'journal', 'res_id': journal.id}) for journal in journals])

    def test_the_read_only_profile_of_the_employee_refuses_the_expense(self):
        self._profile(self.employee_prof, global_readonly=True)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('create', AccessError))
        self._nothing_left(flow)

    def test_the_read_only_profile_of_the_manager_refuses_the_approval(self):
        self._profile(self.manager_prof, global_readonly=True)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('approve', AccessError))
        self.assertEqual(flow.trace, self.baseline[:2])
        self.assertEqual(flow.numbers(), self.baseline[1][1])
        self.assertEqual(flow.left_behind()['entries'], 0)

    def test_no_creation_of_entries_leaves_the_entry_core_makes_for_an_expense(self):
        """ Core makes the entry of an approved expense in sudo: the manager's profile does not stop it. """
        profile = self._profile(self.manager_prof)
        self._line(profile, 'account.move', perm_create=False)
        self._identical(self.manager_prof)

    def test_two_additive_profiles_one_read_only_and_one_full(self):
        readonly = self._profile(self.both, name='MX Flow Read Only')
        full = self._profile(self.both, name='MX Flow Full')
        self._line(readonly, 'hr.expense', perm_write=False, perm_create=False, perm_unlink=False)
        self._line(full, 'hr.expense')
        self._identical()

    def test_an_override_read_only_expense_refuses_the_submission(self):
        override = self._profile(self.both, name='MX Flow Expense Read Only', strictness='override')
        self._line(override, 'hr.expense', perm_write=False, perm_create=False, perm_unlink=False)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('create', AccessError))
        self._nothing_left(flow)

    def test_a_neutral_filter_on_every_model_changes_nothing(self):
        self._neutral(self.both)
        self._identical()


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixProjectFlow(FlowCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('project.task', 'account.analytic.line', 'hr.employee')
        cls._need_field('account.analytic.line', 'employee_id')
        groups = ('base.group_user', 'project.group_project_user', 'hr_timesheet.group_hr_timesheet_user')
        cls.plain = cls._user('project_plain', *groups)
        cls.prof = cls._user('project_prof', *groups)
        cls.record_plain = cls._employee_of(cls.plain)
        cls.record_prof = cls._employee_of(cls.prof)
        cls.project = cls.env['project.project'].create({'name': 'MX Flow Project', 'allow_timesheets': True})
        cls.stage_todo, cls.stage_done = cls.env['project.task.type'].create([
            {'name': 'MX Flow To Do', 'sequence': 1, 'project_ids': [Command.set(cls.project.ids)]},
            {'name': 'MX Flow Done', 'sequence': 2, 'project_ids': [Command.set(cls.project.ids)]},
        ])
        cls.baseline = ProjectFlow(cls, cls.plain, cls.record_plain).run().trace

    def _flow(self):
        return ProjectFlow(self, self.prof, self.record_prof)

    def _identical(self):
        self.assertTrue(self.Profile._resolve(self.prof.id).enabled, "the profile does not reach the user")
        self.assertEqual(self._trace(self._flow()), self.baseline)

    def _passes(self, **values):
        profile = self._profile(self.prof, **values)
        self._identical()
        return profile

    def test_the_flow_without_a_profile(self):
        self.assertEqual([name for name, _numbers in self.baseline], list(ProjectFlow.steps))
        numbers = self.baseline[-1][1]
        self.assertEqual(numbers['task'], ('MX Flow Done', 'MX Flow Project', 2.5, 1))
        self.assertEqual(numbers['line'][:3], (2.5, True, True))

    def test_the_app_user_template_of_the_apps(self):
        for xmlid in ('project.menu_main_pm', 'hr_timesheet.timesheet_menu_root'):
            app = self._menu(xmlid)
            if app:
                self._template('app_user', self.prof, app=app)
        self._identical()

    def test_the_hr_officer_template(self):
        self._template('hr_officer', self.prof)
        self._identical()

    def test_the_switches_that_change_no_right(self):
        self._passes(
            block_export=True, block_import=True, block_duplicate=True, block_archive=True, hide_costs=True,
            hide_sale_prices=True, hide_settings_menu=True, block_developer_mode=True, hide_chatter_all=True,
            hide_activities=True, lock_statusbar=True, hide_print_all=True, hide_action_menu_all=True,
            hide_send_message_all=True, hide_followers_all=True, hide_attachments_all=True, block_rpc=True)

    def test_hidden_menus_of_other_apps(self):
        menus = self.env['ir.ui.menu']
        for xmlid in ('sale.sale_menu_root', 'hr.menu_hr_root', 'crm.crm_menu_root', 'purchase.menu_purchase_root',
                      'mrp.menu_mrp_root', 'point_of_sale.menu_point_root', 'helpdesk.menu_helpdesk_root'):
            menus |= self._menu(xmlid)
        self.assertTrue(menus)
        self._passes(hidden_menu_ids=[Command.set(menus.ids)])

    def test_own_records(self):
        profile = self._profile(self.prof)
        self._line(profile, 'project.task', domain="[('user_ids', 'in', [user.id])]")
        self._line(profile, 'account.analytic.line', domain="[('user_id', '=', user.id)]")
        self._identical()

    def test_the_read_only_profile_refuses_the_task(self):
        self._profile(self.prof, global_readonly=True)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('task', AccessError))
        self._nothing_left(flow)

    def test_no_creation_of_timesheets_refuses_the_timesheet_only(self):
        profile = self._profile(self.prof)
        self._line(profile, 'account.analytic.line', perm_create=False)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('timesheet', AccessError))
        self.assertEqual(flow.trace, self.baseline[:1])
        self.assertEqual(flow.left_behind()['timesheets'], 0)

    def test_two_additive_profiles_one_read_only_and_one_full(self):
        readonly = self._profile(self.prof, name='MX Flow Read Only')
        full = self._profile(self.prof, name='MX Flow Full')
        for model_name in ('project.task', 'account.analytic.line'):
            self._line(readonly, model_name, perm_write=False, perm_create=False, perm_unlink=False)
            self._line(full, model_name)
        self._identical()

    def test_an_override_read_only_task_refuses_the_stage_change(self):
        override = self._profile(self.prof, name='MX Flow Task Read Only', strictness='override')
        self._line(override, 'project.task', perm_write=False, perm_unlink=False)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('stage', AccessError))
        self.assertEqual(flow.trace, self.baseline[:2])
        self.assertEqual(flow.numbers(), self.baseline[1][1])

    def test_a_neutral_filter_on_every_model_changes_nothing(self):
        self._neutral(self.prof)
        self._identical()


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixHelpdeskFlow(FlowCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('helpdesk.ticket')
        groups = ('base.group_user', 'helpdesk.group_helpdesk_user')
        cls.plain = cls._user('helpdesk_plain', *groups)
        cls.prof = cls._user('helpdesk_prof', *groups)
        cls.customer = cls.env['res.partner'].create({'name': 'MX Flow Helpdesk Customer'})
        cls.team = cls.env['helpdesk.team'].create({
            'name': 'MX Flow Team', 'privacy_visibility': 'internal',
            'member_ids': [Command.set((cls.plain | cls.prof).ids)]})
        cls.team.stage_ids = False
        cls.stage_new, cls.stage_done = cls.env['helpdesk.stage'].create([
            {'name': 'MX Flow New', 'sequence': 10, 'team_ids': [Command.set(cls.team.ids)]},
            {'name': 'MX Flow Done', 'sequence': 30, 'fold': True, 'team_ids': [Command.set(cls.team.ids)]},
        ])
        cls.team.use_sla = True
        cls.env['helpdesk.sla'].create({
            'name': 'MX Flow SLA', 'team_id': cls.team.id, 'stage_id': cls.stage_done.id, 'time': 8.0})
        cls.baseline = HelpdeskFlow(cls, cls.plain, cls.customer).run().trace

    def _flow(self):
        return HelpdeskFlow(self, self.prof, self.customer)

    def _identical(self):
        self.assertTrue(self.Profile._resolve(self.prof.id).enabled, "the profile does not reach the user")
        self.assertEqual(self._trace(self._flow()), self.baseline)

    def _passes(self, **values):
        profile = self._profile(self.prof, **values)
        self._identical()
        return profile

    def test_the_flow_without_a_profile(self):
        self.assertEqual([name for name, _numbers in self.baseline], list(HelpdeskFlow.steps))
        self.assertEqual(self.baseline[-1][1]['ticket'], ('MX Flow Done', True, True, True, 'MX Flow Team', False))
        self.assertEqual(self.baseline[-1][1]['sla'], [('MX Flow SLA', True)])

    def test_the_app_user_template(self):
        app = self._menu('helpdesk.menu_helpdesk_root')
        self.assertTrue(app)
        self._template('app_user', self.prof, app=app)
        self._identical()

    def test_the_switches_that_change_no_right(self):
        self._passes(
            block_export=True, block_import=True, block_duplicate=True, block_archive=True, hide_costs=True,
            hide_sale_prices=True, hide_settings_menu=True, block_developer_mode=True, hide_chatter_all=True,
            hide_activities=True, lock_statusbar=True, hide_print_all=True, hide_action_menu_all=True,
            hide_send_message_all=True, hide_followers_all=True, hide_attachments_all=True, block_rpc=True)

    def test_hidden_menus_of_other_apps(self):
        menus = self.env['ir.ui.menu']
        for xmlid in ('sale.sale_menu_root', 'hr.menu_hr_root', 'crm.crm_menu_root', 'purchase.menu_purchase_root',
                      'mrp.menu_mrp_root', 'point_of_sale.menu_point_root', 'project.menu_main_pm'):
            menus |= self._menu(xmlid)
        self.assertTrue(menus)
        self._passes(hidden_menu_ids=[Command.set(menus.ids)])

    def test_own_tickets(self):
        profile = self._profile(self.prof)
        self._line(profile, 'helpdesk.ticket', domain="['|', ('user_id', '=', user.id), ('user_id', '=', False)]")
        self._identical()

    def test_the_read_only_profile_refuses_the_ticket(self):
        self._profile(self.prof, global_readonly=True)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('create', AccessError))
        self._nothing_left(flow)

    def test_no_creation_of_tickets(self):
        profile = self._profile(self.prof)
        self._line(profile, 'helpdesk.ticket', perm_create=False)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('create', AccessError))
        self._nothing_left(flow)

    def test_no_edit_of_tickets_refuses_the_creation_that_writes(self):
        profile = self._profile(self.prof)
        self._line(profile, 'helpdesk.ticket', perm_write=False)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('create', AccessError))
        self.assertIn('Helpdesk Ticket', str(refused.error))
        self._nothing_left(flow)

    def test_only_unassigned_tickets_can_be_edited_refuses_the_closing(self):
        profile = self._profile(self.prof)
        self._line(profile, 'helpdesk.ticket', domain_write="[('user_id', '=', False)]")
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('close', AccessError))
        self.assertEqual(flow.trace, self.baseline[:2])
        self.assertEqual(flow.numbers(), self.baseline[1][1])

    def test_two_additive_profiles_one_read_only_and_one_full(self):
        readonly = self._profile(self.prof, name='MX Flow Read Only')
        full = self._profile(self.prof, name='MX Flow Full')
        self._line(readonly, 'helpdesk.ticket', perm_write=False, perm_create=False, perm_unlink=False)
        self._line(full, 'helpdesk.ticket')
        self._identical()

    def test_a_neutral_filter_on_every_model_changes_nothing(self):
        self._neutral(self.prof)
        self._identical()


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixProductionFlow(FlowCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('mrp.production', 'stock.picking')
        groups = ('base.group_user', 'mrp.group_mrp_user', 'stock.group_stock_user', 'quality.group_quality_manager')
        cls.plain = cls._user('mrp_plain', *groups)
        cls.prof = cls._user('mrp_prof', *groups)
        Product = cls.env['product.product']
        cls.finished = Product.create({
            'name': 'MX Flow Finished', 'default_code': 'MXFF', 'type': 'consu', 'is_storable': True})
        cls.component = Product.create({
            'name': 'MX Flow Component', 'default_code': 'MXFK', 'type': 'consu', 'is_storable': True})
        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.finished.product_tmpl_id.id, 'product_qty': 1.0, 'type': 'normal',
            'bom_line_ids': [Command.create({'product_id': cls.component.id, 'product_qty': 2.0})]})
        cls.baseline = ProductionFlow(cls, cls.plain).run().trace

    def _flow(self):
        return ProductionFlow(self, self.prof)

    def _identical(self):
        self.assertTrue(self.Profile._resolve(self.prof.id).enabled, "the profile does not reach the user")
        self.assertEqual(self._trace(self._flow()), self.baseline)

    def _passes(self, **values):
        profile = self._profile(self.prof, **values)
        self._identical()
        return profile

    def test_the_flow_without_a_profile(self):
        self.assertEqual([name for name, _numbers in self.baseline], list(ProductionFlow.steps))
        numbers = self.baseline[-1][1]
        self.assertEqual(numbers['production'][0], 'done')
        self.assertEqual((numbers['components'], numbers['produced']), (-10.0, 5.0))

    def test_the_warehouse_template(self):
        self._template('warehouse', self.prof)
        self._identical()

    def test_the_app_user_template_of_the_apps(self):
        for xmlid in ('mrp.menu_mrp_root', 'stock.menu_stock_root'):
            app = self._menu(xmlid)
            if app:
                self._template('app_user', self.prof, app=app)
        self._identical()

    def test_the_switches_that_change_no_right(self):
        self._passes(
            block_export=True, block_import=True, block_duplicate=True, block_archive=True, hide_costs=True,
            hide_sale_prices=True, hide_settings_menu=True, block_developer_mode=True, hide_chatter_all=True,
            hide_activities=True, lock_statusbar=True, hide_print_all=True, hide_action_menu_all=True,
            hide_send_message_all=True, hide_followers_all=True, hide_attachments_all=True, block_rpc=True)

    def test_hidden_menus_of_other_apps(self):
        menus = self.env['ir.ui.menu']
        for xmlid in ('sale.sale_menu_root', 'hr.menu_hr_root', 'crm.crm_menu_root', 'purchase.menu_purchase_root',
                      'project.menu_main_pm', 'point_of_sale.menu_point_root', 'helpdesk.menu_helpdesk_root'):
            menus |= self._menu(xmlid)
        self.assertTrue(menus)
        self._passes(hidden_menu_ids=[Command.set(menus.ids)])

    def test_the_allowed_warehouse(self):
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        self._passes(allowed_ids=[Command.create({'kind': 'warehouse', 'res_id': warehouse.id})])

    def test_the_read_only_profile_refuses_the_order(self):
        self._profile(self.prof, global_readonly=True)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('create', AccessError))
        self._nothing_left(flow)

    def test_an_override_read_only_move_refuses_the_production(self):
        override = self._profile(self.prof, name='MX Flow Moves Read Only', strictness='override')
        self._line(override, 'stock.move', perm_write=False, perm_create=False, perm_unlink=False)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertIsInstance(refused.error, AccessError)
        self.assertEqual(flow.left_behind()['finished'], 0)
        self.assertEqual(flow.left_behind()['components'], 0)

    def test_two_additive_profiles_one_read_only_and_one_full(self):
        readonly = self._profile(self.prof, name='MX Flow Read Only')
        full = self._profile(self.prof, name='MX Flow Full')
        self._line(readonly, 'mrp.production', perm_write=False, perm_create=False, perm_unlink=False)
        self._line(full, 'mrp.production')
        self._identical()

    def test_a_neutral_filter_on_every_model_changes_nothing(self):
        self._neutral(self.prof)
        self._identical()


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixSaleFlowClient(FlowCase, HttpCase):
    """ The same flow through /web/dataset: the field, button, archive and read guards of the client door apply. """

    SWITCHES = (
        'block_export', 'block_import', 'block_duplicate', 'block_archive', 'hide_costs', 'hide_sale_prices',
        'hide_settings_menu', 'block_developer_mode', 'hide_chatter_all', 'hide_activities', 'lock_statusbar',
        'hide_print_all', 'hide_action_menu_all', 'hide_send_message_all', 'hide_followers_all',
        'hide_attachments_all', 'block_custom_filter', 'block_custom_group', 'block_favorites', 'block_properties',
        'block_apps',
    )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('sale.order', 'stock.picking', 'account.move')
        cls._need_field('sale.order', 'picking_ids')
        env = cls.env
        groups = ('base.group_user', 'sales_team.group_sale_salesman', 'stock.group_stock_user',
                  'account.group_account_invoice')
        cls.plain = cls._user('client_plain', *groups)
        cls.prof = cls._user('client_prof', *groups)
        cls.partner_plain = env['res.partner'].create({'name': 'MX Flow Client Plain', 'user_id': cls.plain.id})
        cls.partner_prof = env['res.partner'].create({'name': 'MX Flow Client Prof', 'user_id': cls.prof.id})
        cls._products()
        cls.bank = env['account.journal'].search([('type', '=', 'bank'), ('company_id', '=', cls.company.id)], limit=1)

    def setUp(self):
        super().setUp()
        self.baseline = RpcSaleFlow(self, self.plain, self.partner_plain).run().trace

    def _flow(self):
        return RpcSaleFlow(self, self.prof, self.partner_prof)

    def _identical(self):
        self.assertTrue(self.Profile._resolve(self.prof.id).enabled, "the profile does not reach the user")
        self.assertEqual(self._trace(self._flow()), self.baseline)

    def _passes(self, **values):
        profile = self._profile(self.prof, **values)
        self._identical()
        return profile

    def test_the_flow_without_a_profile(self):
        self.assertEqual([name for name, _numbers in self.baseline], list(SaleFlow.steps))
        numbers = self.baseline[-1][1]
        self.assertEqual(numbers['order'][:2], ('sale', 'invoiced'))
        self.assertEqual(numbers['order'][4], 460.0)
        self.assertEqual(numbers['onhand'], -3)
        self.assertEqual(numbers['invoice'][:2], ('posted', 'in_payment'))

    def test_the_templates_of_the_three_roles(self):
        for key in ('salesperson', 'accountant', 'warehouse'):
            self._template(key, self.prof)
        self._identical()

    def test_each_switch_alone(self):
        for name in self.SWITCHES:
            with self.subTest(switch=name), self._undone():
                self._profile(self.prof, **{name: True})
                self._identical()

    def test_every_switch_at_once(self):
        self._passes(**dict.fromkeys(self.SWITCHES, True))

    def test_the_switches_of_the_models_of_the_flow(self):
        flags = ('hide_chatter', 'hide_export', 'hide_import', 'hide_archive', 'hide_duplicate', 'hide_print',
                 'hide_action_menu', 'hide_send_message', 'hide_followers', 'hide_attachments')
        profile = self._profile(self.prof)
        for model_name in ('sale.order', 'sale.order.line', 'stock.picking', 'stock.move', 'account.move',
                           'account.payment', 'account.payment.register', 'sale.advance.payment.inv'):
            self._line(profile, model_name, **dict.fromkeys(flags, True))
        self._identical()

    def test_hidden_prices_leave_the_numbers_of_the_order_untouched(self):
        self._passes(hide_sale_prices=True, hide_costs=True)

    def test_a_client_does_not_read_the_prices_hidden_to_it(self):
        self._profile(self.prof, hide_sale_prices=True)
        flow = self._flow().run(until='quote')
        shown = flow.rpc('sale.order', 'web_read', [flow.order.ids], {'specification': {'amount_total': {}}})
        self.assertFalse(shown[0]['amount_total'])
        self.assertEqual(flow.order.sudo().amount_total, 460.0)

    def test_field_rules_on_fields_the_flow_leaves_alone(self):
        fields = self.env['ir.model.fields']
        profile = self._profile(self.prof)
        for model_name, field_name, mode in (
                ('res.partner', 'function', 'hide'), ('res.partner', 'website', 'readonly'),
                ('sale.order', 'client_order_ref', 'readonly'), ('sale.order', 'note', 'hide'),
                ('sale.order.line', 'discount', 'hide'), ('stock.picking', 'origin', 'readonly'),
                ('account.move', 'narration', 'hide'), ('account.move', 'ref', 'readonly')):
            field = fields._get(model_name, field_name)
            if field:
                profile.field_ids = [Command.create({'model_id': field.model_id.id, 'field_id': field.id, 'mode': mode})]
        self.assertTrue(profile.field_ids)
        self._identical()

    def test_a_required_field_rule_is_a_rule_of_the_view(self):
        field = self.env['ir.model.fields']._get('sale.order', 'client_order_ref')
        profile = self._profile(self.prof)
        profile.field_ids = [Command.create({'model_id': field.model_id.id, 'field_id': field.id, 'mode': 'required'})]
        self._identical()

    def test_a_blocked_button_that_is_not_in_the_flow(self):
        profile = self._profile(self.prof)
        for model_name, button in (('sale.order', 'action_cancel'), ('sale.order', 'action_draft'),
                                   ('account.move', 'button_draft'), ('account.move', 'button_cancel'),
                                   ('stock.picking', 'action_cancel')):
            profile.button_ids = [Command.create({
                'model_id': self.env['ir.model']._get(model_name).id, 'button_name': button, 'mode': 'hide_block'})]
        self._identical()

    def test_the_blocked_confirm_button(self):
        profile = self._profile(self.prof)
        profile.button_ids = [Command.create({
            'model_id': self.env['ir.model']._get('sale.order').id, 'button_name': 'action_confirm',
            'mode': 'hide_block'})]
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('confirm', AccessError))
        self.assertEqual(flow.trace, self.baseline[:1])
        self.assertEqual(flow.numbers(), self.baseline[0][1])
        self.assertEqual(flow.order.sudo().picking_ids, self.env['stock.picking'])

    def test_the_blocked_validate_button(self):
        profile = self._profile(self.prof)
        profile.button_ids = [Command.create({
            'model_id': self.env['ir.model']._get('stock.picking').id, 'button_name': 'button_validate',
            'mode': 'hide_block'})]
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('deliver', AccessError))
        numbers = flow.numbers()
        self.assertEqual(numbers['onhand'], 0)
        self.assertEqual(numbers['order'][:2], ('sale', 'no'))
        self.assertEqual([state for state, _moves, _lines in numbers['pickings']], ['assigned'])
        self.assertEqual(flow.left_behind()['invoices'], 0)

    def test_the_blocked_validate_button_leaves_the_server_side_validation_alone(self):
        profile = self._profile(self.prof)
        profile.button_ids = [Command.create({
            'model_id': self.env['ir.model']._get('stock.picking').id, 'button_name': 'button_validate',
            'mode': 'hide_block'})]
        flow = SaleFlow(self, self.prof, self.partner_prof)
        self.assertEqual(self._trace(flow), self.baseline)

    def test_own_orders_in_the_allowed_journals_and_warehouse(self):
        profile = self._template('salesperson', self.prof)
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        sales = self.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', self.company.id), ('code', '=', self.baseline[-1][1]['invoice'][2])])
        profile.allowed_ids = [
            Command.create({'kind': 'journal', 'res_id': sales.id}),
            Command.create({'kind': 'journal', 'res_id': self.bank.id}),
            Command.create({'kind': 'warehouse', 'res_id': warehouse.id}),
        ]
        self._identical()

    def test_the_read_only_profile_refuses_the_quotation(self):
        self._profile(self.prof, global_readonly=True)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('quote', AccessError))
        self._nothing_left(flow)

    def test_a_neutral_filter_on_every_model_changes_nothing(self):
        self._neutral(self.prof)
        self._identical()


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixPosFlow(FlowCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('pos.session', 'pos.order', 'account.move')
        env = cls.env
        groups = ('base.group_user', 'point_of_sale.group_pos_manager', 'stock.group_stock_user')
        cls.plain = cls._user('pos_plain', *groups)
        cls.prof = cls._user('pos_prof', *groups)
        cash = env['account.journal'].create({'name': 'MX Flow POS Cash', 'code': 'MXPC', 'type': 'cash'})
        sales = env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', cls.company.id), ('code', '=', 'INV')], limit=1)
        cls.pos_method = env['pos.payment.method'].create({'name': 'MX Flow Cash', 'type': 'cash', 'journal_id': cash.id})
        cls.config = env['pos.config'].create({
            'name': 'MX Flow POS', 'payment_method_ids': [Command.set(cls.pos_method.ids)], 'journal_id': sales.id})
        cls.pos_product = env['product.product'].create({
            'name': 'MX Flow POS Product', 'type': 'consu', 'is_storable': False, 'list_price': 10.0,
            'available_in_pos': True, 'taxes_id': [Command.clear()]})
        cls.baseline = PosFlow(cls, cls.plain).run().trace

    def _flow(self):
        return PosFlow(self, self.prof)

    def _identical(self):
        self.assertTrue(self.Profile._resolve(self.prof.id).enabled, "the profile does not reach the user")
        self.assertEqual(self._trace(self._flow()), self.baseline)

    def _passes(self, **values):
        profile = self._profile(self.prof, **values)
        self._identical()
        return profile

    def test_the_flow_without_a_profile(self):
        self.assertEqual([name for name, _numbers in self.baseline], list(PosFlow.steps))
        numbers = self.baseline[-1][1]
        self.assertEqual(numbers['session'][0], 'closed')
        self.assertEqual(numbers['order'][:3], ('done', 20.0, 20.0))

    def test_the_cashier_template(self):
        self._template('cashier', self.prof)
        self._identical()

    def test_the_accountant_template(self):
        self._template('accountant', self.prof)
        self._identical()

    def test_the_app_user_template_of_the_apps(self):
        for xmlid in ('point_of_sale.menu_point_root', ACCOUNTING):
            app = self._menu(xmlid)
            if app:
                self._template('app_user', self.prof, app=app)
        self._identical()

    def test_the_switches_that_change_no_right(self):
        self._passes(
            block_export=True, block_import=True, block_duplicate=True, block_archive=True, hide_costs=True,
            hide_sale_prices=True, hide_settings_menu=True, block_developer_mode=True, hide_chatter_all=True,
            hide_activities=True, lock_statusbar=True, hide_print_all=True, hide_action_menu_all=True,
            hide_send_message_all=True, hide_followers_all=True, hide_attachments_all=True, block_rpc=True)

    def test_hidden_menus_of_other_apps(self):
        menus = self.env['ir.ui.menu']
        for xmlid in ('sale.sale_menu_root', 'hr.menu_hr_root', 'crm.crm_menu_root', 'purchase.menu_purchase_root',
                      'mrp.menu_mrp_root', 'project.menu_main_pm', 'helpdesk.menu_helpdesk_root'):
            menus |= self._menu(xmlid)
        self.assertTrue(menus)
        self._passes(hidden_menu_ids=[Command.set(menus.ids)])

    def test_the_allowed_point_of_sale(self):
        self._passes(allowed_ids=[Command.create({'kind': 'pos', 'res_id': self.config.id})])

    def test_another_point_of_sale_is_not_reachable(self):
        cash = self.env['account.journal'].create({'name': 'MX Flow Other POS Cash', 'code': 'MXPO', 'type': 'cash'})
        method = self.env['pos.payment.method'].create({'name': 'MX Flow Other Cash', 'type': 'cash', 'journal_id': cash.id})
        other = self.env['pos.config'].create({
            'name': 'MX Flow Other POS', 'payment_method_ids': [Command.set(method.ids)],
            'journal_id': self.config.journal_id.id})
        self._profile(self.prof, allowed_ids=[Command.create({'kind': 'pos', 'res_id': other.id})])
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertIsInstance(refused.error, AccessError)
        self.assertEqual(refused.step, 'open')
        self._nothing_left(flow)

    def test_the_read_only_profile_refuses_the_register(self):
        self._profile(self.prof, global_readonly=True)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('open', AccessError))
        self._nothing_left(flow)

    def test_no_creation_of_orders_refuses_the_sale(self):
        profile = self._profile(self.prof)
        self._line(profile, 'pos.order', perm_create=False)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('order', AccessError))
        self.assertEqual(flow.trace, self.baseline[:1])
        self.assertEqual(flow.left_behind()['orders'], 0)

    def test_no_edit_of_sessions_refuses_the_closing(self):
        profile = self._profile(self.prof)
        self._line(profile, 'pos.session', perm_write=False)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('open', AccessError))
        self._nothing_left(flow)

    def test_two_additive_profiles_one_read_only_and_one_full(self):
        readonly = self._profile(self.prof, name='MX Flow Read Only')
        full = self._profile(self.prof, name='MX Flow Full')
        for model_name in ('pos.order', 'pos.session', 'pos.payment'):
            self._line(readonly, model_name, perm_write=False, perm_create=False, perm_unlink=False)
            self._line(full, model_name)
        self._identical()

    def test_a_neutral_filter_on_every_model_changes_nothing(self):
        self._neutral(self.prof)
        self._identical()


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixSaleVariants(FlowCase):
    """ The same profiles on the other ways a sale goes: what the module must not break or must only refuse clearly. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('sale.order', 'stock.picking', 'account.move')
        cls._need_field('sale.order', 'picking_ids')
        env = cls.env
        groups = ('base.group_user', 'sales_team.group_sale_salesman', 'stock.group_stock_user',
                  'account.group_account_invoice', 'quality.group_quality_manager')
        cls.plain = cls._user('variant_plain', *groups)
        cls.prof = cls._user('variant_prof', *groups)
        cls.partner_plain = env['res.partner'].create({'name': 'MX Flow Variant Plain', 'user_id': cls.plain.id})
        cls.partner_prof = env['res.partner'].create({'name': 'MX Flow Variant Prof', 'user_id': cls.prof.id})
        cls._products()
        cls.bank = env['account.journal'].search([('type', '=', 'bank'), ('company_id', '=', cls.company.id)], limit=1)
        cls.baselines = {
            variant: SaleVariantFlow(cls, cls.plain, cls.partner_plain, variant).run().trace
            for variant in SaleVariantFlow.VARIANT_STEPS}

    def _each_variant(self, label=None):
        self.assertTrue(self.Profile._resolve(self.prof.id).enabled, "the profile does not reach the user")
        for variant, baseline in self.baselines.items():
            with self.subTest(variant=variant, profile=label):
                flow = SaleVariantFlow(self, self.prof, self.partner_prof, variant)
                self.assertEqual(self._trace(flow), baseline)

    def test_the_variants_without_a_profile(self):
        self.assertEqual(self.baselines['partial'][-1][1]['all_pickings'],
                         [('done', False, 'outgoing'), ('done', True, 'outgoing')])
        self.assertAlmostEqual(self.baselines['edit'][-1][1]['order'][4], 4 * 100 * 1.15 + 2 * 50 * 1.15)
        self.assertEqual(self.baselines['resize'][-1][1]['onhand'], -5)
        self.assertEqual(self.baselines['cancel'][-1][1]['order'][0], 'cancel')
        self.assertEqual(self.baselines['cancel'][-1][1]['all_pickings'], [('cancel', False, 'outgoing')])
        self.assertEqual([move[:2] for move in self.baselines['refund'][-1][1]['moves']],
                         [('out_invoice', 'posted'), ('out_refund', 'posted')])
        self.assertEqual(self.baselines['refund'][-1][1]['onhand'], 0)
        self.assertAlmostEqual(self.baselines['edit_invoice'][-1][1]['invoice'][5], 2 * 90.0 * 1.15 + 2 * 50 * 1.15)

    def test_the_salesperson_template(self):
        self._template('salesperson', self.prof)
        self._each_variant()

    def test_the_accountant_template(self):
        self._template('accountant', self.prof)
        self._each_variant()

    def test_the_warehouse_template(self):
        self._template('warehouse', self.prof)
        self._each_variant()

    def test_the_templates_of_the_three_roles_together(self):
        for key in ('salesperson', 'accountant', 'warehouse'):
            self._template(key, self.prof)
        self._each_variant()

    def test_the_app_user_template_of_the_three_apps(self):
        for xmlid in ('sale.sale_menu_root', 'stock.menu_stock_root', ACCOUNTING):
            app = self._menu(xmlid)
            if app:
                self._template('app_user', self.prof, app=app)
        self._each_variant()

    def test_the_app_user_template_of_each_app_alone(self):
        for xmlid in ('sale.sale_menu_root', 'stock.menu_stock_root', ACCOUNTING):
            with self._undone():
                self._template('app_user', self.prof, app=self._menu(xmlid))
                self._each_variant(label=xmlid)

    def test_the_salesperson_can_delete_a_line_of_a_draft_quotation(self):
        self._template('salesperson', self.prof)
        flow = SaleVariantFlow(self, self.prof, self.partner_prof, 'edit')
        self.assertEqual(self._trace(flow), self.baselines['edit'])

    def test_the_switches_that_change_no_right(self):
        self._profile(self.prof, **dict.fromkeys((
            'block_export', 'block_import', 'block_duplicate', 'block_archive', 'hide_costs', 'hide_sale_prices',
            'hide_settings_menu', 'block_developer_mode', 'hide_chatter_all', 'hide_activities', 'lock_statusbar',
            'hide_print_all', 'hide_action_menu_all', 'hide_send_message_all', 'hide_followers_all',
            'hide_attachments_all'), True))
        self._each_variant()

    def test_a_neutral_filter_on_every_model_changes_nothing(self):
        self._neutral(self.prof)
        self._each_variant()

    def test_own_records_in_the_allowed_journals_and_warehouse(self):
        profile = self._template('salesperson', self.prof)
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        journals = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('code', 'in', ('INV', self.bank.code))])
        profile.allowed_ids = [Command.create({'kind': 'journal', 'res_id': journal.id}) for journal in journals] + [
            Command.create({'kind': 'warehouse', 'res_id': warehouse.id})]
        self._each_variant()


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixPurchaseVariants(FlowCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('purchase.order', 'stock.picking', 'account.move')
        cls._need_field('purchase.order', 'picking_ids')
        env = cls.env
        groups = ('base.group_user', 'purchase.group_purchase_user', 'stock.group_stock_user',
                  'account.group_account_invoice', 'quality.group_quality_manager')
        cls.plain = cls._user('pvariant_plain', *groups)
        cls.prof = cls._user('pvariant_prof', *groups)
        cls.vendor_plain = env['res.partner'].create({'name': 'MX Flow PVariant Plain'})
        cls.vendor_prof = env['res.partner'].create({'name': 'MX Flow PVariant Prof'})
        cls._products()
        cls.baselines = {
            variant: PurchaseVariantFlow(cls, cls.plain, cls.vendor_plain, variant).run().trace
            for variant in PurchaseVariantFlow.VARIANT_STEPS}

    def _each_variant(self, label=None):
        self.assertTrue(self.Profile._resolve(self.prof.id).enabled, "the profile does not reach the user")
        for variant, baseline in self.baselines.items():
            with self.subTest(variant=variant, profile=label):
                flow = PurchaseVariantFlow(self, self.prof, self.vendor_prof, variant)
                self.assertEqual(self._trace(flow), baseline)

    def test_the_variants_without_a_profile(self):
        self.assertEqual(self.baselines['partial'][-1][1]['all_pickings'],
                         [('done', False, 'incoming'), ('done', True, 'incoming')])
        self.assertEqual(self.baselines['cancel'][-1][1]['order'][0], 'cancel')
        self.assertEqual(self.baselines['edit'][-1][1]['lines'][0][1], 6.0)
        self.assertEqual([move[:2] for move in self.baselines['refund'][-1][1]['moves']],
                         [('in_invoice', 'posted'), ('in_refund', 'posted')])
        self.assertEqual(self.baselines['refund'][-1][1]['onhand'], 0)

    def test_the_purchase_template(self):
        self._template('purchase', self.prof)
        self._each_variant()

    def test_the_accountant_template(self):
        self._template('accountant', self.prof)
        self._each_variant()

    def test_the_warehouse_template(self):
        self._template('warehouse', self.prof)
        self._each_variant()

    def test_the_templates_of_the_three_roles_together(self):
        for key in ('purchase', 'accountant', 'warehouse'):
            self._template(key, self.prof)
        self._each_variant()

    def test_the_app_user_template_of_each_app_alone(self):
        for xmlid in ('purchase.menu_purchase_root', 'stock.menu_stock_root', ACCOUNTING):
            with self._undone():
                self._template('app_user', self.prof, app=self._menu(xmlid))
                self._each_variant(label=xmlid)

    def test_the_switches_that_change_no_right(self):
        self._profile(self.prof, **dict.fromkeys((
            'block_export', 'block_import', 'block_duplicate', 'block_archive', 'hide_costs', 'hide_sale_prices',
            'hide_settings_menu', 'block_developer_mode', 'hide_chatter_all', 'hide_activities', 'lock_statusbar',
            'hide_print_all', 'hide_action_menu_all', 'hide_send_message_all', 'hide_followers_all',
            'hide_attachments_all'), True))
        self._each_variant()

    def test_a_neutral_filter_on_every_model_changes_nothing(self):
        self._neutral(self.prof)
        self._each_variant()


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixProductionVariants(FlowCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('mrp.production', 'stock.picking')
        groups = ('base.group_user', 'mrp.group_mrp_user', 'stock.group_stock_user', 'quality.group_quality_manager')
        cls.plain = cls._user('mvariant_plain', *groups)
        cls.prof = cls._user('mvariant_prof', *groups)
        Product = cls.env['product.product']
        cls.finished = Product.create({
            'name': 'MX Flow Finished', 'default_code': 'MXFF', 'type': 'consu', 'is_storable': True})
        cls.component = Product.create({
            'name': 'MX Flow Component', 'default_code': 'MXFK', 'type': 'consu', 'is_storable': True})
        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.finished.product_tmpl_id.id, 'product_qty': 1.0, 'type': 'normal',
            'bom_line_ids': [Command.create({'product_id': cls.component.id, 'product_qty': 2.0})]})
        cls.baselines = {
            variant: ProductionVariantFlow(cls, cls.plain, variant).run().trace
            for variant in ProductionVariantFlow.VARIANT_STEPS}

    def _each_variant(self, label=None):
        self.assertTrue(self.Profile._resolve(self.prof.id).enabled, "the profile does not reach the user")
        for variant, baseline in self.baselines.items():
            with self.subTest(variant=variant, profile=label):
                flow = ProductionVariantFlow(self, self.prof, variant)
                self.assertEqual(self._trace(flow), baseline)

    def test_the_variants_without_a_profile(self):
        self.assertEqual([state for state, _qty, _produced in self.baselines['partial'][-1][1]['productions']],
                         ['done', 'confirmed'])
        self.assertEqual(self.baselines['edit'][-1][1]['components'], -16.0)
        self.assertEqual(self.baselines['cancel'][-1][1]['production'][0], 'cancel')
        self.assertEqual((self.baselines['unbuild'][-1][1]['components'], self.baselines['unbuild'][-1][1]['produced']),
                         (-6.0, 3.0))

    def test_the_warehouse_template(self):
        self._template('warehouse', self.prof)
        self._each_variant()

    def test_the_app_user_template_of_each_app_alone(self):
        for xmlid in ('mrp.menu_mrp_root', 'stock.menu_stock_root'):
            with self._undone():
                self._template('app_user', self.prof, app=self._menu(xmlid))
                self._each_variant(label=xmlid)

    def test_the_switches_that_change_no_right(self):
        self._profile(self.prof, **dict.fromkeys((
            'block_export', 'block_import', 'block_duplicate', 'block_archive', 'hide_costs', 'hide_sale_prices',
            'hide_settings_menu', 'block_developer_mode', 'hide_chatter_all', 'hide_activities', 'lock_statusbar',
            'hide_print_all', 'hide_action_menu_all', 'hide_send_message_all', 'hide_followers_all',
            'hide_attachments_all'), True))
        self._each_variant()

    def test_a_neutral_filter_on_every_model_changes_nothing(self):
        self._neutral(self.prof)
        self._each_variant()


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixFlowViews(FlowCase):
    """ The screens of the flows still load, with their buttons and fields, for a user carrying a profile that hides
    no field: the web client of that user is what the flows above cannot show. """

    MODELS = (
        'sale.order', 'sale.order.line', 'purchase.order', 'purchase.order.line', 'stock.picking', 'stock.move',
        'stock.move.line', 'stock.quant', 'account.move', 'account.move.line', 'account.payment', 'hr.expense',
        'project.task', 'project.project', 'account.analytic.line', 'helpdesk.ticket', 'mrp.production', 'mrp.bom',
        'pos.order', 'pos.session', 'pos.config', 'product.template', 'product.product', 'res.partner', 'crm.lead')
    VIEW_TYPES = ('form', 'list', 'search', 'kanban')
    CHATTER_FIELDS = frozenset({
        'message_ids', 'message_follower_ids', 'activity_ids', 'activity_state', 'activity_user_id', 'activity_type_id',
        'activity_summary', 'activity_date_deadline', 'activity_exception_decoration', 'activity_exception_icon',
        'message_attachment_count', 'message_has_error', 'my_activity_date_deadline', 'message_is_follower',
        'message_partner_ids', 'website_message_ids'})
    SWITCHES = (
        'block_export', 'block_import', 'block_duplicate', 'block_archive', 'hide_settings_menu',
        'block_developer_mode', 'lock_statusbar', 'hide_print_all', 'hide_action_menu_all', 'hide_send_message_all',
        'hide_followers_all', 'hide_attachments_all', 'block_custom_filter', 'block_custom_group', 'block_favorites',
        'block_properties', 'block_apps')

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = (
            'base.group_user', 'sales_team.group_sale_manager', 'purchase.group_purchase_manager',
            'stock.group_stock_manager', 'account.group_account_manager', 'hr_expense.group_hr_expense_manager',
            'project.group_project_manager', 'hr_timesheet.group_hr_timesheet_user', 'helpdesk.group_helpdesk_manager',
            'mrp.group_mrp_manager', 'point_of_sale.group_pos_manager', 'quality.group_quality_manager')
        cls.plain = cls._user('views_plain', *groups)
        cls.prof = cls._user('views_prof', *groups)
        cls.baseline = cls._signature(cls.plain)

    @classmethod
    def _signature(cls, user, pairs=None):
        """ {(model, view type): (button names, field names)} of the views the user gets. """
        result = {}
        for model_name in cls.MODELS:
            if model_name not in cls.env:
                continue
            for view_type in cls.VIEW_TYPES:
                if pairs is not None and (model_name, view_type) not in pairs:
                    continue
                try:
                    views = cls.env[model_name].with_user(user).get_views([(False, view_type)])
                except Exception:  # noqa: BLE001
                    if pairs is not None:
                        raise
                    continue
                arch = etree.fromstring(views['views'][view_type]['arch'])
                result[(model_name, view_type)] = (
                    frozenset(node.get('name') for node in arch.iter('button') if node.get('name')),
                    frozenset(node.get('name') for node in arch.iter('field')) - cls.CHATTER_FIELDS)
        return result

    def _same_screens(self, allowed_fields=()):
        self.assertTrue(self.Profile._resolve(self.prof.id).enabled, "the profile does not reach the user")
        seen = self._signature(self.prof, pairs=set(self.baseline))
        for key, (buttons, fields_) in self.baseline.items():
            with self.subTest(view=key):
                self.assertEqual(seen[key][0], buttons)
                self.assertEqual(seen[key][1] - fields_, frozenset())
                self.assertLessEqual(fields_ - seen[key][1], set(allowed_fields))

    def test_the_views_exist(self):
        for model_name in ('sale.order', 'purchase.order', 'stock.picking', 'account.move', 'hr.expense', 'project.task',
                           'helpdesk.ticket', 'mrp.production', 'pos.order'):
            if model_name in self.env:
                self.assertIn((model_name, 'form'), self.baseline)
                self.assertIn((model_name, 'list'), self.baseline)
                self.assertTrue(self.baseline[(model_name, 'form')][0])

    def test_every_switch_that_hides_no_field_at_once(self):
        self._profile(self.prof, **dict.fromkeys(self.SWITCHES, True))
        self._same_screens()

    def test_the_chatter_and_activities_switches(self):
        self._profile(self.prof, hide_chatter_all=True, hide_activities=True)
        self._same_screens()

    def test_each_template_alone(self):
        hidden = {'hr_officer': {'wage'}}
        offered = dict(self.env['gec.access.template.wizard']._selection_templates())
        for key in ('salesperson', 'sales_readonly', 'accountant', 'auditor', 'warehouse', 'purchase', 'cashier',
                    'hr_officer'):
            if key not in offered:
                continue
            with self.subTest(template=key), self._undone():
                self._template(key, self.prof)
                self._same_screens(allowed_fields=hidden.get(key, ()))

    def test_the_app_user_template_of_each_app(self):
        for xmlid in ('sale.sale_menu_root', 'purchase.menu_purchase_root', 'stock.menu_stock_root',
                      ACCOUNTING, 'hr_expense.menu_hr_expense_root', 'project.menu_main_pm',
                      'helpdesk.menu_helpdesk_root', 'mrp.menu_mrp_root', 'point_of_sale.menu_point_root'):
            app = self._menu(xmlid)
            if not app:
                continue
            with self.subTest(app=xmlid), self._undone():
                self._template('app_user', self.prof, app=app)
                self._same_screens()

    def test_the_hidden_costs_and_prices_only_leave_their_fields(self):
        from odoo.addons.gec_access_manager.models.gec_access_rules import COST_FIELDS, SALE_PRICE_FIELDS
        self._profile(self.prof, hide_costs=True, hide_sale_prices=True)
        self._same_screens(allowed_fields={name for _model, name in COST_FIELDS + SALE_PRICE_FIELDS})

    def test_a_neutral_filter_on_every_model(self):
        self._neutral(self.prof)
        self._same_screens()

    def test_the_hidden_menus_of_other_apps(self):
        menus = self.env['ir.ui.menu']
        for xmlid in ('hr.menu_hr_root', 'crm.crm_menu_root', 'helpdesk.menu_helpdesk_root'):
            menus |= self._menu(xmlid)
        self._profile(self.prof, hidden_menu_ids=[Command.set(menus.ids)])
        self._same_screens()


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixExpenseVariants(FlowCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('hr.expense', 'account.move')
        manager_groups = ('base.group_user', 'hr_expense.group_hr_expense_manager', 'account.group_account_invoice',
                          'hr.group_hr_user')
        cls.employee_plain = cls._user('xvariant_employee_plain', 'base.group_user')
        cls.employee_prof = cls._user('xvariant_employee_prof', 'base.group_user')
        cls.manager_plain = cls._user('xvariant_manager_plain', *manager_groups)
        cls.manager_prof = cls._user('xvariant_manager_prof', *manager_groups)
        cls.record_plain = cls._employee_of(cls.employee_plain, expense_manager_id=cls.manager_plain.id)
        cls.record_prof = cls._employee_of(cls.employee_prof, expense_manager_id=cls.manager_prof.id)
        cls.expense_product = cls.env['product.product'].create({
            'name': 'MX Flow Expense', 'type': 'service', 'standard_price': 0.0, 'list_price': 0.0,
            'can_be_expensed': True})
        cls.baseline = ExpenseVariantFlow(cls, cls.employee_plain, cls.manager_plain, cls.record_plain).run().trace
        cls.both = cls.employee_prof | cls.manager_prof

    def _flow(self):
        return ExpenseVariantFlow(self, self.employee_prof, self.manager_prof, self.record_prof)

    def _identical(self, users=None):
        for user in users or self.both:
            self.assertTrue(self.Profile._resolve(user.id).enabled, "the profile does not reach the user")
        self.assertEqual(self._trace(self._flow()), self.baseline)

    def test_the_refusal_without_a_profile(self):
        self.assertEqual([name for name, _numbers in self.baseline], list(ExpenseVariantFlow.steps))
        self.assertEqual(self.baseline[2][1]['expense'][:2], ('refused', 'refused'))
        self.assertEqual(self.baseline[3][1]['expense'][:2], ('draft', False))
        self.assertEqual(self.baseline[-1][1]['expense'][:2], ('posted', 'approved'))

    def test_the_hr_officer_template(self):
        self._template('hr_officer', self.both)
        self._identical()

    def test_the_accountant_template_of_the_manager(self):
        self._template('accountant', self.manager_prof)
        self._identical(self.manager_prof)

    def test_the_app_user_template_of_each_app_alone(self):
        for xmlid in ('hr_expense.menu_hr_expense_root', 'hr.menu_hr_root', ACCOUNTING):
            app = self._menu(xmlid)
            if not app:
                continue
            with self.subTest(app=xmlid), self._undone():
                self._template('app_user', self.both, app=app)
                self._identical()

    def test_the_switches_that_change_no_right(self):
        self._profile(self.both, **dict.fromkeys((
            'block_export', 'block_import', 'block_duplicate', 'block_archive', 'hide_costs', 'hide_settings_menu',
            'block_developer_mode', 'hide_chatter_all', 'hide_activities', 'lock_statusbar', 'hide_print_all',
            'hide_action_menu_all', 'hide_send_message_all', 'hide_followers_all', 'hide_attachments_all'), True))
        self._identical()

    def test_a_neutral_filter_on_every_model_changes_nothing(self):
        self._neutral(self.both)
        self._identical()


CLIENT_SWITCHES = (
    'block_export', 'block_import', 'block_duplicate', 'block_archive', 'hide_costs', 'hide_sale_prices',
    'hide_settings_menu', 'block_developer_mode', 'hide_chatter_all', 'hide_activities', 'lock_statusbar',
    'hide_print_all', 'hide_action_menu_all', 'hide_send_message_all', 'hide_followers_all', 'hide_attachments_all',
    'block_custom_filter', 'block_custom_group', 'block_favorites', 'block_properties', 'block_apps')


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixPurchaseFlowClient(FlowCase, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('purchase.order', 'stock.picking', 'account.move')
        cls._need_field('purchase.order', 'picking_ids')
        groups = ('base.group_user', 'purchase.group_purchase_user', 'stock.group_stock_user',
                  'account.group_account_invoice', 'quality.group_quality_manager')
        cls.plain = cls._user('pclient_plain', *groups)
        cls.prof = cls._user('pclient_prof', *groups)
        cls.vendor_plain = cls.env['res.partner'].create({'name': 'MX Flow PClient Plain'})
        cls.vendor_prof = cls.env['res.partner'].create({'name': 'MX Flow PClient Prof'})
        cls._products()

    def setUp(self):
        super().setUp()
        self.baseline = RpcPurchaseFlow(self, self.plain, self.vendor_plain).run().trace

    def _flow(self):
        return RpcPurchaseFlow(self, self.prof, self.vendor_prof)

    def _identical(self):
        self.assertTrue(self.Profile._resolve(self.prof.id).enabled, "the profile does not reach the user")
        self.assertEqual(self._trace(self._flow()), self.baseline)

    def test_the_flow_without_a_profile(self):
        self.assertEqual([name for name, _numbers in self.baseline], list(PurchaseFlow.steps))
        self.assertEqual(self.baseline[-1][1]['bill'][:2], ('posted', 'not_paid'))
        self.assertEqual(self.baseline[-1][1]['onhand'], 4)

    def test_the_templates_of_the_three_roles(self):
        for key in ('purchase', 'accountant', 'warehouse'):
            self._template(key, self.prof)
        self._identical()

    def test_every_switch_at_once(self):
        self._profile(self.prof, **dict.fromkeys(CLIENT_SWITCHES, True))
        self._identical()

    def test_the_switches_of_the_models_of_the_flow(self):
        flags = ('hide_chatter', 'hide_export', 'hide_import', 'hide_archive', 'hide_duplicate', 'hide_print',
                 'hide_action_menu', 'hide_send_message', 'hide_followers', 'hide_attachments')
        profile = self._profile(self.prof)
        for model_name in ('purchase.order', 'purchase.order.line', 'stock.picking', 'stock.move', 'account.move'):
            self._line(profile, model_name, **dict.fromkeys(flags, True))
        self._identical()

    def test_a_blocked_button_that_is_not_in_the_flow(self):
        profile = self._profile(self.prof)
        for model_name, button in (('purchase.order', 'button_cancel'), ('purchase.order', 'button_draft'),
                                   ('account.move', 'button_draft'), ('stock.picking', 'action_cancel')):
            profile.button_ids = [Command.create({
                'model_id': self.env['ir.model']._get(model_name).id, 'button_name': button, 'mode': 'hide_block'})]
        self._identical()

    def test_the_blocked_confirm_button(self):
        profile = self._profile(self.prof)
        profile.button_ids = [Command.create({
            'model_id': self.env['ir.model']._get('purchase.order').id, 'button_name': 'button_confirm',
            'mode': 'hide_block'})]
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('confirm', AccessError))
        self.assertEqual(flow.trace, self.baseline[:1])
        self.assertEqual(flow.numbers(), self.baseline[0][1])

    def test_the_read_only_profile_refuses_the_quotation(self):
        self._profile(self.prof, global_readonly=True)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('rfq', AccessError))
        self._nothing_left(flow)

    def test_no_creation_of_entries_stops_the_bill(self):
        profile = self._profile(self.prof)
        self._line(profile, 'account.move', perm_create=False)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('bill', AccessError))
        self.assertEqual(flow.trace, self.baseline[:3])
        self.assertEqual(flow.left_behind()['bills'], 0)


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixProjectFlowClient(FlowCase, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('project.task', 'account.analytic.line', 'hr.employee')
        cls._need_field('account.analytic.line', 'employee_id')
        groups = ('base.group_user', 'project.group_project_user', 'hr_timesheet.group_hr_timesheet_user')
        cls.plain = cls._user('jclient_plain', *groups)
        cls.prof = cls._user('jclient_prof', *groups)
        cls.record_plain = cls._employee_of(cls.plain)
        cls.record_prof = cls._employee_of(cls.prof)
        cls.project = cls.env['project.project'].create({'name': 'MX Flow Project', 'allow_timesheets': True})
        cls.stage_todo, cls.stage_done = cls.env['project.task.type'].create([
            {'name': 'MX Flow To Do', 'sequence': 1, 'project_ids': [Command.set(cls.project.ids)]},
            {'name': 'MX Flow Done', 'sequence': 2, 'project_ids': [Command.set(cls.project.ids)]},
        ])

    def setUp(self):
        super().setUp()
        self.baseline = RpcProjectFlow(self, self.plain, self.record_plain).run().trace

    def _flow(self):
        return RpcProjectFlow(self, self.prof, self.record_prof)

    def _identical(self):
        self.assertTrue(self.Profile._resolve(self.prof.id).enabled, "the profile does not reach the user")
        self.assertEqual(self._trace(self._flow()), self.baseline)

    def test_the_flow_without_a_profile(self):
        self.assertEqual(self.baseline[-1][1]['task'], ('MX Flow Done', 'MX Flow Project', 2.5, 1))

    def test_the_hr_officer_template(self):
        self._template('hr_officer', self.prof)
        self._identical()

    def test_every_switch_at_once(self):
        self._profile(self.prof, **dict.fromkeys(CLIENT_SWITCHES, True))
        self._identical()

    def test_the_read_only_profile_refuses_the_task(self):
        self._profile(self.prof, global_readonly=True)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('task', AccessError))
        self._nothing_left(flow)

    def test_no_creation_of_timesheets_refuses_the_timesheet_only(self):
        profile = self._profile(self.prof)
        self._line(profile, 'account.analytic.line', perm_create=False)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('timesheet', AccessError))
        self.assertEqual(flow.trace, self.baseline[:1])
        self.assertEqual(flow.left_behind()['timesheets'], 0)


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixHelpdeskFlowClient(FlowCase, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('helpdesk.ticket')
        groups = ('base.group_user', 'helpdesk.group_helpdesk_user')
        cls.plain = cls._user('hclient_plain', *groups)
        cls.prof = cls._user('hclient_prof', *groups)
        cls.customer = cls.env['res.partner'].create({'name': 'MX Flow HClient Customer'})
        cls.team = cls.env['helpdesk.team'].create({
            'name': 'MX Flow Team', 'privacy_visibility': 'internal',
            'member_ids': [Command.set((cls.plain | cls.prof).ids)]})
        cls.team.stage_ids = False
        cls.stage_new, cls.stage_done = cls.env['helpdesk.stage'].create([
            {'name': 'MX Flow New', 'sequence': 10, 'team_ids': [Command.set(cls.team.ids)]},
            {'name': 'MX Flow Done', 'sequence': 30, 'fold': True, 'team_ids': [Command.set(cls.team.ids)]},
        ])
        cls.team.use_sla = True
        cls.env['helpdesk.sla'].create({
            'name': 'MX Flow SLA', 'team_id': cls.team.id, 'stage_id': cls.stage_done.id, 'time': 8.0})

    def setUp(self):
        super().setUp()
        self.baseline = RpcHelpdeskFlow(self, self.plain, self.customer).run().trace

    def _flow(self):
        return RpcHelpdeskFlow(self, self.prof, self.customer)

    def _identical(self):
        self.assertTrue(self.Profile._resolve(self.prof.id).enabled, "the profile does not reach the user")
        self.assertEqual(self._trace(self._flow()), self.baseline)

    def test_the_flow_without_a_profile(self):
        self.assertEqual(self.baseline[-1][1]['ticket'], ('MX Flow Done', True, True, True, 'MX Flow Team', False))
        self.assertEqual(self.baseline[-1][1]['sla'], [('MX Flow SLA', True)])

    def test_the_app_user_template(self):
        self._template('app_user', self.prof, app=self._menu('helpdesk.menu_helpdesk_root'))
        self._identical()

    def test_every_switch_at_once(self):
        self._profile(self.prof, **dict.fromkeys(CLIENT_SWITCHES, True))
        self._identical()

    def test_the_read_only_profile_refuses_the_ticket(self):
        self._profile(self.prof, global_readonly=True)
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('create', AccessError))
        self._nothing_left(flow)

    def test_only_unassigned_tickets_can_be_edited_refuses_the_closing(self):
        profile = self._profile(self.prof)
        self._line(profile, 'helpdesk.ticket', domain_write="[('user_id', '=', False)]")
        flow = self._flow()
        refused = self._refusal(flow)
        self.assertEqual((refused.step, type(refused.error)), ('close', AccessError))
        self.assertEqual(flow.trace, self.baseline[:2])

