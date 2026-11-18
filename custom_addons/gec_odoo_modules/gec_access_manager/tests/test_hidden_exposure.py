# What a hidden menu still exposes, and the Block / Unblock that deny that data to the profile's members.
# The fixture models belong to this module and to gec_user_audit, always installed: a model of base or mail
# would be core data and never show the other statuses.
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.gec_access_manager.models.gec_access_rules import PERM_FIELDS

UNUSED = 'gec.user.audit.rule'
SHARED = 'gec.user.audit.log'
LINKED = 'gec.access.profile.version'
DOCUMENT = 'gec.access.profile'
CORE = 'mail.activity.type'


@tagged('post_install', '-at_install')
class TestHiddenExposure(TransactionCase):
    """ One hidden folder opens the data of each status: an audit rule nothing else shows (unused), the audit
    log (shared with a visible menu), the profile versions (linked from the profiles a visible menu opens),
    the profiles themselves (a document with line models), contacts and activity types (core). A second profile hides every
    other app, so the navbar of the members is the two fixture folders and nothing of the database. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Menu = cls.env['ir.ui.menu']
        cls.hidden = Menu.create({'name': 'GEC Exposure Hidden'})
        cls.visible = Menu.create({'name': 'GEC Exposure Visible'})
        for name, model_name in (('Rules', UNUSED), ('Logs', SHARED), ('Versions', LINKED),
                                 ('Profiles', DOCUMENT), ('Contacts', 'res.partner'), ('Activity types', CORE)):
            Menu.create({'name': name, 'parent_id': cls.hidden.id, 'action': cls._action(model_name)})
        client = cls.env['ir.actions.client'].create({'name': 'GEC Exposure Client', 'tag': 'gec_exposure_test'})
        cls.client_menu = Menu.create({'name': 'Dashboard', 'parent_id': cls.hidden.id,
                                       'action': f'ir.actions.client,{client.id}'})
        cls.visible_logs = Menu.create({'name': 'Logs', 'parent_id': cls.visible.id, 'action': cls._action(SHARED)})
        Menu.create({'name': 'Profiles', 'parent_id': cls.visible.id, 'action': cls._action(DOCUMENT)})

        cls.line_models = cls.env['gec.access.app.wizard']._line_models(DOCUMENT)
        group = cls.env['res.groups'].create({'name': 'GEC Exposure Test Group'})
        IrModel = cls.env['ir.model']
        cls.env['ir.access'].create([
            {'name': f'gec_access_manager exposure: {name}', 'model_id': IrModel._get(name).id,
             'group_id': group.id, 'operation': 'crud'}
            for name in {UNUSED, SHARED, LINKED, DOCUMENT, 'res.partner', *cls.line_models}
        ])
        groups = [(6, 0, [cls.env.ref('base.group_user').id, group.id])]
        cls.member_a = cls.env['res.users'].create({
            'name': 'Exposure Member A', 'login': 'gec_exposure_a', 'group_ids': groups})
        cls.member_b = cls.env['res.users'].create({
            'name': 'Exposure Member B', 'login': 'gec_exposure_b', 'group_ids': groups})
        members = cls.member_a | cls.member_b
        cls.employee = new_test_user(cls.env, 'gec_exposure_employee', groups='base.group_user')

        Profile = cls.env['gec.access.profile']
        cls.profile = Profile.create({
            'name': 'Exposure', 'user_ids': [(6, 0, members.ids)], 'hidden_menu_ids': [(6, 0, cls.hidden.ids)]})
        other_apps = Menu.search([('parent_id', '=', False), ('id', 'not in', (cls.hidden | cls.visible).ids)])
        Profile.create({
            'name': 'Exposure navbar', 'strictness': 'override', 'user_ids': [(6, 0, members.ids)],
            'hidden_menu_ids': [(6, 0, other_apps.ids)]})

    @classmethod
    def _action(cls, model_name):
        action = cls.env['ir.actions.act_window'].create({'name': model_name, 'res_model': model_name})
        return f'ir.actions.act_window,{action.id}'

    def _items(self, exposure):
        return {item['model']: item for entry in exposure['entries'] for item in entry['models']}

    def _line(self, model_name):
        return self.profile.model_ids.filtered(lambda line: line.model_id.model == model_name)

    def _allows(self, user, model_name, operation):
        return self.env['gec.access.profile'].with_user(user)._current_rules().allows(model_name, operation)

    def test_each_status_on_the_fixture(self):
        exposure = self.profile.gec_hidden_exposure(self.hidden.id)
        items = self._items(exposure)
        self.assertEqual(exposure['members'], 2)
        self.assertEqual(exposure['runs_as'], [])
        self.assertEqual(
            {name: items[name]['status'] for name in (UNUSED, SHARED, LINKED, 'res.partner')},
            {UNUSED: 'unused', SHARED: 'shared', LINKED: 'linked', 'res.partner': 'core'})
        self.assertEqual(items[SHARED]['also'], [self.profile._gec_menu_path(self.visible_logs)])
        self.assertIn('Access Profile › Versions', items[LINKED]['links'])
        self.assertEqual((items[UNUSED]['also'], items[UNUSED]['links'], items[UNUSED]['inherits']), ([], [], []))
        self.assertEqual((items[UNUSED]['by'], items[UNUSED]['by_menus'], items[UNUSED]['lines']), (False, [], []))
        self.assertEqual(exposure['entries'][0]['unknown'], [self.profile._gec_menu_path(self.client_menu)])
        # the page asks without a menu: one entry per menu the profile hides directly
        page = self.profile.gec_hidden_exposure()
        self.assertEqual([entry['menu_id'] for entry in page['entries']], [self.hidden.id])

    def test_block_then_unblock_gives_back_read_only(self):
        items = self._items(self.profile.gec_block_data(self.hidden.id, [UNUSED]))
        self.assertEqual((items[UNUSED]['status'], items[UNUSED]['by']), ('blocked', 'line'))
        self.assertEqual([self._line(UNUSED)[name] for name in PERM_FIELDS], [False] * 4)
        self.assertFalse(self._allows(self.member_a, UNUSED, 'read'))
        self.assertCountEqual(items[UNUSED]['still_readable_by'], [
            user.name for user in self.member_a | self.member_b if self._allows(user, UNUSED, 'read')])
        self.assertFalse(self.env[UNUSED].with_user(self.member_a).browse().has_access('read'))

        items = self._items(self.profile.gec_unblock_data(self.hidden.id, [UNUSED]))
        line = self._line(UNUSED)
        self.assertTrue(line, "the line stays while Edit, Create and Delete are off")
        self.assertEqual([line[name] for name in PERM_FIELDS], [True, False, False, False])
        self.assertEqual((items[UNUSED]['status'], items[UNUSED]['by']), ('unused', False))
        self.assertTrue(self._allows(self.member_a, UNUSED, 'read'))
        self.assertTrue(self.env[UNUSED].with_user(self.member_a).browse().has_access('read'))
        for operation in ('write', 'create', 'unlink'):
            self.assertFalse(self._allows(self.member_a, UNUSED, operation), operation)

    def test_a_menu_level_block_is_shown_and_cannot_be_unblocked_here(self):
        """ A menu rule with Also shared data covers the data another app opens too: it shows as blocked by the
        menu, and Unblock refuses it (it is changed on that menu). """
        self.profile.gec_menu_panel_set(self.hidden.id, {
            'kind': 'menu_rights', 'perm_read': False, 'perm_write': False, 'perm_create': False,
            'perm_unlink': False, 'include_shared': True})
        items = self._items(self.profile.gec_hidden_exposure(self.hidden.id))
        self.assertEqual((items[UNUSED]['status'], items[UNUSED]['by']), ('blocked', 'menu'))
        self.assertEqual(items[UNUSED]['by_menus'], [self.hidden.complete_name])
        self.assertFalse(self.profile.model_ids)
        with self.assertRaises(UserError):
            self.profile.gec_unblock_data(self.hidden.id, [UNUSED])
        self.assertFalse(self._allows(self.member_a, UNUSED, 'read'))

    def test_still_readable_by_a_member_of_a_second_additive_profile(self):
        self.env['gec.access.profile'].create({'name': 'Exposure second', 'user_ids': [(6, 0, self.member_b.ids)]})
        items = self._items(self.profile.gec_hidden_exposure(self.hidden.id))
        self.assertIn(self.member_b.name, items[UNUSED]['still_readable_by'])
        items = self._items(self.profile.gec_block_data(self.hidden.id, [UNUSED]))
        self.assertIn(self.member_b.name, items[UNUSED]['still_readable_by'])
        self.assertTrue(self._allows(self.member_b, UNUSED, 'read'))
        self.assertFalse(self._allows(self.member_a, UNUSED, 'read'))

    def test_the_server_refuses_core_data_unknown_data_and_non_managers(self):
        with self.assertRaises(UserError):
            self.profile.gec_block_data(self.hidden.id, ['res.partner'])
        with self.assertRaises(UserError):
            self.profile.gec_block_data(self.hidden.id, ['res.country.state'])
        with self.assertRaises(UserError):
            self.profile.gec_block_data(self.hidden.id, [UNUSED, 'res.partner'])
        with self.assertRaises(UserError):
            self.profile.gec_unblock_data(self.hidden.id, [UNUSED])
        self.assertFalse(self.profile.model_ids, "a refused call writes nothing")
        for call in (lambda profile: profile.gec_hidden_exposure(self.hidden.id),
                     lambda profile: profile.gec_block_data(self.hidden.id, [UNUSED]),
                     lambda profile: profile.gec_unblock_data(self.hidden.id, [UNUSED])):
            with self.assertRaises(AccessError):
                call(self.profile.with_user(self.employee))

    def test_block_covers_the_line_models_of_a_document(self):
        self.assertTrue(self.line_models)
        before = self._items(self.profile.gec_hidden_exposure(self.hidden.id))
        expected = [name for name in (DOCUMENT, *self.line_models)
                    if name in before and before[name]['status'] != 'core']
        self.assertIn(DOCUMENT, expected)
        self.assertTrue(set(expected) - {DOCUMENT}, "the lines are exposed with their document")
        self.assertEqual(before[DOCUMENT]['lines'], [self.env['ir.model']._get(name).name for name in expected[1:]])
        items = self._items(self.profile.gec_block_data(self.hidden.id, [DOCUMENT]))
        self.assertEqual(items[DOCUMENT]['lines'], [])
        for name in expected:
            self.assertEqual((items[name]['status'], items[name]['by']), ('blocked', 'line'), name)
            self.assertEqual([self._line(name)[field] for field in PERM_FIELDS], [False] * 4, name)
        items = self._items(self.profile.gec_unblock_data(self.hidden.id, expected))
        for name in expected:
            self.assertTrue(self._line(name).perm_read, name)
            self.assertNotEqual(items[name]['status'], 'blocked', name)

    def test_core_data_is_found_through_the_module_that_created_it(self):
        """ An activity type is core because mail created it: no special case by name. """
        items = self._items(self.profile.gec_hidden_exposure(self.hidden.id))
        self.assertEqual(items[CORE]['status'], 'core')
        with self.assertRaises(UserError):
            self.profile.gec_block_data(self.hidden.id, [CORE])
        self.assertFalse(self.profile.model_ids, "a refused call writes nothing")

    def test_a_caller_with_more_companies_than_the_members(self):
        """ The navbar of a member is read under the member's own companies, not the caller's: a caller working
        in two companies can still read and block for a member of one. """
        company_a = self.member_a.company_id
        company_b = self.env['res.company'].create({'name': 'GEC Exposure Company B'})
        manager = new_test_user(
            self.env, 'gec_exposure_manager', groups='base.group_user,gec_access_manager.group_access_manager',
            company_id=company_a.id, company_ids=[Command.set([company_a.id, company_b.id])])
        self.assertEqual(self.member_a.company_ids, company_a)
        profile = self.profile.with_user(manager).with_context(allowed_company_ids=[company_a.id, company_b.id])
        self.assertIn(UNUSED, self._items(profile.gec_hidden_exposure(self.hidden.id)))
        items = self._items(profile.gec_block_data(self.hidden.id, [UNUSED]))
        self.assertEqual(items[UNUSED]['status'], 'blocked')
        self.assertFalse(self._allows(self.member_a, UNUSED, 'read'))

    def test_the_inherits_children_are_listed(self):
        """ Blocking res.partner would also block res.users: the row says so. """
        items = self._items(self.profile.gec_hidden_exposure(self.hidden.id))
        self.assertIn(self.env['ir.model']._get('res.users').name, items['res.partner']['inherits'])

    def test_unblock_acts_only_on_the_names_it_gets(self):
        """ Each line model of a document has its own row and button: unblocking the document leaves them. """
        before = self._items(self.profile.gec_hidden_exposure(self.hidden.id))
        lines = [name for name in self.line_models if name in before and before[name]['status'] != 'core']
        self.assertTrue(lines)
        self.profile.gec_block_data(self.hidden.id, [DOCUMENT])
        items = self._items(self.profile.gec_unblock_data(self.hidden.id, [DOCUMENT]))
        self.assertTrue(self._line(DOCUMENT).perm_read)
        self.assertNotEqual(items[DOCUMENT]['status'], 'blocked')
        for name in lines:
            self.assertEqual((items[name]['status'], items[name]['by']), ('blocked', 'line'), name)
            self.assertFalse(self._line(name).perm_read, name)
