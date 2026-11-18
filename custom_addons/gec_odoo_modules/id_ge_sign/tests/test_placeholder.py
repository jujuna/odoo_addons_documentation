from odoo.tests import tagged

from .common import COMMON_NAME, PERSONAL_NUMBER, GeoeidCommon

PLACEHOLDER_NAME = 'Georgian ID Card signer'
NUMBER = '01001000077'


@tagged('post_install', '-at_install')
class TestPlaceholder(GeoeidCommon):

    def update(self, partner, **info):
        item = self.card_item(partner)
        item._geoeid_update_placeholder({
            'common_name': COMMON_NAME, 'personal_number': NUMBER, **info})
        return item

    def new_placeholder(self):
        return self.placeholder('holder@id-card.invalid')

    def test_regular_partner_is_untouched(self):
        partner = self.make_partner('Regular', email='regular@example.com')
        self.update(partner)
        self.assertEqual((partner.name, partner.vat, partner.active), ('Regular', False, True))

    def test_certificate_sets_the_name_and_vat_and_shows_the_contact(self):
        partner = self.new_placeholder()
        self.update(partner)
        self.assertEqual((partner.name, partner.vat, partner.active), (COMMON_NAME, NUMBER, True))

    def test_active_duplicate_without_company_keeps_the_placeholder_archived(self):
        self.make_partner('Existing', vat=NUMBER, company_id=False)
        partner = self.new_placeholder()
        self.update(partner)
        self.assertEqual((partner.vat, partner.active), (NUMBER, False))

    def test_active_duplicate_of_the_same_company_keeps_the_placeholder_archived(self):
        partner = self.new_placeholder()
        item = self.card_item(partner)
        self.assertTrue(item.communication_company_id)
        self.make_partner('Existing', vat=NUMBER, company_id=item.communication_company_id.id)
        item._geoeid_update_placeholder({'common_name': COMMON_NAME, 'personal_number': NUMBER})
        self.assertEqual((partner.vat, partner.active), (NUMBER, False))

    def test_duplicate_of_another_company_does_not_count(self):
        self.make_partner('Existing', vat=NUMBER, company_id=self.card_company.id)
        partner = self.new_placeholder()
        self.update(partner)
        self.assertTrue(partner.active)

    def test_duplicate_stored_with_the_country_prefix_counts(self):
        duplicate = self.make_partner('Existing', vat='GE' + NUMBER, company_id=False)
        self.assertEqual(duplicate.vat, 'GE' + NUMBER)
        partner = self.new_placeholder()
        self.update(partner)
        self.assertEqual((partner.vat, partner.active), (NUMBER, False))

    def test_archived_duplicate_does_not_count(self):
        self.make_partner('Existing', vat=NUMBER, company_id=False, active=False)
        partner = self.new_placeholder()
        self.update(partner)
        self.assertTrue(partner.active)

    def test_certificate_without_number_shows_the_contact_without_vat(self):
        partner = self.new_placeholder()
        self.update(partner, personal_number='')
        self.assertEqual((partner.vat, partner.active), (False, True))

    def test_certificate_without_common_name_keeps_the_name(self):
        partner = self.new_placeholder()
        self.update(partner, common_name=False)
        self.assertEqual(partner.name, PLACEHOLDER_NAME)

    def test_submit_activates_the_placeholder(self):
        self.signer.vat = False
        partner = self.new_placeholder()
        item = self.launched_item(partner)
        item.sudo()._geoeid_submit_document(self.card_sign(item)[1])
        self.assertEqual((partner.name, partner.vat, partner.active), (COMMON_NAME, PERSONAL_NUMBER, True))
