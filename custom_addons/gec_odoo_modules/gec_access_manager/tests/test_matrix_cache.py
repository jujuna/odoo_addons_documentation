# Matrix of the cache: every change of the configuration takes effect on the very next call of the user, and is
# signaled to the other workers. A commit signals the caches whose layer in the transaction was invalidated (Transaction
# .committing in odoo/orm/environments.py: a layer with no parent, of a name in _CACHES_BY_KEY of odoo/orm/registry.py).
import logging
import threading
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import AccessError
from odoo.orm.registry import _CACHES_BY_KEY
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.gec_access_manager.models import gec_access_allowed

_logger = logging.getLogger(__name__)

TEST_KIND = ('Partner Tags', 'res.partner.category', {
    'res.partner.category': "[('id', 'in', {ids})]",
    'res.partner': "[('category_id', 'in', {ids})]",
})
ONE = "[('name', '=', 'MX Cache One')]"
TWO = "[('name', '=', 'MX Cache Two')]"


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixCache(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env['res.partner']
        cls.red, cls.blue = cls.env['res.partner.category'].create([{'name': 'MX Cache Red'}, {'name': 'MX Cache Blue'}])
        cls.one, cls.two, cls.three = Partner.create([
            {'name': 'MX Cache One', 'email': 'mx-one@cache.example', 'category_id': [Command.set(cls.red.ids)]},
            {'name': 'MX Cache Two', 'email': 'mx-two@cache.example', 'category_id': [Command.set(cls.red.ids)]},
            {'name': 'MX Cache Three', 'email': 'mx-three@cache.example', 'category_id': [Command.set(cls.blue.ids)]},
        ])
        cls.partners = cls.one | cls.two | cls.three
        cls.user = new_test_user(cls.env, 'mx_cache_user',
                                 groups='base.group_user,base.group_partner_manager,base.group_allow_export')
        cls.other = new_test_user(cls.env, 'mx_cache_other', groups='base.group_user,base.group_partner_manager')
        cls.manager = new_test_user(
            cls.env, 'mx_cache_manager', groups='base.group_user,gec_access_manager.group_access_manager')
        cls.Partner = Partner
        cls.Profile = cls.env['gec.access.profile']
        cls.partner_model = cls.env['ir.model']._get('res.partner')

    def setUp(self):
        super().setUp()
        patcher = patch.dict(gec_access_allowed.ALLOWED_KINDS, {'gec_test': TEST_KIND})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _profile(self, **values):
        return self.Profile.create({'name': 'MX Cache', 'user_ids': [Command.set(self.user.ids)], **values})

    def _line(self, profile, **values):
        return self.env['gec.access.profile.model'].create(
            {'profile_id': profile.id, 'model_id': self.partner_model.id, **values})

    def _seen(self, user=None):
        return self.Partner.with_user(user or self.user).search([('id', 'in', self.partners.ids)])

    def _may(self, operation, record=None):
        return (record or self.one).with_user(self.user).has_access(operation)

    def _signaled(self):
        """ The caches a commit would signal to the other workers: the layers invalidated in this transaction. """
        transaction = self.env.transaction
        return {name for name in transaction._registry_caches__
                if name in _CACHES_BY_KEY and transaction.ormcaches__[name].parent is None}

    def _change(self, label, change):
        """ Run ``change`` in a savepoint, so only its own invalidations show; it must signal the 'default' cache,
        the one of the ormcache of the rules, the access domains and the menus. """
        with self.env.cr.savepoint():
            result = change()
            signaled = self._signaled()
        _logger.info("MX cache | %-46s | signaled to the other workers: %s", label, sorted(signaled) or 'NO')
        self.assertIn('default', signaled, f"{label}: the change is not signaled to the other workers")
        return result

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

    def _email_as_client(self):
        with self._client_call('res.partner', 'read'):
            return self.one.with_user(self.user).read(['email'])[0]['email']

    def _fields_as_client(self):
        with self._client_call('res.partner', 'fields_get'):
            return self.Partner.with_user(self.user).fields_get(['email'], ['readonly'])

    def _field_rule(self, profile, mode):
        return self.env['gec.access.profile.field'].create({
            'profile_id': profile.id, 'model_id': self.partner_model.id, 'mode': mode,
            'field_id': self.env['ir.model.fields']._get('res.partner', 'email').id})

    def test_the_instrument_tells_a_change_that_signals_nothing(self):
        """ A note on a profile changes nothing the rules read: no cache is marked, so a marked cache means a signal. """
        profile = self._profile()
        with self.env.cr.savepoint():
            profile.write({'note': '<p>MX Cache note</p>'})
            self.assertNotIn('default', self._signaled())

    def test_a_model_line_created(self):
        profile = self._profile()
        self.assertEqual(self._seen(), self.partners)
        self._change('model line create', lambda: self._line(profile, domain=ONE))
        self.assertEqual(self._seen(), self.one)

    def test_a_model_line_permission_written(self):
        profile = self._profile()
        line = self._line(profile)
        self.assertTrue(self._may('write') and self._may('unlink'))
        self._change('model line write perm_write off', lambda: line.write({'perm_write': False}))
        self.assertFalse(self._may('write'))
        with self.assertRaises(AccessError):
            self.one.with_user(self.user).write({'name': 'MX Cache One'})
        self.assertTrue(self._may('unlink'))
        self._change('model line write perm_write on', lambda: line.write({'perm_write': True}))
        self.assertTrue(self._may('write'))
        self._change('model line write perm_unlink off', lambda: line.write({'perm_unlink': False}))
        self.assertFalse(self._may('unlink'))
        self._change('model line write perm_read off', lambda: line.write({'perm_read': False}))
        with self.assertRaises(AccessError):
            self._seen()
        self.assertFalse(self._may('read'))

    def test_a_model_line_domain_written(self):
        profile = self._profile()
        line = self._line(profile, domain=ONE)
        self.assertEqual(self._seen(), self.one)
        self._change('model line write domain', lambda: line.write({'domain': TWO}))
        self.assertEqual(self._seen(), self.two)
        self._change('model line write domain_write', lambda: line.write({'domain': False, 'domain_write': ONE}))
        self.assertEqual(self._seen(), self.partners)
        self.assertTrue(self._may('write', self.one))
        self.assertFalse(self._may('write', self.two))

    def test_a_model_line_deleted(self):
        profile = self._profile()
        line = self._line(profile, domain=ONE)
        self.assertEqual(self._seen(), self.one)
        self._change('model line unlink', line.unlink)
        self.assertEqual(self._seen(), self.partners)

    def test_a_field_rule_added_changed_and_removed(self):
        profile = self._profile()
        self.assertEqual(self._email_as_client(), 'mx-one@cache.example')
        self.assertIn('email', self._fields_as_client())
        rule = self._change('field rule add (hide)', lambda: self._field_rule(profile, 'hide'))
        self.assertFalse(self._email_as_client())
        self.assertNotIn('email', self._fields_as_client())
        self._change('field rule write mode (readonly)', lambda: rule.write({'mode': 'readonly'}))
        self.assertEqual(self._email_as_client(), 'mx-one@cache.example')
        self.assertEqual(self._fields_as_client()['email']['readonly'], True)
        self._change('field rule remove', rule.unlink)
        self.assertEqual(self._fields_as_client()['email']['readonly'], False)

    def _menu_ids(self):
        return self.env['ir.ui.menu'].with_user(self.user).load_menus(False)

    def test_a_hidden_menu_added_and_removed(self):
        Menu = self.env['ir.ui.menu']
        action = self.env['ir.actions.act_window'].create({'name': 'MX Cache Menu', 'res_model': 'res.partner'})
        app = Menu.create({'name': 'MX Cache App', 'action': f'ir.actions.act_window,{action.id}'})
        page = Menu.create({'name': 'MX Cache Page', 'parent_id': app.id, 'action': f'ir.actions.act_window,{action.id}'})
        profile = self._profile()
        self.assertIn(page.id, self._menu_ids())
        self._change('hidden menu add', lambda: profile.write({'hidden_menu_ids': [Command.link(page.id)]}))
        self.assertNotIn(page.id, self._menu_ids())
        self.assertIn(app.id, self._menu_ids())
        self._change('hidden menu remove', lambda: profile.write({'hidden_menu_ids': [Command.unlink(page.id)]}))
        self.assertIn(page.id, self._menu_ids())

    def test_a_profile_archived_and_unarchived(self):
        profile = self._profile()
        self._line(profile, domain=ONE)
        self.assertEqual(self._seen(), self.one)
        self._change('profile archive', lambda: profile.write({'active': False}))
        self.assertEqual(self._seen(), self.partners)
        self._change('profile unarchive', lambda: profile.write({'active': True}))
        self.assertEqual(self._seen(), self.one)

    def test_the_strictness_changed(self):
        restricting = self._profile()
        self._line(restricting, domain=ONE)
        self._profile(name='MX Cache Open', hide_activities=True)
        self.assertEqual(self._seen(), self.partners, "an additive profile with no filter opens the records")
        self._change('strictness additive to override', lambda: restricting.write({'strictness': 'override'}))
        self.assertEqual(self._seen(), self.one)
        self._change('strictness override to additive', lambda: restricting.write({'strictness': 'additive'}))
        self.assertEqual(self._seen(), self.partners)

    def test_the_company_of_a_profile_set_and_cleared(self):
        company = self.env['res.company'].create({'name': 'MX Cache Company'})
        profile = self._profile()
        self._line(profile, domain=ONE)
        self.assertEqual(self._seen(), self.one)
        self._change('profile company set (not the user\'s)', lambda: profile.write({'company_id': company.id}))
        self.assertEqual(self._seen(), self.partners)
        self._change('profile company cleared', lambda: profile.write({'company_id': False}))
        self.assertEqual(self._seen(), self.one)

    def test_the_companies_of_the_user_changed(self):
        company = self.env['res.company'].create({'name': 'MX Cache Member Company'})
        profile = self._profile(company_id=company.id)
        self._line(profile, domain=ONE)
        self.assertEqual(self._seen(), self.partners)
        self._change('user company added', lambda: self.user.write({'company_ids': [Command.link(company.id)]}))
        self.assertEqual(self._seen(), self.one)
        self._change('user company removed', lambda: self.user.write({'company_ids': [Command.unlink(company.id)]}))
        self.assertEqual(self._seen(), self.partners)

    def test_apply_to_admin_toggled_for_a_settings_user(self):
        settings = new_test_user(self.env, 'mx_cache_settings',
                                 groups='base.group_user,base.group_system,base.group_partner_manager')
        profile = self._profile(user_ids=[Command.set(settings.ids)])
        self._line(profile, domain=ONE)
        self.assertEqual(self._seen(settings), self.partners)
        self._change('apply_to_admin on', lambda: profile.write({'apply_to_admin': True}))
        self.assertEqual(self._seen(settings), self.one)
        self._change('apply_to_admin off', lambda: profile.write({'apply_to_admin': False}))
        self.assertEqual(self._seen(settings), self.partners)

    def test_a_user_added_and_removed_through_the_profile(self):
        profile = self._profile(user_ids=[Command.clear()])
        self._line(profile, domain=ONE)
        self.assertEqual(self._seen(), self.partners)
        self._change('profile.user_ids add', lambda: profile.write({'user_ids': [Command.link(self.user.id)]}))
        self.assertEqual(self._seen(), self.one)
        self._change('profile.user_ids remove', lambda: profile.write({'user_ids': [Command.unlink(self.user.id)]}))
        self.assertEqual(self._seen(), self.partners)

    def test_a_user_added_and_removed_through_the_user(self):
        profile = self._profile(user_ids=[Command.clear()])
        self._line(profile, domain=ONE)
        self.assertEqual(self._seen(), self.partners)
        self._change('user.access_profile_ids add',
                     lambda: self.user.write({'access_profile_ids': [Command.link(profile.id)]}))
        self.assertEqual(self._seen(), self.one)
        self._change('user.access_profile_ids remove',
                     lambda: self.user.write({'access_profile_ids': [Command.unlink(profile.id)]}))
        self.assertEqual(self._seen(), self.partners)

    def test_an_odoo_group_member_changed_through_the_user(self):
        group = self.env['res.groups'].create({'name': 'MX Cache Group'})
        profile = self._profile(user_ids=[Command.clear()], group_ids=[Command.set(group.ids)])
        self._line(profile, domain=ONE)
        self.assertEqual(self._seen(), self.partners)
        self._change('res.users.write group_ids add', lambda: self.user.write({'group_ids': [Command.link(group.id)]}))
        self.assertEqual(self._seen(), self.one)
        self._change('res.users.write group_ids remove',
                     lambda: self.user.write({'group_ids': [Command.unlink(group.id)]}))
        self.assertEqual(self._seen(), self.partners)

    def test_an_odoo_group_member_changed_through_the_group(self):
        group = self.env['res.groups'].create({'name': 'MX Cache Group'})
        profile = self._profile(user_ids=[Command.clear()], group_ids=[Command.set(group.ids)])
        self._line(profile, domain=ONE)
        self.assertEqual(self._seen(), self.partners)
        self._change('res.groups.write user_ids add', lambda: group.write({'user_ids': [Command.link(self.user.id)]}))
        self.assertEqual(self._seen(), self.one)
        self._change('res.groups.write user_ids remove',
                     lambda: group.write({'user_ids': [Command.unlink(self.user.id)]}))
        self.assertEqual(self._seen(), self.partners)

    def test_a_temporary_assignment_started_and_ended_by_the_cron(self):
        profile = self._profile(user_ids=[Command.clear()])
        self._line(profile, domain=ONE)
        Assignment = self.env['gec.access.profile.assignment']
        today = date(2026, 3, 10)
        with freeze_time(today):
            Assignment.create({'profile_id': profile.id, 'user_id': self.user.id,
                               'date_from': today + timedelta(days=1), 'date_to': today + timedelta(days=2)})
            self.assertEqual(self._seen(), self.partners)
        with freeze_time(today + timedelta(days=1)):
            self._change('assignment started by _cron_refresh', Assignment._cron_refresh)
            self.assertEqual(self._seen(), self.one)
        with freeze_time(today + timedelta(days=3)):
            self._change('assignment ended by _cron_refresh', Assignment._cron_refresh)
            self.assertEqual(self._seen(), self.partners)

    def test_a_temporary_assignment_created_and_deleted(self):
        profile = self._profile(user_ids=[Command.clear()])
        self._line(profile, domain=ONE)
        Assignment = self.env['gec.access.profile.assignment']
        line = self._change('assignment create (running)', lambda: Assignment.create(
            {'profile_id': profile.id, 'user_id': self.user.id, 'date_from': date.today() - timedelta(days=1)}))
        self.assertEqual(self._seen(), self.one)
        self._change('assignment unlink', line.unlink)
        self.assertEqual(self._seen(), self.partners)

    def test_a_granted_group_added_and_removed(self):
        group = self.env.ref('base.group_multi_company')
        profile = self._profile()
        self.assertFalse(self.user.with_user(self.user).has_group('base.group_multi_company'))
        self._change('granted_group_ids add', lambda: profile.write({'granted_group_ids': [Command.link(group.id)]}))
        self.assertTrue(self.user.with_user(self.user).has_group('base.group_multi_company'))
        self._change('granted_group_ids remove',
                     lambda: profile.write({'granted_group_ids': [Command.unlink(group.id)]}))
        self.assertFalse(self.user.with_user(self.user).has_group('base.group_multi_company'))

    def test_an_allowed_record_line_added_and_removed(self):
        profile = self._profile()
        Allowed = self.env['gec.access.allowed']
        self.assertEqual(self._seen(), self.partners)
        line = self._change('allowed record add', lambda: Allowed.create(
            {'profile_id': profile.id, 'kind': 'gec_test', 'res_id': self.red.id}))
        self.assertEqual(self._seen(), self.one | self.two)
        self._change('allowed record write', lambda: line.write({'res_id': self.blue.id}))
        self.assertEqual(self._seen(), self.three)
        self._change('allowed record remove', line.unlink)
        self.assertEqual(self._seen(), self.partners)

    def test_an_allowed_record_of_the_user_added_and_removed(self):
        self._profile(allowed_ids=[Command.create({'kind': 'gec_test', 'per_user': True})])
        self.assertFalse(self._seen(), "nothing set on the user yet: nothing allowed")
        line = self._change('user allowed record add', lambda: self.env['gec.access.allowed'].create(
            {'user_id': self.user.id, 'kind': 'gec_test', 'res_id': self.red.id}))
        self.assertEqual(self._seen(), self.one | self.two)
        self._change('user allowed record remove', line.unlink)
        self.assertFalse(self._seen())

    def test_read_only_everywhere_toggled(self):
        profile = self._profile()
        self.assertTrue(self._may('write') and self._may('create', self.Partner) and self._may('unlink'))
        self._change('global_readonly on', lambda: profile.write({'global_readonly': True}))
        self.assertFalse(self._may('write'))
        self.assertFalse(self._may('unlink'))
        self.assertTrue(self._may('read'))
        with self.assertRaises(AccessError):
            self.Partner.with_user(self.user).create({'name': 'MX Cache refused'})
        self._change('global_readonly off', lambda: profile.write({'global_readonly': False}))
        self.assertTrue(self._may('write') and self._may('unlink'))

    def test_block_export_toggled(self):
        profile = self._profile()
        self.assertTrue(self.user.with_user(self.user).has_group('base.group_allow_export'))
        self._change('block_export on', lambda: profile.write({'block_export': True}))
        self.assertFalse(self.user.with_user(self.user).has_group('base.group_allow_export'))
        self._change('block_export off', lambda: profile.write({'block_export': False}))
        self.assertTrue(self.user.with_user(self.user).has_group('base.group_allow_export'))

    def test_a_change_made_through_sudo_is_seen(self):
        profile = self._profile()
        mine = self.Partner.with_user(self.user)
        ids = [('id', 'in', self.partners.ids)]
        self.assertEqual(mine.search(ids), self.partners)
        self.env['gec.access.profile.model'].sudo().create(
            {'profile_id': profile.id, 'model_id': self.partner_model.id, 'domain': ONE})
        self.assertEqual(mine.search(ids), self.one, "the environment of the user, made before the change")
        self.assertEqual(mine.with_context(lang='fr_FR').search(ids), self.one)
        self.assertEqual(self.Partner.with_user(self.user).search(ids), self.one)

    def test_a_change_made_by_another_user_is_seen(self):
        profile = self._profile()
        mine, other = self.Partner.with_user(self.user), self.Partner.with_user(self.other)
        ids = [('id', 'in', self.partners.ids)]
        self.assertEqual(mine.search(ids), self.partners)
        self.assertEqual(other.search(ids), self.partners)
        line = self.env['gec.access.profile.model'].with_user(self.manager).create(
            {'profile_id': profile.id, 'model_id': self.partner_model.id, 'domain': ONE})
        self.assertEqual(mine.search(ids), self.one)
        self.assertEqual(other.search(ids), self.partners, "the other user does not carry the profile")
        line.with_user(self.manager).write({'perm_write': False})
        self.assertFalse(mine.browse(self.one.id).has_access('write'))
        self.assertTrue(other.browse(self.one.id).has_access('write'))
        profile.with_user(self.manager).write({'user_ids': [Command.link(self.other.id)]})
        self.assertEqual(other.search(ids), self.one)
