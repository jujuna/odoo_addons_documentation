from odoo.tests import tagged
from odoo.tools import file_open

from odoo.addons.l10n_tr_nilvera_einvoice.tests.test_xml_ubl_tr_common import TestUBLTRCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestImportRefund(TestUBLTRCommon):
    def test_import_iade_creates_refund(self):
        with file_open('l10n_tr_nilvera_einvoice/tests/test_files/refund/refund_iade.xml', 'rb') as xml_file:
            invoice = self._create_invoice_from_xml(xml_file.read())
        self.assertEqual(invoice.move_type, 'in_refund')
        self.assertRecordValues(invoice.invoice_line_ids.filtered(lambda line: line.display_type == 'product'), [{'quantity': 1.0, 'price_unit': 0.2}])
        self.assertEqual(invoice.l10n_tr_gib_invoice_type, 'IADE')

    def test_import_tevkifatiade_creates_refund(self):
        with file_open('l10n_tr_nilvera_einvoice/tests/test_files/refund/refund_tevkifatiade.xml', 'rb') as xml_file:
            invoice = self._create_invoice_from_xml(xml_file.read())
        self.assertEqual(invoice.move_type, 'in_refund')
        self.assertRecordValues(invoice.invoice_line_ids.filtered(lambda line: line.display_type == 'product'), [{'quantity': 1.0, 'price_unit': 0.5}])
        self.assertEqual(invoice.l10n_tr_gib_invoice_type, 'TEVKIFATIADE')

    def test_import_matches_partner_by_vat(self):
        supplier = self.env['res.partner'].create({'name': 'Supplier', 'vat': '1234567801'})
        with file_open('l10n_tr_nilvera_einvoice/tests/test_files/refund/refund_iade.xml', 'rb') as xml_file:
            invoice = self._create_invoice_from_xml(xml_file.read())
        self.assertEqual(invoice.partner_id, supplier)
