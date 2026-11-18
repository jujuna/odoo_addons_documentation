from lxml import etree

from freezegun import freeze_time
from .common import TestMxEdiCommon
from odoo import Command
from odoo.tests import tagged, Form


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestCFDIAccountMove(TestMxEdiCommon):

    _test_user_groups = None  # FIXME list needed groups

    @freeze_time('2017-01-01')
    def test_extra_print_items(self):
        invoice = self._create_invoice_mx()
        print_items_before = invoice.get_extra_print_items()
        with self.with_mocked_pac_sign_success():
            invoice._l10n_mx_edi_cfdi_invoice_try_send()
        print_items_after = invoice.get_extra_print_items()
        self.assertEqual(len(print_items_before) + 1, len(print_items_after))

    @freeze_time('2017-01-01')
    def test_get_invoice_legal_documents_cfdi(self):
        invoice_with_cfdi = self._create_invoice_mx()
        invoice_without_cfdi = self._create_invoice_mx()
        with self.with_mocked_pac_sign_success():
            invoice_with_cfdi._l10n_mx_edi_cfdi_invoice_try_send()
        legal_documents = invoice_with_cfdi._get_invoice_legal_documents('cfdi')
        self.assertEqual(len(legal_documents), 1)
        self.assertEqual(legal_documents[0], {
            'filename': invoice_with_cfdi.l10n_mx_edi_cfdi_attachment_id.name,
            'filetype': 'xml',
            'content': invoice_with_cfdi.l10n_mx_edi_cfdi_attachment_id.raw,
        })
        self.assertFalse(invoice_without_cfdi._get_invoice_legal_documents('cfdi'))

    def test_cfdi_origin(self):
        """ Test that the l10n_mx_edi_cfdi_origin field can be set correctly. """
        invoice = self._create_invoice_mx(move_type='out_refund')
        invoice.l10n_mx_edi_cfdi_origin = '01|E19C50D2-1292-5817-BDDE-2666967C7471'
        invoice._l10n_mx_edi_get_refund_original_invoices()
        self.assertEqual(invoice.l10n_mx_edi_cfdi_origin, '01|E19C50D2-1292-5817-BDDE-2666967C7471')

    @freeze_time('2017-01-01')
    def test_invoice_tax_objects_required(self):
        """Test that the invoice can be save, when there is a move line with a total amount of 0 that without its field tax objects set"""
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_mx.id,
            'currency_id': self.comp_curr.id,
        })
        with Form(invoice) as f:
            with f.invoice_line_ids.new() as line:
                line.price_unit = 0

    def test_invoice_payment_policy_and_method(self):
        """Test that the invoice can be manipulated accordingly when payment policy and method are set or not set accordingly on the form view"""
        with self.mx_external_setup(self.frozen_today):
            invoice = Form(self.env['account.move'].with_context(default_move_type='out_invoice'))
            invoice.partner_id = self.partner_mx
            with invoice.invoice_line_ids.new() as new_line:
                new_line.product_id = self.product

            # Invoice should be saved without problems when in draft
            invoice = invoice.save()
            self.assertRecordValues(invoice, [
                {'l10n_mx_edi_payment_policy': False, 'l10n_mx_edi_payment_method_id': False, 'state': 'draft'}
            ])

            invoice._post()
            transferencia_method = self.env.ref('l10n_mx_edi.payment_method_transferencia')
            # Test invalid ways
            with Form(invoice) as f:
                # Payment policy is required if cfdi needed
                with self.assertRaisesRegex(AssertionError, 'l10n_mx_edi_payment_policy is a required field'):
                    f.l10n_mx_edi_payment_policy = False
                    f.save()

                # When PUE payment method is required
                with self.assertRaisesRegex(AssertionError, 'l10n_mx_edi_payment_method_id is a required field'):
                    f.l10n_mx_edi_payment_policy = 'PUE'
                    f.save()

                f.l10n_mx_edi_payment_policy = 'PPD'
                # When PPD payment method is invisible
                with self.assertRaisesRegex(AssertionError, "can't write on invisible field 'l10n_mx_edi_payment_method_id'"):
                    f.l10n_mx_edi_payment_method_id = transferencia_method

            with self.with_mocked_pac_sign_success():
                invoice._l10n_mx_edi_cfdi_invoice_try_send()

            # Not editable once the invoice is sent to the PAC
            with Form(invoice) as f:
                with self.assertRaisesRegex(AssertionError, "can't write on readonly field 'l10n_mx_edi_payment_policy'"):
                    f.l10n_mx_edi_payment_policy = False
                with self.assertRaisesRegex(AssertionError, "can't write on readonly field 'l10n_mx_edi_payment_method_id'"):
                    f.l10n_mx_edi_payment_method_id = self.env['l10n_mx_edi.payment.method']

    def test_invoice_cfdi_uom_translation(self):
        """ The CFDI must use the customer's language, just like the PDF. """
        self.env['res.lang']._activate_lang('es_MX')
        self.product.uom_id.with_context(lang='es_MX').name = 'Piezas'
        self.partner_mx.lang = 'es_MX'

        with self.mx_external_setup(self.frozen_today):
            invoice = self._create_invoice_mx()
            with self.with_mocked_pac_sign_success():
                invoice.with_context(lang=None)._l10n_mx_edi_cfdi_invoice_try_send()

            document = invoice.l10n_mx_edi_invoice_document_ids.filtered(lambda x: x.state == 'invoice_sent')[:1]
            cfdi_node = self.get_xml_tree_from_string(bytes(document.attachment_id.raw))
            concepto = cfdi_node.xpath("//*[local-name()='Concepto']")[0]
            self.assertEqual(concepto.get('Unidad'), 'PIEZAS')

    @freeze_time('2017-01-01')
    def test_cfdi_line_name_partner_specific_code_not_duplicated(self):
        """ When a customer has their own product code (product.supplierinfo),
        the invoice line description uses it (e.g. "[CUSTOM-CODE] Product"),
        exactly like on a sale order line. _l10n_mx_edi_get_cfdi_line_name must
        not re-resolve the product's display_name without that customer in
        context, or it would find a different string ("[product_mx] product_mx")
        and prepend it, duplicating the product name in the CFDI Descripcion. """
        self.env['product.supplierinfo'].create({
            'partner_id': self.partner_mx.id,
            'product_tmpl_id': self.product.product_tmpl_id.id,
            'product_code': 'CUSTOM-CODE',
        })
        line_name = self.product.with_context(partner_id=self.partner_mx.id).display_name
        invoice = self._create_invoice_mx(invoice_line_ids=[
            Command.create({'product_id': self.product.id, 'name': line_name}),
        ])
        with self.with_mocked_pac_sign_success():
            invoice._l10n_mx_edi_cfdi_invoice_try_send()
        self.assertEqual(invoice.l10n_mx_edi_cfdi_state, 'sent', f'Error: {invoice.l10n_mx_edi_document_ids.message}')

        xml_tree = self.get_xml_tree_from_attachment(invoice.l10n_mx_edi_cfdi_attachment_id)
        concepto = xml_tree.xpath("//*[local-name()='Concepto']")[0]
        self.assertEqual(concepto.get('Descripcion'), line_name)

    @freeze_time('2017-01-01')
    def test_cfdi_line_name_standard_code_not_duplicated(self):
        """ An existing description containing the standard product name must
        not gain the customer-specific name in the CFDI Descripcion. """
        invoice = self._create_invoice_mx(invoice_line_ids=[
            Command.create({'product_id': self.product.id, 'name': self.product.display_name}),
        ])
        line_name = invoice.invoice_line_ids.name
        self.env['product.supplierinfo'].create({
            'partner_id': self.partner_mx.id,
            'product_tmpl_id': self.product.product_tmpl_id.id,
            'product_code': 'CUSTOM-CODE',
        })
        with self.with_mocked_pac_sign_success():
            invoice._l10n_mx_edi_cfdi_invoice_try_send()
        self.assertEqual(invoice.l10n_mx_edi_cfdi_state, 'sent', f'Error: {invoice.l10n_mx_edi_document_ids.message}')

        xml_tree = self.get_xml_tree_from_attachment(invoice.l10n_mx_edi_cfdi_attachment_id)
        concepto = xml_tree.xpath("//*[local-name()='Concepto']")[0]
        self.assertEqual(concepto.get('Descripcion'), line_name)

    def test_import_cfdi_line_keeps_original_description(self):
        """The importer must preserve bracketed notes in Descripcion when matching a product."""
        xml_tree = self.get_xml_tree_from_string(
            self.file_read('l10n_mx_edi/tests/test_files/import/test_import_bill.xml').content,
        )
        concepto = xml_tree.find('{*}Conceptos/{*}Concepto')
        description = f'[URGENT] {self.product.display_name}'
        concepto.set('Descripcion', description)

        bill = self._upload_document_on_journal(
            journal=self.company_data['default_journal_purchase'],
            content=etree.tostring(xml_tree),
            filename='test_import_bill.xml',
        )
        self.assertEqual(bill.l10n_mx_edi_cfdi_state, 'received')
        self.assertRecordValues(bill.invoice_line_ids, [{
            'product_id': self.product.id,
            # The current importer appends NoIdentificacion after the original description.
            'name': f"{description} | {concepto.get('NoIdentificacion')}",
        }])
