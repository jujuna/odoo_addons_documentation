# Regression tests of the second review (B1-B13), each through the entry point
# concerned and with the real user: env.su bypasses every hook of this module.
import ast
import io
import time
import xmlrpc.client
from datetime import datetime, timedelta, timezone
from unittest import SkipTest
from unittest.mock import MagicMock, patch

from PIL import Image

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.modules.registry import Registry
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tests.common import JsonRpcException, get_db_name
from odoo.tools import BinaryBytes, mute_logger

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.gec_access_manager import uninstall_hook
from odoo.addons.gec_access_manager.models.gec_access_rules import SALE_PRICE_FIELDS
from odoo.addons.gec_access_manager.models.gec_access_templates import TEMPLATES, TEMPLATES_BY_KEY
from odoo.addons.gec_access_manager.models.res_users import LOGIN_STAMP_KEY
from odoo.addons.gec_access_manager.models.gec_access_version import PENDING

# a Monday
OFFICE_HOURS = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)
EVENING = datetime(2026, 10, 5, 20, 0, tzinfo=timezone.utc)


class ClientCalls:
    """ The calls of the web client by JSON-RPC, for the HttpCase tests: their result, or the message of their error. """

    def _call(self, model, method, args, kwargs=None, route='call_kw'):
        return self.make_jsonrpc_request(f'/web/dataset/{route}/{model}/{method}', {
            'model': model, 'method': method, 'args': args, 'kwargs': kwargs or {},
        })

    def _error(self, model, method, args, kwargs=None, route='call_kw'):
        response = self.url_open(f'/web/dataset/{route}/{model}/{method}', json={
            'jsonrpc': '2.0', 'method': 'call', 'id': 1,
            'params': {'model': model, 'method': method, 'args': args, 'kwargs': kwargs or {}},
        })
        return response.json()['error']['data']['message']


@tagged('post_install', '-at_install')
class TestCompanyJournals(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        if 'account.journal' not in Registry(get_db_name()):
            raise SkipTest("account is not installed")
        super().setUpClass()

    def test_the_journals_odoo_posts_to_stay_allowed(self):
        """ B1: a user limited to some journals keeps the exchange difference journal of the company. """
        Journal = self.env['account.journal']
        allowed = Journal.create({'name': 'GEC Allowed', 'code': 'OMA', 'type': 'general'})
        exchange = Journal.create({'name': 'GEC Exchange', 'code': 'OMX', 'type': 'general'})
        hidden = Journal.create({'name': 'GEC Hidden', 'code': 'OMH', 'type': 'general'})
        self.env.company.currency_exchange_journal_id = exchange
        filters = self.env['gec.access.allowed']._filters('journal', [allowed.id])
        ids = ast.literal_eval(filters['account.move'])[0][2]
        self.assertLessEqual({allowed.id, exchange.id}, set(ids))
        self.assertNotIn(hidden.id, ids)
        user = new_test_user(self.env, 'gec_fix_journal_user', groups='base.group_user,account.group_account_readonly')
        self.env['gec.access.profile'].sudo().create({
            'name': 'Journals', 'user_ids': [(6, 0, user.ids)],
            'allowed_ids': [(0, 0, {'kind': 'journal', 'res_id': allowed.id})],
        })
        seen = Journal.with_user(user).search([('id', 'in', (allowed | exchange | hidden).ids)])
        self.assertEqual(seen, allowed | exchange)

    def test_the_deferral_journals_do_not_open_the_general_journal(self):
        """ B1: a company whose deferral journals are the general journal (the Enterprise default) does not make
        that journal allowed. """
        misc = self.env['account.journal'].create({'name': 'GEC Misc', 'code': 'OMM', 'type': 'general'})
        allowed = self.env['account.journal'].create({'name': 'GEC Allowed', 'code': 'OMA', 'type': 'general'})
        deferral_fields = [name for name in ('deferred_expense_journal_id', 'deferred_revenue_journal_id')
                           if name in self.env.company._fields]
        for name in deferral_fields:
            self.env.company[name] = misc
        filters = self.env['gec.access.allowed']._filters('journal', [allowed.id])
        self.assertNotIn(misc.id, ast.literal_eval(filters['account.move'])[0][2])

    def test_a_foreign_currency_payment_books_its_exchange_difference(self):
        """ B1: a user limited to the bank and purchase journals pays a bill in euros, rate 3 at the bill and 2
        at the payment: Odoo books the difference in the exchange journal, which the user is not allowed. """
        bank = self.company_data['default_journal_bank']
        purchase = self.company_data['default_journal_purchase']
        exchange = self.env.company.currency_exchange_journal_id
        self.assertTrue(exchange)
        self.assertNotIn(exchange, bank | purchase)
        euro = self.setup_other_currency('EUR')
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.partner_a.id, 'currency_id': euro.id,
            'date': '2016-01-01', 'invoice_date': '2016-01-01',
            'invoice_line_ids': [Command.create({'product_id': self.product_a.id, 'price_unit': 1200.0, 'tax_ids': []})],
        })
        bill.action_post()
        user = new_test_user(self.env, 'gec_fix_payer', groups='base.group_user,account.group_account_manager')
        self.env['gec.access.profile'].sudo().create({
            'name': 'Pays bills', 'user_ids': [Command.set(user.ids)],
            'allowed_ids': [Command.create({'kind': 'journal', 'res_id': journal.id}) for journal in bank | purchase],
        })
        wizard = self.env['account.payment.register'].with_user(user).with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({'payment_date': '2017-01-01', 'journal_id': bank.id})
        payment = wizard._create_payments()
        lines = (bill | payment.move_id).sudo().line_ids.filtered(lambda line: line.account_type == 'liability_payable')
        partials = lines.mapped('matched_debit_ids') | lines.mapped('matched_credit_ids')
        self.assertTrue(all(lines.mapped('reconciled')))
        self.assertTrue(partials.exchange_move_id)
        self.assertEqual(partials.exchange_move_id.mapped('journal_id'), exchange)


