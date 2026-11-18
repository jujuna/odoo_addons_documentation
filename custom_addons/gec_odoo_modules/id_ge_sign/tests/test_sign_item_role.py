from odoo.tests import tagged

from .common import GeoeidCommon


@tagged('post_install', '-at_install')
class TestSignItemRole(GeoeidCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sms_role = cls.env['sign.item.role'].create({'name': 'SMS', 'auth_method': 'sms'})

    def test_geoeid_role_requires_external_signature(self):
        self.assertTrue(self.card_role_1.requires_external_signature)

    def test_plain_and_sms_roles_do_not_require_external_signature(self):
        self.assertFalse(self.plain_role.requires_external_signature)
        self.assertFalse(self.sms_role.requires_external_signature)

    def test_geoeid_role_is_not_billed_to_an_iap_service(self):
        self.assertFalse(self.card_role_1._get_iap_service_name())

    def test_sms_role_keeps_core_iap_service(self):
        expected = self.sms_role._get_auth_method_iap_mapping()['sms']
        self.assertEqual(self.sms_role._get_iap_service_name(), expected)

    def test_geoeid_role_provider_name(self):
        self.assertEqual(self.card_role_1._get_external_signature_provider_name(), "Georgian ID Card")

    def test_plain_role_has_no_provider_name(self):
        self.assertFalse(self.plain_role._get_external_signature_provider_name())
