from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import GeoeidCommon


@tagged('post_install', '-at_install')
class TestRequestCreate(GeoeidCommon):

    def test_geoeid_role_refuses_two_documents(self):
        template = self.make_template([self.card_role_1], documents=2)
        with self.assertRaises(UserError):
            self.make_request([(self.signer, self.card_role_1)], template=template)

    def test_two_documents_are_fine_without_geoeid_role(self):
        template = self.make_template([self.plain_role], documents=2)
        request = self.make_request([(self.signer, self.plain_role)], template=template)
        self.assertEqual(len(request.template_id.document_ids), 2)

    def test_card_signer_is_placed_after_regular_signer(self):
        card_partner = self.make_partner('Card signer', email='card@example.com')
        request = self.make_request([(card_partner, self.card_role_1), (self.signer, self.plain_role)])
        card_item = request.request_item_ids.filtered(lambda item: item.role_id == self.card_role_1)
        regular_item = request.request_item_ids - card_item
        self.assertEqual(regular_item.mail_sent_order, 1)
        self.assertEqual(card_item.mail_sent_order, 2)

    def test_card_signer_goes_after_the_last_regular_signer_and_orders_are_strict(self):
        card_partner = self.make_partner('Card signer', email='card@example.com')
        regular_partner = self.make_partner('Regular 2', email='regular2@example.com')
        request = self.make_request([
            (card_partner, self.card_role_1),
            (self.signer, self.plain_role, {'mail_sent_order': 1}),
            (regular_partner, self.plain_role_2, {'mail_sent_order': 5}),
        ])
        items = request.request_item_ids.sorted('mail_sent_order')
        self.assertEqual(items.mapped('mail_sent_order'), [1, 2, 3])
        self.assertEqual(items.role_id.ids, (self.plain_role + self.plain_role_2 + self.card_role_1).ids)
