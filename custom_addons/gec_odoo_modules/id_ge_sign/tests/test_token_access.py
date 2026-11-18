from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .common import GeoeidCommon


@tagged('post_install', '-at_install')
class TestTokenAccess(GeoeidCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sign_user = new_test_user(cls.env, login='geoeid_sign_user', groups='sign.group_sign_user')
        cls.admin = new_test_user(cls.env, login='geoeid_admin', groups='base.group_system,sign.group_sign_manager')

    def launched_item_of(self, user):
        return self.launched_item(user.partner_id)

    def test_sign_user_cannot_read_the_token(self):
        item = self.launched_item_of(self.sign_user)
        self.assertEqual(item.with_user(self.sign_user).geoeid_state, 'launched')
        with self.assertRaises(AccessError):
            item.with_user(self.sign_user).read(['geoeid_token'])

    def test_system_user_can_read_the_token(self):
        item = self.launched_item_of(self.sign_user)
        self.assertEqual(item.with_user(self.admin).geoeid_token, item.geoeid_token)

    def test_sign_user_cannot_read_technical_acknowledgement_or_attempt_fields(self):
        item = self.launched_item_of(self.sign_user)
        with self.assertRaises(AccessError):
            item.with_user(self.sign_user).read(['geoeid_signed_digest'])
        with self.assertRaises(AccessError):
            item.sign_request_id.with_user(self.sign_user).read(['geoeid_public_attempt'])