@tagged('post_install', '-at_install')
class TestClientArchiveAndCopy(ClientCalls, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'gec-access-manager-fixes-pw'
        cls.user = new_test_user(cls.env, 'gec_fix_client_user', groups='base.group_user,base.group_partner_manager',
                                 password=cls.password)
        cls.partner = cls.env['res.partner'].create({'name': 'Archivable'})
        cls.partner_model = cls.env['ir.model']._get('res.partner')

    def setUp(self):
        super().setUp()
        self.authenticate(self.user.login, self.password)

    def _profile(self, **values):
        return self.env['gec.access.profile'].create(dict(values, name='Client calls', user_ids=[(6, 0, self.user.ids)]))

    def _activity(self):
        return self.env['mail.activity'].create({
            'res_model_id': self.partner_model.id, 'res_id': self.partner.id, 'user_id': self.user.id,
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
        })

    @mute_logger('odoo.http')
    def test_block_archive_refuses_the_client_archive(self):
        """ B2: the archive a client asks for, by action_archive or by writing active. """
        self._profile(block_archive=True)
        ids = self.partner.ids
        self.assertIn('archiving', self._error('res.partner', 'action_archive', [ids]))
        self.assertIn('archiving', self._error('res.partner', 'write', [ids, {'active': False}]))
        self.assertIn('archiving', self._error('res.partner', 'web_save', [ids, {'active': False}],
                                               {'specification': {}}))
        self.assertTrue(self.partner.active)
        self._call('res.partner', 'write', [ids, {'name': 'Renamed by a client'}])
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.name, 'Renamed by a client')

    @mute_logger('odoo.addons.rpc.controllers.xmlrpc', 'odoo.http')
    def test_block_archive_through_xmlrpc_and_json2(self):
        self._profile(block_archive=True)
        with self.assertRaises(xmlrpc.client.Fault):
            self.xmlrpc_object.execute_kw(
                self.env.cr.dbname, self.user.id, self.password, 'res.partner', 'write',
                [self.partner.ids, {'active': False}])
        key = self.env['res.users.apikeys'].with_user(self.user)._generate(
            'rpc', 'fixes test', datetime.now() + timedelta(days=1))
        headers = {'Authorization': f'bearer {key}', 'X-Odoo-Database': self.env.cr.dbname}
        response = self.url_open('/json/2/res.partner/write', json={
            'ids': self.partner.ids, 'vals': {'active': False}}, headers=headers)
        self.assertNotEqual(response.status_code, 200)
        self.assertIn('archiving', response.json()['message'])
        self.assertTrue(self.partner.active)

    @mute_logger('odoo.http')
    def test_block_archive_covers_crafted_calls(self):
        """ B2: call_button, an x2many command and an import column cannot set active; a creation still can. """
        self._profile(block_archive=True)
        ids = self.partner.ids
        self.assertIn('archiving', self._error('res.partner', 'write', [ids, {'active': False}], route='call_button'))
        self.assertIn('archiving', self._error(
            'res.partner', 'write', [ids, {'child_ids': [(0, 0, {'name': 'Child', 'active': False})]}]))
        self.assertIn('archiving', self._error(
            'res.partner', 'load', [['name', 'child_ids/name', 'child_ids/active'], [['Imported', 'Child', '0']]]))
        self.assertTrue(self.partner.active)
        self._call('res.partner', 'web_save', [[], {'name': 'Created archived', 'active': False}], {'specification': {}})
        created = self.env['res.partner'].with_context(active_test=False).search([('name', '=', 'Created archived')])
        self.assertEqual(len(created), 1)
        self.assertFalse(created.active)

    @mute_logger('odoo.http')
    def test_block_archive_covers_an_update_command_in_a_create(self):
        """ N11: a create whose x2many UPDATE command archives an existing record is refused, a create setting
        its own active still goes through. """
        self._profile(block_archive=True)
        child = self.env['res.partner'].create({'name': 'Existing child', 'parent_id': self.partner.id})
        self.assertIn('archiving', self._error('res.partner', 'create', [
            {'name': 'New parent', 'child_ids': [[1, child.id, {'active': False}]]}]))
        self.assertIn('archiving', self._error('res.partner', 'web_save', [
            [], {'name': 'New parent', 'child_ids': [[1, child.id, {'active': False}]]}], {'specification': {}}))
        self.assertTrue(child.active)
        self._call('res.partner', 'create', [{'name': 'Created archived by create', 'active': False}])
        created = self.env['res.partner'].with_context(active_test=False).search(
            [('name', '=', 'Created archived by create')])
        self.assertFalse(created.active)

    def test_block_archive_leaves_odoo_own_archiving_alone(self):
        """ B2: marking an activity done archives it, for a user who may not archive. """
        self._profile(block_archive=True)
        self._activity().with_user(self.user).action_feedback()
        activity = self._activity()
        self.assertTrue(self._call('mail.activity', 'action_feedback', [activity.ids], {'feedback': 'Done'}))
        activity.invalidate_recordset()
        self.assertFalse(activity.active)
        self.partner.with_user(self.user).write({'active': False})
        self.assertFalse(self.partner.active)

    @mute_logger('odoo.http')
    def test_block_duplicate_refuses_the_client_copy_only(self):
        """ B2: copy() called by the client is refused, the copies Odoo makes of its own go through. """
        self._profile(model_ids=[(0, 0, {'model_id': self.partner_model.id, 'hide_duplicate': True})])
        self.assertIn('duplicating', self._error('res.partner', 'copy', [self.partner.ids]))
        self.assertTrue(self.partner.with_user(self.user).copy())


