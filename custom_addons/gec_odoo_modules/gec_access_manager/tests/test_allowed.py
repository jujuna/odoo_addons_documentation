# Allowed Records. The test database lacks the business apps, so a test kind on
# partner tags stands in for them.
from unittest.mock import patch

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.gec_access_manager.models import gec_access_allowed

TEST_KIND = ('Partner Tags', 'res.partner.category', {
    'res.partner.category': "[('id', 'in', {ids})]",
    'res.partner': "[('category_id', 'in', {ids})]",
    'res.partner.bank': "[('gec_no_such_field', 'in', {ids})]",
})


@tagged('post_install', '-at_install')
class TestAllowed(TransactionCase):

    def setUp(self):
        super().setUp()
        patcher = patch.dict(gec_access_allowed.ALLOWED_KINDS, {'gec_test': TEST_KIND})
        patcher.start()
        self.addCleanup(patcher.stop)
        Tag = self.env['res.partner.category']
        self.red, self.blue = Tag.create({'name': 'Red'}), Tag.create({'name': 'Blue'})
        Partner = self.env['res.partner']
        self.red_partner = Partner.create({'name': 'Red One', 'category_id': [(6, 0, self.red.ids)]})
        self.blue_partner = Partner.create({'name': 'Blue One', 'category_id': [(6, 0, self.blue.ids)]})
        self.ann = new_test_user(self.env, 'gec_allowed_ann', groups='base.group_user,base.group_partner_manager')
        self.bob = new_test_user(self.env, 'gec_allowed_bob', groups='base.group_user,base.group_partner_manager')

    def _visible(self, user, model='res.partner', records=None):
        records = records or (self.red_partner | self.blue_partner)
        return self.env[model].with_user(user).search([('id', 'in', records.ids)])

    def test_kinds_follow_the_installed_models(self):
        kinds = dict(self.env['gec.access.allowed']._selection_kinds())
        self.assertIn('gec_test', kinds)
        for kind, (_label, model_name, _filters) in gec_access_allowed.ALLOWED_KINDS.items():
            self.assertEqual(kind in kinds, model_name in self.env, kind)

    def test_allowed_records_and_what_belongs_to_them(self):
        self.env['gec.access.profile'].create({
            'name': 'Red only', 'user_ids': [(6, 0, self.ann.ids)],
            'allowed_ids': [(0, 0, {'kind': 'gec_test', 'res_id': self.red.id})],
        })
        self.assertEqual(self._visible(self.ann, 'res.partner.category', self.red | self.blue), self.red)
        self.assertEqual(self._visible(self.ann), self.red_partner)
        # a filter on a field the model lacks is left out, not an error
        self.env['res.partner.bank'].with_user(self.ann).search([])

    def test_each_users_own(self):
        self.env['gec.access.profile'].create({
            'name': 'Own tag', 'user_ids': [(6, 0, (self.ann | self.bob).ids)],
            'allowed_ids': [(0, 0, {'kind': 'gec_test', 'per_user': True})],
        })
        # nothing set on the user yet: nothing allowed
        self.assertFalse(self._visible(self.ann))
        self.ann.access_allowed_ids = [(0, 0, {'kind': 'gec_test', 'res_id': self.red.id})]
        self.bob.access_allowed_ids = [(0, 0, {'kind': 'gec_test', 'res_id': self.blue.id})]
        self.assertEqual(self._visible(self.ann), self.red_partner)
        self.assertEqual(self._visible(self.bob), self.blue_partner)

    def test_a_clear_refusal(self):
        self.env['gec.access.profile'].create({
            'name': 'Red only', 'user_ids': [(6, 0, self.ann.ids)],
            'allowed_ids': [(0, 0, {'kind': 'gec_test', 'res_id': self.red.id})],
        })
        with self.assertRaises(AccessError) as caught:
            self.blue_partner.with_user(self.ann).write({'name': 'Renamed'})
        self.assertIn('outside the records allowed to you', str(caught.exception))
        self.assertNotIn('Blue One', str(caught.exception))

    def test_a_line_needs_a_record_and_an_owner(self):
        Allowed = self.env['gec.access.allowed']
        profile = self.env['gec.access.profile'].create({'name': 'P'})
        with self.assertRaises(ValidationError):
            Allowed.create({'kind': 'gec_test', 'profile_id': profile.id})
        with self.assertRaises(ValidationError):
            Allowed.create({'kind': 'gec_test', 'res_id': self.red.id})
        with self.assertRaises(ValidationError):
            Allowed.create({'kind': 'gec_test', 'user_id': self.ann.id, 'per_user': True})

    def test_a_line_of_a_user_follows_the_editor_rule_of_their_profiles(self):
        """ N2: a manager outside Settings cannot add, change or delete the allowed record of a user carrying a
        profile for Settings users, or one granting a group the manager lacks; a Settings user can. """
        Profile = self.env['gec.access.profile']
        Allowed = self.env['gec.access.allowed']
        manager = new_test_user(self.env, 'gec_allowed_manager',
                                groups='base.group_user,gec_access_manager.group_access_manager')
        settings = new_test_user(self.env, 'gec_allowed_settings',
                                 groups='base.group_user,base.group_system,gec_access_manager.group_access_manager')
        lacking = self.env['res.groups'].create({'name': 'GEC Allowed Lacking'})
        Profile.with_user(settings).create({
            'name': 'For admins', 'apply_to_admin': True, 'user_ids': [(6, 0, self.ann.ids)]})
        Profile.with_user(settings).create({
            'name': 'Grants lacking', 'granted_group_ids': [(6, 0, lacking.ids)], 'user_ids': [(6, 0, self.bob.ids)]})
        vals = {'kind': 'gec_test', 'res_id': self.red.id}
        for user in (self.ann, self.bob):
            with self.assertRaises(AccessError):
                Allowed.with_user(manager).create({**vals, 'user_id': user.id})
            line = Allowed.with_user(settings).create({**vals, 'user_id': user.id})
            with self.assertRaises(AccessError):
                line.with_user(manager).write({'res_id': self.blue.id})
            with self.assertRaises(AccessError):
                line.with_user(manager).unlink()
            line.with_user(settings).write({'res_id': self.blue.id})
            line.with_user(settings).unlink()
        free = new_test_user(self.env, 'gec_allowed_free', groups='base.group_user')
        line = Allowed.with_user(manager).create({**vals, 'user_id': free.id})
        with self.assertRaises(AccessError):
            line.write({'user_id': self.ann.id})
        line.unlink()

    def test_a_line_of_a_user_follows_the_profiles_they_get_by_group_or_assignment(self):
        """ N2: a profile for Settings users reaching a user through an Odoo group or a temporary assignment
        protects the allowed lines of that user like a directly assigned one. """
        Profile = self.env['gec.access.profile']
        Allowed = self.env['gec.access.allowed']
        manager = new_test_user(self.env, 'gec_allowed_manager2',
                                groups='base.group_user,gec_access_manager.group_access_manager')
        group = self.env['res.groups'].create({'name': 'GEC Allowed Admin Group'})
        Profile.create({'name': 'For admins by group', 'apply_to_admin': True, 'group_ids': [(6, 0, group.ids)]})
        self.ann.write({'group_ids': [(4, group.id)]})
        for_a_while = Profile.create({'name': 'For admins for a while', 'apply_to_admin': True})
        self.env['gec.access.profile.assignment'].create({'profile_id': for_a_while.id, 'user_id': self.bob.id})
        vals = {'kind': 'gec_test', 'res_id': self.red.id}
        for user in (self.ann, self.bob):
            with self.assertRaises(AccessError):
                Allowed.with_user(manager).create({**vals, 'user_id': user.id})
            line = Allowed.create({**vals, 'user_id': user.id})
            with self.assertRaises(AccessError):
                line.with_user(manager).write({'res_id': self.blue.id})
            with self.assertRaises(AccessError):
                line.with_user(manager).unlink()
