from odoo.tests.common import TransactionCase


class TestStudioMailThread(TransactionCase):

    def test_track_get_fields_not_polluted_by_studio_context(self):
        """ Studio calls fields_get as superuser, which must not leak
        group-restricted fields in the tracked fields. """
        admin = self.env.ref('base.user_admin')
        field_name = 'name'
        Partner = self.env['res.partner'].with_user(admin)
        self.assertFalse(Partner.env.su)
        self.assertIn(field_name, Partner._track_get_fields())

        # restrict the field to a group the user is not a member of
        self.patch(Partner._fields[field_name], 'groups', 'base.group_portal')
        self.assertFalse(admin.has_groups('base.group_portal'))
        self.assertTrue(admin.has_group('base.group_system'))
        self.env.transaction.invalidate_ormcache()

        # first call is made from Studio, and fills the cache
        Partner.with_context(studio=True)._track_get_fields()

        # regular calls must not see the restricted field
        self.assertNotIn(field_name, Partner._track_get_fields())
        self.assertNotIn(field_name, Partner.with_context(studio=False)._track_get_fields())
