from odoo.tests import tagged

from odoo.addons.id_ge_sign.tools.cms import CmsVerificationError

from .common import PERSONAL_NUMBER, GeoeidCommon


@tagged('post_install', '-at_install')
class TestIdentity(GeoeidCommon):

    def check(self, partner, personal_number=PERSONAL_NUMBER):
        self.card_item(partner)._geoeid_check_identity({'personal_number': personal_number})

    def assertMismatch(self, partner, personal_number=PERSONAL_NUMBER):
        with self.assertRaises(CmsVerificationError):
            self.check(partner, personal_number)

    def test_own_vat_equal_is_accepted(self):
        self.check(self.make_partner('Own', email='own@example.com', vat=PERSONAL_NUMBER))

    def test_own_vat_different_is_refused(self):
        self.assertMismatch(self.make_partner('Own', email='own@example.com', vat='01001000002'))

    def test_prefixed_vat_equal_is_accepted(self):
        self.check(self.make_partner('Own', email='own@example.com', vat='GE' + PERSONAL_NUMBER))

    def test_prefixed_vat_different_is_refused(self):
        self.assertMismatch(self.make_partner('Own', email='own@example.com', vat='GE01001000002'))

    def test_company_vat_of_nine_digits_is_not_compared(self):
        self.check(self.make_partner('ACME', email='acme@example.com', is_company=True, vat='204566978'))

    def test_contact_person_of_a_company_is_not_compared(self):
        company = self.make_partner('ACME', is_company=True, vat='204566978')
        self.check(self.make_partner('Director', email='director@example.com', parent_id=company.id))

    def test_contact_person_of_an_individual_entrepreneur_is_not_compared(self):
        entrepreneur = self.make_partner('IE owner', is_company=True, vat='01001000099')
        contact = self.make_partner('IE employee', email='employee@example.com', parent_id=entrepreneur.id)
        self.assertEqual(contact.vat, '01001000099')
        self.check(contact)

    def test_signer_without_vat_is_not_compared(self):
        self.check(self.make_partner('No vat', email='novat@example.com'))

    def test_empty_certificate_number_against_own_vat_is_refused(self):
        self.assertMismatch(self.signer, personal_number='')

    def test_submit_refuses_a_certificate_of_another_person(self):
        item = self.launched_item(self.make_partner('Other', email='other@example.com', vat='01001000002'))
        __, signed = self.card_sign(item)
        with self.assertRaises(CmsVerificationError):
            item.sudo()._geoeid_submit_document(signed)
        self.assertEqual((item.state, item.geoeid_state), ('sent', 'launched'))
