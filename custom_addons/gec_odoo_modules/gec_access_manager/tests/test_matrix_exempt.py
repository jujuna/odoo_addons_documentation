# Matrix of who is never restricted (the superuser, sudo, the Administrator, a Settings user unless the profile says
# otherwise, portal and public users) and who always is (a cron running as a restricted user, a restricted user trying
# to widen their own access), then the switches of a profile that the entry-point matrix could not reach, over HTTP.
import threading
from contextlib import contextmanager
from datetime import timedelta

from odoo import SUPERUSER_ID, Command, fields
from odoo.exceptions import AccessDenied, AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger

from .test_codex_fixes import GuardCase
from .test_fixes import ClientCalls

ONE = "[('name', '=', 'MX Exempt One')]"
CRON_PARAMETER = 'gec_access_manager.mx_exempt_cron_count'


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixExempt(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env['res.partner']
        cls.one, cls.two, cls.three = Partner.create([
            {'name': f'MX Exempt {name}', 'email': f'mx-{name.lower()}@exempt.example'}
            for name in ('One', 'Two', 'Three')])
        cls.partners = cls.one | cls.two | cls.three
        cls.password = 'mx-exempt-pw'
        cls.user = new_test_user(cls.env, 'mx_exempt_user', password=cls.password,
                                 groups='base.group_user,base.group_partner_manager')
        cls.Partner = Partner
        cls.Profile = cls.env['gec.access.profile']
        cls.partner_model = cls.env['ir.model']._get('res.partner')
        cls.email = cls.env['ir.model.fields']._get('res.partner', 'email')

    def _profile(self, users=None, **values):
        users = self.user if users is None else users
        return self.Profile.create({'name': 'MX Exempt', 'user_ids': [Command.set(users.ids)], **values})

    def _restrictive_profile(self, users=None, **values):
        """ One partner readable and writable, none deletable, the email hidden to the client. """
        return self._profile(users, model_ids=[Command.create({
            'model_id': self.partner_model.id, 'domain': ONE, 'perm_unlink': False})],
            field_ids=[Command.create({'model_id': self.partner_model.id, 'field_id': self.email.id, 'mode': 'hide'})],
            **values)

    def _seen(self, user):
        return self.Partner.with_user(user).search([('id', 'in', self.partners.ids)])

    @contextmanager
    def _client_call(self, model_name, method):
        """ Like the XML-RPC door: the thread tells which call the client made (gec_user_audit's _gec_rpc_entry). """
        thread = threading.current_thread()
        previous = getattr(thread, 'rpc_model_method', None)
        thread.rpc_model_method = f'{model_name}.{method}'
        try:
            yield
        finally:
            thread.rpc_model_method = previous

    def _email_as_client(self, partners):
        with self._client_call('res.partner', 'read'):
            return partners.read(['email'])[0]['email']

    def test_sudo_of_a_restricted_user_is_not_restricted(self):
        self._restrictive_profile()
        mine = self.one.with_user(self.user)
        self.assertEqual(self._seen(self.user), self.one)
        self.assertFalse(self._email_as_client(mine))
        self.assertFalse(self.three.with_user(self.user).has_access('read'))
        self.assertFalse(mine.has_access('unlink'))
        with self.assertRaises(AccessError):
            mine.unlink()
        everything = self.Partner.with_user(self.user).sudo()
        self.assertEqual(everything.search([('id', 'in', self.partners.ids)]), self.partners)
        self.assertEqual(self._email_as_client(mine.sudo()), 'mx-one@exempt.example')
        self.assertTrue(self.three.with_user(self.user).sudo().has_access('read'))
        self.assertTrue(self.three.with_user(self.user).sudo().has_access('unlink'))
        self.three.with_user(self.user).sudo().unlink()
        self.assertFalse(self.three.exists())

    def test_the_superuser_is_not_restricted(self):
        self._restrictive_profile(self.env['res.users'].browse(SUPERUSER_ID))
        root = self.env['res.users'].browse(SUPERUSER_ID)
        self.assertFalse(self.Profile._resolve(SUPERUSER_ID).enabled)
        self.assertEqual(self._seen(root), self.partners)
        self.assertEqual(self._email_as_client(self.one.with_user(root)), 'mx-one@exempt.example')

    def test_the_administrator_is_not_restricted_even_in_a_profile_for_settings_users(self):
        admin = self.env.ref('base.user_admin')
        self._restrictive_profile(admin, apply_to_admin=True)
        self.assertFalse(self.Profile._resolve(admin.id).enabled)
        self.assertEqual(self._seen(admin), self.partners)
        self.assertTrue(self.three.with_user(admin).has_access('unlink'))
        self.assertEqual(self._email_as_client(self.one.with_user(admin)), 'mx-one@exempt.example')

    def test_a_settings_user_is_exempt_unless_the_profile_applies_to_them(self):
        settings = new_test_user(self.env, 'mx_exempt_settings',
                                 groups='base.group_user,base.group_system,base.group_partner_manager')
        profile = self._restrictive_profile(settings)
        self.assertFalse(self.Profile._resolve(settings.id).enabled)
        self.assertEqual(self._seen(settings), self.partners)
        self.assertTrue(self.three.with_user(settings).has_access('unlink'))
        self.assertEqual(self._email_as_client(self.one.with_user(settings)), 'mx-one@exempt.example')
        profile.apply_to_admin = True
        self.assertEqual(self._seen(settings), self.one)
        self.assertFalse(self.one.with_user(settings).has_access('unlink'))
        self.assertFalse(self._email_as_client(self.one.with_user(settings)))

    def test_portal_and_public_users_never_get_a_profile_for_new_users(self):
        profile = self._profile(self.env['res.users'], for_new_users=True, hide_activities=True)
        portal = new_test_user(self.env, 'mx_exempt_portal', groups='base.group_portal')
        public = new_test_user(self.env, 'mx_exempt_public', groups='base.group_public')
        internal = new_test_user(self.env, 'mx_exempt_internal', groups='base.group_user')
        self.assertEqual(internal.access_profile_ids, profile)
        self.assertFalse(portal.access_profile_ids)
        self.assertFalse(public.access_profile_ids)
        self.assertTrue(self.Profile._resolve(internal.id).enabled)
        self.assertFalse(self.Profile._resolve(portal.id).enabled)
        self.assertFalse(self.Profile._resolve(public.id).enabled)

    def test_a_profile_of_the_internal_group_never_applies_to_a_portal_user(self):
        portal = new_test_user(self.env, 'mx_exempt_portal', groups='base.group_portal')
        profile = self._profile(
            self.env['res.users'], group_ids=[Command.set(self.env.ref('base.group_user').ids)],
            model_ids=[Command.create({'model_id': self.partner_model.id, 'perm_read': False})])
        self.assertEqual(profile._gec_members(), self.env['res.users'].search([('share', '=', False)]))
        self.assertTrue(self.Profile._resolve(self.user.id).enabled)
        self.assertFalse(self.Profile._resolve(portal.id).enabled)
        self.assertNotIn(portal, profile._gec_members())

    def test_a_portal_user_keeps_the_access_to_their_own_records(self):
        portal = new_test_user(self.env, 'mx_exempt_portal', groups='base.group_portal')
        own = portal.partner_id
        own.message_post(body='MX portal note', message_type='comment', subtype_xmlid='mail.mt_comment',
                         partner_ids=own.ids)
        Message = self.env['mail.message'].with_user(portal)
        domain = [('model', '=', 'res.partner'), ('res_id', '=', own.id), ('body', 'ilike', 'MX portal note')]
        before = (own.with_user(portal).read(['name'])[0]['name'], Message.search(domain).ids,
                  self.Partner.with_user(portal).search([('id', 'in', (own | self.one).ids)]).ids)
        self.assertEqual(before[0], own.name)
        self.assertTrue(before[1], "the portal user sees the message sent to them")
        self._profile(self.env['res.users'], group_ids=[Command.set(self.env.ref('base.group_user').ids)],
                      global_readonly=True, model_ids=[Command.create({
                          'model_id': self.partner_model.id, 'domain': ONE})])
        after = (own.with_user(portal).read(['name'])[0]['name'], Message.search(domain).ids,
                 self.Partner.with_user(portal).search([('id', 'in', (own | self.one).ids)]).ids)
        self.assertEqual(after, before)
        own.with_user(portal).check_access('read')

    def test_a_cron_running_as_a_restricted_user_is_restricted(self):
        """ Core runs a cron as its user_id, so the profile applies to the code of the cron. """
        self._profile(model_ids=[Command.create({'model_id': self.partner_model.id, 'domain': ONE})])
        cron = self.env['ir.cron'].create({
            'name': 'MX Exempt cron', 'model_id': self.partner_model.id, 'user_id': self.user.id, 'state': 'code',
            'code': f"env['ir.config_parameter'].sudo().set_str({CRON_PARAMETER!r}, "
                    f"str(env['res.partner'].search_count([('id', 'in', {self.partners.ids})])))",
        })
        self.assertEqual(self._seen(self.user), self.one)
        with self.registry_test_mode():
            self.assertIs(cron.method_direct_trigger(), True)
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_str(CRON_PARAMETER), str(len(self.one)))

    def test_a_cron_running_as_an_unrestricted_user_sees_everything(self):
        cron = self.env['ir.cron'].create({
            'name': 'MX Exempt control cron', 'model_id': self.partner_model.id, 'user_id': self.user.id,
            'state': 'code',
            'code': f"env['ir.config_parameter'].sudo().set_str({CRON_PARAMETER!r}, "
                    f"str(env['res.partner'].search_count([('id', 'in', {self.partners.ids})])))",
        })
        with self.registry_test_mode():
            self.assertIs(cron.method_direct_trigger(), True)
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_str(CRON_PARAMETER), str(len(self.partners)))

    def test_change_password_works_for_a_restricted_user(self):
        self._profile(global_readonly=True)
        self.user.with_user(self.user).change_password(self.password, 'mx-exempt-new-pw')
        self.env.flush_all()
        credential = {'login': self.user.login, 'type': 'password'}
        mine = self.user.with_user(self.user)
        mine._check_credentials({**credential, 'password': 'mx-exempt-new-pw'}, {'interactive': True})
        with self.assertRaises(AccessDenied):
            mine._check_credentials({**credential, 'password': self.password}, {'interactive': True})

    def test_preferences_saved_by_the_browser_under_read_only_everywhere(self):
        """ The settings the web client saves by itself stay writable, only the user's own. """
        self._profile(global_readonly=True)
        Settings = self.env['res.users.settings']
        mine = Settings._find_or_create_for_user(self.user)
        theirs = Settings._find_or_create_for_user(self.env.ref('base.user_admin'))
        mine.with_user(self.user).write({'channel_notifications': 'no_notif'})
        self.assertEqual(mine.channel_notifications, 'no_notif')
        mine.with_user(self.user).set_res_users_settings({'channel_notifications': 'all'})
        self.assertEqual(mine.channel_notifications, 'all')
        with self.assertRaises(AccessError):
            theirs.with_user(self.user).write({'channel_notifications': 'no_notif'})

    def test_own_saved_searches_under_read_only_everywhere(self):
        self._profile(global_readonly=True)
        Filters = self.env['ir.filters'].with_user(self.user)
        saved = Filters.create({'name': 'MX Exempt filter', 'model_id': 'res.partner', 'domain': '[]',
                                'user_ids': [Command.set(self.user.ids)]})
        saved.write({'name': 'MX Exempt renamed'})
        saved.unlink()
        with self.assertRaises(AccessError):
            self.one.with_user(self.user).write({'name': 'MX Exempt One'})

    def test_accepted_limit_the_user_cannot_write_their_own_profile_under_read_only_everywhere(self):
        """ Accepted limit (D11): the Preferences form (language, time zone, signature) saves the user's own
        res.users record, which Read Only Everywhere refuses, as its help says. """
        self.user.with_user(self.user).write({'tz': 'Europe/Brussels'})
        self._profile(global_readonly=True)
        with self.assertRaises(AccessError):
            self.user.with_user(self.user).write({'tz': 'Asia/Tbilisi'})
        self.assertEqual(self.user.tz, 'Europe/Brussels')

    def test_a_note_and_an_activity_on_a_readable_record_of_a_restricted_user(self):
        self._profile(model_ids=[Command.create({'model_id': self.partner_model.id, 'domain': ONE})])
        mine = self.one.with_user(self.user)
        message = mine.message_post(body='MX Exempt note', message_type='comment', subtype_xmlid='mail.mt_note')
        self.assertEqual(message.model, 'res.partner')
        self.assertEqual(message.res_id, self.one.id)
        activity = mine.activity_schedule('mail.mail_activity_data_todo', summary='MX Exempt activity',
                                          user_id=self.user.id)
        self.assertEqual(activity.res_id, self.one.id)
        activity.action_feedback(feedback='done')
        self.assertFalse(activity.active)

    def test_a_note_on_a_record_the_profile_hides_is_refused(self):
        self._profile(model_ids=[Command.create({'model_id': self.partner_model.id, 'domain': ONE})])
        with self.assertRaises(AccessError):
            self.two.with_user(self.user).message_post(
                body='MX Exempt hidden note', message_type='comment', subtype_xmlid='mail.mt_note')

    def test_a_restricted_user_cannot_widen_their_own_access(self):
        profile = self._restrictive_profile()
        mine = self.user.with_user(self.user)
        with self.assertRaises(AccessError):
            mine.write({'access_profile_ids': [Command.clear()]})
        with self.assertRaises(AccessError):
            mine.write({'access_profile_ids': [Command.unlink(profile.id)]})
        with self.assertRaises(AccessError):
            profile.with_user(self.user).write({'global_readonly': False, 'name': 'Widened'})
        with self.assertRaises(AccessError):
            self.Profile.with_user(self.user).create({'name': 'MX Exempt own', 'user_ids': [Command.set(self.user.ids)]})
        with self.assertRaises(AccessError):
            profile.with_user(self.user).unlink()
        with self.assertRaises(AccessError):
            self.env['gec.access.profile.model'].with_user(self.user).search([]).write({'domain': False})
        with self.assertRaises(AccessError):
            self.env['gec.access.profile.model'].with_user(self.user).search([]).unlink()
        self.assertEqual(self._seen(self.user), self.one)

    def test_a_restricted_user_cannot_create_an_access_row(self):
        self._restrictive_profile()
        with self.assertRaises(AccessError):
            self.env['ir.access'].with_user(self.user).create({
                'name': 'MX Exempt widened', 'model_id': self.partner_model.id, 'group_id': False,
                'operation': 'crud', 'domain': '[]'})
        with self.assertRaises(AccessError):
            self.env['ir.access'].with_user(self.user).search([]).write({'domain': '[]'})

    def test_a_restricted_user_cannot_join_a_group_or_get_a_temporary_profile(self):
        self._restrictive_profile()
        group = self.env.ref('base.group_system')
        with self.assertRaises(AccessError):
            group.with_user(self.user).write({'user_ids': [Command.link(self.user.id)]})
        with self.assertRaises(AccessError):
            self.user.with_user(self.user).write({'group_ids': [Command.link(group.id)]})
        with self.assertRaises(AccessError):
            self.env['gec.access.profile.assignment'].with_user(self.user).create({
                'profile_id': self.Profile.search([], limit=1).id, 'user_id': self.user.id})
        self.assertNotIn(group, self.user.group_ids)

    def test_an_access_manager_under_a_profile_that_hides_profiles_cannot_edit_them(self):
        manager = new_test_user(self.env, 'mx_exempt_manager',
                                groups='base.group_user,gec_access_manager.group_access_manager')
        profile = self._profile(self.env['res.users'], name='MX Exempt target')
        profile.with_user(manager).write({'note': '<p>edited</p>'})
        self._profile(manager, name='MX Exempt no edits', strictness='override', model_ids=[Command.create({
            'model_id': self.env['ir.model']._get('gec.access.profile').id, 'perm_write': False})])
        with self.assertRaises(AccessError):
            profile.with_user(manager).write({'note': '<p>edited again</p>'})


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixSwitchGaps(ClientCalls, GuardCase):
    """ The profile switches the entry-point matrix did not reach, through the web client's own door. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'gec-access-manager-matrix-gaps-pw'
        cls.user = new_test_user(cls.env, 'mx_gaps_user', password=cls.password,
                                 groups='base.group_user,base.group_partner_manager,base.group_allow_export')
        Partner = cls.env['res.partner']
        cls.partner, cls.second = Partner.create([{'name': 'MX Gaps Partner'}, {'name': 'MX Gaps Second'}])
        cls.partner_model = cls.env['ir.model']._get('res.partner')
        cls.be, cls.de = cls.env.ref('base.be'), cls.env.ref('base.de')

    def setUp(self):
        super().setUp()
        self.enterContext(mute_logger('odoo.http'))
        self.authenticate(self.user.login, self.password)

    def _profile(self, **values):
        return self.env['gec.access.profile'].create(
            {'name': 'MX Gaps', 'user_ids': [Command.set(self.user.ids)], **values})

    def _refusal(self, model, method, args, kwargs=None, route='call_kw'):
        """ The message a call is refused with, or None when it went through. """
        response = self.url_open(f'/web/dataset/{route}/{model}/{method}', json={
            'jsonrpc': '2.0', 'method': 'call', 'id': 1,
            'params': {'model': model, 'method': method, 'args': args, 'kwargs': kwargs or {}},
        })
        error = response.json().get('error')
        return error['data']['message'] if error else None

    def _partners(self, name):
        return self.env['res.partner'].with_context(active_test=False).search([('name', '=', name)])

    def _filter_values(self, command=False):
        return {'name': 'MX Gaps filter', 'model_id': 'res.partner', 'domain': '[]',
                'user_ids': [Command.set(self.user.ids)] if command else [self.user.id]}

    def _view_source(self):
        view = self.env['ir.ui.view'].create({
            'name': 'MX Gaps note', 'type': 'qweb', 'key': 'mx_gaps.note',
            'arch': '<t t-name="mx_gaps.note"><p>MX gaps source note</p></t>'})
        self.env['ir.model.data'].create({'module': 'mx_gaps', 'name': 'note', 'model': 'ir.ui.view', 'res_id': view.id})
        return 'mx_gaps.note'

    def _archived_partner_with_xmlid(self):
        self.env['ir.model.data'].create({
            'module': 'mx_gaps', 'name': 'archived', 'model': 'res.partner', 'res_id': self.second.id})
        self.second.active = False
        return 'mx_gaps.archived'

    def test_block_archive_refuses_write_of_active_and_action_archive(self):
        self._profile(block_archive=True)
        ids = self.partner.ids
        self.assertIn('archiving', self._refusal('res.partner', 'write', [ids, {'active': False}]))
        self.assertIn('archiving', self._refusal('res.partner', 'action_archive', [ids]))
        self.assertIn('archiving', self._refusal('res.partner', 'action_archive', [ids], route='call_button'))
        self.assertTrue(self.partner.active)

    def test_toggle_active_archives_nothing(self):
        """ v20 has no toggle_active: the call fails and the record is untouched. """
        self._profile(block_archive=True)
        self.assertIsNotNone(self._refusal('res.partner', 'toggle_active', [self.partner.ids]))
        self.assertTrue(self.partner.active)

    def test_web_resequence_cannot_archive(self):
        """ R1e: web_resequence on the field active archives under Block Archiving. """
        self._profile(block_archive=True)
        self._refusal('res.partner', 'web_resequence', [(self.partner | self.second).ids, {}], {'field_name': 'active'})
        self.partner.invalidate_recordset()
        self.assertTrue(self.partner.active, "R1e: web_resequence(field_name='active') archived the first record")

    def test_an_import_of_active_true_cannot_unarchive(self):
        """ C9: importing active=True unarchives a record under Block Archiving. """
        xmlid = self._archived_partner_with_xmlid()
        self._profile(block_archive=True)
        self._refusal('res.partner', 'load', [['id', 'active'], [[xmlid, 'True']]])
        self.second.invalidate_recordset()
        self.assertFalse(self.second.active, "C9: the import set active=True on an archived record")

    def test_an_import_that_keeps_active_true_on_an_active_record_passes(self):
        """ An export-edit-import round trip keeps the active column: it changes no archive state. """
        self.env['ir.model.data'].create({
            'module': 'mx_gaps', 'name': 'active', 'model': 'res.partner', 'res_id': self.partner.id})
        self._profile(block_archive=True)
        self._refusal('res.partner', 'load', [['id', 'active', 'name'], [['mx_gaps.active', 'True', 'MX Gaps Renamed']]])
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.name, 'MX Gaps Renamed')
        self.assertTrue(self.partner.active)

    def test_block_duplicate_refuses_copy(self):
        self._profile(block_duplicate=True)
        self.assertIn('duplicating', self._refusal('res.partner', 'copy', [self.partner.ids]))
        self.assertEqual(len(self._partners('MX Gaps Partner')), 1)

    def test_block_import_refuses_load(self):
        self.assertIsNone(self._refusal('res.partner', 'load', [['name'], [['MX Gaps imported control']]]))
        self.assertEqual(len(self._partners('MX Gaps imported control')), 1)
        self._profile(block_import=True)
        self.assertIn('importing', self._refusal('res.partner', 'load', [['name'], [['MX Gaps imported']]]))
        self.assertFalse(self._partners('MX Gaps imported'))

    def test_block_export_refuses_export_data(self):
        self.assertIsNone(self._refusal('res.partner', 'export_data', [self.partner.ids, ['name']]))
        self._profile(block_export=True)
        self.assertIn('exporting', self._refusal('res.partner', 'export_data', [self.partner.ids, ['name']]))

    def test_hide_send_message_refuses_message_post_but_not_a_note(self):
        self._profile(hide_send_message_all=True)
        self.assertIn('sending messages', self._refusal(
            'res.partner', 'message_post', [self.partner.ids], {'body': 'MX gaps sent', 'subtype_xmlid': 'mail.mt_comment'}))
        self.assertIn('sending messages', self._refusal(
            'res.partner', 'message_post', [self.partner.ids],
            {'body': 'MX gaps sent', 'partner_ids': self.user.partner_id.ids}))
        self.assertIsNone(self._refusal(
            'res.partner', 'message_post', [self.partner.ids], {'body': 'MX gaps note', 'subtype_xmlid': 'mail.mt_note'}))
        self.assertFalse(self.env['mail.message'].search([('body', 'ilike', 'MX gaps sent')]))
        self.assertTrue(self.env['mail.message'].search([('body', 'ilike', 'MX gaps note')]))

    def test_message_notify_is_refused_by_hide_send_message(self):
        """ R1h: message_notify sends a message to a partner, past Hide Send Message. """
        self._profile(hide_send_message_all=True)
        refusal = self._refusal('res.partner', 'message_notify', [self.partner.ids], {
            'partner_ids': self.user.partner_id.ids, 'body': 'MX gaps notified', 'subject': 'MX gaps'})
        self.assertIsNotNone(refusal, "R1h: message_notify went through")

    def test_message_notify_on_mail_thread_is_refused_for_the_model_it_names(self):
        self._profile(hide_send_message_all=True)
        refusal = self._refusal('mail.thread', 'message_notify', [[]], {
            'model': 'res.partner', 'res_id': self.partner.id, 'partner_ids': self.user.partner_id.ids,
            'body': 'MX gaps notified', 'subject': 'MX gaps'})
        self.assertIn('sending messages', refusal)

    def test_message_post_with_source_is_refused_by_hide_send_message(self):
        """ R1h: message_post_with_source posts a comment, past Hide Send Message. """
        source = self._view_source()
        self._profile(hide_send_message_all=True)
        refusal = self._refusal('res.partner', 'message_post_with_source', [self.partner.ids, source],
                                {'subtype_xmlid': 'mail.mt_comment'})
        self.assertIsNotNone(refusal, "R1h: message_post_with_source went through")

    def test_block_favorites_refuses_create_filter(self):
        self.assertIsNone(self._refusal('ir.filters', 'create_filter', [self._filter_values()]))
        self._profile(block_favorites=True)
        values = dict(self._filter_values(), name='MX Gaps second')
        self.assertIn('saving searches', self._refusal('ir.filters', 'create_filter', [values]))
        self.assertFalse(self.env['ir.filters'].search([('name', '=', 'MX Gaps second')]))

    def test_block_favorites_refuses_web_save_of_a_filter(self):
        """ C20: web_save creates a saved search under No Saved Searches. """
        self._profile(block_favorites=True)
        refusal = self._refusal('ir.filters', 'web_save', [[], self._filter_values(command=True)],
                                {'specification': {'name': {}}})
        self.assertIsNotNone(refusal, "C20: web_save created the saved search")

    def test_a_button_blocked_under_a_condition_is_refused_on_matching_records(self):
        """ C13 appears fixed: Hide and block with an Only When condition is refused where the condition holds. """
        blocked = self.env['res.partner'].create({'name': 'MX Gaps Blocked'})
        self._profile(button_ids=[Command.create({
            'model_id': self.partner_model.id, 'button_type': 'object', 'button_name': 'action_archive',
            'mode': 'hide_block', 'condition': "name == 'MX Gaps Blocked'"})])
        self.assertIsNone(self._refusal('res.partner', 'action_archive', [self.second.ids], route='call_button'))
        self.assertIn('cannot use this button', self._refusal(
            'res.partner', 'action_archive', [blocked.ids], route='call_button'))
        self.assertTrue(blocked.active)

    def test_name_create_cannot_set_a_read_only_name(self):
        """ A name_create of a record whose name is read-only for the user is refused. """
        self._profile(field_ids=[Command.create({
            'model_id': self.partner_model.id, 'mode': 'readonly',
            'field_id': self.env['ir.model.fields']._get('res.partner', 'name').id})])
        self.assertIsNotNone(self._refusal('res.partner', 'name_create', ['MX Gaps quick']))
        self.assertFalse(self._partners('MX Gaps quick'))

    def test_a_created_line_is_judged_by_the_value_filter_of_the_one2many(self):
        """ C7: a Command.CREATE line is not judged by the value filter of the parent's one2many field. """
        self._profile(field_ids=[Command.create({
            'model_id': self.partner_model.id, 'mode': 'keep',
            'field_id': self.env['ir.model.fields']._get('res.partner', 'child_ids').id,
            'field_domain': repr([('country_id', '=', self.be.id)])})])
        self._refusal('res.partner', 'write', [self.partner.ids, {
            'child_ids': [Command.create({'name': 'MX Gaps child', 'country_id': self.de.id})]}])
        self.assertFalse(self._partners('MX Gaps child'), "C7: a line outside the value filter was created")

    def test_a_created_line_is_judged_with_the_defaults_core_gives_it(self):
        self._profile(field_ids=[Command.create({
            'model_id': self.partner_model.id, 'mode': 'keep',
            'field_id': self.env['ir.model.fields']._get('res.partner', 'child_ids').id,
            'field_domain': repr([('active', '=', True)])})])
        self.assertIsNone(self._refusal('res.partner', 'write', [self.partner.ids, {
            'child_ids': [Command.create({'name': 'MX Gaps defaulted child'})]}]))
        self.assertTrue(self._partners('MX Gaps defaulted child'))
        self.assertIsNotNone(self._refusal('res.partner', 'write', [self.partner.ids, {
            'child_ids': [Command.create({'name': 'MX Gaps inactive child', 'active': False})]}]))
        self.assertFalse(self._partners('MX Gaps inactive child'))

    def test_a_copy_of_several_records_is_judged_per_record_by_a_value_filter(self):
        parent = self.env['res.partner'].create({'name': 'MX Gaps parent', 'country_id': self.be.id})
        (self.partner | self.second).country_id = self.be
        self._profile(field_ids=[Command.create({
            'model_id': self.partner_model.id, 'mode': 'keep',
            'field_id': self.env['ir.model.fields']._get('res.partner', 'parent_id').id,
            'field_domain': "[('country_id', '=', country_id)]"})])
        ids, default = (self.partner | self.second).ids, {'parent_id': parent.id}
        self.assertIsNone(self._refusal('res.partner', 'copy', [ids, default]))
        self.second.country_id = self.de
        before = self.env['res.partner'].search_count([('name', 'ilike', 'MX Gaps')])
        self.assertIsNotNone(self._refusal('res.partner', 'copy', [ids, default]))
        self.assertEqual(self.env['res.partner'].search_count([('name', 'ilike', 'MX Gaps')]), before)

    def test_a_scheduled_message_the_client_creates_is_judged_by_hide_send_message(self):
        self._profile(hide_send_message_all=True)
        values = {
            'model': 'res.partner', 'res_id': self.partner.id, 'author_id': self.user.partner_id.id,
            'scheduled_date': fields.Datetime.to_string(fields.Datetime.now() + timedelta(days=1)),
            'body': '<p>MX gaps scheduled</p>', 'is_note': True}
        self.assertIsNone(self._refusal('mail.scheduled.message', 'create', [values]))
        sent = dict(values, is_note=False, partner_ids=[Command.set(self.user.partner_id.ids)])
        self.assertIn('sending messages', self._refusal('mail.scheduled.message', 'create', [sent]))
        self.assertEqual(self.env['mail.scheduled.message'].search_count([('model', '=', 'res.partner')]), 1)

    def test_a_linked_line_is_judged_by_the_value_filter_of_the_one2many(self):
        self._profile(field_ids=[Command.create({
            'model_id': self.partner_model.id, 'mode': 'keep',
            'field_id': self.env['ir.model.fields']._get('res.partner', 'child_ids').id,
            'field_domain': repr([('country_id', '=', self.be.id)])})])
        self.second.country_id = self.de
        self.assertIsNotNone(self._refusal(
            'res.partner', 'write', [self.partner.ids, {'child_ids': [Command.link(self.second.id)]}]))
        self.assertFalse(self.second.parent_id)
        self.second.country_id = self.be
        self.assertIsNone(self._refusal(
            'res.partner', 'write', [self.partner.ids, {'child_ids': [Command.link(self.second.id)]}]))
        self.assertEqual(self.second.parent_id, self.partner)

    def test_read_only_everywhere_lets_a_user_open_a_read_only_wizard(self):
        """ A wizard that only reads (the preview of a mail template) opens under Read Only Everywhere. """
        template = self.env['mail.template'].create({
            'name': 'MX Gaps template', 'model_id': self.partner_model.id, 'subject': 'MX', 'body_html': '<p>MX</p>'})
        Preview = self.env['mail.template.preview'].with_user(self.user)
        Preview.create({'mail_template_id': template.id})
        self._profile(global_readonly=True)
        Preview.create({'mail_template_id': template.id})

    def test_read_only_everywhere_lets_a_user_open_the_change_password_wizard(self):
        self._profile(global_readonly=True)
        self.env['change.password.own'].with_user(self.user).create({'new_password': 'mx', 'confirm_password': 'mx'})

    def test_read_only_everywhere_still_refuses_the_access_wizards(self):
        """ READONLY_KEPT_WIZARDS: the wizards that change what a profile gives stay under Read Only Everywhere. """
        manager = new_test_user(self.env, 'mx_gaps_manager', groups='gec_access_manager.group_access_manager')
        Assign = self.env['gec.access.assign'].with_user(manager)
        Assign.create({'user_ids': [Command.set(manager.ids)]})
        self.env['gec.access.profile'].create({
            'name': 'MX Gaps manager', 'user_ids': [Command.set(manager.ids)], 'global_readonly': True})
        with self.assertRaises(AccessError):
            Assign.create({'user_ids': [Command.set(manager.ids)]})

    def test_a_models_line_still_refuses_a_wizard_under_read_only_everywhere(self):
        template = self.env['mail.template'].create({
            'name': 'MX Gaps template', 'model_id': self.partner_model.id, 'subject': 'MX', 'body_html': '<p>MX</p>'})
        self._profile(global_readonly=True, model_ids=[Command.create({
            'model_id': self.env['ir.model']._get('mail.template.preview').id, 'perm_create': False})])
        with self.assertRaises(AccessError):
            self.env['mail.template.preview'].with_user(self.user).create({'mail_template_id': template.id})

    def test_a_wizard_that_creates_a_real_record_is_still_refused_under_read_only_everywhere(self):
        """ The wizard itself opens, but the activity it creates is a record of the user: the profile refuses it. """
        values = {'activity_user_id': self.user.id, 'summary': 'MX Gaps wizard'}
        Schedule = self.env['mail.activity.schedule'].with_user(self.user)
        Schedule.create(values).action_schedule_activities()
        self.assertEqual(self.env['mail.activity'].search_count([('summary', '=', 'MX Gaps wizard')]), 1)
        self._profile(global_readonly=True)
        wizard = Schedule.create(values)
        with self.assertRaises(AccessError) as caught:
            wizard.action_schedule_activities()
        self.assertIn('Your access profile', str(caught.exception))

    def test_the_gap_calls_work_without_a_profile(self):
        """ Each call of the known gaps does what the gap says when nothing refuses it. """
        xmlid = self._archived_partner_with_xmlid()
        source = self._view_source()
        self._refusal('res.partner', 'web_resequence', [(self.partner | self.second).ids, {}], {'field_name': 'sequence'})
        self.assertIsNone(self._refusal('res.partner', 'web_resequence', [(self.partner | self.second).ids, {}],
                                        {'field_name': 'active'}))
        self.partner.invalidate_recordset()
        self.assertFalse(self.partner.active, "web_resequence on active archives the first record")
        self.assertIsNone(self._refusal('res.partner', 'load', [['id', 'active'], [[xmlid, 'True']]]))
        self.second.invalidate_recordset()
        self.assertTrue(self.second.active, "an import of active=True unarchives")
        self.assertIsNone(self._refusal('res.partner', 'message_notify', [self.partner.ids], {
            'partner_ids': self.user.partner_id.ids, 'body': 'MX gaps notified', 'subject': 'MX gaps'}))
        self.assertTrue(self.env['mail.message'].search([('body', 'ilike', 'MX gaps notified')]))
        self.assertIsNone(self._refusal('res.partner', 'message_post_with_source', [self.partner.ids, source],
                                        {'subtype_xmlid': 'mail.mt_comment'}))
        self.assertTrue(self.env['mail.message'].search([('body', 'ilike', 'MX gaps source note')]))
        self.assertIsNone(self._refusal('ir.filters', 'web_save', [[], self._filter_values(command=True)],
                                        {'specification': {'name': {}}}))
        self.assertEqual(len(self.env['ir.filters'].search([('name', '=', 'MX Gaps filter')])), 1)
        self.assertIsNone(self._refusal('res.partner', 'action_archive', [self.partner.ids], route='call_button'))
        self.assertIsNone(self._refusal('res.partner', 'name_create', ['MX Gaps quick']))
        self.assertTrue(self._partners('MX Gaps quick'))
        self.assertIsNone(self._refusal('res.partner', 'write', [self.second.ids, {
            'child_ids': [Command.create({'name': 'MX Gaps child', 'country_id': self.de.id})]}]))
        self.assertTrue(self._partners('MX Gaps child'))

    def test_a_read_only_name_refuses_a_create_of_the_client(self):
        """ The mechanism behind R1g: the name is dropped on a create, which fails (name is required). """
        self._profile(field_ids=[Command.create({
            'model_id': self.partner_model.id, 'mode': 'readonly',
            'field_id': self.env['ir.model.fields']._get('res.partner', 'name').id})])
        with mute_logger('odoo.sql_db'):
            self.assertIsNotNone(self._refusal('res.partner', 'create', [{'name': 'MX Gaps created'}]))
        self.assertFalse(self._partners('MX Gaps created'))
