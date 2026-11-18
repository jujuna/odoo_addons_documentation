from odoo.exceptions import AccessError
from odoo.tests import Form, tagged
from odoo.tests.common import new_test_user

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestProductAccess(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.internal_user = new_test_user(cls.env, login='rsw_internal', groups='base.group_user')
        cls.template = cls.product.product_tmpl_id
        cls.ext_ref = cls.env['rs.product.external.ref'].create({
            'product_id': cls.template.id,
            'seller_partner_id': cls.buyer.id,
            'external_barcode': '4860000000001',
        })

    def test_internal_user_opens_product_form(self):
        self.env.invalidate_all()
        with Form(self.template.with_user(self.internal_user)) as form:
            self.assertEqual(form.external_ref_count, 1)

    def test_internal_user_reads_external_references(self):
        self.env.invalidate_all()
        values = self.template.with_user(self.internal_user).read(['external_ref_ids', 'external_ref_count'])[0]
        self.assertEqual(values['external_ref_ids'], self.ext_ref.ids)
        self.assertEqual(values['external_ref_count'], 1)

    def test_internal_user_cannot_create_external_reference(self):
        with self.assertRaises(AccessError):
            self.env['rs.product.external.ref'].with_user(self.internal_user).create({
                'product_id': self.template.id,
                'seller_partner_id': self.buyer.id,
                'external_barcode': '4860000000002',
            })
