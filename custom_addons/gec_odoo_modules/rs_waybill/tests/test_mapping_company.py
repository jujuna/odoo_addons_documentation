"""Resolve Now maps a seller's goods only to products the waybill's company can buy: its own or shared ones."""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestMappingCompany(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        other = self.env['res.company'].create({'name': 'Other Company LLC'})
        self.foreign = self.env['product.product'].create({'name': 'Other Milk', 'company_id': other.id})
        self.shared = self.env['product.product'].create({'name': 'Shared Milk', 'company_id': False})
        self.waybill = self.make_waybill(waybill_direction='buyer', company_id=self.env.company.id)
        line = self.add_line(self.waybill, product_id=False, name='Milk 1L', unresolved=True,
                             external_barcode='S-1', external_name='Milk 1L')
        self.wizard = self.env['rs.waybill.mapping.wizard'].browse(
            self.waybill.action_open_mapping_wizard()['res_id'])
        self.assertEqual(self.wizard.line_ids.line_id, line)

    def test_another_companys_product_is_refused(self):
        self.wizard.line_ids.write({'product_id': self.foreign.id, 'uom_id': self.foreign.uom_id.id})

        with self.assertRaisesRegex(UserError, 'another company'):
            self.wizard.action_apply()
        self.assertFalse(self.waybill.line_ids.product_id)

    def test_a_shared_product_is_accepted(self):
        self.wizard.line_ids.write({'product_id': self.shared.id, 'uom_id': self.shared.uom_id.id})

        with patch.object(type(self.waybill), '_rs_documents_after_mapping'):
            self.wizard.action_apply()
        self.assertEqual(self.waybill.line_ids.product_id, self.shared)

    def test_the_missing_count_message_reads_right(self):
        with self.assertRaisesRegex(UserError, r'applying \(1 still unmapped\)'):
            self.wizard.action_apply()
