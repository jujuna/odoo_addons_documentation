# The result block of the panel: what the groups of a profile give, and what its own limits take away.
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

ALL = ('read', 'create', 'write', 'unlink')


@tagged('post_install', '-at_install')
class TestPanelResult(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        IrModel = cls.env['ir.model']
        cls.model = IrModel._get('res.users.log')
        cls.group = cls.env['res.groups'].create({'name': 'GEC Result Test Group'})
        Menu = cls.env['ir.ui.menu']
        cls.shop = Menu.create({'name': 'GEC Result Shop'})
        cls.leaf = Menu.create({'name': 'Logins', 'parent_id': cls.shop.id, 'sequence': 10,
                                'action': cls._action('res.users.log')})
        cls.tags = Menu.create({'name': 'Tags', 'parent_id': cls.shop.id, 'sequence': 20,
                                'action': cls._action('res.partner.category')})
        cls.config = Menu.create({'name': 'Configuration', 'parent_id': cls.shop.id, 'sequence': 5})
        cls.precision = Menu.create({'name': 'Precision', 'parent_id': cls.config.id,
                                     'action': cls._action('decimal.precision')})
        # tags are opened by another app too: shared data
        cls.other = Menu.create({'name': 'GEC Result Other'})
        Menu.create({'name': 'People', 'parent_id': cls.other.id, 'action': cls._action('res.partner.category')})
        cls._isolate_fixture({'res.users.log', 'res.partner.category', 'decimal.precision'}, cls.shop | cls.other)
        cls.profile = cls.env['gec.access.profile'].create({'name': 'Panel Result'})
        cls.profile.granted_group_ids = cls.group
        cls.admin = cls.env.ref('base.user_admin')

    @classmethod
    def _isolate_fixture(cls, model_names, apps):
        """ Archive the menus of installed apps that open the fixture's data, so which app owns it does not
        depend on the database. """
        Menu = cls.env['ir.ui.menu']
        Wizard = cls.env['gec.access.app.wizard']
        others = Menu.search([('action', '!=', False)]) - Menu.search([('id', 'child_of', apps.ids)])
        others.filtered(lambda menu: Wizard._menu_model(menu) in model_names).active = False

    @classmethod
    def _action(cls, model_name):
        action = cls.env['ir.actions.act_window'].create({'name': model_name, 'res_model': model_name})
        return f'ir.actions.act_window,{action.id}'

    def _group_gives(self, operation, domain=False):
        self.env['ir.access'].create({
            'name': 'gec_access_manager panel result', 'model_id': self.model.id,
            'group_id': self.group.id, 'operation': operation, 'domain': domain})

    def _result(self, menu=None):
        return self.profile.with_user(self.admin).gec_menu_panel((menu or self.leaf).id)['result']

    def _ops(self, menu=None):
        result = self._result(menu)
        self.assertEqual([entry['model'] for entry in result['models']], ['res.users.log'])
        return result['models'][0]

    def test_a_group_with_a_domain_and_no_delete(self):
        self._group_gives('cru', "[('id', '>', 0)]")
        entry = self._ops()
        for operation in ('read', 'create', 'write'):
            self.assertEqual(entry['ops'][operation], {
                'allowed': True, 'filtered': True, 'profile_filtered': False, 'source': False})
        self.assertEqual(entry['ops']['unlink'], {
            'allowed': False, 'filtered': False, 'profile_filtered': False, 'source': 'group'})
        self.assertFalse(entry['row_id'])
        self.assertEqual(entry['limited_by'], [])
        self.assertEqual(entry['name'], self.model.name)

    def test_a_group_with_every_right_and_a_models_line(self):
        self._group_gives('crud')
        entry = self._ops()
        for operation in ALL:
            self.assertEqual(entry['ops'][operation], {
                'allowed': True, 'filtered': False, 'profile_filtered': False, 'source': False})
        line = self.env['gec.access.profile.model'].create({
            'profile_id': self.profile.id, 'model_id': self.model.id, 'perm_unlink': False})
        entry = self._ops()
        self.assertEqual(entry['ops']['unlink']['allowed'], False)
        self.assertEqual(entry['ops']['unlink']['source'], 'row')
        self.assertTrue(entry['ops']['write']['allowed'])
        self.assertEqual(entry['row_id'], line.id)

    def test_read_only_everywhere(self):
        self._group_gives('crud')
        self.profile.global_readonly = True
        result = self._result()
        self.assertTrue(result['readonly_everywhere'])
        ops = result['models'][0]['ops']
        self.assertTrue(ops['read']['allowed'])
        for operation in ('create', 'write', 'unlink'):
            self.assertEqual((ops[operation]['allowed'], ops[operation]['source']), (False, 'readonly'))

    def test_a_menu_rule_limits_the_data_below_it(self):
        self._group_gives('crud')
        self.env['gec.access.profile.menu'].create({
            'profile_id': self.profile.id, 'menu_id': self.shop.id,
            'perm_read': False, 'perm_write': False, 'perm_create': False, 'perm_unlink': False})
        entry = self._ops()
        for operation in ALL:
            self.assertEqual((entry['ops'][operation]['allowed'], entry['ops'][operation]['source']), (False, 'menu'))
        self.assertEqual(entry['limited_by'], ['GEC Result Shop'])
        self.assertFalse(entry['row_id'])

    def test_a_models_line_cancels_the_menu_rule_but_the_panel_still_names_it(self):
        self._group_gives('crud')
        self.env['gec.access.profile.menu'].create({
            'profile_id': self.profile.id, 'menu_id': self.shop.id, 'perm_write': False})
        line = self.env['gec.access.profile.model'].create({'profile_id': self.profile.id, 'model_id': self.model.id})
        entry = self._ops()
        self.assertTrue(entry['ops']['write']['allowed'])
        self.assertFalse(entry['ops']['write']['source'])
        self.assertEqual(entry['row_id'], line.id)
        self.assertEqual(entry['limited_by'], ['GEC Result Shop'])

    def test_the_models_line_domain_is_the_profile_filter(self):
        self._group_gives('crud')
        self.env['gec.access.profile.model'].create({
            'profile_id': self.profile.id, 'model_id': self.model.id, 'domain': "[('id', '>', 0)]"})
        for right in self._ops()['ops'].values():
            self.assertEqual((right['allowed'], right['filtered'], right['profile_filtered']), (True, False, True))

    def test_shared_data_keeps_its_place_and_is_flagged(self):
        self.env['gec.access.profile.menu'].create({
            'profile_id': self.profile.id, 'menu_id': self.shop.id, 'perm_write': False})
        entries = self._result(self.shop)['models']
        self.assertEqual([(entry['model'], entry['shared']) for entry in entries], [
            ('res.users.log', False), ('res.partner.category', True), ('decimal.precision', False)])
        self.assertEqual([entry['limited_by'] for entry in entries], [['GEC Result Shop'], [], ['GEC Result Shop']])

    def test_the_configuration_data_comes_last_even_after_shared_main_data(self):
        entries = self._result(self.shop)['models']
        self.assertEqual([entry['model'] for entry in entries][-2:], ['res.partner.category', 'decimal.precision'])
        self.assertTrue(entries[-2]['shared'])
        self.assertFalse(entries[-1]['shared'])
        self.assertEqual(self._result(self.shop)['more'], 0)

    def _member(self, login, group=None):
        """ A user of the profile, holding ``group`` of their own. """
        user = new_test_user(self.env, login, groups='base.group_user')
        if group:
            user.group_ids |= group
        self.profile.user_ids |= user
        return user

    def _for(self, user):
        result = self.profile.with_user(self.admin).gec_panel_result(self.leaf.id, user.id)
        return result, (result['models'][0]['ops'] if result['models'] else {})

    def test_a_member_shows_what_their_own_groups_give(self):
        self._group_gives('r')
        own = self.env['res.groups'].create({'name': 'GEC Result Own Group'})
        self.env['ir.access'].create({
            'name': 'gec_access_manager panel result own', 'model_id': self.model.id,
            'group_id': own.id, 'operation': 'c'})
        member = self._member('gec_result_member', own)
        self.assertEqual(self._ops()['ops']['create']['source'], 'group')
        _result, ops = self._for(member)
        self.assertTrue(ops['create']['allowed'])
        self.assertTrue(ops['read']['allowed'])
        self.assertEqual(ops['write']['source'], 'group')

    def test_another_profile_of_the_member_denying_is_named(self):
        self._group_gives('crud')
        member = self._member('gec_result_member_other')
        self.env['gec.access.profile'].create({
            'name': 'Result Other Profile', 'strictness': 'override', 'user_ids': [(6, 0, member.ids)],
            'model_ids': [(0, 0, {'model_id': self.model.id, 'perm_create': False})]})
        _result, ops = self._for(member)
        self.assertEqual((ops['create']['allowed'], ops['create']['source']), (False, 'other'))
        self.assertTrue(ops['write']['allowed'])

    def test_an_administrator_is_not_limited(self):
        self.profile.user_ids |= self.admin
        result, _ops = self._for(self.admin)
        self.assertTrue(result['exempt'])
        self.assertEqual(result['models'], [])

    def test_the_members_are_direct_assigned_and_of_the_also_given_groups(self):
        direct = self._member('gec_result_direct')
        by_group = new_test_user(self.env, 'gec_result_by_group', groups='base.group_user')
        given = self.env['res.groups'].create({'name': 'GEC Result Given', 'user_ids': [(6, 0, by_group.ids)]})
        self.profile.group_ids = given
        assigned = new_test_user(self.env, 'gec_result_assigned', groups='base.group_user')
        self.env['gec.access.profile.assignment'].create({
            'profile_id': self.profile.id, 'user_id': assigned.id, 'date_from': '2000-01-01'})
        members = self.profile.with_user(self.admin).gec_menu_panel(self.leaf.id)['members']
        self.assertEqual([member['name'] for member in members], sorted([direct.name, by_group.name, assigned.name]))
        self.assertEqual({member['id'] for member in members}, set((direct | by_group | assigned).ids))

    def test_a_settings_user_under_a_profile_that_spares_administrators_is_not_limited(self):
        self._group_gives('crud')
        self.profile.apply_to_admin = False
        user = new_test_user(self.env, 'gec_result_settings', groups='base.group_user,base.group_system')
        self.profile.user_ids |= user
        result, _ops = self._for(user)
        self.assertTrue(result['exempt'])

    def test_an_archived_profile_does_not_apply_to_its_member(self):
        self._group_gives('crud')
        member = self._member('gec_result_archived', self.group)
        self.profile.active = False
        result, ops = self._for(member)
        self.assertTrue(result['not_applied'])
        self.assertTrue(ops['read']['allowed'])

    def test_only_a_member_of_the_profile_can_be_shown(self):
        stranger = new_test_user(self.env, 'gec_result_stranger', groups='base.group_user')
        with self.assertRaises(UserError):
            self.profile.with_user(self.admin).gec_panel_result(self.leaf.id, stranger.id)

    def test_only_an_access_manager_can_ask(self):
        member = self._member('gec_result_member_ask')
        with self.assertRaises(AccessError):
            self.profile.with_user(member).gec_panel_result(self.leaf.id, member.id)

    def test_a_denial_this_additive_profile_shares_with_an_override_one_is_named_other(self):
        self._group_gives('crud')
        member = self._member('gec_result_member_both')
        self.env['gec.access.profile.model'].create({
            'profile_id': self.profile.id, 'model_id': self.model.id, 'perm_create': False})
        self.env['gec.access.profile'].create({
            'name': 'Result Override Profile', 'strictness': 'override', 'user_ids': [(6, 0, member.ids)],
            'model_ids': [(0, 0, {'model_id': self.model.id, 'perm_create': False})]})
        self.assertEqual(self._ops()['ops']['create']['source'], 'row')
        _result, ops = self._for(member)
        self.assertEqual((ops['create']['allowed'], ops['create']['source']), (False, 'other'))
