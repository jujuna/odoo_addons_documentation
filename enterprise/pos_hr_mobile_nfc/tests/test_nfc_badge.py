from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user

from odoo.addons.point_of_sale.tests.common import CommonPosTest
from odoo.addons.pos_hr_mobile_nfc.models import sdm

ENCODING_KEY = bytes.fromhex('000102030405060708090A0B0C0D0E0F')
UID = bytes.fromhex('04DE5F1EACC040')


def payload(key, uid, counter):
    """Badge read as the chip would produce it."""
    return f'https://odoo.com/badge?uid={uid.hex().upper()}&ctr={counter:06X}&cmac={sdm.sdm_mac(key, uid, counter).hex().upper()}'


class TestNfcBadge(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({'name': 'Badge Holder', 'barcode': UID.hex().upper()})
        cls.config = cls.env['pos.config'].create({
            'name': 'Badge POS',
            'nfc_secure_login': True,
            'nfc_encoding_key': ENCODING_KEY.hex(),
            'cashier_employee_ids': cls.employee.ids,
        })

    def verify(self, payload):
        return self.config.verify_nfc_badge(payload)

    def test_an12196_vector(self):
        self.assertEqual(sdm.sdm_mac(bytes(16), UID, 0x3D).hex().upper(), '94EED9EE65337086')

    def test_genuine_badge_identifies_its_employee(self):
        self.assertEqual(self.verify(payload(ENCODING_KEY, UID, 1)), self.employee.id)
        self.assertEqual(self.employee.nfc_badge_counter, 1)

    def test_counter_must_advance(self):
        self.verify(payload(ENCODING_KEY, UID, 5))
        self.assertFalse(self.verify(payload(ENCODING_KEY, UID, 5)))
        self.assertFalse(self.verify(payload(ENCODING_KEY, UID, 4)))
        self.assertEqual(self.verify(payload(ENCODING_KEY, UID, 6)), self.employee.id)

    def test_forged_badge_is_rejected(self):
        self.assertFalse(self.verify(payload(bytes(16), UID, 1)))
        self.assertFalse(self.verify('https://odoo.com/badge?uid=04DE5F1EACC040&ctr=000001&cmac=0000000000000000'))
        self.assertFalse(self.verify('04DE5F1EACC040'))
        self.assertEqual(self.employee.nfc_badge_counter, 0)

    def test_unknown_badge_is_rejected(self):
        self.assertFalse(self.verify(payload(ENCODING_KEY, bytes.fromhex('04000000000000'), 1)))

    def test_secure_badges_need_the_encoding_key(self):
        with self.assertRaises(ValidationError):
            self.env['pos.config'].create({'name': 'Keyless POS', 'nfc_secure_login': True})
        with self.assertRaises(ValidationError):
            self.config.nfc_encoding_key = False
        self.config.write({'nfc_secure_login': False, 'nfc_encoding_key': False})
        with self.assertRaises(ValidationError):
            self.config.nfc_secure_login = True
        self.config.write({'nfc_secure_login': True, 'nfc_encoding_key': ENCODING_KEY.hex()})
        self.assertTrue(self.config.nfc_secure_login)

    def test_reencoding_the_badges_resets_the_counters(self):
        self.verify(payload(ENCODING_KEY, UID, 5))
        self.config.write({'nfc_encoding_key': ENCODING_KEY.hex()})
        self.config.write({'nfc_encoding_key': ENCODING_KEY.hex().upper()})
        self.assertEqual(self.employee.nfc_badge_counter, 5)
        new_key = bytes(16)
        self.config.nfc_encoding_key = new_key.hex()
        self.assertEqual(self.employee.nfc_badge_counter, 0)
        self.assertEqual(self.verify(payload(new_key, UID, 1)), self.employee.id)

    def test_enrolling_a_badge_resets_the_counter(self):
        self.verify(payload(ENCODING_KEY, UID, 5))
        self.employee.name = 'Badge Holder 2'
        self.assertEqual(self.employee.nfc_badge_counter, 5)
        new_uid = bytes.fromhex('04000000000001')
        self.employee.barcode = new_uid.hex().upper()
        self.assertEqual(self.employee.nfc_badge_counter, 0)
        self.assertEqual(self.verify(payload(ENCODING_KEY, new_uid, 1)), self.employee.id)

    def test_reenrolling_a_reencoded_badge_resets_the_counter(self):
        self.verify(payload(ENCODING_KEY, UID, 5))
        self.employee.barcode = UID.hex().upper()
        self.assertEqual(self.employee.nfc_badge_counter, 0)
        self.assertEqual(self.verify(payload(ENCODING_KEY, UID, 1)), self.employee.id)

    def test_employee_sets_their_own_badge(self):
        user = new_test_user(self.env, 'badge_holder', groups='base.group_user')
        self.employee.user_id = user
        self.verify(payload(ENCODING_KEY, UID, 5))
        user.with_user(user).barcode = '04000000000001'
        self.assertEqual(self.employee.barcode, '04000000000001')
        self.assertEqual(self.employee.nfc_badge_counter, 0)

    def test_employee_form_reads_badges_over_nfc(self):
        self.assertEqual(self.employee.open_badge_scanner()['tag'], 'pos_hr_mobile_nfc.badge_scanner')

    def test_encoding_key_is_an_aes128_key(self):
        with self.assertRaises(ValidationError):
            self.config.nfc_encoding_key = ENCODING_KEY.hex()[:-2]
        with self.assertRaises(ValidationError):
            self.config.nfc_encoding_key = 'not a key'
        self.config.nfc_encoding_key = ENCODING_KEY.hex().upper()

    def test_encoding_key_is_per_pos(self):
        other = self.config.copy({'name': 'Other POS', 'nfc_secure_login': True, 'nfc_encoding_key': bytes(16).hex()})
        self.assertFalse(other.verify_nfc_badge(payload(ENCODING_KEY, UID, 1)))
        duplicate = self.config.copy()
        self.assertFalse(duplicate.nfc_secure_login)
        self.assertFalse(duplicate.nfc_encoding_key)

    def test_encoding_key_is_hidden_from_cashiers(self):
        cashier = new_test_user(self.env, 'cashier', groups='point_of_sale.group_pos_user,hr.group_hr_user')
        config = self.config.with_user(cashier)
        with self.assertRaises(AccessError):
            config.read(['nfc_encoding_key'])
        with self.assertRaises(AccessError):
            config.write({'nfc_encoding_key': bytes(16).hex()})
        self.assertEqual(config.verify_nfc_badge(payload(ENCODING_KEY, UID, 1)), self.employee.id)

    def test_secure_login_off_nothing_is_genuine(self):
        self.config.nfc_secure_login = False
        self.assertFalse(self.verify(payload(ENCODING_KEY, UID, 1)))

    def test_employee_of_another_company_is_rejected(self):
        self.employee.company_id = self.env['res.company'].create({'name': 'Other Company'})
        self.assertFalse(self.verify(payload(ENCODING_KEY, UID, 1)))


class TestNfcBadgeLoading(CommonPosTest):

    def test_encoding_key_is_not_loaded_in_the_pos(self):
        self.pos_config_usd.write({
            'module_pos_hr': True,
            'nfc_secure_login': True,
            'nfc_encoding_key': ENCODING_KEY.hex(),
        })
        self.pos_config_usd.open_ui()
        session = self.pos_config_usd.current_session_id
        config = session.load_data({'only_records': True})['pos.config'][0]
        self.assertNotIn('nfc_encoding_key', config)
        self.assertTrue(config['nfc_secure_login'])
        config = session.load_data({'only_records': False})['pos.config']['records'][0]
        self.assertNotIn('nfc_encoding_key', config)
        config = session.load_data({'models': ['pos.config'], 'records': {'pos.config': {}}})['pos.config']['records'][0]
        self.assertNotIn('nfc_encoding_key', config)
