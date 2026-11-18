"""RS.GE allows each product only once per waybill; Odoo refuses before calling RS.GE."""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestDuplicateProducts(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.service = type(self.env['rs.waybill.soap.service'])

    def _save(self, waybill):
        with patch.object(self.service, 'save_waybill') as save:
            try:
                waybill.action_save_to_rs()
            except UserError as error:
                return save, str(error)
        return save, None

    def test_same_product_twice_is_refused_before_rs(self):
        waybill = self.make_waybill(state='draft')
        self.add_line(waybill, quantity=40, unit_price=2.0)
        self.add_line(waybill, quantity=30, unit_price=2.1)

        save, message = self._save(waybill)

        save.assert_not_called()
        self.assertIn(self.product.display_name, message or '')
        self.assertIn('separate sales order', message or '')

    def test_same_product_same_price_is_refused_too(self):
        waybill = self.make_waybill(state='draft')
        self.add_line(waybill, quantity=40, unit_price=2.0)
        self.add_line(waybill, quantity=30, unit_price=2.0)

        save, message = self._save(waybill)

        save.assert_not_called()
        self.assertTrue(message)

    def test_different_products_pass_this_check(self):
        other = self.env['product.product'].create({'name': 'Sugar'})
        waybill = self.make_waybill(state='draft')
        self.add_line(waybill, quantity=40)
        self.add_line(waybill, quantity=30, product_id=other.id, name='Sugar')

        waybill._validate_before_save()
