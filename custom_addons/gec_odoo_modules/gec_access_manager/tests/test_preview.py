# Preview as a user: the screens of another user, read only, in the
# administrator's own session.
import time

from odoo.exceptions import UserError
from odoo.http.session import session_store
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tools import mute_logger

from .audit import lines_after_transaction


@tagged('post_install', '-at_install')
class TestPreview(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'gec-access-manager-preview-pw'
        cls.manager = new_test_user(
            cls.env, 'gec_preview_manager', password=cls.password,
            groups='base.group_user,base.group_system,gec_access_manager.group_access_manager')
        cls.user = new_test_user(cls.env, 'gec_preview_user', groups='base.group_user,base.group_partner_manager',
                                 password=cls.password)
        partner_model = cls.env['ir.model']._get('res.partner')
        cls.discuss = cls.env.ref('mail.menu_root_discuss')
        cls.mine = cls.env['res.partner'].create({'name': 'Previewed Own'})
        cls.other = cls.env['res.partner'].create({'name': 'Previewed Other'})
        cls.profile = cls.env['gec.access.profile'].create({
            'name': 'Previewed Profile',
            'user_ids': [(6, 0, cls.user.ids)],
            'hidden_menu_ids': [(6, 0, cls.discuss.ids)],
            'model_ids': [(0, 0, {
                'model_id': partner_model.id,
                'perm_read': True, 'perm_write': True, 'perm_create': True, 'perm_unlink': True,
                'domain': repr([('id', '=', cls.mine.id)]),
            })],
            'button_ids': [(0, 0, {
                'model_id': partner_model.id, 'button_type': 'object',
                'button_name': 'action_archive', 'mode': 'block',
            })],
        })

    def setUp(self):
        super().setUp()
        self.authenticate(self.manager.login, self.password, session_extra={'identity-check-last': time.time()})

    def _call(self, model, method, args, kwargs=None, route='call_kw'):
        return self.make_jsonrpc_request(f'/web/dataset/{route}/{model}/{method}', {
            'model': model, 'method': method, 'args': args, 'kwargs': kwargs or {},
        })

    def _error(self, model, method, args, kwargs=None, route='call_kw'):
        """ The message of the error a call answers with. """
        response = self.url_open(f'/web/dataset/{route}/{model}/{method}', json={
            'jsonrpc': '2.0', 'method': 'call', 'id': 1,
            'params': {'model': model, 'method': method, 'args': args, 'kwargs': kwargs or {}},
        })
        return response.json()['error']['data']['message']

    def _start(self, user=None):
        return self._call('res.users', 'action_gec_preview', [(user or self.user).ids], route='call_button')

    def _change_preview(self, **values):
        """ Edit the preview stored in the session, as if time had passed or another user had signed in. """
        store = session_store()
        stored = store.get(self.opener.cookies.get('session_id'))
        stored['gec_access_preview'] = dict(stored['gec_access_preview'], **values)
        store.save(stored)

    def _menu_ids(self):
        return {int(key) for key in self.url_open('/web/webclient/load_menus').json() if key.isdigit()}

    def test_who_may_preview(self):
        self.assertTrue(self.user._gec_preview_refusal(self.user))
        self.assertFalse(self.user._gec_preview_refusal(self.manager))
        self.assertTrue(self.manager._gec_preview_refusal(self.manager))
        self.assertTrue(self.env.ref('base.user_admin')._gec_preview_refusal(self.manager))
        # an access manager outside Settings never previews: the preview reads what they may not
        manager = new_test_user(self.env, 'gec_preview_small', groups='base.group_user,'
                                'gec_access_manager.group_access_manager')
        self.assertIn('Settings', self.user._gec_preview_refusal(manager))
        plain = new_test_user(self.env, 'gec_preview_plain', groups='base.group_user')
        self.assertIn('Settings', plain._gec_preview_refusal(manager))

    def test_the_session_is_seen_as_the_user(self):
        self.assertIn(self.discuss.id, self._menu_ids())
        result = self._start()
        self.assertEqual(result['type'], 'ir.actions.act_url')
        info = self.make_jsonrpc_request('/web/session/get_session_info')
        self.assertEqual(info['uid'], self.user.id)
        self.assertEqual(info['gec_preview']['name'], self.user.name)
        self.assertEqual(info['gec_preview']['profiles'], ['Previewed Profile'])
        self.assertIn('o_gec_preview', info['gec_access_classes'])
        # the page of the web client too, although /odoo is served without a user
        self.assertIn('"gec_preview"', self.url_open('/odoo').text)
        self.assertNotIn(self.discuss.id, self._menu_ids())
        rows = self._call('res.partner', 'search_read', [[('id', 'in', [self.mine.id, self.other.id])], ['name']])
        self.assertEqual([row['id'] for row in rows], [self.mine.id])
        # and back
        result = self.make_jsonrpc_request('/gec_access_manager/preview/stop')
        self.assertIn('/odoo', result['url'])
        self.assertEqual(self.make_jsonrpc_request('/web/session/get_session_info')['uid'], self.manager.id)
        self.assertIn(self.discuss.id, self._menu_ids())

    @mute_logger('odoo.http')
    def test_nothing_is_saved(self):
        self._start()
        self.assertIn('preview', self._error('res.partner', 'web_save', [self.mine.ids, {'name': 'Changed'}],
                                             {'specification': {}}))
        self.assertEqual(self.mine.name, 'Previewed Own')
        self.assertIn('preview', self._error('res.partner', 'create', [{'name': 'Created in a preview'}]))
        self.assertFalse(self.env['res.partner'].search([('name', '=', 'Created in a preview')]))

    @mute_logger('odoo.http')
    def test_buttons_say_what_the_user_may_do(self):
        self._start()
        # blocked for the user: the profile's refusal
        self.assertIn('You cannot use this button',
                      self._error('res.partner', 'action_archive', [self.mine.ids], route='call_button'))
        # allowed: said, not run
        self.assertIn('%s can use this' % self.user.name,
                      self._error('res.partner', 'action_unarchive', [self.mine.ids], route='call_button'))
        self.assertTrue(self.mine.active)

    @mute_logger('odoo.http')
    def test_server_actions_run_read_only(self):
        """ Menus open server actions that pick a view: they run in a preview,
        and what one would save is refused. """
        partner_model = self.env['ir.model']._get('res.partner')
        opens = self.env['ir.actions.server'].create({
            'name': 'GEC Open Partners', 'model_id': partner_model.id, 'state': 'code',
            'code': "action = {'type': 'ir.actions.act_window', 'res_model': 'res.partner', 'views': [[False, 'list']]}",
        })
        saves = self.env['ir.actions.server'].create({
            'name': 'GEC Save a Partner', 'model_id': partner_model.id, 'state': 'code',
            'code': "env['res.partner'].create({'name': 'Saved in a preview'})",
        })
        for action in (opens, saves):
            self.env['ir.ui.menu'].create({'name': action.name, 'action': f'ir.actions.server,{action.id}'})
        self._start()
        result = self.make_jsonrpc_request('/web/action/run', {'action_id': opens.id})
        self.assertEqual(result['res_model'], 'res.partner')
        response = self.url_open('/web/action/run', json={
            'jsonrpc': '2.0', 'method': 'call', 'id': 1, 'params': {'action_id': saves.id}})
        self.assertIn('preview', response.json()['error']['data']['message'])
        self.assertFalse(self.env['res.partner'].search([('name', '=', 'Saved in a preview')]))

    def test_reads_are_logged_as_the_administrator(self):
        self.env['gec.user.audit.rule'].create({'name': 'Partners', 'model_ids': [
            (6, 0, self.env['ir.model']._get('res.partner').ids)], 'log_read': True})
        self._start()
        with lines_after_transaction(self.env) as lines:
            self._call('res.partner', 'web_read', [self.mine.ids], {'specification': {'name': {}}})
        reads = [line for line in lines if line['event'] == 'read']
        self.assertTrue(reads)
        self.assertEqual({line['user_id'] for line in reads}, {self.manager.id})
        self.assertIn(self.user.name, reads[0]['detail'])

    def test_reads_are_logged_without_a_rule_or_the_setting(self):
        """ N7: with no audit rule and log_reads not set, a read in a preview is logged as read by the viewer. """
        self.env['gec.user.audit.rule'].search([]).unlink()
        self.env['ir.config_parameter'].sudo().set_bool('gec_user_audit.log_reads', False)
        self._start()
        with lines_after_transaction(self.env) as lines:
            self._call('res.partner', 'web_read', [self.mine.ids], {'specification': {'name': {}}})
        reads = [line for line in lines if line['event'] == 'read' and line['model'] == 'res.partner']
        self.assertTrue(reads)
        self.assertEqual({line['user_id'] for line in reads}, {self.manager.id})

    def test_a_rule_naming_an_excluded_model_logs_its_reads(self):
        """ N7: a rule naming a model the settings exclude logs its reads in a preview too, as it does outside. """
        self.env['gec.user.audit.rule'].create({'name': 'Partners', 'model_ids': [
            (6, 0, self.env['ir.model']._get('res.partner').ids)], 'log_read': True})
        self.env['ir.config_parameter'].sudo().set_str('gec_user_audit.excluded_models', 'res.partner')
        self._start()
        with lines_after_transaction(self.env) as lines:
            self._call('res.partner', 'web_read', [self.mine.ids], {'specification': {'name': {}}})
        reads = [line for line in lines if line['event'] == 'read' and line['model'] == 'res.partner']
        self.assertTrue(reads)
        self.assertEqual({line['user_id'] for line in reads}, {self.manager.id})

    def test_client_context_cannot_disable_preview_read_logging(self):
        """ A preview still logs a read when the client supplies the former bypass flag. """
        self.env['gec.user.audit.rule'].search([]).unlink()
        self.env['ir.config_parameter'].sudo().set_bool('gec_user_audit.log_reads', False)
        self._start()
        with lines_after_transaction(self.env) as lines:
            result = self._call('res.partner', 'web_read', [self.mine.ids], {
                'specification': {'name': {}}, 'context': {'gec_user_audit_off': True},
            })
        self.assertEqual(result[0]['name'], self.mine.name)
        reads = [line for line in lines if line['event'] == 'read' and line['model'] == 'res.partner']
        self.assertTrue(reads)
        self.assertEqual({line['user_id'] for line in reads}, {self.manager.id})

    def test_an_expired_preview_ends(self):
        self._start()
        session = self.opener.cookies.get('session_id')
        self.assertTrue(session)
        self.assertEqual(self.make_jsonrpc_request('/web/session/get_session_info')['uid'], self.user.id)
        store = session_store()
        stored = store.get(session)
        stored['gec_access_preview'] = dict(stored['gec_access_preview'], until=time.time() - 1)
        store.save(stored)
        self.assertEqual(self.make_jsonrpc_request('/web/session/get_session_info')['uid'], self.manager.id)

    @mute_logger('odoo.http')
    def test_an_ended_preview_saves_nothing(self):
        """ After the hour the session is still a preview: read only, with the ended message. """
        self._start()
        self._change_preview(until=time.time() - 1)
        message = 'The preview has ended'
        self.assertIn(message, self._error('res.partner', 'write', [self.mine.ids, {'name': 'Changed'}]))
        self.mine.invalidate_recordset(['name'])
        self.assertEqual(self.mine.name, 'Previewed Own')
        self.assertIn(message, self._error('res.partner', 'action_archive', [self.mine.ids], route='call_button'))
        self.assertTrue(self.mine.active)

    @mute_logger('odoo.http')
    def test_an_ended_preview_is_read_only_in_the_database(self):
        """ Past the controllers' refusals, the transaction itself refuses a write once the preview has ended:
        a menu's server action writing as the superuser (which Base.create lets through) saves nothing. """
        partner_model = self.env['ir.model']._get('res.partner')
        saves = self.env['ir.actions.server'].create({
            'name': 'GEC Save after the end', 'model_id': partner_model.id, 'state': 'code',
            'code': "env['res.partner'].sudo().create({'name': 'Saved after the end'})",
        })
        self.env['ir.ui.menu'].create({'name': saves.name, 'action': f'ir.actions.server,{saves.id}'})
        self._start()
        self._change_preview(until=time.time() - 1)
        response = self.url_open('/web/action/run', json={
            'jsonrpc': '2.0', 'method': 'call', 'id': 1, 'params': {'action_id': saves.id}})
        self.assertIn('read-only transaction', response.json()['error']['data']['message'])
        self.assertFalse(self.env['res.partner'].search([('name', '=', 'Saved after the end')]))

    def test_an_ended_preview_still_loads_the_web_client(self):
        """ The web client starts, as the administrator, and its banner knows the preview has ended. """
        self._start()
        self._change_preview(until=time.time() - 1)
        self.assertEqual(self.url_open('/web/webclient/translations').status_code, 200)
        response = self.url_open('/web/webclient/load_menus')
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.discuss.id, {int(key) for key in response.json() if key.isdigit()})
        info = self.make_jsonrpc_request('/web/session/get_session_info')
        self.assertEqual(info['uid'], self.manager.id)
        self.assertTrue(info['gec_preview']['ended'])
        self.assertEqual(info['gec_preview']['name'], self.user.name)
        self.assertIn('o_gec_preview', info['gec_access_classes'])

    def test_exit_after_the_preview_ended(self):
        """ The Exit route works once the preview has ended; what is written after it is saved as the administrator. """
        self._start()
        self._change_preview(until=time.time() - 1)
        result = self.make_jsonrpc_request('/gec_access_manager/preview/stop')
        self.assertIn('/odoo', result['url'])
        self.assertNotIn('gec_access_preview', session_store().get(self.opener.cookies.get('session_id')))
        info = self.make_jsonrpc_request('/web/session/get_session_info')
        self.assertEqual(info['uid'], self.manager.id)
        self.assertNotIn('gec_preview', info)
        partner = self.manager.partner_id
        self._call('res.partner', 'write', [partner.ids, {'name': 'Saved After Exit'}])
        partner.invalidate_recordset()
        self.assertEqual(partner.name, 'Saved After Exit')
        self.assertEqual(partner.write_uid, self.manager)

    def test_a_preview_of_another_viewer_is_dropped(self):
        """ A preview started by another user of the session is neither shown nor kept: the request runs normally. """
        self._start()
        self._change_preview(by=self.user.id)
        info = self.make_jsonrpc_request('/web/session/get_session_info')
        self.assertEqual(info['uid'], self.manager.id)
        self.assertNotIn('gec_preview', info)
        self.assertNotIn('gec_access_preview', session_store().get(self.opener.cookies.get('session_id')))
        partner = self.manager.partner_id
        self._call('res.partner', 'write', [partner.ids, {'name': 'Saved Without Preview'}])
        partner.invalidate_recordset()
        self.assertEqual(partner.write_uid, self.manager)

    def test_a_profile_previews_its_users_only(self):
        Profile = self.env['gec.access.profile'].with_user(self.manager)
        empty = Profile.create({'name': 'Nobody yet'})
        with self.assertRaisesRegex(UserError, 'No user has this profile yet'):
            empty.action_test_user()
        action = Profile.browse(self.profile.id).action_test_user()
        wizard = self.env['gec.access.test.user'].with_user(self.manager).with_context(action['context']).create({})
        self.assertEqual(wizard.user_id, self.user)
        self.assertEqual(wizard.preview_user_ids, self.user)
        outsider = new_test_user(self.env, 'gec_preview_outsider', groups='base.group_user')
        wizard.user_id = outsider
        with self.assertRaisesRegex(UserError, 'does not have the profile'):
            wizard.action_open_preview()

    def test_web_client_in_a_preview(self):
        self.manager.password = self.manager.login
        self.start_tour(f'/odoo/action-base.action_res_users/{self.user.id}', 'gec_access_manager_preview',
                        login=self.manager.login, timeout=120)

    def test_add_existing_users_from_the_profile(self):
        target = new_test_user(self.env, 'gec_add_users_target', groups='base.group_user')
        profile = self.env['gec.access.profile'].create({'name': 'Add Users Profile'})
        self.manager.password = self.manager.login
        self.start_tour(f'/odoo/action-gec_access_manager.gec_access_profile_action/{profile.id}',
                        'gec_access_manager_add_users', login=self.manager.login, timeout=120)
        self.assertEqual(profile.user_ids, target)


