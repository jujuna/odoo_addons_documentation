"""A shared product registered in one company's RS.GE account is not registered in another's."""

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestRsProductCompany(RsWaybillCommon):

    def test_registration_belongs_to_the_company(self):
        company_a = self.env.company
        company_b = self.env['res.company'].create({'name': 'Company B'})
        self.assertFalse(self.product.company_id, "products are shared by default")

        self.product.with_company(company_a).is_rs_product = True

        self.assertTrue(self.product.with_company(company_a).is_rs_product)
        self.assertFalse(self.product.with_company(company_b).is_rs_product,
                         "company B can still send it to its own RS.GE account")