@tagged('post_install', '-at_install')
class TestProfileEditors(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, 'gec_fix_manager',
                                    groups='base.group_user,gec_access_manager.group_access_manager')
        cls.settings_manager = new_test_user(
            cls.env, 'gec_fix_settings_manager',
            groups='base.group_user,base.group_system,gec_access_manager.group_access_manager')
        cls.employee = new_test_user(cls.env, 'gec_fix_employee', groups='base.group_user')
        cls.held = cls.env['res.groups'].create({'name': 'GEC Fix Held'})
        cls.lacking = cls.env['res.groups'].create({'name': 'GEC Fix Lacking'})
        cls.manager.group_ids = [(4, cls.held.id)]
        cls.partner_model = cls.env['ir.model']._get('res.partner')

    def test_a_manager_grants_only_what_they_hold(self):
        """ B3: outside Settings, a profile grants the groups its editor holds. """
        Profile = self.env['gec.access.profile'].with_user(self.manager)
        profile = Profile.create({'name': 'Held', 'granted_group_ids': [(6, 0, self.held.ids)]})
        with self.assertRaises(AccessError):
            Profile.create({'name': 'Lacking', 'granted_group_ids': [(6, 0, self.lacking.ids)]})
        with self.assertRaises(AccessError):
            profile.write({'granted_group_ids': [(4, self.lacking.id)]})
        settings = self.env['gec.access.profile'].with_user(self.settings_manager).create({
            'name': 'Lacking by Settings', 'granted_group_ids': [(6, 0, self.lacking.ids)]})
        # and cannot take part in a profile that grants more than they hold
        with self.assertRaises(AccessError):
            settings.with_user(self.manager).write({'name': 'Renamed'})
        with self.assertRaises(AccessError):
            settings.with_user(self.manager).unlink()
        with self.assertRaises(AccessError):
            self.env['gec.access.profile.model'].with_user(self.manager).create({
                'profile_id': settings.id, 'model_id': self.partner_model.id})

    def test_profiles_for_settings_users_need_a_settings_user(self):
        """ B3: a profile applying to Settings users, its lines and its members. """
        Profile = self.env['gec.access.profile']
        with self.assertRaises(AccessError):
            Profile.with_user(self.manager).create({'name': 'For admins', 'apply_to_admin': True})
        admins = Profile.with_user(self.settings_manager).create({'name': 'For admins', 'apply_to_admin': True})
        plain = Profile.with_user(self.manager).create({'name': 'Plain'})
        with self.assertRaises(AccessError):
            plain.write({'apply_to_admin': True})
        with self.assertRaises(AccessError):
            admins.with_user(self.manager).write({'name': 'Renamed'})
        with self.assertRaises(AccessError):
            self.env['gec.access.profile.model'].with_user(self.manager).create({
                'profile_id': admins.id, 'model_id': self.partner_model.id})
        with self.assertRaises(AccessError):
            self.env['gec.access.profile.assignment'].with_user(self.manager).create({
                'profile_id': admins.id, 'user_id': self.employee.id})
        # the wizards write with sudo: the real user counts
        with self.assertRaises(AccessError):
            self.env['gec.access.assign'].with_user(self.manager).create({
                'user_ids': [(6, 0, self.employee.ids)], 'profile_ids': [(6, 0, admins.ids)], 'mode': 'add',
            }).action_apply()
        with self.assertRaises(AccessError):
            self.employee.with_user(self.manager).sudo().write({'access_profile_ids': [(4, admins.id)]})
        # a plain profile is theirs to give
        self.env['gec.access.profile.model'].with_user(self.manager).create({
            'profile_id': plain.id, 'model_id': self.partner_model.id})
        self.env['gec.access.assign'].with_user(self.manager).create({
            'user_ids': [(6, 0, self.employee.ids)], 'profile_ids': [(6, 0, plain.ids)], 'mode': 'add',
        }).action_apply()
        self.assertEqual(self.employee.sudo().access_profile_ids, plain)
        # a Settings user is not limited
        self.employee.with_user(self.settings_manager).sudo().write({'access_profile_ids': [(4, admins.id)]})
        self.assertIn(admins, self.employee.sudo().access_profile_ids)


    def test_a_call_with_no_real_user_passes_the_editor_check(self):
        """ N13: an environment without a user (a sign-in creating a user) is not an error. """
        admins = self.env['gec.access.profile'].create({'name': 'For admins', 'apply_to_admin': True})
        self.assertFalse(admins.with_env(self.env(user=0, su=False))._gec_check_editor())

    def test_only_the_profiles_a_write_changes_are_checked(self):
        """ B3: a user carrying a profile a Settings user made, which grants a group the manager lacks, takes a
        plain profile from the manager; taking that profile away, or giving it to another user, is refused. """
        Profile = self.env['gec.access.profile']
        granting = Profile.with_user(self.settings_manager).create({
            'name': 'Grants Lacking', 'granted_group_ids': [(6, 0, self.lacking.ids)],
            'user_ids': [(6, 0, self.employee.ids)]})
        plain = Profile.with_user(self.manager).create({'name': 'Plain'})
        other = new_test_user(self.env, 'gec_fix_other_employee', groups='base.group_user')
        employee = self.employee.with_user(self.manager).sudo()
        employee.write({'access_profile_ids': [(4, plain.id)]})
        self.assertEqual(self.employee.sudo().access_profile_ids, granting | plain)
        with self.assertRaises(AccessError):
            employee.write({'access_profile_ids': [(3, granting.id)]})
        with self.assertRaises(AccessError):
            other.with_user(self.manager).sudo().write({'access_profile_ids': [(4, granting.id)]})

    def test_a_manager_cannot_point_a_profile_at_a_group(self):
        """ A1: the technical group is the module's own: a manager who may not do it cannot make it Settings. """
        Profile = self.env['gec.access.profile'].with_user(self.manager)
        system = self.env.ref('base.group_system')
        users, implied, name = system.user_ids, system.implied_ids, system.name
        with self.assertRaises(AccessError):
            Profile.create({'name': 'Takeover', 'group_id': system.id})
        profile = Profile.create({'name': 'Own group'})
        own = profile.sudo().group_id
        self.assertTrue(own)
        self.assertNotEqual(own, system)
        with self.assertRaises(AccessError):
            profile.write({'group_id': system.id})
        with self.assertRaises(AccessError):
            profile.write({'group_id': system.id, 'name': 'Renamed'})
        with self.assertRaises(AccessError):
            profile.write({'group_id': False})
        with self.assertRaises(AccessError):
            Profile.create({'name': 'No group', 'group_id': False})
        self.assertEqual(profile.sudo().group_id, own)
        system.invalidate_recordset()
        self.assertEqual((system.user_ids, system.implied_ids, system.name), (users, implied, name))
        copy = profile.copy()
        self.assertTrue(copy.sudo().group_id)
        self.assertNotIn(copy.sudo().group_id, own | system)