@tagged('post_install', '-at_install')
class TestTickToGrant(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, 'gec_tick_manager',
            groups='base.group_user,base.group_system,gec_access_manager.group_access_manager')
        privilege = cls.env['res.groups.privilege'].create({'name': 'GEC Tick App'})
        cls.app_user = cls.env['res.groups'].create({'name': 'User', 'privilege_id': privilege.id})
        cls.app_manager = cls.env['res.groups'].create({
            'name': 'Manager', 'privilege_id': privilege.id, 'implied_ids': [(4, cls.app_user.id)]})
        cls.root = cls.env['ir.ui.menu'].create({
            'name': 'GEC Tick App', 'group_ids': [(6, 0, (cls.app_user | cls.app_manager).ids)]})
        cls.env['ir.ui.menu'].create({
            'name': 'GEC Tick Records', 'parent_id': cls.root.id,
            'action': f'ir.actions.act_window,{cls.env.ref("base.action_partner_form").id}'})
        cls.user = new_test_user(cls.env, 'gec_tick_user', groups='base.group_user')
        cls.profile = cls.env['gec.access.profile'].create({'name': 'Tick', 'user_ids': [(6, 0, cls.user.ids)]})

    def test_app_access(self):
        Profile = self.env['gec.access.profile'].with_user(self.manager)
        access = Profile.browse(self.profile.id).gec_app_access(self.user.ids)[self.root.id]
        self.assertFalse(access['open'])
        self.assertEqual(access['grant']['id'], self.app_user.id)
        self.assertEqual(access['grant']['name'], 'GEC Tick App / User')
        self.assertEqual(set(access['group_ids']), {self.app_user.id, self.app_manager.id})
        # a user who already has the app
        holder = new_test_user(self.env, 'gec_tick_holder', groups='base.group_user')
        holder.group_ids |= self.app_user
        self.assertTrue(Profile.browse(self.profile.id).gec_app_access(holder.ids)[self.root.id]['open'])
        # nobody yet: nothing to tell
        self.assertTrue(Profile.gec_app_access([])[self.root.id]['open'])

    def test_ticking_an_app_gives_it(self):
        self.start_tour(f'/odoo/action-gec_access_manager.gec_access_profile_action/{self.profile.id}',
                        'gec_access_manager_tick_grant', login=self.manager.login, timeout=120)
        self.assertEqual(self.profile.granted_group_ids, self.app_user)
        self.assertIn(self.app_user, self.user.all_group_ids)

    def test_unticking_an_app_takes_it_back(self):
        self.profile.granted_group_ids = self.app_user
        self.start_tour(f'/odoo/action-gec_access_manager.gec_access_profile_action/{self.profile.id}',
                        'gec_access_manager_untick_grant', login=self.manager.login, timeout=120)
        self.assertFalse(self.profile.granted_group_ids)
        self.assertIn(self.root, self.profile.hidden_menu_ids)
        self.assertNotIn(self.app_user, self.user.all_group_ids)