@tagged('post_install', '-at_install')
class TestPreviewFixes(ClientCalls, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'gec-access-manager-fixes-preview-pw'
        cls.manager = new_test_user(
            cls.env, 'gec_fix_preview_manager', password=cls.password,
            groups='base.group_user,base.group_system,gec_access_manager.group_access_manager')
        cls.small_manager = new_test_user(
            cls.env, 'gec_fix_preview_small', groups='base.group_user,gec_access_manager.group_access_manager')
        cls.user = new_test_user(cls.env, 'gec_fix_preview_user', groups='base.group_user,base.group_partner_manager')
        cls.partner = cls.env['res.partner'].create({'name': 'Previewed Contact'})
        cls.partner.message_post(body='Visible note')
        cls.channel = cls.env['discuss.channel'].create({
            'name': 'GEC Private Chat', 'channel_type': 'channel', 'group_public_id': False})
        cls.channel.message_post(body='Chat message')

    def setUp(self):
        super().setUp()
        self.authenticate(self.manager.login, self.password, session_extra={'identity-check-last': time.time()})

    def _run_error(self, action):
        response = self.url_open('/web/action/run', json={
            'jsonrpc': '2.0', 'method': 'call', 'id': 1, 'params': {'action_id': action.id}})
        return response.json()['error']['data']['message']

    def _start(self):
        return self._call('res.users', 'action_gec_preview', [self.user.ids], route='call_button')

    @mute_logger('odoo.http')
    def test_only_settings_users_preview(self):
        """ B4: an access manager outside Settings is told so, and cannot start a preview. """
        profile = self.env['gec.access.profile'].create({'name': 'Previewable', 'user_ids': [(6, 0, self.user.ids)]})
        self.assertIn('Settings', self.user._gec_preview_refusal(self.small_manager))
        with self.assertRaisesRegex(UserError, 'Only Settings administrators can preview a user'):
            profile.with_user(self.small_manager).action_test_user()
        self.authenticate(self.small_manager.login, self.small_manager.login,
                          session_extra={'identity-check-last': time.time()})
        self.assertIn('Only Settings administrators can preview a user',
                      self._error('res.users', 'action_gec_preview', [self.user.ids], route='call_button'))
        self.assertTrue(profile.with_user(self.manager).action_test_user())

    def test_chats_are_out_of_reach_in_a_preview(self):
        """ B4: the previewed user's chats stay out of the administrator's reach, the other messages stay. """
        domain = [('id', '=', self.channel.id)]
        self.assertEqual(self.env['discuss.channel'].with_user(self.user).search(domain), self.channel)
        self._start()
        self.assertFalse(self._call('discuss.channel', 'search_read', [domain, ['name']]))
        self.assertFalse(self._call('discuss.channel.member', 'search_read', [[('channel_id', '=', self.channel.id)],
                                                                              ['channel_id']]))
        self.assertFalse(self._call('mail.message', 'search_read', [
            [('model', '=', 'discuss.channel'), ('res_id', '=', self.channel.id)], ['body']]))
        self.assertTrue(self._call('mail.message', 'search_read', [
            [('model', '=', 'res.partner'), ('res_id', '=', self.partner.id)], ['body']]))

    @mute_logger('odoo.http')
    def test_a_preview_calls_readonly_methods_only(self):
        """ B5: a method Odoo does not declare readonly is refused, a readonly one and the screen helpers pass. """
        self._start()
        self.assertIn('preview', self._error('ir.filters', 'get_filters', ['res.partner']))
        self.assertIn('preview', self._error('res.partner', 'message_post', [self.partner.ids], {'body': 'Hi'}))
        self.assertTrue(self._call('res.partner', 'read', [self.partner.ids, ['name']]))
        self.assertTrue(self._call('res.partner', 'fields_get', [], {'attributes': ['string']}))
        self._call('res.partner', 'default_get', [['name']])

    def test_a_preview_calls_the_read_helpers_of_the_screens(self):
        """ N12: the helpers calendar, hr and invoice screens call, which only read, are not refused. """
        calls = [
            ('res.partner', 'get_attendee_detail', [self.partner.ids, []]),
            ('hr.department', 'get_department_hierarchy', [[]]),
            ('hr.employee', 'cycles_in_hierarchy_read', [[]]),
            ('account.move', 'get_extra_print_items', [[]]),
            ('account.move', 'check_move_sequence_chain', [[]]),
        ]
        self._start()
        for model, method, args in calls:
            if model in self.env and hasattr(self.env[model], method):
                self._call(model, method, args)

    @mute_logger('odoo.http')
    def test_a_preview_runs_only_the_server_actions_of_menus(self):
        """ B5: not an action bound to a model's Action menu, a scheduled one, or one no menu opens. """
        partner_model = self.env['ir.model']._get('res.partner')
        code = "action = {'type': 'ir.actions.act_window', 'res_model': 'res.partner', 'views': [[False, 'list']]}"
        Action = self.env['ir.actions.server']
        opens = Action.create({'name': 'GEC Menu Action', 'model_id': partner_model.id, 'state': 'code', 'code': code})
        no_menu = Action.create({'name': 'GEC No Menu', 'model_id': partner_model.id, 'state': 'code', 'code': code})
        bound = Action.create({'name': 'GEC Bound', 'model_id': partner_model.id, 'state': 'code', 'code': code,
                               'binding_model_id': partner_model.id})
        scheduled = self.env.ref('base.autovacuum_job').ir_actions_server_id
        for action in (opens, bound, scheduled):
            self.env['ir.ui.menu'].create({'name': action.name, 'action': f'ir.actions.server,{action.id}'})
        self._start()
        self.assertEqual(self.make_jsonrpc_request('/web/action/run', {'action_id': opens.id})['res_model'],
                         'res.partner')
        for action in (no_menu, bound, scheduled):
            self.assertIn('preview', self._run_error(action), action.name)


@tagged('post_install', '-at_install')
class TestSignInAndServerActions(ClientCalls, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'gec-access-manager-fixes-signin-pw'
        cls.user = new_test_user(cls.env, 'gec_fix_rpc_user', groups='base.group_user,base.group_partner_manager',
                                 password=cls.password)
        cls.partner_model = cls.env['ir.model']._get('res.partner')

    @mute_logger('odoo.addons.rpc.controllers.xmlrpc', 'odoo.http')
    def test_every_rpc_call_follows_the_working_hours(self):
        """ B6: the password check of an object call is cached, the hours are not. """
        self.env['gec.access.profile'].create({
            'name': 'Office hours', 'user_ids': [(6, 0, self.user.ids)], 'login_tz': 'UTC',
            'login_slot_ids': [(0, 0, {'dayofweek': '0', 'hour_from': 8, 'hour_to': 17})]})

        def count():
            return self.xmlrpc_object.execute_kw(
                self.env.cr.dbname, self.user.id, self.password, 'res.partner', 'search_count', [[]])

        with patch('odoo.addons.gec_access_manager.models.res_users.utc_now', return_value=OFFICE_HOURS):
            self.assertIsInstance(count(), int)
        with patch('odoo.addons.gec_access_manager.models.res_users.utc_now', return_value=EVENING):
            with self.assertRaises(xmlrpc.client.Fault):
                count()
        with patch('odoo.addons.gec_access_manager.models.res_users.utc_now', return_value=OFFICE_HOURS):
            self.assertIsInstance(count(), int)

    @mute_logger('odoo.http')
    def test_a_hidden_server_action_is_refused_when_the_client_runs_it(self):
        """ B7: run() called by the client; the run Odoo's own code makes is left alone. """
        self.authenticate(self.user.login, self.password)
        action = self.env['ir.actions.server'].create({
            'name': 'GEC Hidden Action', 'model_id': self.partner_model.id, 'state': 'code', 'code': 'pass',
            'group_ids': [(6, 0, self.env.ref('base.group_user').ids)]})
        profile = self.env['gec.access.profile'].create({
            'name': 'Hides an action', 'user_ids': [(6, 0, self.user.ids)],
            'hidden_action_ids': [(6, 0, action.ids)]})
        response = self.url_open('/web/dataset/call_kw/ir.actions.server/run', json={
            'jsonrpc': '2.0', 'method': 'call', 'id': 1,
            'params': {'model': 'ir.actions.server', 'method': 'run', 'args': [action.ids], 'kwargs': {}}})
        self.assertIn('Your access profile hides it', response.json()['error']['data']['message'])
        action.with_user(self.user).run()
        profile.hidden_action_ids = [(5,)]
        self.assertFalse(self._call('ir.actions.server', 'run', [action.ids]))


@tagged('post_install', '-at_install')
class TestTemplatesAndImport(TransactionCase):

    def test_a_read_only_template_cannot_be_overruled(self):
        """ B8: the Auditor profile is an override, so another profile of the user cannot lift its read only. """
        for template in TEMPLATES:
            if template.get('switches', {}).get('global_readonly'):
                self.assertEqual(template['switches'].get('strictness'), 'override', template['key'])
        user = new_test_user(self.env, 'gec_fix_auditor', groups='base.group_user,base.group_partner_manager')
        wizard = self.env['gec.access.template.wizard'].create({
            'template_key': 'auditor', 'name': 'GEC Auditor', 'user_ids': [(6, 0, user.ids)]})
        profile = self.env['gec.access.profile'].browse(wizard.action_create()['res_id'])
        self.assertEqual(profile.strictness, 'override')
        self.env['gec.access.profile'].create({'name': 'GEC Lets Write', 'user_ids': [(6, 0, user.ids)]})
        rules = self.env['gec.access.profile'].with_user(user)._current_rules()
        self.assertTrue(rules.allows('res.partner', 'read'))
        self.assertFalse(rules.allows('res.partner', 'write'))

    def test_the_uploaded_file_is_imported(self):
        """ B9: the wizard reads the uploaded file as bytes, and an exported profile comes back with its name. """
        profile = self.env['gec.access.profile'].create({'name': 'Pr\u00fcfer GEC', 'block_export': True})
        wizard = self.env['gec.access.import'].create({
            'file': BinaryBytes(profile._gec_export().encode()), 'filename': 'access_profiles.json'})
        action = wizard.action_import()
        imported = self.env['gec.access.profile'].browse(action['domain'][0][2])
        self.assertEqual(imported.name, 'Pr\u00fcfer GEC (imported)')
        self.assertTrue(imported.block_export)


@tagged('post_install', '-at_install')
class TestHiddenImage(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'gec-access-manager-fixes-image-pw'
        cls.user = new_test_user(cls.env, 'gec_fix_image_user', groups='base.group_user,base.group_partner_manager',
                                 password=cls.password)
        buffer = io.BytesIO()
        Image.new('RGB', (4, 4), 'red').save(buffer, 'PNG')
        cls.partner = cls.env['res.partner'].create({
            'name': 'With Picture', 'image_1920': BinaryBytes(buffer.getvalue())})
        cls.env['gec.access.profile'].create({
            'name': 'Hides the picture', 'user_ids': [(6, 0, cls.user.ids)],
            'field_ids': [(0, 0, {
                'model_id': cls.env['ir.model']._get('res.partner').id,
                'field_id': cls.env['ir.model.fields']._get('res.partner', 'image_1920').id, 'mode': 'hide'})]})

    def setUp(self):
        super().setUp()
        self.authenticate(self.user.login, self.password)

    def test_a_form_with_a_hidden_image_still_opens(self):
        """ B10: the client reads the model itself: the image comes back blank instead of failing the read. """
        rows = self.make_jsonrpc_request('/web/dataset/call_kw/res.partner/web_read', {
            'model': 'res.partner', 'method': 'web_read', 'args': [self.partner.ids],
            'kwargs': {'specification': {'name': {}, 'image_1920': {}}}})
        self.assertEqual(rows[0]['name'], 'With Picture')
        self.assertIs(rows[0]['image_1920'], False)

    def test_the_content_routes_refuse_a_hidden_image(self):
        """ B10: /web/image and the binary stream do not give the picture. """
        # a refused image is answered with the placeholder (status 200); a download is answered 404
        response = self.url_open(f'/web/image/res.partner/{self.partner.id}/image_1920?download=true')
        self.assertEqual(response.status_code, 404)
        partner = self.env['ir.binary'].with_user(self.user)._find_record(
            res_model='res.partner', res_id=self.partner.id, field='image_1920')
        with self.assertRaises(AccessError):
            self.env['ir.binary'].with_user(self.user)._record_to_stream(partner, 'image_1920')


@tagged('post_install', '-at_install')
class TestUninstallHook(TransactionCase):

    def test_uninstall_removes_the_profiles_and_their_groups(self):
        """ B11: no hidden group is left behind, and no version waits to be saved after the tables are gone. """
        profile = self.env['gec.access.profile'].create({'name': 'GEC To Uninstall'})
        group = profile.group_id
        self.assertTrue(group)
        self.env.cr.precommit.data.pop(PENDING, None)
        uninstall_hook(self.env)
        self.assertFalse(self.env['gec.access.profile'].with_context(active_test=False).search([]))
        self.assertFalse(group.exists())
        self.assertNotIn(PENDING, self.env.cr.precommit.data)


@tagged('post_install', '-at_install')
class TestValueFilterContext(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'gec-access-manager-fixes-filter-pw'
        cls.user = new_test_user(cls.env, 'gec_fix_filter_user', groups='base.group_user,base.group_partner_manager',
                                 password=cls.password)
        cls.other = new_test_user(cls.env, 'gec_fix_filter_other', groups='base.group_user')
        cls.partner = cls.env['res.partner'].create({'name': 'Filtered by user'})
        cls.env['gec.access.profile'].create({
            'name': 'Own salesperson', 'user_ids': [(6, 0, cls.user.ids)],
            'field_ids': [(0, 0, {
                'model_id': cls.env['ir.model']._get('res.partner').id,
                'field_id': cls.env['ir.model.fields']._get('res.partner', 'user_id').id,
                'mode': 'keep', 'field_domain': "[('id', '=', user.id)]"})]})

    def _write(self, vals):
        return self.make_jsonrpc_request('/web/dataset/call_kw/res.partner/write', {
            'model': 'res.partner', 'method': 'write', 'args': [self.partner.ids, vals], 'kwargs': {}})

    @mute_logger('odoo.http')
    def test_a_filter_may_use_the_user(self):
        """ B12: ``user`` is known to the server check, as in the web client and in an access row. """
        self.authenticate(self.user.login, self.password)
        with self.assertRaises(JsonRpcException):
            self._write({'user_id': self.other.id})
        self._write({'user_id': self.user.id})
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.user_id, self.user)


@tagged('post_install', '-at_install')
class TestImportScreen(ClientCalls, HttpCase):

    @classmethod
    def setUpClass(cls):
        if 'base_import.import' not in Registry(get_db_name()):
            raise SkipTest("base_import is not installed")
        super().setUpClass()
        cls.password = 'gec-access-manager-fixes-import-pw'
        cls.user = new_test_user(cls.env, 'gec_fix_import_user', groups='base.group_user,base.group_partner_manager',
                                 password=cls.password)
        cls.other = new_test_user(cls.env, 'gec_fix_import_other', groups='base.group_user')
        Fields = cls.env['ir.model.fields']
        partner_model = cls.env['ir.model']._get('res.partner')
        cls.env['gec.access.profile'].create({
            'name': 'Import guard', 'user_ids': [(6, 0, cls.user.ids)],
            'field_ids': [
                (0, 0, {'model_id': partner_model.id, 'field_id': Fields._get('res.partner', 'phone').id,
                        'mode': 'readonly'}),
                (0, 0, {'model_id': partner_model.id, 'field_id': Fields._get('res.partner', 'user_id').id,
                        'mode': 'keep', 'field_domain': "[('id', '=', user.id)]"}),
            ]})

    def setUp(self):
        super().setUp()
        self.authenticate(self.user.login, self.password)

    def _import(self, content, columns):
        """ The result of the Import screen run on ``content`` through the web client; a call refused as a
        whole (a locked column) comes back as the same dict with the error as its only message. """
        record = self.env['base_import.import'].with_user(self.user).create({
            'res_model': 'res.partner', 'file': BinaryBytes(content), 'file_type': 'text/csv',
            'file_name': 'partners.csv'})
        options = {
            'date_format': '', 'datetime_format': '', 'quoting': '"', 'separator': ',', 'encoding': 'utf-8',
            'float_decimal_separator': '.', 'float_thousand_separator': ',', 'has_headers': True}
        args = [record.ids, columns, columns, options]
        response = self.url_open('/web/dataset/call_kw/base_import.import/execute_import', json={
            'jsonrpc': '2.0', 'method': 'call', 'id': 1,
            'params': {'model': 'base_import.import', 'method': 'execute_import', 'args': args, 'kwargs': {}}})
        body = response.json()
        if 'error' in body:
            return {'ids': False, 'messages': [{'message': body['error']['data']['message']}]}
        return body['result']

    def _partners(self, name):
        return self.env['res.partner'].search([('name', '=', name)])

    @mute_logger('odoo.http')
    def test_the_import_screen_follows_the_field_rules(self):
        """ A15: a read-only field is refused as a column of the Import screen; the same file without it loads. """
        refused = self._import(b'name,phone\nImported phone,123\n', ['name', 'phone'])
        self.assertFalse(refused['ids'])
        self.assertIn('does not allow', str(refused['messages']))
        self.assertFalse(self._partners('Imported phone'))
        result = self._import(b'name\nImported plain\n', ['name'])
        self.assertTrue(result['ids'], result)
        self.assertEqual(len(self._partners('Imported plain')), 1)

    @mute_logger('odoo.http')
    def test_the_import_screen_follows_the_value_filters(self):
        """ A15: a row whose value is outside the filter of its field is refused, a row within it loads. """
        refused = self._import(b'name,user_id/.id\nImported other,%d\n' % self.other.id, ['name', 'user_id/.id'])
        self.assertFalse(refused['ids'])
        self.assertIn('does not allow', str(refused['messages']))
        self.assertFalse(self._partners('Imported other'))
        result = self._import(b'name,user_id/.id\nImported own,%d\n' % self.user.id, ['name', 'user_id/.id'])
        self.assertTrue(result['ids'], result)
        self.assertEqual(self._partners('Imported own').user_id, self.user)


@tagged('post_install', '-at_install')
class TestOpenItemsRules(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env['gec.access.profile']
        cls.password = 'gec-access-manager-open-items-pw'
        cls.user = new_test_user(cls.env, 'gec_open_user', groups='base.group_user,base.group_partner_manager',
                                 password=cls.password)

    def _profile(self, **values):
        return self.Profile.create(dict({'name': 'Open items', 'user_ids': [Command.set(self.user.ids)]}, **values))

    def test_the_hr_template_hides_the_wage_of_both_models(self):
        """ A14: hr.employee inherits the wage of hr.version, so it gets its own rule; the price of a variant too;
        the payroll menu of Odoo comes first, the one of Odoo Mates is the fallback. """
        template = TEMPLATES_BY_KEY['hr_officer']
        self.assertLessEqual({('hr.version', 'wage', 'hide'), ('hr.employee', 'wage', 'hide')}, set(template['fields']))
        self.assertEqual(template['hide_menus'], [
            ('hr_payroll.menu_hr_payroll_root', 'om_hr_payroll.menu_hr_payroll_root')])
        self.assertIn(('product.product', 'list_price'), SALE_PRICE_FIELDS)

    def test_a_menu_with_alternatives_hides_the_first_found_and_reports_a_miss(self):
        """ A14: of the xmlids of one entry the first one found is hidden; an entry with none found is reported. """
        recipe = {
            'key': 'gec_alternatives', 'name': 'Alternatives', 'description': 'A recipe of the tests.',
            'requires': [],
            'hide_menus': [('gec_not_installed.menu', 'base.menu_administration'),
                           ('gec_not_installed.other', 'base.menu_no_such_menu')],
        }
        TEMPLATES.append(recipe)
        TEMPLATES_BY_KEY[recipe['key']] = recipe
        self.addCleanup(TEMPLATES.remove, recipe)
        self.addCleanup(TEMPLATES_BY_KEY.pop, recipe['key'])
        wizard = self.env['gec.access.template.wizard'].create({'template_key': recipe['key'], 'name': 'GEC Alt'})
        profile = self.Profile.browse(wizard.action_create()['res_id'])
        self.assertEqual(profile.hidden_menu_ids, self.env.ref('base.menu_administration'))
        self.assertIn('base.menu_no_such_menu', profile.note)

    def test_read_only_everywhere_spares_the_own_settings_of_the_user(self):
        """ A25: the user's settings and favorites stay writable, the favorites of another user and the contacts
        do not, even for a user whom Odoo lets write every favorite. """
        user = new_test_user(self.env, 'gec_open_auditor', groups='base.group_user,base.group_erp_manager')
        other = new_test_user(self.env, 'gec_open_auditor_other', groups='base.group_user')
        self.Profile.create({'name': 'Auditor', 'global_readonly': True, 'user_ids': [Command.set(user.ids)]})
        settings = self.env['res.users.settings']._find_or_create_for_user(user)
        settings.with_user(user).write({'channel_notifications': 'no_notif'})
        self.assertEqual(settings.channel_notifications, 'no_notif')
        values = {'name': 'GEC favorite', 'model_id': 'res.partner'}
        own = self.env['ir.filters'].with_user(user).create(dict(values, user_ids=[Command.set(user.ids)]))
        own.write({'name': 'GEC renamed'})
        own.unlink()
        theirs = self.env['ir.filters'].create(dict(values, user_ids=[Command.set(other.ids)]))
        with self.assertRaises(AccessError):
            theirs.with_user(user).write({'name': 'Taken'})
        self.assertFalse(self.env['res.partner'].with_user(user).browse().has_access('write'))
        self.assertIn('saved searches', self.Profile._fields['global_readonly'].help)

    def test_a_note_does_not_clear_the_cached_rules(self):
        """ A18: a write that changes no rule leaves the 'default' cache alone, a switch clears it and the next
        resolution sees it. """
        profile = self._profile()
        self.assertFalse(self.Profile.with_user(self.user)._current_rules().has_flag('block_export'))
        transaction = type(self.env.transaction)
        with patch.object(transaction, 'invalidate_ormcache') as invalidate:
            profile.write({'note': '<p>Only a note</p>'})
        self.assertNotIn('default', [call.args[0] for call in invalidate.call_args_list if call.args])
        profile.write({'block_export': True})
        self.assertTrue(self.Profile.with_user(self.user)._current_rules().has_flag('block_export'))

    def test_one_session_stamps_the_completed_sign_in_only(self):
        """ A10: the credential check stamps nothing (2FA may follow); the open session does. """
        self._profile(single_session=True)
        request = MagicMock()
        request.session = {}
        with patch('odoo.addons.gec_access_manager.models.res_users.request', request):
            self.env['res.users']._login(
                {'login': self.user.login, 'password': self.password, 'type': 'password'}, {'interactive': True})
            self.assertFalse(self.user.sudo().gec_access_login_stamp)
            self.assertNotIn(LOGIN_STAMP_KEY, request.session)
            self.user.with_user(self.user)._after_session_login()
        self.assertTrue(self.user.sudo().gec_access_login_stamp)
        self.assertIn(LOGIN_STAMP_KEY, request.session)

    def test_block_rpc_says_what_it_blocks(self):
        """ A7: the help names the sign-in through /web/session/authenticate as a browser sign-in. """
        self.assertIn('/web/session/authenticate', self.Profile._fields['block_rpc'].help)

    def test_a_group_form_change_refreshes_the_cached_rules(self):
        """ A22: a user put into Settings from the group form is no longer restricted by a profile that spares
        Settings users, though no profile uses groups. """
        self._profile(global_readonly=True)
        self.assertTrue(self.Profile.with_user(self.user)._current_rules().enabled)
        self.env.ref('base.group_system').write({'user_ids': [Command.link(self.user.id)]})
        self.assertFalse(self.Profile.with_user(self.user)._current_rules().enabled)

    def test_an_import_judges_its_rows_not_the_writes_odoo_makes(self):
        """ N9: during an import of partners, a partner Odoo writes by itself keeps a read only field, the row of
        the import does not. """
        self._profile(field_ids=[Command.create({
            'model_id': self.env['ir.model']._get('res.partner').id,
            'field_id': self.env['ir.model.fields']._get('res.partner', 'phone').id, 'mode': 'readonly'})])
        Partner = self.env['res.partner'].with_user(self.user).with_context(gec_access_import='res.partner')
        self.assertEqual(Partner.create({'name': 'GEC Nested', 'phone': '123'}).sudo().phone, '123')
        imported = Partner._load_records_create([{'name': 'GEC Imported', 'phone': '456'}])
        self.assertFalse(imported.sudo().phone)

    def test_block_archiving_refuses_only_what_archives(self):
        """ N10: an import column of True values and a CREATE command with active True archive nothing; a False
        value, or an UPDATE command setting active, is refused. """
        self._profile(block_archive=True)
        Partner = self.env['res.partner'].with_user(self.user)
        self.assertTrue(Partner.load(['name', 'active'], [['GEC Active', '1']])['ids'])
        with self.assertRaisesRegex(UserError, 'archiving'):
            Partner.load(['name', 'active'], [['GEC Gone', '0']])
        Profile = self.Profile.with_user(self.user)
        Profile._check_archive_call('res.partner', 'write', [[1], {'child_ids': [(0, 0, {'name': 'C', 'active': True})]}], {})
        with self.assertRaisesRegex(UserError, 'archiving'):
            Profile._check_archive_call('res.partner', 'write', [[1], {'child_ids': [(0, 0, {'active': False})]}], {})
        with self.assertRaisesRegex(UserError, 'archiving'):
            Profile._check_archive_call('res.partner', 'write', [[1], {'child_ids': [(1, 2, {'active': True})]}], {})


@tagged('post_install', '-at_install')
class TestOpenItemsClient(ClientCalls, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'gec-access-manager-open-items-client-pw'
        cls.user = new_test_user(cls.env, 'gec_open_client', groups='base.group_user,base.group_partner_manager',
                                 password=cls.password)
        cls.partner = cls.env['res.partner'].create({'name': 'Open items partner'})

    def setUp(self):
        super().setUp()
        self.authenticate(self.user.login, self.password)

    def _profile(self, **values):
        return self.env['gec.access.profile'].create(
            dict({'name': 'Open items', 'user_ids': [Command.set(self.user.ids)]}, **values))

    def _load_error(self, action):
        response = self.url_open('/web/action/load', json={
            'jsonrpc': '2.0', 'method': 'call', 'id': 1, 'params': {'action_id': action.id}})
        return response.json().get('error', {}).get('data', {}).get('message')

    def test_hide_print_refuses_the_report_route_not_the_server_render(self):
        """ A16: the route of the web client is refused; the rendering the server does for Send & Print is not. """
        self.env['ir.ui.view'].create({
            'name': 'gec_open_report', 'type': 'qweb', 'key': 'gec_access_manager.gec_open_report',
            'arch': '<t t-name="gec_access_manager.gec_open_report"><div>GEC sheet</div></t>'})
        report = self.env['ir.actions.report'].create({
            'name': 'GEC Sheet', 'model': 'res.partner', 'report_type': 'qweb-html',
            'report_name': 'gec_access_manager.gec_open_report'})
        self._profile(hide_print_all=True)
        response = self.url_open(f'/report/html/{report.report_name}/{self.partner.id}')
        self.assertEqual(response.status_code, 403)
        html = self.env['ir.actions.report'].with_user(self.user)._render_qweb_html(report.report_name, self.partner.ids)[0]
        self.assertIn('GEC sheet', str(html))

    def test_a_hidden_menu_does_not_open_its_action_by_url(self):
        """ A21: an action whose only menu is hidden is refused; one with a visible menu, or with none, loads. """
        Action = self.env['ir.actions.act_window']
        Menu = self.env['ir.ui.menu']
        only_hidden, both, no_menu = (Action.create({'name': name, 'res_model': 'res.partner.category'})
                                      for name in ('GEC Only Hidden', 'GEC Both', 'GEC No Menu'))
        hidden = Menu.create({'name': 'GEC Hidden', 'action': f'ir.actions.act_window,{only_hidden.id}'})
        hidden_too = Menu.create({'name': 'GEC Hidden Too', 'action': f'ir.actions.act_window,{both.id}'})
        Menu.create({'name': 'GEC Visible', 'action': f'ir.actions.act_window,{both.id}'})
        self._profile(hidden_menu_ids=[Command.set((hidden | hidden_too).ids)])
        self.assertIn('hides it', self._load_error(only_hidden))
        for action in (both, no_menu):
            self.assertIsNone(self._load_error(action), action.name)

    @mute_logger('odoo.http')
    def test_hide_send_message_refuses_the_full_composer(self):
        """ composer: the Send button of the wizard (call_button of action_send_mail) is refused as the chatter
        is, the Log button (a note) is not. The wizard is made by the user: transient records are per user. """
        self._profile(hide_send_message_all=True)
        Composer = self.env['mail.compose.message'].with_user(self.user).with_context(
            active_model='res.partner', active_ids=self.partner.ids)
        message = Composer.create({'body': 'Hello', 'composition_mode': 'comment',
                                   'model': 'res.partner', 'res_ids': f'{self.partner.ids}'})
        self.assertIn('sending messages', self._error(
            'mail.compose.message', 'action_send_mail', [message.ids], route='call_button'))
        note = Composer.create({
            'body': 'A note', 'composition_mode': 'comment', 'subtype_id': self.env.ref('mail.mt_note').id,
            'model': 'res.partner', 'res_ids': f'{self.partner.ids}'})
        self._call('mail.compose.message', 'action_send_mail', [note.ids], route='call_button')
